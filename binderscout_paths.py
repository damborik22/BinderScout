"""Location helpers shared by the CLI, the TUI and the configurator (stdlib only).

Three copies of "where is conda?" used to live in binderscout.py, tui/app.py and
configurator/configurator.py, each with a different candidate list, so the same
box was "conda not found" in one and fine in another -- and a miss silently drops
refold engines. This is the one copy.

A conda base is valid when it has ``etc/profile.d/conda.sh``: that is the file every
generated script sources, so it is the thing that has to exist.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_FIXED_HOME_NAMES = ("miniforge3", "mambaforge", "miniconda3", "anaconda3", "conda")
_FIXED_SYSTEM_DIRS = ("/opt/conda", "/opt/miniforge3", "/opt/miniconda3", "/opt/anaconda3")


def _is_base(path: Path | None) -> bool:
    try:
        return path is not None and (path / "etc" / "profile.d" / "conda.sh").is_file()
    except OSError:
        return False


def _base_from_env_prefix(prefix: Path) -> Path:
    """``<base>/envs/<name>`` -> ``<base>``; a base prefix is returned unchanged."""
    return prefix.parent.parent if prefix.parent.name == "envs" else prefix


def find_conda_base(repo: Path | None = None, environ: dict[str, str] | None = None) -> Path | None:
    """The conda base directory this box should use, or None.

    Order (first valid wins): ``$BINDERSCOUT_CONDA``; the checkout's own ``conda/``
    (standalone install); ``$CONDA_EXE``; ``$CONDA_PREFIX``; ``conda``/``mamba``/
    ``micromamba`` on PATH; then the usual install locations. No subprocess is run.
    """
    env = os.environ if environ is None else environ
    candidates: list[Path] = []
    if env.get("BINDERSCOUT_CONDA"):
        candidates.append(Path(env["BINDERSCOUT_CONDA"]).expanduser())
    if repo is not None:
        candidates.append(Path(repo) / "conda")
    if env.get("CONDA_EXE"):
        candidates.append(Path(env["CONDA_EXE"]).resolve().parent.parent)
    if env.get("CONDA_PREFIX"):
        candidates.append(_base_from_env_prefix(Path(env["CONDA_PREFIX"])))
    for tool in ("conda", "mamba", "micromamba"):
        found = shutil.which(tool, path=env.get("PATH"))
        if found:
            candidates.append(Path(found).resolve().parent.parent)
    try:
        home = Path.home()
        candidates.extend(home / name for name in _FIXED_HOME_NAMES)
    except RuntimeError:  # no resolvable home directory
        pass
    candidates.extend(Path(p) for p in _FIXED_SYSTEM_DIRS)
    for base in candidates:
        if _is_base(base):
            return base
    return None
