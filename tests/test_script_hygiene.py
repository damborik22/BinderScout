"""Repo-hygiene tests for the shell scripts under ``scripts/`` and ``install/``.

Regression guard for audit finding F25: ``scripts/install_pxdesign.sh`` shipped
another user's absolute paths (``/home/david/tools/PXDesign``,
``/home/david/cutlass``, ``/home/david/BindMaster/tests/...``) and ran
``conda env create --force``, which silently deletes and recreates the live
``bindmaster_pxdesign`` env — the env that carries the CPATH/CUTLASS
``activate.d`` hooks written by ``install/install.sh``.

These checks are directory-wide (not file-specific) so they also cover any
future script added to ``scripts/`` or ``install/``.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("scripts", "install")

# A literal user home directory: /home/<name>/ or /Users/<name>/.
# Variable forms ("$HOME", "${HOME}", "/home/$USER", "~") do not match, because
# "$" is outside the character class — those are the portable spellings we want.
USER_HOME_RE = re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+")

# `conda [env] create ... --force` wipes an existing environment without asking.
# House convention (install/install.sh) is: check env_exists, remove it only
# under an explicit --force flag, then create WITHOUT --force.
CONDA_CREATE_RE = re.compile(r"\bconda\s+(?:env\s+)?create\b")


def _shell_files() -> list[Path]:
    files: list[Path] = []
    for d in SCAN_DIRS:
        root = REPO_ROOT / d
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file() and not p.name.startswith("."):
                files.append(p)
    return files


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""  # binary or unreadable: nothing to lint


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """Join backslash continuations and drop comments; keep 1-based line numbers."""
    out: list[tuple[int, str]] = []
    lineno = 0
    buf = ""
    buf_start = 0
    for raw in text.splitlines():
        lineno += 1
        if not buf:
            buf_start = lineno
        stripped = raw.rstrip()
        if stripped.endswith("\\"):
            buf += stripped[:-1] + " "
            continue
        buf += stripped
        line = buf
        buf = ""
        if line.lstrip().startswith("#"):
            continue
        out.append((buf_start, line))
    if buf:
        out.append((buf_start, buf))
    return out


def find_user_home_paths(text: str) -> list[tuple[int, str]]:
    """Return (lineno, matched path) for every hardcoded user home directory."""
    hits = []
    for i, line in enumerate(text.splitlines(), start=1):
        for m in USER_HOME_RE.finditer(line):
            hits.append((i, m.group(0)))
    return hits


def find_forced_conda_creates(text: str) -> list[tuple[int, str]]:
    """Return (lineno, command) for every `conda [env] create` carrying --force."""
    hits = []
    for lineno, line in _logical_lines(text):
        if CONDA_CREATE_RE.search(line) and re.search(r"(?:^|\s)--force(?:=|\s|$)", line):
            hits.append((lineno, line.strip()))
    return hits


@pytest.mark.parametrize("path", _shell_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_hardcoded_user_home_paths(path):
    """No script may carry a developer's own /home/<user>/ path (F25)."""
    hits = find_user_home_paths(_read(path))
    assert not hits, (
        f"{path.relative_to(REPO_ROOT)} contains hardcoded user home path(s): "
        + ", ".join(f"line {n}: {m}" for n, m in hits)
        + ". Derive paths from ${BASH_SOURCE[0]} / $HOME / a required argument instead."
    )


@pytest.mark.parametrize("path", _shell_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_unconditional_conda_env_create_force(path):
    """`conda env create --force` silently destroys a live environment (F25)."""
    hits = find_forced_conda_creates(_read(path))
    assert not hits, (
        f"{path.relative_to(REPO_ROOT)} runs a destructive conda create: "
        + "; ".join(f"line {n}: {c}" for n, c in hits)
        + ". Guard removal behind an explicit --force flag (see install/install.sh "
        "confirm_destructive / FORCE) and create without --force."
    )


def test_detectors_catch_the_original_f25_patterns():
    """Self-test: the detectors above must flag exactly what F25 reported."""
    original = (
        "#!/usr/bin/env bash\n"
        'PXDESIGN_DIR="${1:-/home/david/tools/PXDesign}"\n'
        'CUTLASS_DIR="${CUTLASS_PATH:-/home/david/cutlass}"\n'
        'conda env create -f "$ENV_YAML" --force\n'
        'echo "  python -m pytest /home/david/BindMaster/tests/tools/pxdesign/ -v"\n'
    )
    assert [m for _, m in find_user_home_paths(original)] == [
        "/home/david",
        "/home/david",
        "/home/david",
    ]
    assert len(find_forced_conda_creates(original)) == 1

    portable = (
        'REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)\n'
        'PXDESIGN_DIR="${1:-${REPO_ROOT}/PXDesign}"\n'
        'CUTLASS_DIR="${CUTLASS_PATH:-${HOME}/cutlass}"\n'
        'conda env create -f "$ENV_YAML"\n'
    )
    assert find_user_home_paths(portable) == []
    assert find_forced_conda_creates(portable) == []
