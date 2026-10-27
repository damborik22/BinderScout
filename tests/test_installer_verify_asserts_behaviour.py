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


def _run_verify_tool(installer: Path, root: Path, tool: str) -> tuple[int, str]:
    """Call the installer's own verify_tool() against a fake tree under `root`."""
    harness = [
        "set -u",
        f'BINDCRAFT_DIR="{root}/BindCraft"',
        f'MOSAIC_DIR="{root}/Mosaic"',
        f'CONDA_BASE="{root}/conda"',
        'VERIFY_REASON=""',
        # No conda env exists in the fake tree, which is the point: a verifier that
        # needs one must say so instead of returning 0.
        "env_exists() { return 1; }",
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
