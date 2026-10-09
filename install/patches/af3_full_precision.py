#!/usr/bin/env python3
"""Make AlphaFold 3 write its confidence scores at full precision.

WHY THIS EXISTS. Upstream AF3 rounds every confidence value it writes to TWO decimals
(``np.round(..., decimals=2)`` in ``alphafold3/model/confidence_types.py``), so iPTM, pTM and
ranking_score reach us as 0.87, not 0.868557. Measured on the 563-design Adaptyv benchmark, AF3
had 81 distinct iPTM values against 563 for each of the other engines, with one tie block of 29.
Every rank-based metric therefore understated AF3 against engines that report full precision.
Some builds also round the PAE matrix to ONE decimal; that is patched where present.

This is an edit to the installed package, so it is lost whenever AF3 is reinstalled. The
installers re-apply it on every ``install_af3`` and ``--verify`` re-checks it. It runs as a
script file, never as a heredoc: ``conda run`` does not forward stdin, so a heredoc-fed patch
executes nothing and still exits 0 (the PXDesign patches were silently skipped that way).

Usage (inside the binder-eval-af3 env):
    python af3_full_precision.py           apply (idempotent), then verify; exit 1 on any failure
    python af3_full_precision.py --check   report only; exit 0 iff the package is at full precision
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

# (old, new, required). A required edit must be present in either form: if neither is found the
# upstream source changed and this patch no longer describes it, which must fail loudly rather
# than report success. An optional edit exists only in some builds and may be absent.
EDITS = (
    (
        "rounded_data = np.round(data.astype(np.float64), decimals=2).tolist()",
        "rounded_data = np.round(data.astype(np.float64), decimals=6).tolist()",
        True,
    ),
    (
        "rounded_data = np.round(data, decimals=2)",
        "rounded_data = np.round(data, decimals=6)",
        True,
    ),
    (
        "np.clip(np.asarray(o.pae, dtype=np.float64), 0.0, 99.9), 1",
        "np.clip(np.asarray(o.pae, dtype=np.float64), 0.0, 99.9), 3",
        False,
    ),
)


def locate() -> pathlib.Path:
    """Find confidence_types.py WITHOUT importing alphafold3 (which would load JAX)."""
    spec = importlib.util.find_spec("alphafold3")
    if spec is None or not spec.submodule_search_locations:
        raise SystemExit("FAILED: alphafold3 is not installed in this environment")
    path = pathlib.Path(next(iter(spec.submodule_search_locations))) / "model" / "confidence_types.py"
    if not path.is_file():
        raise SystemExit(f"FAILED: {path} does not exist")
    return path


def classify(text: str) -> dict[str, str]:
    """Per edit: 'patched', 'unpatched' or 'absent'."""
    out = {}
    for old, new, _ in EDITS:
        out[old] = "patched" if new in text else ("unpatched" if old in text else "absent")
    return out


def problems(text: str) -> list[str]:
    bad = []
    for old, _new, required in EDITS:
        state = classify(text)[old]
        if state == "unpatched":
            bad.append(f"not patched: {old}")
        elif state == "absent" and required:
            bad.append(f"required code not found (upstream changed?): {old}")
    return bad


def main(argv: list[str]) -> int:
    path = locate()
    text = path.read_text()
    if "--check" in argv:
        bad = problems(text)
        for line in bad:
            print(f"  {line}")
        print(f"{path}: {'FULL PRECISION' if not bad else 'ROUNDED (not patched)'}")
        return 1 if bad else 0

    backup = path.with_name(path.name + ".orig")
    if not backup.exists():
        backup.write_text(text)
    applied = 0
    for old, new, _ in EDITS:
        if classify(text)[old] == "unpatched":
            if text.count(old) != 1:
                raise SystemExit(f"FAILED: expected exactly one occurrence of {old!r}, found {text.count(old)}")
            text = text.replace(old, new)
            applied += 1
    path.write_text(text)
    # Verify what is on disk, not what we think we wrote.
    bad = problems(path.read_text())
    if bad or "decimals=2" in path.read_text():
        for line in bad:
            print(f"  {line}")
        raise SystemExit("FAILED: AF3 would still round its confidence scores")
    print(f"{path}: {applied} edit(s) applied; confidence scores are now written at full precision")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
