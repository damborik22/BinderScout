"""Location helpers shared by the CLI, the TUI and the configurator (stdlib only).

Three copies of "where is conda?" used to live in binderscout.py, tui/app.py and
configurator/configurator.py, each with a different candidate list, so the same
box was "conda not found" in one and fine in another -- and a miss silently drops
refold engines. This is the one copy.

A conda base is valid when it has ``etc/profile.d/conda.sh``: that is the file every
generated script sources, so it is the thing that has to exist. A caller that also
needs an executable under the base (``bin/conda``) says so with ``require``: a base
that lacks it is skipped, not allowed to shadow one that has it.

Conda envs are not always ``<base>/envs/<name>``; ``find_env_prefix`` is the one place the
Python side asks where an env is, mirroring install.sh's ``bs_env_lookup``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_FIXED_HOME_NAMES = ("miniforge3", "mambaforge", "miniconda3", "anaconda3", "conda")
_FIXED_SYSTEM_DIRS = ("/opt/conda", "/opt/miniforge3", "/opt/miniconda3", "/opt/anaconda3")


def _is_base(path: Path | None, require: str | None = None) -> bool:
    try:
        if path is None or not (path / "etc" / "profile.d" / "conda.sh").is_file():
            return False
        return require is None or (path / require).is_file()
    except OSError:
        return False


def _base_from_env_prefix(prefix: Path) -> Path:
    """``<base>/envs/<name>`` -> ``<base>``; a base prefix is returned unchanged."""
    return prefix.parent.parent if prefix.parent.name == "envs" else prefix


def find_conda_base(
    repo: Path | None = None, environ: dict[str, str] | None = None, require: str | None = None
) -> Path | None:
    """The conda base directory this box should use, or None.

    Order (first valid wins): ``$BINDERSCOUT_CONDA``; the checkout's own ``conda/``
    (standalone install); ``$CONDA_EXE``; ``$CONDA_PREFIX``; ``conda``/``mamba``/
    ``micromamba`` on PATH; then the usual install locations. No subprocess is run.
    With ``require`` (a path relative to the base, e.g. ``"bin/conda"``) a candidate
    lacking that file is skipped, so the first base that has it wins.
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
        if _is_base(base, require):
            return base
    return None


def _condarc_envs_dirs(path: Path) -> list[Path]:
    """The ``envs_dirs`` list of one condarc file (block or inline list), without a YAML parser."""
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    found: list[str] = []
    in_key = False
    for raw in lines:
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not raw[:1].isspace() and not line.lstrip().startswith("-"):
            in_key = False
            key, _, rest = line.partition(":")
            if key.strip() == "envs_dirs":
                rest = rest.strip()
                if rest.startswith("["):
                    found.extend(item for item in rest.strip("[]").split(",") if item.strip())
                else:
                    in_key = True
            continue
        if in_key and line.lstrip().startswith("-"):
            found.append(line.lstrip()[1:])
    return [Path(os.path.expandvars(item.strip().strip("'\""))).expanduser() for item in found if item.strip()]


def find_env_prefix(name: str, base: Path | None, environ: dict[str, str] | None = None) -> Path | None:
    """Where the conda env ``name`` lives, or None.

    An env is not always ``<base>/envs/<name>``: ``$CONDA_ENVS_PATH``, a condarc ``envs_dirs``
    and the per-user ``~/.conda/envs`` all put it elsewhere, and install.sh (``bs_env_lookup``)
    already looks there -- so the wizard and the TUI used to call a tool the installer had just
    finished "not installed". Order: ``$CONDA_ENVS_PATH`` entries, ``<base>/envs``, then the
    ``envs_dirs`` of the condarc files conda reads, then ``~/.conda/envs``. No subprocess is run.
    """
    env = os.environ if environ is None else environ
    dirs: list[Path] = [Path(d).expanduser() for d in env.get("CONDA_ENVS_PATH", "").split(os.pathsep) if d]
    if base is not None:
        dirs.append(Path(base) / "envs")
    try:
        home = Path(env["HOME"]) if env.get("HOME") else Path.home()
    except RuntimeError:  # no resolvable home directory
        home = None
    rcs = [Path(base) / ".condarc"] if base is not None else []
    if home is not None:
        rcs += [home / ".condarc", home / ".conda" / ".condarc", home / ".config" / "conda" / ".condarc"]
    if env.get("CONDARC"):
        rcs.append(Path(env["CONDARC"]).expanduser())
    for rc in rcs:
        dirs.extend(_condarc_envs_dirs(rc))
    if home is not None:
        dirs.append(home / ".conda" / "envs")
    for d in dirs:
        try:
            if (d / name).is_dir():
                return d / name
        except OSError:
            continue
    return None
