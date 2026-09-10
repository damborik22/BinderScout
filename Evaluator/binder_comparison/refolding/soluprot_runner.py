"""SoluProt 1.0 wrapper — sequence-only solubility screen.

Wraps the standalone SoluProt distribution (Hon et al. 2021) by
invoking its `soluprot.py` entry script inside the
``binder-eval-soluprot`` conda env, then collecting the per-sequence
probability scores into a CSV.

SoluProt is NOT a refolding engine — it produces no structure, no PAE,
no pLDDT. It outputs a single probability per sequence indicating how
likely the sequence is to express solubly in *E. coli*. We file it
under ``refolding/`` for convenience: the call shape (sequences in,
CSV out) matches the other engines, and the orchestration in
``evaluate.sh`` treats it as another optional step.

Performance reality check (Hon et al. 2021): the reported AUC on the
balanced independent test set is 0.62 (MCC 0.17). The right use is
*screening* (drop the bottom of the distribution), not *re-ranking*
(small differences in the 0.4–0.6 band are noise).
"""

from __future__ import annotations

import csv
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_THRESHOLD = 0.5  # paper default; tune via --threshold for binder-length sequences

# SoluProt's expected output column names (from the standalone script). The
# exact column name has varied between distribution versions; the runner
# accepts any of these and falls back to the first numeric column if none
# matches verbatim. Update this list if a future SoluProt version changes
# the schema.
_SCORE_COLUMN_CANDIDATES = ("soluprot_score", "soluble", "solubility", "score")


def run_soluprot_filter(
    sequences: list[str],
    output_csv: str | Path,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    scripts_path: str | Path | None = None,
    binder_ids: list[str] | None = None,
    no_tmhmm: bool | None = None,
    usearch_path: str | Path | None = None,
) -> None:
    """Score every entry in *sequences* with SoluProt and write a CSV.

    Args:
        sequences:     binder amino acid strings.
        output_csv:    path for the per-binder score CSV.
        threshold:     score >= threshold is considered soluble; written
                       to a ``soluprot_passes`` boolean column.
        scripts_path:  path to an unpacked SoluProt distribution. If
                       None, falls back to ``$SOLUPROT_HOME`` and then
                       ``Evaluator/tools/soluprot/`` relative to the
                       repo root.
        binder_ids:    optional 1-to-1 list of binder identifiers; if
                       provided, they're emitted as the first column.
        no_tmhmm:      use SoluProt's TMHMM-free model (``--no_tmhmm``,
                       grad_clf_v1_tc_notmhmm.pkl, -0.5% accuracy). If
                       None, auto: enabled when no TMHMM binary is found
                       (always the case on aarch64 — TMHMM ships x86 only).
        usearch_path:  path to the USEARCH binary for the identity
                       feature. If None, resolved from ``$SOLUPROT_USEARCH``,
                       then ``<scripts_path>/usearch.<arch>``, then
                       ``<scripts_path>/usearch``, then ``usearch`` on PATH.
                       Raises if none of those exist — SoluProt cannot score
                       without it.

    Output schema (one row per sequence):
        ``binder_id (optional), sequence, soluprot_score,
        soluprot_passes, soluprot_threshold``
    """
    output_csv = Path(output_csv).resolve()
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    soluprot_dir = _resolve_scripts_path(scripts_path)
    soluprot_entry = _find_entry_script(soluprot_dir)

    if binder_ids is not None and len(binder_ids) != len(sequences):
        raise ValueError(f"binder_ids length {len(binder_ids)} != sequences length {len(sequences)}")

    # SoluProt reads FASTA, so we hand it one with deterministic identifiers
    # and read the scores back keyed by position.
    fasta_tmp = output_csv.with_suffix(".soluprot_in.fasta")
    score_tmp = output_csv.with_suffix(".soluprot_out.csv")
    work_dir = output_csv.with_suffix(".soluprot_work")
    _write_fasta(sequences, fasta_tmp)

    use_no_tmhmm = _decide_no_tmhmm(no_tmhmm, soluprot_dir)
    usearch = _resolve_usearch(usearch_path, soluprot_dir)
    soluprot_python = _resolve_soluprot_python()

    try:
        # SoluProt 1.0.1.0 CLI: --i_fa / --o_csv / --tmp_dir (required), plus
        # --no_tmhmm (use the TMHMM-free model) and --usearch (identity-feature
        # binary). --pdb defaults to the bundled E. coli reference, resolved
        # relative to the script, so we don't pass it. SoluProt runs under its
        # own Python 3.7 interpreter (see _resolve_soluprot_python), not ours.
        cmd = [
            soluprot_python,
            str(soluprot_entry),
            "--i_fa",
            str(fasta_tmp),
            "--o_csv",
            str(score_tmp),
            "--tmp_dir",
            str(work_dir),
        ]
        if use_no_tmhmm:
            cmd.append("--no_tmhmm")
        cmd += ["--usearch", str(usearch)]
        # SoluProt's CWD matters because its data files (training-set features,
        # reference DB, model) are looked up relative to the script.
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        print(f"[soluprot] running: {' '.join(cmd)}  (cwd={soluprot_dir})")
        proc = subprocess.run(cmd, cwd=soluprot_dir, env=env, capture_output=True, text=True, check=False)
        # SoluProt's main() swallows tool failures (USEARCH/TMHMM) — it prints to
        # stderr and exits 0 without writing the CSV. So a missing output file,
        # not the return code, is the real failure signal.
        if proc.returncode != 0 or not score_tmp.exists():
            raise RuntimeError(
                f"SoluProt did not produce {score_tmp} (exit {proc.returncode}).\n"
                f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )

        scores = _parse_scores(score_tmp, n_expected=len(sequences))
    finally:
        # Keep the intermediate files if the run failed (helpful for debugging),
        # clean them up on success. NB: this module may itself run under Python
        # 3.7 (the binder-eval-soluprot env), so we avoid
        # Path.unlink(missing_ok=...) (3.8+) and guard with exists().
        if not _keep_intermediates():
            for tmp in (fasta_tmp, score_tmp):
                if tmp.exists():
                    tmp.unlink()
            if work_dir.exists():
                shutil.rmtree(work_dir, ignore_errors=True)

    _write_csv(
        output_csv,
        sequences=sequences,
        scores=scores,
        threshold=threshold,
        binder_ids=binder_ids,
    )
    print(f"[soluprot] wrote {len(sequences)} rows → {output_csv}")


