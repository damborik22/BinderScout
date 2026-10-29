"""TmProt 1.0 wrapper — sequence-only melting-temperature screen.

Wraps the standalone TmProt CLI (Pailozian, Kohout et al., Loschmidt Laboratories)
by invoking its ``tmprot`` entry point inside the ``binder-eval-tmprot`` conda env,
then collecting the per-sequence Tm predictions into a CSV that
``binder-compare report --tmprot-results`` can ingest.

TmProt is NOT a refolding engine — no structure, no PAE, no pLDDT. It predicts one
number per sequence: the melting temperature in °C, from ESM-2 650M with a LoRA
adapter. It is filed under ``refolding/`` for the same reason SoluProt is: the call
shape (sequences in, CSV out) matches the engines, and the orchestration treats it
as another optional pre-screen.

**Advisory, like SoluProt.** A predicted Tm is a stability signal, not a binding
signal; nothing here reorders or drops a design. The published binary task
(thermostable at Tm >= 60 °C) scores AUC 0.75, so the right use is to notice the
bottom of the distribution, not to separate 68 °C from 71 °C.

Two upstream behaviours this wrapper has to absorb, both of which silently lose rows:

* **TmProt skips sequences it will not score** — shorter than 20 aa, longer than
  2000, or carrying anything outside the 20 standard residues. It warns on stderr
  and omits the row. Binder pools are mostly 50–130 aa so this is rare, but a
  short designed peptide would vanish without explanation.
* **Its output is sorted by Tm, descending**, and identifies rows by FASTA ID only.
  So the ID has to carry the identity; this wrapper writes its own ``tm<N>`` IDs and
  maps them back by position rather than trusting a design's own header, which may
  contain spaces (Biopython's ``rec.id`` keeps only the first token) or repeat.

Every sequence handed in appears in the output CSV. One that TmProt declined to
score gets an empty Tm rather than being dropped, and the count is reported.
"""

from __future__ import annotations

import csv
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Upstream default: the Yes/No label in TmProt's own output, not a filter we apply.
DEFAULT_THRESHOLD = 60.0

# TmProt's own guards (src/tmprot/cli.py). Mirrored here only so the wrapper can say
# which sequence it dropped and why, instead of reporting an unexplained short CSV.
MIN_LENGTH = 20
MAX_LENGTH = 2000
_VALID_AA = set("ACDEFGHIKLMNPQRSTVWY")

# TmProt writes `Rank, ID, Predicted Tm [°C], Thermostable`. The Tm header carries a
# degree sign and brackets, so it is matched leniently rather than by exact spelling.
_TM_HEADER_HINTS = ("predicted tm", "tm [", "tm_c", "tm")


def _skip_reason(seq: str) -> str | None:
    """Why TmProt will refuse this sequence, or None if it will score it."""
    if len(seq) < MIN_LENGTH:
        return f"shorter than {MIN_LENGTH} aa"
    if len(seq) > MAX_LENGTH:
        return f"longer than {MAX_LENGTH} aa"
    bad = sorted(set(seq.upper()) - _VALID_AA)
    if bad:
        return f"non-standard residue(s) {''.join(bad)}"
    return None


def _tm_column(fieldnames: list[str]) -> str | None:
    for hint in _TM_HEADER_HINTS:
        for name in fieldnames:
            if hint in name.strip().lower():
                return name
    return None


def run_tmprot_filter(
    sequences: list[str],
    output_csv: str | Path,
    *,
    binder_ids: list[str] | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    tmprot_bin: str = "tmprot",
    timeout: int | None = None,
) -> Path:
    """Score *sequences* with TmProt and write ``sequence,native_tmprot_tm,…`` to *output_csv*.

    Returns the path written. Raises RuntimeError if the TmProt CLI is missing or
    fails — a stability screen that silently produced nothing would read as "no
    design is thermostable", which is a different claim entirely.
    """
    output_csv = Path(output_csv)
    if not sequences:
        raise ValueError("no sequences supplied to TmProt")
    if binder_ids is not None and len(binder_ids) != len(sequences):
        raise ValueError(f"binder_ids has {len(binder_ids)} entries for {len(sequences)} sequences")

    if shutil.which(tmprot_bin) is None:
        raise RuntimeError(
            f"TmProt CLI {tmprot_bin!r} not found on PATH. Run this inside the env that has it:\n"
            f"    conda run -n binder-eval-tmprot binder-compare filter-tmprot …\n"
            f"or install it with `bindmaster install --tool tmprot`."
        )

    # Our own IDs: TmProt identifies rows by FASTA ID alone, and a design's own header
    # may repeat or contain spaces. Index-keyed IDs make the join exact.
    ids = [f"tm{i}" for i in range(len(sequences))]
    scorable = {i: s for i, s in enumerate(sequences) if _skip_reason(s) is None}
    for i, seq in enumerate(sequences):
        reason = _skip_reason(seq)
        if reason:
            print(f"[filter-tmprot] [warn] sequence {i} ({len(seq)} aa) will be skipped by TmProt: {reason}")

    results: dict[int, tuple[float | None, str]] = {}
    with tempfile.TemporaryDirectory(prefix="tmprot-") as tmp:
        tmpdir = Path(tmp)
        fasta = tmpdir / "binders.fasta"
        with fasta.open("w", encoding="utf-8") as fh:
            for i, seq in scorable.items():
                fh.write(f">{ids[i]}\n{seq}\n")

        if scorable:
            outdir = tmpdir / "out"
            cmd = [tmprot_bin, "-i", str(fasta), "-o", str(outdir), "-t", str(threshold), "-d", ","]
            print(f"[filter-tmprot] running: {' '.join(cmd)}")
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if proc.returncode != 0:
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-20:]
                raise RuntimeError("TmProt failed (exit {}):\n  {}".format(proc.returncode, "\n  ".join(tail)))

            # outfile is <outdir>/<input stem>.csv (upstream cli.py), i.e. binders.csv.
            produced = outdir / f"{fasta.stem}.csv"
            if not produced.exists():
                found = sorted(outdir.glob("*.csv")) if outdir.is_dir() else []
                if not found:
                    raise RuntimeError(f"TmProt exited 0 but wrote no CSV under {outdir}")
                produced = found[0]

            with produced.open(newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh, delimiter=",")
                tm_col = _tm_column(list(reader.fieldnames or []))
                if tm_col is None:
                    raise RuntimeError(f"TmProt output {produced} has no recognisable Tm column: {reader.fieldnames}")
                by_id = {i: n for n, i in enumerate(ids)}
                for row in reader:
                    rid = (row.get("ID") or "").strip()
                    if rid not in by_id:
                        continue
                    try:
                        tm = float(str(row[tm_col]).strip())
                    except (TypeError, ValueError):
                        continue
                    results[by_id[rid]] = (tm, (row.get("Thermostable") or "").strip())

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        header = ["sequence", "native_tmprot_tm", "tmprot_thermostable"]
        if binder_ids is not None:
            header.insert(0, "binder_id")
        writer.writerow(header)
        for i, seq in enumerate(sequences):
            tm, label = results.get(i, (None, ""))
            row = [seq, "" if tm is None else tm, label]
            if binder_ids is not None:
                row.insert(0, binder_ids[i])
            writer.writerow(row)

    scored = len(results)
    missing = len(sequences) - scored
    print(f"[filter-tmprot] scored {scored}/{len(sequences)} sequence(s) → {output_csv}")
    if missing:
        print(f"[filter-tmprot] [warn] {missing} sequence(s) have no Tm — empty cells, not dropped", file=sys.stderr)
    return output_csv
