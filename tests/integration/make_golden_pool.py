"""One-shot: turn a real archived campaign into the committed golden fixture.

Run once, commit the output, keep this script for provenance. It is not part of
the test run.

What it does, and why each step is load-bearing:

* **Subsets** to a handful of designs. A full pool's PAE matrices are tens of
  megabytes; the fixture exists to pin behaviour, not to be representative.
* **Relativises** every recorded path. Refold CSVs record absolute paths from
  the machine that produced them — ``/home/<user>/eval_workdir/...`` — which
  both breaks on any other machine and puts a username into a public repo.
* **Quantises** PAE to float16 at 0.25 Å. Halves the bytes and leaves long runs
  of repeated values, which git packs well. 0.25 is exactly representable in
  binary floating point, so the rounding is deterministic across platforms.
* Keeps ``.npy`` and never ``.npz``: the loaders call a bare ``np.load`` and an
  ``NpzFile`` would sail through it and fail later, somewhere less obvious.

Usage:
    python tests/integration/make_golden_pool.py <refold-dir> <out-dir> [n]
"""

from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

import numpy as np

ENGINES = ("boltz2", "af3", "esmfold2")
PAE_QUANTUM = 0.25
_PATH_COLUMNS = ("pae_file", "pdb", "cif", "plddt_file", "structure")


def _shrink_pae(src: Path, dst: Path) -> None:
    a = np.load(src).astype(np.float32)
    dst.parent.mkdir(parents=True, exist_ok=True)
    np.save(dst, (np.round(a / PAE_QUANTUM) * PAE_QUANTUM).astype(np.float16))


def build(refold: Path, out: Path, n: int = 6) -> None:
    out.mkdir(parents=True, exist_ok=True)

    # Choose the designs from the anchor engine, then keep the same sequences
    # across all three so every design is genuinely 3-engine — that is what the
    # cross-engine gate needs to have something to act on.
    with (refold / "boltz2_results.csv").open(newline="") as fh:
        anchor = list(csv.DictReader(fh))[:n]
    keep = {r["sequence"] for r in anchor}

    for engine in ENGINES:
        src_csv = refold / f"{engine}_results.csv"
        with src_csv.open(newline="") as fh:
            reader = csv.DictReader(fh)
            fields = list(reader.fieldnames or [])
            rows = [r for r in reader if r.get("sequence") in keep]

        for row in rows:
            for col in _PATH_COLUMNS:
                raw = (row.get(col) or "").strip()
                if not raw:
                    continue
                # The recorded path is absolute and from another machine. Find
                # it under the archive by its tail, then re-record it RELATIVE
                # to this engine's CSV so the fixture is portable and carries
                # no username.
                parts = Path(raw).parts[1:] if Path(raw).is_absolute() else Path(raw).parts
                found = next(
                    (refold.joinpath(*parts[i:]) for i in range(len(parts)) if refold.joinpath(*parts[i:]).exists()),
                    None,
                )
                if found is None:
                    row[col] = ""
                    continue
                rel = found.relative_to(refold)
                dst = out / rel
                if col == "pae_file":
                    _shrink_pae(found, dst)
                elif dst.suffix in (".pdb", ".cif"):
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(found, dst)
                else:
                    row[col] = ""
                    continue
                row[col] = str(rel)

        with (out / f"{engine}_results.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        print(f"  {engine}: {len(rows)} rows")

    # The FASTA, subset to the same designs.
    src_fa = next((p for p in (refold / "inputs").glob("*.fasta")), None)
    if src_fa:
        out_fa, hdr, buf, kept = out / "sequences.fasta", None, [], 0
        with src_fa.open() as fh, out_fa.open("w") as o:

            def flush():
                nonlocal kept
                if hdr and "".join(buf).strip() in keep:
                    o.write(hdr + "".join(buf))
                    kept += 1

            for line in fh:
                if line.startswith(">"):
                    flush()
                    hdr, buf = line, []
                else:
                    buf.append(line)
            flush()
        print(f"  sequences.fasta: {kept} records")

    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"  total: {total / 1e6:.2f} MB")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    build(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 6)
