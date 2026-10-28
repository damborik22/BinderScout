"""Emit a pip constraints file from an environment's installed distributions.

Run with the TARGET env's interpreter, from the repo root:

    conda/envs/<env>/bin/python -I install/locks/generate.py > install/locks/<env>.txt

-I matters: it keeps the repo's own directory off sys.path, so this cannot
accidentally import repo code instead of the stdlib.

Editable and VCS installs cannot be written as a version constraint, so they are
listed as comments instead. Their paths are emitted REPO-RELATIVE: this file is
tracked in a public repo, and tests/test_script_hygiene.py rejects an absolute
/home/<user> path (CLAUDE.md: no infrastructure identifiers in tracked files).
"""

import importlib.metadata as md
import json
import os
import sys

REPO = os.getcwd()

# Two families are deliberately NEVER emitted. Both were found by running
# `pip install --dry-run` against an early version of these files, not by reasoning,
# and both turned a constraints file into a hard ResolutionImpossible:
#
#   nvidia-*   torch pins each of these with `==` in its own metadata, and to a
#              DIFFERENT version per index — the cu121-index torch 2.5.1 requires
#              nvidia-cuda-nvrtc-cu12==12.1.105, the PyPI torch 2.5.1 requires
#              12.4.127. Constraining them fights torch. Pin torch; torch pins these.
#
#   setuptools / wheel / pip
#              `--index-url` REPLACES PyPI rather than adding to it, and
#              download.pytorch.org serves only torch and its CUDA siblings. A
#              constrained setuptools is then unfindable, so torch's own
#              `depends on setuptools` cannot be satisfied. These versions also have
#              no bearing on results.
#
# The rules live here, not in a post-processing step, so refreshing a lock cannot
# quietly reintroduce them. tests/test_pinned_versions.py asserts they stay out.
INFRA = {"setuptools", "wheel", "pip"}


def excluded(name: str) -> bool:
    return name.lower().startswith("nvidia") or name.lower() in INFRA


# A CUDA local-version label is stripped below. PEP 440: a constraint with no
# local version matches any local version, so `torch==2.5.1` resolves the +cu121
# wheel from download.pytorch.org, while `torch==2.5.1+cu121` is unfindable on
# PyPI and breaks any later PyPI-only install in the same env. pyrosetta is the
# exception — there the local version IS the build identity, and its find-links
# index serves that exact string.


def relative(url: str) -> str:
    """file:///abs/path/inside/repo -> <repo>/path/inside/repo."""
    path = url.removeprefix("file://")
    if path.startswith(REPO):
        return "<repo>" + path[len(REPO) :]
    return url


EVIDENCE_FILE = "install/locks/EVIDENCE.md"

HEADER = """\
# {env} — pip constraints, captured from the working installation.
#
# NOT hand-written and NOT hand-maintained: regenerate, do not edit.
#
#   {python} -I install/locks/generate.py \\
#     > install/locks/{env}.txt
#
# What this is for: install.sh names only a couple of dozen packages explicitly,
# while each env holds anywhere from ~25 to ~236 distributions. The unnamed remainder is where all
# three of this repo's dependency outages came from — BUG-14 (pyrosetta 2026.29
# changed set_interface), BUG-20 (atomworks 3.0.0 deleted AtomSelectionStack) and
# the RUF071 CI failure (ruff 0.17 added a rule) — and no realistic number of
# inline pins reaches it. So the transitive set is pinned here too.
#
# Consumed as `pip install -c install/locks/{env}.txt ...`. A constraints file
# restricts resolution without installing anything, so an entry the install never
# asks for is simply ignored. That makes the file safe to be over-complete, and
# means it needs no edit when install.sh drops a dependency.
#
# Deliberately ABSENT, both because they make resolution impossible rather than
# reproducible (see generate.py for the evidence):
#   * nvidia-*                 torch pins these itself, differently per index
#   * setuptools / wheel / pip --index-url replaces PyPI, which does not serve them
# CUDA local-version labels (+cu121, ...) are stripped for the same reason;
# pyrosetta keeps its label, where the label is the build identity.
#
# Which run this env is evidence for: see {evidence}.
#
"""


def header(env: str) -> str:
    return HEADER.format(env=env, python=interpreter(), evidence=EVIDENCE_FILE)


def env_name() -> str:
    """The lock's name, derived from the running interpreter's prefix.

    A conda env's prefix basename is already the env name. A uv venv's is always
    ".venv", which names nothing, so fall back to the project directory holding
    it (Proteina-Complexa/.venv -> proteina-complexa).
    """
    base = os.path.basename(sys.prefix)
    if base.startswith("."):
        base = os.path.basename(os.path.dirname(sys.prefix)).lower()
    return base


def interpreter() -> str:
    """This interpreter, repo-relative, for the refresh command in the header.

    Taken from sys.executable rather than assembled from a conda/envs/<name>
    template, because the uv venvs do not live under conda/envs at all.
    """
    return relative("file://" + sys.executable)


def main() -> None:
    pinned: set[str] = set()
    unpinnable: set[str] = set()

    for dist in md.distributions():
        name = (dist.metadata["Name"] or "").strip()
        if not name:
            continue
        raw = dist.read_text("direct_url.json")
        info = {}
        if raw:
            try:
                info = json.loads(raw)
            except ValueError:
                info = {}
        if excluded(name):
            continue
        editable = info.get("dir_info", {}).get("editable")
        vcs = info.get("vcs_info", {})
        if editable or vcs:
            where = relative(info.get("url", ""))
            commit = vcs.get("commit_id", "")
            unpinnable.add(f"{name}=={dist.version}  # {where}{'@' + commit if commit else ''}")
            continue
        version = dist.version
        if "+" in version and name.lower() != "pyrosetta":
            version = version.split("+", 1)[0]
        pinned.add(f"{name}=={version}")

    print(header(env_name()), end="")
    print("\n".join(sorted(pinned, key=str.lower)))
    if unpinnable:
        print("\n# Not constrainable (editable or VCS installs) — pinned elsewhere:")
        for line in sorted(unpinnable, key=str.lower):
            print(f"#   {line}")


if __name__ == "__main__":
    main()
