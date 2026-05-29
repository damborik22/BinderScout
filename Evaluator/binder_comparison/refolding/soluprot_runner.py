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
import subprocess
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
    _write_fasta(sequences, fasta_tmp)

    try:
        cmd = [
            "python",
            str(soluprot_entry),
            "--input",
            str(fasta_tmp),
            "--output",
            str(score_tmp),
        ]
        # SoluProt's CWD matters because its data files (training-set features,
        # etc.) are looked up relative to the script.
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        print(f"[soluprot] running: {' '.join(cmd)}  (cwd={soluprot_dir})")
        proc = subprocess.run(cmd, cwd=soluprot_dir, env=env, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(
                f"SoluProt exited with code {proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )

        scores = _parse_scores(score_tmp, n_expected=len(sequences))
    finally:
        # Keep the intermediate files if the run failed (helpful for debugging),
        # clean them up on success.
        if fasta_tmp.exists() and not _keep_intermediates():
            fasta_tmp.unlink(missing_ok=True)
        if score_tmp.exists() and not _keep_intermediates():
            score_tmp.unlink(missing_ok=True)

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
