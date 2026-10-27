"""`--verify` must assert what breaks, not what is merely present.

Two arms of ``verify_tool`` were a file count and a file test, and both reported a
tool usable on an environment that cannot produce a single design:

* **BindCraft** was ``(( $(_count_glob params/*.npz) >= 5 ))`` and nothing else.
  PyRosetta 2026.29 changed ``InterfaceAnalyzerMover.set_interface()`` from
  accepting a ``str`` to requiring ``core::pose::DockingPartners``, and
  ``score_interface()`` runs only *after* a full trajectory — so an env with the
  new PyRosetta and an unmigrated call site burned ~8 GPU-minutes per trajectory,
  wrote header-only stats CSVs, and was reported "installed" by this very
  function. Exercised against five empty ``params/*.npz`` and no conda env, the
  old arm said **usable**.

* **Mosaic** was ``[[ -x .venv/bin/python ]]`` — the existence of an interpreter.
  ``esm2quinox`` 0.2.0 rewrote the private token table that
  ``mosaic/losses/esm.py`` indexes with ``"b"``/``"e"``/``"m"`` against a
  hardcoded one-hot width of 33, and that loss is on by default, so the venv
  reported usable while the first optimisation step raised ``KeyError: 'b'``.

The tests drive the real ``verify_tool`` out of the installer against fake trees,
rather than grepping for a string, because the defect was behavioural: the
function returned 0. They are parametrised over both installers — the verify
family is required to be byte-identical across them
(``tests/test_installers_do_not_drift.py``), so a fix that lands in one only is
itself a defect.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
INSTALLERS = [REPO / "install" / "install.sh", REPO / "install" / "install_aarch.sh"]

# Enough of the verify family to reach the bindcraft and mosaic arms. The other arms
# are parsed but never expanded, so their variables need not exist.
_NEEDED = ("_env_python_ok", "_count_glob", "verify_tool")


def _function_source(path: Path, name: str) -> str:
    m = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}\n", path.read_text(), re.S | re.M)
    assert m, f"{path.name} does not define {name}()"
    return m.group(0)


def _run_verify_tool(installer: Path, root: Path, tool: str, env_exists: bool = False) -> tuple[int, str]:
    """Call the installer's own verify_tool() against a fake tree under `root`.

    `env_exists=False` is the "nothing is installed" case. Pass True when the fake
    tree has an interpreter at ${CONDA_BASE}/envs/<env>/bin/python: _env_python_ok
    returns 1 on a missing env BEFORE it runs any code, so with the default the
    probe expressions are never evaluated and a mutated probe still passes.
    """
    harness = [
        "set -u",
        f'BINDCRAFT_DIR="{root}/BindCraft"',
        f'MOSAIC_DIR="{root}/Mosaic"',
        f'CONDA_BASE="{root}/conda"',
        'VERIFY_REASON=""',
        # A verifier that needs a conda env must say so instead of returning 0.
        f"env_exists() {{ return {0 if env_exists else 1}; }}",
    ]
    harness += [_function_source(installer, n) for n in _NEEDED]
    harness += [
        f'verify_tool "{tool}"',
        "rc=$?",
        'printf "RC=%s\\nREASON=%s\\n" "${rc}" "${VERIFY_REASON}"',
    ]
    proc = subprocess.run(
        ["bash", "-c", "\n".join(harness)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    rc = int(re.search(r"^RC=(\d+)$", proc.stdout, re.M).group(1))
    reason = re.search(r"^REASON=(.*)$", proc.stdout, re.M).group(1)
    return rc, reason


@pytest.mark.parametrize("installer", INSTALLERS, ids=lambda p: p.name)
def test_bindcraft_is_not_verified_by_counting_weight_files(installer, tmp_path):
    """Five .npz files are not evidence BindCraft can produce a design."""
    params = tmp_path / "BindCraft" / "params"
    params.mkdir(parents=True)
    for i in range(5):
        (params / f"params_model_{i}.npz").write_bytes(b"")
    functions = tmp_path / "BindCraft" / "functions"
    functions.mkdir(parents=True)
    # The unmigrated upstream call site, verbatim.
    (functions / "pyrosetta_utils.py").write_text('    iam.set_interface("A_B")\n')

    rc, reason = _run_verify_tool(installer, tmp_path, "bindcraft")
    assert rc != 0, (
        "verify_tool reported BindCraft usable on a tree with five empty weight files "
        "and no conda env — the shape that burns 8 GPU-minutes per trajectory and "
        "delivers zero designs"
    )
    assert "pyrosetta" in reason.lower(), f"the reason does not mention PyRosetta: {reason!r}"


@pytest.mark.parametrize("installer", INSTALLERS, ids=lambda p: p.name)
def test_mosaic_is_not_verified_by_the_existence_of_an_interpreter(installer, tmp_path):
    """A venv whose default-enabled ESM2 prior dies on batch 1 is not usable."""
    venv_bin = tmp_path / "Mosaic" / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    # An interpreter that exists and refuses every import — i.e. a venv missing the
    # token table the ESM prior indexes.
    python = venv_bin / "python"
    python.write_text("#!/bin/sh\nexit 1\n")
    python.chmod(0o755)

    rc, reason = _run_verify_tool(installer, tmp_path, "mosaic")
    assert rc != 0, (
        "verify_tool reported Mosaic usable on a venv whose interpreter cannot import "
        "esm2quinox — the ESM2 prior is on by default and raises KeyError on the first "
        "optimisation step"
    )
    assert "esm2quinox" in reason, f"the reason does not name esm2quinox: {reason!r}"


@pytest.mark.parametrize("installer", INSTALLERS, ids=lambda p: p.name)
def test_an_absent_bindcraft_still_fails_on_the_weights_first(installer, tmp_path):
    """The weight count is still the first thing checked, and still reported.

    Guards against the stronger PyRosetta probe shadowing the original message on a
    tree where the AF2 download never finished.
    """
    (tmp_path / "BindCraft" / "params").mkdir(parents=True)
    rc, reason = _run_verify_tool(installer, tmp_path, "bindcraft")
    assert rc != 0
    assert ".npz" in reason, f"expected the weights reason, got {reason!r}"


# --- The discriminating branches, with an env that EXISTS -------------------
#
# Everything above runs with `env_exists() { return 1; }`, so `_env_python_ok`
# returns 1 before it ever launches an interpreter. That pins "verify needs a
# working env" -- a property the OLD arms already failed -- but NOT the probe
# logic itself. Measured by mutation: replacing the whole BindCraft agreement
# probe with `sys.exit(0)`, and reducing the Mosaic check to `python -c "pass"`,
# left every test above green. The harness below gives the fake tree a real
# interpreter with a stub module, so the probe's own expression decides.

_OLD_API_PYROSETTA = '''
class _Mover:
    def set_interface(self, spec: str) -> None:
        """set_interface(self: InterfaceAnalyzerMover, interface_id: str) -> None"""
'''
_NEW_API_PYROSETTA = '''
class _Mover:
    def set_interface(self, partners) -> None:
        """set_interface(self: InterfaceAnalyzerMover, partners: core::pose::DockingPartners) -> None"""
'''


def _stub_pyrosetta(root: Path, body: str) -> Path:
    """A `pyrosetta` package exposing InterfaceAnalyzerMover with a chosen docstring.

    The probe reads `M.set_interface.__doc__` and looks for ': str', so the
    docstring IS the API signal it reads on a real install.
    """
    pkg = root / "stub" / "pyrosetta" / "rosetta" / "protocols" / "analysis"
    pkg.mkdir(parents=True)
    for part in (root / "stub" / "pyrosetta", pkg.parent.parent, pkg.parent, pkg):
        (part / "__init__.py").touch(exist_ok=True)
    (pkg / "__init__.py").write_text(f"{body}\nInterfaceAnalyzerMover = _Mover\n")
    return root / "stub"


def _fake_env_python(root: Path, env: str, stub_dir: Path) -> None:
    """Install a real python3 at ${CONDA_BASE}/envs/<env>/bin/python with stub_dir first."""
    bin_dir = root / "conda" / "envs" / env / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    python = bin_dir / "python"
    python.write_text(f'#!/bin/sh\nexec env PYTHONPATH="{stub_dir}" {sys.executable} "$@"\n')
    python.chmod(0o755)


def _bindcraft_tree(root: Path, call_site: str) -> None:
    params = root / "BindCraft" / "params"
    params.mkdir(parents=True, exist_ok=True)
    for i in range(5):
        (params / f"params_model_{i}.npz").write_bytes(b"")
    functions = root / "BindCraft" / "functions"
    functions.mkdir(parents=True, exist_ok=True)
    (functions / "pyrosetta_utils.py").write_text(call_site)


_UNPATCHED_CALL_SITE = '    iam.set_interface("A_B")\n'
_PATCHED_CALL_SITE = (
    "    try:\n"
    "        from pyrosetta.rosetta.core.pose import DockingPartners\n"
    '        iam.set_interface(DockingPartners.docking_partners_from_string("A_B"))\n'
    "    except ImportError:\n"
    '        iam.set_interface("A_B")\n'
)


@pytest.mark.parametrize("installer", INSTALLERS, ids=lambda p: p.name)
def test_the_bindcraft_probe_fails_a_new_api_pyrosetta_against_an_unpatched_call_site(installer, tmp_path):
    """This is BUG-14 exactly: both halves present, disagreeing.

    The env imports pyrosetta fine and the weights are all there, so every
    earlier arm passes. Only the agreement probe can catch it.
    """
    _bindcraft_tree(tmp_path, _UNPATCHED_CALL_SITE)
    _fake_env_python(tmp_path, "BindCraft", _stub_pyrosetta(tmp_path, _NEW_API_PYROSETTA))

    rc, reason = _run_verify_tool(installer, tmp_path, "bindcraft", env_exists=True)
    assert rc != 0, (
        "verify_tool reported BindCraft usable with a DockingPartners-only PyRosetta and "
        "an unmigrated call site — the exact shape that yields zero designs after a full "
        "GPU trajectory"
    )
    assert "set_interface" in reason, f"the reason does not name the call: {reason!r}"


@pytest.mark.parametrize("installer", INSTALLERS, ids=lambda p: p.name)
def test_the_bindcraft_probe_passes_when_the_two_sides_agree(installer, tmp_path):
    """Both agreeing shapes must verify, or --repair would loop on a healthy env."""
    stub_old = _stub_pyrosetta(tmp_path / "old", _OLD_API_PYROSETTA)
    _bindcraft_tree(tmp_path / "old", _UNPATCHED_CALL_SITE)
    _fake_env_python(tmp_path / "old", "BindCraft", stub_old)
    rc, reason = _run_verify_tool(installer, tmp_path / "old", "bindcraft", env_exists=True)
    assert rc == 0, f"old-API PyRosetta with the upstream call site must verify: {reason!r}"

    stub_new = _stub_pyrosetta(tmp_path / "new", _NEW_API_PYROSETTA)
    _bindcraft_tree(tmp_path / "new", _PATCHED_CALL_SITE)
    _fake_env_python(tmp_path / "new", "BindCraft", stub_new)
    rc, reason = _run_verify_tool(installer, tmp_path / "new", "bindcraft", env_exists=True)
    assert rc == 0, f"new-API PyRosetta with the migrated call site must verify: {reason!r}"


# Exactly 33 unique keys including 'b'/'e'/'m': the width mosaic/losses/esm.py
# hardcodes for its one-hot, and the keys it indexes.
_GOOD_ESM2QUINOX = "_alphabet = {k: i for i, k in enumerate('ACDEFGHIKLMNPQRSTVWYXBUZO-.|<>bem')}\n"
# 32 keys, '^'/'$'/'#' instead -- esm2quinox 0.2.0's table.
_BAD_ESM2QUINOX = "_alphabet = {k: i for i, k in enumerate('ACDEFGHIKLMNPQRSTVWYXBUZO-.|<^$#')}\n"


def _mosaic_venv(root: Path, alphabet: str) -> None:
    stub = root / "stub"
    (stub / "esm2quinox").mkdir(parents=True)
    (stub / "esm2quinox" / "__init__.py").touch()
    (stub / "esm2quinox" / "_esm2.py").write_text(alphabet)
    venv_bin = root / "Mosaic" / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    python = venv_bin / "python"
    python.write_text(f'#!/bin/sh\nexec env PYTHONPATH="{stub}" {sys.executable} "$@"\n')
    python.chmod(0o755)


@pytest.mark.parametrize("installer", INSTALLERS, ids=lambda p: p.name)
def test_the_mosaic_probe_reads_the_token_table_not_just_the_import(installer, tmp_path):
    """esm2quinox 0.2.0's table imports fine and still breaks the default ESM2 prior."""
    _mosaic_venv(tmp_path / "bad", _BAD_ESM2QUINOX)
    rc, reason = _run_verify_tool(installer, tmp_path / "bad", "mosaic", env_exists=True)
    assert rc != 0, (
        "verify_tool reported Mosaic usable against the 0.2.0 token table — importable, "
        "32 entries keyed '^'/'$'/'#', and KeyError on the first optimisation step"
    )
    assert "esm2quinox" in reason, f"the reason does not name esm2quinox: {reason!r}"

    _mosaic_venv(tmp_path / "good", _GOOD_ESM2QUINOX)
    rc, reason = _run_verify_tool(installer, tmp_path / "good", "mosaic", env_exists=True)
    assert rc == 0, f"the 33-entry table keyed 'b'/'e'/'m' must verify: {reason!r}"
