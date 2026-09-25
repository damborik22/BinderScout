"""No file may send an operator to a conda env the installer never creates.

Found by auditing CLAUDE.md's checkable claims: ``binder-eval-boltz2`` was named
in two module docstrings and one CLAUDE.md line as the environment to run the
Boltz-2 refold in. The installer has never created it. Boltz-2 refolding runs in
the **Mosaic venv** — ``evaluate.sh`` calls ``$MOSAIC_VENV/bin/binder-compare``,
and CLAUDE.md says elsewhere, in the same file, "must use Mosaic venv, NOT
conda".

So the instruction was not merely stale, it was self-contradicting within one
document, and following it gives "env not found" after the reader has already
decided that is what they should do.

This pins the environment vocabulary: a name appearing in a `conda run -n X` or
"'X' conda environment" instruction must be one this project actually builds.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The environments this project creates. Mirrors CLAUDE.md's "Environment
# isolation" table; Mosaic, BindCraft 2 and Proteina-Complexa use venvs, not
# conda, and so are deliberately absent.
REAL_ENVS = {
    "BindCraft",
    "BoltzGen",
    "binder-eval",
    "binder-eval-af3",
    "binder-eval-esmfold2",
    "binder-eval-soluprot",
    "binder-eval-tmprot",
    "binderscout_protein_hunter",
    "binderscout_pxdesign",
    "binderscout_rfd3",
}

# Names that appear as placeholders/defaults rather than real instructions.
IGNORE = {"base", "ENV", "NAME", "X", "$ENV", "${ENV}"}

# English that can follow "conda activate"/"conda run -n" in prose. Kept
# explicit so a real env name can never be excused by a pattern.
PROSE_WORDS = {"for", "the", "a", "an", "and", "in", "to", "it", "this", "that", "your", "each"}

PATTERNS = [
    re.compile(r"conda run -n ([A-Za-z0-9_.\-]+)"),
    re.compile(r"conda activate ([A-Za-z0-9_.\-]+)"),
    re.compile(r"'([A-Za-z0-9_.\-]+)' conda environment"),
]

SEARCH_SUFFIXES = {".py", ".md", ".sh", ".template"}


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True)
    return out.stdout.split()


def test_every_referenced_conda_env_is_one_we_build():
    offenders: dict[str, set[str]] = {}
    for rel in _tracked():
        path = REPO / rel
        if path.suffix not in SEARCH_SUFFIXES or not path.is_file():
            continue
        # This file names the bad env on purpose, to describe the bug.
        if rel == "tests/test_referenced_conda_envs_exist.py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pat in PATTERNS:
            for name in pat.findall(text):
                if name in REAL_ENVS or name in IGNORE or name.startswith(("$", "{", "%")):
                    continue
                # An explicit stoplist, NOT a lowercase heuristic. The earlier
                # rule ("a bare lowercase word is prose") let `conda activate
                # mosaic` through -- which is the single highest-value case
                # here, since Mosaic is a uv VENV and not a conda env at all --
                # and `boltzgen`, one character-class away from the real
                # BoltzGen.
                if name in PROSE_WORDS:
                    continue
                offenders.setdefault(rel, set()).add(name)

    assert not offenders, (
        "file(s) instruct the reader to use a conda env this project does not create:\n"
        + "\n".join(f"  {rel}: {', '.join(sorted(v))}" for rel, v in sorted(offenders.items()))
        + "\nEither the env is missing from the installer, or the instruction is stale."
    )