# ─── Internals ────────────────────────────────────────────────────────────────


def _resolve_scripts_path(override: str | Path | None) -> Path:
    if override is not None:
        p = Path(override).resolve()
        if not p.exists():
            raise FileNotFoundError(f"SoluProt scripts path not found: {p}")
        return p
    env_path = os.environ.get("SOLUPROT_HOME")
    if env_path:
        p = Path(env_path).resolve()
        if p.exists():
            return p
    # Default install location used by `bindmaster install --tool soluprot`.
    repo_root = Path(__file__).resolve().parents[3]
    bundled = repo_root / "Evaluator" / "tools" / "soluprot"
    if bundled.exists():
        return bundled
    raise FileNotFoundError(
        "SoluProt is not installed. Run `bindmaster install --tool soluprot`, "
        "set $SOLUPROT_HOME, or pass --scripts-path."
    )


def _resolve_soluprot_python() -> str:
    """Interpreter that executes SoluProt's ``soluprot.py``.

    SoluProt needs Python 3.7 + scikit-learn 0.20.x, which cannot host the
    py3.10+ ``binder-comparison`` package — so ``binder-compare`` runs in the
    ``binder-eval`` env and shells out to the ``binder-eval-soluprot`` env's
    interpreter here. Resolution order: ``$SOLUPROT_PYTHON`` (set by
    ``evaluate.sh`` / the ``soluprot`` shortcut), then a sibling
    ``binder-eval-soluprot`` env next to the current interpreter, then bare
    ``python`` (works when binder-compare is itself run inside that env).
    """
    override = os.environ.get("SOLUPROT_PYTHON")
    if override and Path(override).exists():
        return override
    exe = Path(sys.executable)
    for parent in exe.parents:
        if parent.name == "envs":
            cand = parent / "binder-eval-soluprot" / "bin" / "python"
            if cand.exists():
                return str(cand)
            break
    return "python"


def _decide_no_tmhmm(override: bool | None, soluprot_dir: Path) -> bool:
    """Whether to pass ``--no_tmhmm`` (SoluProt's TMHMM-free model).

    Explicit override wins, then ``$SOLUPROT_NO_TMHMM``, else auto:
    enabled when no TMHMM binary is available. TMHMM 2.0 ships an x86-only
    ``decodeanhmm`` binary, so this is always the case on aarch64; the
    TMHMM-free model (grad_clf_v1_tc_notmhmm.pkl) costs ~-0.5% accuracy.
    """
    if override is not None:
        return override
    env_val = os.environ.get("SOLUPROT_NO_TMHMM")
    if env_val is not None:
        return env_val not in ("", "0", "false", "False")
    bundled = soluprot_dir / "tmhmm-2.0" / "bin" / "tmhmm"
    return not (bundled.exists() or shutil.which("tmhmm"))


