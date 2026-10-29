"""CI's hand-written test-dependency list must keep mirroring what the package declares.

`.github/workflows/ci.yml` does not install `Evaluator/`. Its `pytest` job pip-installs a list typed
in by hand, under a comment saying the list "must mirror Evaluator/pyproject.toml
[project.dependencies]". Nothing enforced the comment, and the two have drifted before: matplotlib
was declared but fell out of the CI list in a reland (976b853), and `requests` was imported at module
level yet named in neither file (930cedb), which turned master's CI red at collection.

Both of those were loud, because `pytest` stops at collection without any one of the four dependencies
the package declares today. A dependency the package imports behind a guard is not loud: the tests that
need it skip and the job stays green. `test_af3_env.py` already skips six tests for want of `gemmi`,
and `pytest -q` still exits 0. So this pins that every declared dependency is installed by the CI job,
whatever the package happens to do with it.

It also pins the versions. pyproject declares ceilings rather than `==` pins (it is editable-installed
into four envs on two Pythons); the CI pins are the versions verified green. A pin that climbs past its
ceiling leaves CI green on a configuration `pip install -e Evaluator` can never produce, so what was
certified is not what ships.

The mirror is one-directional on purpose: CI also installs pytest and PyYAML, which the package does
not declare. And if CI ever installs the package itself (`pip install -e Evaluator`) the two lists
become one and this file should simply be deleted.
"""

import re
import shlex
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

REPO = Path(__file__).resolve().parents[1]
CI_YML = REPO / ".github" / "workflows" / "ci.yml"
PYPROJECT = REPO / "Evaluator" / "pyproject.toml"


def _pip_installs_of_the_pytest_job(workflow: str) -> dict[str, SpecifierSet]:
    """Everything the workflow's `pytest` job pip-installs: canonical name -> specifier.

    Read the way the job's shell would read it: comment lines dropped, backslash continuations
    joined, the rest split into words. Words that are not requirements (options, paths, URLs) are
    skipped. Only the `pytest` job counts; the `ruff` job installs things too.
    """
    job = re.search(r"^  pytest:\n(.*?)(?=^  [^\s#]|\Z)", workflow, re.S | re.M)
    if job is None:
        return {}
    body = "\n".join(ln for ln in job.group(1).splitlines() if not ln.lstrip().startswith("#"))
    installed = {}
    for command in re.finditer(r"\bpip install\b((?:[^\n]*\\\n)*[^\n]*)", body):
        for word in shlex.split(command.group(1).replace("\\\n", " "), comments=True):
            try:
                requirement = Requirement(word)
            except InvalidRequirement:
                continue  # an option (--no-cache-dir), a path, a URL: not a requirement
            installed[canonicalize_name(requirement.name)] = requirement.specifier
    return installed


def _ci_installs() -> dict[str, SpecifierSet]:
    installed = _pip_installs_of_the_pytest_job(CI_YML.read_text(encoding="utf-8"))
    assert installed, (
        "found no `pip install` in the `pytest` job of .github/workflows/ci.yml. If the job was "
        "renamed or now installs the package itself, this test has nothing left to guard: update "
        "or delete it, do not let it pass on an empty list."
    )
    return installed


def _declared() -> dict[str, SpecifierSet]:
    """[project.dependencies] of Evaluator/pyproject.toml: canonical name -> specifier."""
    try:
        import tomllib
    except ModuleNotFoundError:  # CPython 3.10, which CI runs; pytest itself requires tomli there
        import tomli as tomllib
    with PYPROJECT.open("rb") as fh:
        entries = tomllib.load(fh).get("project", {}).get("dependencies", [])
    assert entries, "Evaluator/pyproject.toml declares no [project.dependencies]; nothing to mirror"
    return {canonicalize_name(r.name): r.specifier for r in map(Requirement, entries)}


def _exact_pin(spec: SpecifierSet) -> Version | None:
    """The one version an `==X.Y.Z` specifier names; None for a range or anything else."""
    if len(spec) == 1:
        (only,) = spec
        if only.operator == "==" and "*" not in only.version:
            return Version(only.version)
    return None


_WORKFLOW = r"""
name: CI
jobs:
  ruff:
    runs-on: ubuntu-24.04
    steps:
      - run: pip install ruff==0.17.3 decoy-in-another-job==1.0
  pytest:
    runs-on: ubuntu-24.04
    steps:
      - name: Install test deps
        # Not `pip install -e Evaluator`: a comment that names the command is not the command.
        # pip install decoy-in-a-comment==1.0
        run: |
          pip install --no-cache-dir \
            pytest==9.1.1 \
            Some_Package==2.0.1\
            numpy==2.2.6  # verified
      - name: Run unit tests
        run: python -m pytest -q
  docker-build:
    runs-on: ubuntu-24.04
    steps:
      - run: pip install decoy-in-the-last-job==1.0
"""


def test_the_pip_install_reader_counts_only_the_pytest_job_and_only_real_requirements():
    """Guard the reader, so the two checks below cannot pass because it over- or under-collects.

    The workflow above is shaped like the real ci.yml: a `ruff` job that pip-installs too, a comment
    block above the list, a backslash-continued command, and a job after `pytest`. It adds an option
    (`--no-cache-dir`), a trailing comment and a continuation with no space before its backslash, none
    of which the real list uses yet.
    """
    installed = _pip_installs_of_the_pytest_job(_WORKFLOW)

    assert {name: str(spec) for name, spec in installed.items()} == {
        "pytest": "==9.1.1",
        "some-package": "==2.0.1",
        "numpy": "==2.2.6",
    }


def test_every_dependency_the_package_declares_is_installed_by_the_ci_pytest_job():
    installed = _ci_installs()
    missing = sorted(set(_declared()) - set(installed))

    assert not missing, (
        f"Evaluator/pyproject.toml declares {missing} as runtime dependencies, but the `pytest` job in "
        ".github/workflows/ci.yml never installs them (it installs "
        f"{sorted(installed)}). CI installs a hand-written list instead of the package, so the suite "
        "runs without them: an unguarded import fails collection, a guarded one makes its tests skip "
        "and the job stays green. Add them to that list, pinned."
    )


def test_every_ci_pin_of_a_declared_dependency_lies_inside_the_declared_range():
    installed = _ci_installs()
    problems = []
    for name, allowed in sorted(_declared().items()):
        if name not in installed:
            continue  # the test above reports it
        pin = _exact_pin(installed[name])
        if pin is None:
            problems.append(f"{name}: ci.yml installs '{installed[name]}', which is not an exact == pin")
        elif not allowed.contains(pin, prereleases=True):
            problems.append(f"{name}: ci.yml pins {pin}, outside the declared '{allowed}'")

    assert not problems, (
        "ci.yml and Evaluator/pyproject.toml disagree:\n  "
        + "\n  ".join(problems)
        + "\nEach must be an exact == pin inside the range pyproject declares; outside it, CI is green on "
        "a configuration `pip install -e Evaluator` cannot produce. Move the pin and the range together, "
        "in one commit."
    )
