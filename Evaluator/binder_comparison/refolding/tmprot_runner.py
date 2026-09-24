"""TmProt 1.0 — sequence-only melting-temperature screen.

TmProt (https://github.com/loschmidt/TmProt, Loschmidt Lab, Masaryk University)
is a LoRA-adapted ESM-2 predictor of protein melting temperature, and the
sister tool to SoluProt from the same group. Sequence-only: no GPU is required
and nothing is refolded.

**This is a screen, never a ranking term.** Item D1 of the 2.0 assessment is
explicit about why: Tm predictors are trained on natural proteins and are out of
domain on hyperstable de novo miniproteins, which is most of what this pipeline
produces. The published AUC of 0.75-0.77 is for separating Tm >= 60 C on
heterogeneous natural datasets. So ``native_tmprot_tm`` is an advisory column
and must stay out of ``rank_designs``.

**Not redistributed.** TmProt is GPL-3.0 and this repository is MIT, so the
installer fetches and builds it rather than vendoring it — the same posture the
USEARCH binaries were moved to.

Output of the tool itself is ``Rank, ID, Predicted Tm [C], Thermostable``,
keyed by FASTA header and sorted by rank. ``report.py::_attach_tmprot_results``
joins on ``sequence``, so this module owns the remapping.
"""

from __future__ import annotations

import csv
import os
import subprocess
import tempfile
from pathlib import Path

# TmProt's own thermostability cutoff: the AUC it reports is for Tm >= 60 C.
DEFAULT_THRESHOLD = 60.0

_TM_COLUMN_CANDIDATES = (
    "predicted tm [°c]",
    "predicted tm [c]",
    "predicted_tm",
    "predicted_tm_c",
    "tm",
)


def make_fasta_ids(sequences: list[str]) -> list[str]:
    """Positional IDs for the FASTA we hand TmProt.

    We generate these rather than reusing binder_ids so the mapping back cannot
    be broken by a duplicate, empty or exotic binder name — TmProt returns rows
    sorted by rank, not by input order, so the ID is the only thing tying a
    prediction to its sequence.
    """
    return [f"seq{i:06d}" for i in range(len(sequences))]


def _write_fasta(sequences: list[str], ids: list[str], path: Path) -> None:
    path.write_text("".join(f">{i}\n{s}\n" for i, s in zip(ids, sequences, strict=True)))


def _parse_tmprot_output(csv_path: Path, ids: list[str]) -> list[float | None]:
    """Map TmProt's rank-sorted rows back onto input order.

    A sequence TmProt did not return is ``None``, never 0.0 — a missing
    prediction and a 0 C melting temperature must not be the same value
    downstream.
    """
    by_id: dict[str, float | None] = {}
    with Path(csv_path).open(newline="") as fh:
        reader = csv.DictReader(fh)
        headers = {(h or "").strip().lower(): h for h in (reader.fieldnames or [])}
        tm_key = next((headers[c] for c in _TM_COLUMN_CANDIDATES if c in headers), None)
        id_key = headers.get("id")
        if tm_key is None or id_key is None:
            raise ValueError(
                f"{csv_path} is not TmProt output: expected an 'ID' column and one of "
                f"{_TM_COLUMN_CANDIDATES}, got {reader.fieldnames}"
            )
        for row in reader:
            raw = (row.get(tm_key) or "").strip()
            try:
                by_id[(row.get(id_key) or "").strip()] = float(raw)
            except ValueError:
                by_id[(row.get(id_key) or "").strip()] = None
    return [by_id.get(i) for i in ids]


def _write_csv(
    output_csv: Path,
    *,
    sequences: list[str],
    tms: list[float | None],
    threshold: float,
    binder_ids: list[str] | None,
) -> None:
    output_csv = Path(output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    head = ["sequence", "tmprot_tm", "tmprot_thermostable", "tmprot_threshold"]
    if binder_ids is not None:
        head = ["binder_id", *head]
    with output_csv.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(head)
        for i, (seq, tm) in enumerate(zip(sequences, tms, strict=True)):
            tm_s = "" if tm is None else f"{tm:.6f}"
            flag = "" if tm is None else int(tm >= threshold)
            row = [seq, tm_s, flag, threshold]
            if binder_ids is not None:
                row = [binder_ids[i], *row]
            w.writerow(row)


def _resolve_tmprot_bin() -> str:
    """The `tmprot` console script. ``$TMPROT_BIN`` wins, as the installer's
    shortcut sets it; otherwise rely on PATH inside the tmprot env."""
    return os.environ.get("TMPROT_BIN") or "tmprot"


def run_tmprot_screen(
    sequences: list[str],
    output_csv: str | Path,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    binder_ids: list[str] | None = None,
    tmprot_bin: str | None = None,
) -> None:
    """Predict Tm for every entry in *sequences* and write a per-binder CSV.

    A row is emitted for every input sequence even when TmProt returns nothing
    for it — this is a screen and must never silently shorten the pool.

    Output schema:
        ``binder_id (optional), sequence, tmprot_tm, tmprot_thermostable,
        tmprot_threshold``
    """
    output_csv = Path(output_csv).resolve()
    ids = make_fasta_ids(sequences)
    binary = tmprot_bin or _resolve_tmprot_bin()

    with tempfile.TemporaryDirectory(prefix="tmprot_") as tmp:
        tmpdir = Path(tmp)
        fasta = tmpdir / "input.fasta"
        outdir = tmpdir / "out"
        _write_fasta(sequences, ids, fasta)

        cmd = [binary, "--input", str(fasta), "--outdir", str(outdir), "--threshold", str(threshold)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            # The common case by far: run from the wrong env. A bare
            # FileNotFoundError traceback tells a human nothing about which
            # binary or how to get it.
            raise RuntimeError(
                f"'{binary}' not found. TmProt runs in its own conda env:\n"
                f"    binderscout install --tool tmprot\n"
                f"    conda run -n binder-eval-tmprot binder-compare screen-tmprot ...\n"
                f"Or point --tmprot-bin / $TMPROT_BIN at an existing tmprot install."
            ) from exc
        if proc.returncode != 0:
            raise RuntimeError(
                f"tmprot exited {proc.returncode}\ncommand: {' '.join(cmd)}\nstderr:\n{proc.stderr.strip()[:2000]}"
            )

        produced = sorted(outdir.rglob("*.csv"))
        if not produced:
            raise RuntimeError(f"tmprot wrote no CSV into {outdir}\nstdout:\n{proc.stdout.strip()[:2000]}")
        tms = _parse_tmprot_output(produced[0], ids)

    _write_csv(output_csv, sequences=sequences, tms=tms, threshold=threshold, binder_ids=binder_ids)
    scored = sum(1 for t in tms if t is not None)
    print(f"[tmprot] {scored}/{len(sequences)} sequence(s) scored → {output_csv}")