def _resolve_usearch(override: str | Path | None, soluprot_dir: Path) -> Path:
    """Locate the USEARCH binary for SoluProt's identity feature.

    Order: explicit arg, ``$SOLUPROT_USEARCH``, ``<soluprot_dir>/usearch.<arch>``,
    a bare ``<soluprot_dir>/usearch``, then ``usearch`` on PATH. USEARCH is a
    native binary and the dist carries per-arch copies (``usearch.x86_64`` /
    ``usearch.aarch64``, built from source by the installer) so a checkout/merge
    on one machine can't clobber the other's. Paths are returned absolute
    (SoluProt resolves relative paths against its own script directory, not the
    caller's CWD).

    Raises if nothing is found: SoluProt cannot score without USEARCH, and its
    own diagnostic for a missing binary is the opaque "Path to USEARCH is
    invalid: None", so we fail here with the remediation instead.
    """
    for cand in (override, os.environ.get("SOLUPROT_USEARCH")):
        if cand:
            p = Path(cand).resolve()
            if not p.exists():
                raise FileNotFoundError(f"USEARCH binary not found: {p}")
            return p
    for bundled in (soluprot_dir / f"usearch.{platform.machine()}", soluprot_dir / "usearch"):
        if bundled.exists():
            return bundled.resolve()
    on_path = shutil.which("usearch")
    if on_path:
        return Path(on_path).resolve()
    raise FileNotFoundError(
        "USEARCH not found — SoluProt cannot compute its identity feature without it. "
        f"Looked at: $SOLUPROT_USEARCH, {soluprot_dir}/usearch.{platform.machine()}, "
        f"{soluprot_dir}/usearch, and 'usearch' on PATH.\n"
        "Build it with `bindmaster install --tool soluprot` (source-builds "
        "rcedgar/usearch12, GPLv3), or pass --usearch /path/to/usearch."
    )


def _find_entry_script(soluprot_dir: Path) -> Path:
    """SoluProt's distribution has shipped under a couple of script names
    across versions; try the documented one first then fall back."""
    for candidate in ("soluprot.py", "predict_solubility.py", "predict.py"):
        p = soluprot_dir / candidate
        if p.exists():
            return p
    raise FileNotFoundError(
        f"No SoluProt entry script (soluprot.py / predict_solubility.py / "
        f"predict.py) found under {soluprot_dir}. Did the install complete?"
    )


def _write_fasta(sequences: list[str], path: Path) -> None:
    with path.open("w") as fh:
        for i, seq in enumerate(sequences):
            fh.write(f">binder_{i:06d}\n{seq}\n")


def _parse_scores(score_csv: Path, n_expected: int) -> list[float | None]:
    """Read SoluProt's output CSV and return a list of per-sequence scores
    aligned with the input order.

    SoluProt's columns have varied between releases; we look up the score
    column by name (with several alternatives), and if none of them match
    we fall back to the first numeric column. If the row count doesn't
    match the input, we error out — silent misalignment would be worse
    than failing visibly.
    """
    if not score_csv.exists():
        raise FileNotFoundError(f"SoluProt did not produce {score_csv}")

    rows: list[dict[str, str]] = []
    with score_csv.open() as fh:
        # SoluProt sometimes uses tab-separated, sometimes comma; sniff once.
        sample = fh.read(2048)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(fh, dialect=dialect)
        rows = list(reader)

    if len(rows) != n_expected:
        raise RuntimeError(
            f"SoluProt produced {len(rows)} rows for {n_expected} sequences "
            f"({score_csv}) — refusing to guess the alignment."
        )

    if not rows:
        return []

    score_col: str | None = None
    for cand in _SCORE_COLUMN_CANDIDATES:
        if cand in rows[0]:
            score_col = cand
            break
    if score_col is None:
        # Last resort: pick the first numeric column.
        for col, val in rows[0].items():
            try:
                float(val)
                score_col = col
                break
            except (TypeError, ValueError):
                continue
    if score_col is None:
        raise RuntimeError(f"Could not identify a numeric score column in {score_csv}; columns: {list(rows[0])}")

    out: list[float | None] = []
    for row in rows:
        raw = row.get(score_col, "")
        try:
            out.append(float(raw))
        except (TypeError, ValueError):
            out.append(None)
    return out


def _write_csv(
    output_csv: Path,
    *,
    sequences: list[str],
    scores: list[float | None],
    threshold: float,
    binder_ids: list[str] | None,
) -> None:
    with output_csv.open("w", newline="") as fh:
        writer = csv.writer(fh)
        if binder_ids is not None:
            writer.writerow(["binder_id", "sequence", "soluprot_score", "soluprot_passes", "soluprot_threshold"])
        else:
            writer.writerow(["sequence", "soluprot_score", "soluprot_passes", "soluprot_threshold"])
        for i, (seq, score) in enumerate(zip(sequences, scores)):
            passes = "" if score is None else int(score >= threshold)
            row_score = "" if score is None else f"{score:.6f}"
            if binder_ids is not None:
                writer.writerow([binder_ids[i], seq, row_score, passes, threshold])
            else:
                writer.writerow([seq, row_score, passes, threshold])


def _keep_intermediates() -> bool:
    return os.environ.get("SOLUPROT_KEEP_INTERMEDIATES", "0") not in ("", "0", "false")


# Convenience: expose the binary discovery for the installer's smoke test.
def find_soluprot_installation(scripts_path: str | Path | None = None) -> Path:
    return _find_entry_script(_resolve_scripts_path(scripts_path))


__all__ = ["DEFAULT_THRESHOLD", "find_soluprot_installation", "run_soluprot_filter"]
