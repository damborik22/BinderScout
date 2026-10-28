"""Pinned code against a floating dependency is this project's most productive bug.

Three outages in one audit came from a dependency nobody had named:

* ``pyrosetta`` — the 2026.29 quarterly changed
  ``InterfaceAnalyzerMover.set_interface()`` from accepting a ``str`` to requiring
  ``core::pose::DockingPartners``. ``BINDCRAFT_COMMIT`` was pinned; PyRosetta was
  not, so BindCraft produced **zero designs** on any fresh install, each
  trajectory dying after ~8 minutes of GPU.
* ``atomworks`` — 3.0.0 (2026-10-05) deleted ``AtomSelectionStack``, which
  Proteina-Complexa's ``pdb_utils.py`` imports at module level. Upstream installs
  it unpinned, so every install from that date on could not generate at all.
* ``esm2quinox`` — 0.2.0 rewrote the private token table Mosaic's ESM2 prior
  indexes (32 entries keyed ``"^"``/``"$"``/``"#"`` instead of 33 keyed
  ``"b"``/``"e"``/``"m"``, against a hardcoded one-hot width of 33), so a fresh
  resolve dies with ``KeyError: 'b'`` on the first optimisation step.

Each was invisible to the installer's own smoke test, because each smoke test
imported a package whose top level does not reach the broken symbol. So these
tests check two things: that the version is pinned somewhere a reader will find
it, and that the check guarding it asserts the **symbol** rather than the
success of an import.

Deliberately NOT covered: a captured constraints tree for every environment.
``install/locks/`` does not exist on this branch, and the 1.0.x line's ten files
are named for the pre-2.0 environments and have no entry for TmProt or the
renamed envs, so they would have to be regenerated against live environments.
Untested lock files are worse than none — the first Mosaic lock pinned the
*broken* esm2quinox because it was captured from an install that had never been
run.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
X86 = REPO / "install" / "install.sh"
ARM = REPO / "install" / "install_aarch.sh"
INSTALLERS = [X86, ARM]


def _assign(path: Path, name: str) -> str | None:
    m = re.search(rf'^{re.escape(name)}="([^"]*)"', path.read_text(), re.M)
    return m.group(1) if m else None


def _function_source(path: Path, name: str) -> str:
    m = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}\n", path.read_text(), re.S | re.M)
    assert m, f"{path.name} does not define {name}()"
    return m.group(0)


def _run_bash(lines: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", "\n".join(lines)], capture_output=True, text=True, timeout=180)


_STUB_PRINTERS = [
    'print_ok() { echo "OK: $*"; }',
    'print_warn() { echo "WARN: $*"; }',
    'print_fail() { echo "FAIL: $*"; }',
]


class TestPyRosettaIsPinnedAndTheCallSiteMigrated:
    """BUG-14, the blocker: BindCraft yielded zero designs on a fresh install."""

    def test_pyrosetta_is_pinned_next_to_the_bindcraft_commit(self):
        version = _assign(X86, "PYROSETTA_VERSION")
        assert version, "install.sh does not pin PYROSETTA_VERSION"
        assert re.match(r"^\d{4}\.\d+\+", version), f"PYROSETTA_VERSION={version!r} is not a concrete quarterly version"
        text = X86.read_text()
        # Adjacency is the point: the repo commit and the dependency version have to
        # agree, so they must be readable together.
        bc = text.index('BINDCRAFT_COMMIT="')
        pr = text.index('PYROSETTA_VERSION="')
        assert 0 < pr - bc < 1500, "PYROSETTA_VERSION is not next to BINDCRAFT_COMMIT"

    def test_the_pin_reaches_bindcrafts_own_installer(self, tmp_path):
        """BindCraft's installer creates the conda env itself, so the pin has to be
        sed'd into their line — there is no env to pre-install a wheel into."""
        bc = tmp_path / "BindCraft"
        bc.mkdir()
        (bc / "install_bindcraft.sh").write_text(
            'pip install pyrosetta --find-links https://example.invalid/quarterly\npython -c "import pyrosetta"\n'
        )
        version = _assign(X86, "PYROSETTA_VERSION")
        links = _assign(X86, "PYROSETTA_FIND_LINKS")
        proc = _run_bash(
            [
                f'BINDCRAFT_DIR="{bc}"',
                f'PYROSETTA_VERSION="{version}"',
                f'PYROSETTA_FIND_LINKS="{links}"',
                *_STUB_PRINTERS,
                _function_source(X86, "_pin_bindcraft_pyrosetta"),
                "_pin_bindcraft_pyrosetta",
                # Twice: the installer re-runs over an existing clone.
                "_pin_bindcraft_pyrosetta",
            ]
        )
        assert proc.returncode == 0, proc.stderr
        pinned = (bc / "install_bindcraft.sh").read_text()
        assert f'pip install "pyrosetta=={version}"' in pinned, pinned
        assert "pip install pyrosetta --find-links" not in pinned, "the unpinned line survived"

    def test_the_one_call_site_is_migrated_back_compatibly(self, tmp_path):
        """The migration must keep working on an env that predates the pin: the
        installer also runs over environments that are already built."""
        functions = tmp_path / "BindCraft" / "functions"
        functions.mkdir(parents=True)
        f = functions / "pyrosetta_utils.py"
        f.write_text(
            "def score_interface(pdb_file, binder_chain='B'):\n"
            "    iam = InterfaceAnalyzerMover()\n"
            '    iam.set_interface("A_B")\n'
            "    return iam\n"
        )
        proc = _run_bash(
            [
                f'BINDCRAFT_DIR="{tmp_path / "BindCraft"}"',
                *_STUB_PRINTERS,
                _function_source(X86, "_patch_bindcraft_pyrosetta"),
                "_patch_bindcraft_pyrosetta",
                "_patch_bindcraft_pyrosetta",  # idempotent
            ]
        )
        assert proc.returncode == 0, proc.stderr
        patched = f.read_text()
        ast.parse(patched)  # a broken indent here costs a whole campaign
        assert "DockingPartners.docking_partners_from_string" in patched
        assert "except ImportError" in patched, "no fallback for PyRosetta < 2026.29"
        assert 'iam.set_interface("A_B")' in patched, "the old form must remain as fallback"
        assert patched.count("DockingPartners.docking_partners_from_string") == 1, (
            "re-running the patch duplicated the migration"
        )

    def test_a_tree_without_the_expected_call_site_is_not_silently_declared_patched(self, tmp_path):
        functions = tmp_path / "BindCraft" / "functions"
        functions.mkdir(parents=True)
        (functions / "pyrosetta_utils.py").write_text("def score_interface():\n    pass\n")
        proc = _run_bash(
            [
                f'BINDCRAFT_DIR="{tmp_path / "BindCraft"}"',
                *_STUB_PRINTERS,
                _function_source(X86, "_patch_bindcraft_pyrosetta"),
                "_patch_bindcraft_pyrosetta",
            ]
        )
        assert "WARN:" in proc.stdout, f"an unrecognised tree was passed over silently: {proc.stdout!r}"

    def test_install_bindcraft_patches_before_it_builds_and_smoke_tests_the_call(self):
        body = _function_source(X86, "install_bindcraft")
        pin = body.index("_pin_bindcraft_pyrosetta")
        patch = body.index("_patch_bindcraft_pyrosetta")
        build = body.index("install_bindcraft.sh --cuda")
        assert pin < build and patch < build, (
            "the PyRosetta pin and the call-site patch must run BEFORE BindCraft's own "
            "installer, which creates the env and resolves pyrosetta"
        )
        # score_interface() runs only after a full ~8 min trajectory, so the API has to
        # be exercised at install time, not inferred from an import.
        assert "set_interface" in body, "install_bindcraft has no set_interface smoke test"
        assert "pyrosetta.init" in body, "the smoke test does not initialise PyRosetta, so it cannot call the mover"


class TestAtomworksIsPinnedAndTheSymbolAsserted:
    """BUG-20: Proteina-Complexa could not generate at all."""

    @pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
    def test_atomworks_is_pinned_below_the_release_that_deleted_the_class(self, path):
        version = _assign(path, "ATOMWORKS_VERSION")
        assert version, f"{path.name} does not pin ATOMWORKS_VERSION"
        major = int(version.split(".")[0])
        assert major < 3, (
            f"{path.name} pins atomworks {version}; 3.0.0 removed AtomSelectionStack, "
            "which proteinfoundation/utils/pdb_utils.py imports at module level"
        )

    @pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
    def test_the_check_asserts_the_symbol_not_the_version(self, path):
        text = path.read_text()
        assert "from atomworks.io.utils.selection import AtomSelectionStack" in text, (
            f"{path.name} never imports AtomSelectionStack — a version check alone passes "
            "on any future release that drops the class again"
        )

    @pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
    def test_the_smoke_test_imports_the_module_that_broke(self, path):
        text = path.read_text()
        assert "proteinfoundation.utils.pdb_utils" in text, (
            f"{path.name}'s Proteina-Complexa smoke test does not import pdb_utils. "
            "`import proteinfoundation` stayed green through the whole atomworks 3.x "
            "breakage: that package's __init__ imports nothing."
        )


class TestRfd3GetsTheAtomworksPinToo:
    """BUG-28: the same floating dependency, a second consumer, a different symptom.

    rc-foundry installs atomworks unpinned into the RFD3 env as well. 3.0.0 did not
    delete anything RFD3 imports -- it moved ``extra_fields`` and ``build_assembly``
    off ``parse_atom_array()`` into a ``PrepareConfig`` object and made leftover
    kwargs an error, while rfd3's pinned ``input_parsing.py`` still passes them. So
    ``import atomworks`` passes, a version check passes, and the failure arrives in
    the dataloader once a GPU has been committed.

    Ported from master, where this helper existed in ``install.sh`` only. RFD3 is
    installable on aarch64 too (opt-in), and rc-foundry floats there identically,
    so the aarch64 copy is not optional.
    """

    @pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
    def test_the_check_asserts_the_signature_not_the_version(self, path):
        body = _function_source(path, "_pin_rfd3_atomworks")
        assert "inspect.signature(parse_atom_array)" in body, (
            f"{path.name}'s RFD3 atomworks check does not inspect the signature; a "
            "version string alone passes on any release that moves the kwargs again"
        )
        for kwarg in ("extra_fields", "build_assembly"):
            assert kwarg in body, f"{path.name} does not assert {kwarg} is still accepted"

    @pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
    def test_install_rfd3_actually_calls_the_pin(self, path):
        """The function is not the fix; the call is.

        A test that exercises ``_pin_rfd3_atomworks`` directly stays green when the
        call is deleted from ``install_rfd3``, which is the whole bug.
        """
        body = _function_source(path, "install_rfd3")
        assert "_pin_rfd3_atomworks" in body, (
            f"{path.name}'s install_rfd3 never calls _pin_rfd3_atomworks, so the env is "
            "built with whatever atomworks rc-foundry resolved"
        )

    @pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
    def test_a_3x_env_is_refused_and_a_pinned_one_accepted(self, tmp_path, path):
        """Behavioural: drive the helper against a stub env that reports 3.x."""
        results = {}
        for label, version, sig_rc in (("floating", "3.0.4", 1), ("pinned", "2.2.1", 0)):
            env_bin = tmp_path / label / "envs" / "binderscout_rfd3" / "bin"
            env_bin.mkdir(parents=True)
            py = env_bin / "python"
            py.write_text(
                "#!/bin/bash\n"
                'case "$*" in\n'
                f'  *importlib.metadata*) echo "{version}" ;;\n'
                f'  *parse_atom_array*) exit {sig_rc} ;;\n'
                "esac\n"
                "exit 0\n"
            )
            py.chmod(0o755)
            proc = _run_bash(
                _STUB_PRINTERS
                + [
                    "env_exists() { return 0; }",
                    'run_logged() { shift; "$@"; }',
                    f'CONDA_BASE="{tmp_path / label}"',
                    'RFD3_ENV="binderscout_rfd3"',
                    'ATOMWORKS_VERSION="2.2.1"',
                    _function_source(path, "_env_python_ok"),
                    _function_source(path, "_pin_rfd3_atomworks"),
                    "_pin_rfd3_atomworks; echo RC=$?",
                ]
            )
            results[label] = proc.stdout

        assert "RC=1" in results["floating"], (
            f"{path.name}: an env whose parse_atom_array lost the kwargs was accepted:\n"
            + results["floating"]
        )
        assert "FAIL:" in results["floating"], "the refusal does not say what is wrong"
        assert "RC=0" in results["pinned"], f"a correctly pinned env was refused:\n{results['pinned']}"


class TestEsm2QuinoxIsPinnedAndTheAlphabetAsserted:
    """BUG-24: Mosaic died on its first optimisation step."""

    @pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
    def test_esm2quinox_is_pinned_to_the_line_whose_token_table_mosaic_reads(self, path):
        version = _assign(path, "ESM2QUINOX_VERSION")
        assert version, f"{path.name} does not pin ESM2QUINOX_VERSION"
        assert version.startswith("0.1."), (
            f"{path.name} pins esm2quinox {version}; mosaic/losses/esm.py needs the "
            "33-entry 0.1.x alphabet keyed 'b'/'e'/'m'"
        )

    @pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
    def test_the_smoke_test_asserts_both_the_symbols_and_the_width(self, path):
        text = path.read_text()
        assert "from esm2quinox._esm2 import _alphabet" in text, (
            f"{path.name} never reads the alphabet Mosaic's ESM prior indexes"
        )
        assert "assert len(a) == 33" in text, (
            f"{path.name} does not assert the one-hot width; 0.2.0 kept a table and "
            "changed its size, so the keys alone are not enough"
        )
        for key in ("'b'", "'e'", "'m'"):
            assert key in text, f"{path.name} does not assert the {key} token"

    def test_the_pin_rewrites_the_clones_pyproject_before_the_resolve(self, tmp_path):
        """Mosaic/ is gitignored and recloned, so a committed pin cannot reach it; and
        a post-sync downgrade would be undone by the next `uv sync`."""
        mosaic = tmp_path / "Mosaic"
        mosaic.mkdir()
        (mosaic / "pyproject.toml").write_text(
            '[project]\ndependencies = [\n    "esm2quinox>=0.1.0",\n    "esmj",\n]\n'
        )
        version = _assign(X86, "ESM2QUINOX_VERSION")
        proc = _run_bash(
            [
                f'MOSAIC_DIR="{mosaic}"',
                f'ESM2QUINOX_VERSION="{version}"',
                *_STUB_PRINTERS,
                _function_source(X86, "_pin_mosaic_esm2quinox"),
                "_pin_mosaic_esm2quinox",
                "_pin_mosaic_esm2quinox",  # idempotent
            ]
        )
        assert proc.returncode == 0, proc.stderr
        toml = (mosaic / "pyproject.toml").read_text()
        assert f'"esm2quinox=={version}"' in toml, toml
        assert ">=0.1.0" not in toml, "the unbounded requirement survived"
        assert '"esmj",' in toml, "the pin touched a neighbouring requirement"

    @pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
    def test_the_pin_runs_before_uv_resolves(self, path):
        body = _function_source(path, "install_mosaic")
        assert "_pin_mosaic_esm2quinox" in body, f"{path.name}: install_mosaic does not pin it"
        assert body.index("_pin_mosaic_esm2quinox") < body.index("uv sync --group jax-cuda"), (
            "the ceiling must be in pyproject.toml before uv resolves, or uv resolves "
            "the broken version and the venv has to be corrected afterwards"
        )


class TestUvSyncDoesNotPruneTheEvaluatorOutOfTheMosaicVenv:
    """BUG-25: installing one tool silently broke the Evaluator."""

    @pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
    def test_both_injected_packages_are_restored_after_the_sync(self, path):
        body = _function_source(path, "install_mosaic")
        sync = body.index("uv sync --group jax-cuda")
        tail = body[sync:]
        assert "mosaic_venv_path" in tail, (
            f"{path.name}: install_mosaic does not restore anything after `uv sync`, which "
            "prunes every package the resolve does not list"
        )
        assert "[boltz2]" in tail, (
            "binder-compare[boltz2] is not re-injected — the entire Boltz-2 refold stage "
            "runs out of this venv, so evaluate.sh would fail with command-not-found"
        )
        assert "fair-esm" in tail, (
            "fair-esm is not re-injected — Mosaic would then design without the ESM2 "
            "prior, which is not an error, just worse binders"
        )

    @pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
    def test_the_restore_is_conditional_on_the_evaluator_being_wired_here(self, path):
        body = _function_source(path, "install_mosaic")
        assert '[[ -f "${EVALUATOR_DIR}/envs/mosaic_venv_path" ]]' in body, (
            f"{path.name}: the re-injection must be guarded by the marker install_evaluator "
            "writes, so a Mosaic-only install on a fresh machine does not try to install "
            "an Evaluator that is not there yet"
        )


class TestNothingIsPinnedToAMovingTarget:
    """BUG-23: a pin that does not hold, and two pins that were the string "HEAD"."""

    @pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
    def test_no_tool_is_pinned_to_the_literal_HEAD(self, path):
        floating = re.findall(r'^([A-Z0-9_]*COMMIT)="(?:\$\{[A-Z0-9_]*:-)?HEAD\}?"', path.read_text(), re.M)
        assert not floating, (
            f"{path.name} pins {floating} to the literal 'HEAD', so two installs a week "
            "apart get different code while every other tool is pinned to a SHA"
        )

    def test_the_boltzgen_torch_pin_survives_the_editable_install(self):
        """The old pin was overwritten by the very next line: BoltzGen declares
        `torch>=2.4.1` with no ceiling, so `pip install -e BoltzGen` re-resolved torch
        and upgraded over it. install.sh then named a version nobody had run."""
        version = _assign(X86, "BOLTZGEN_TORCH_VERSION")
        assert version, "install.sh does not define BOLTZGEN_TORCH_VERSION"
        body = _function_source(X86, "install_boltzgen")
        editable = [line for line in body.splitlines() if "pip install" in line and "${BOLTZGEN_DIR}" in line]
        assert editable, "could not find BoltzGen's editable install line"
        assert all("BOLTZGEN_TORCH_VERSION" in line for line in editable), (
            f"the editable install does not carry the torch pin, so it can re-resolve torch over it: {editable}"
        )
        assert "torch==2.5.1+cu121" not in body, "the overwritten cu121 pin is back"

    @pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
    def test_uv_itself_is_pinned(self, path):
        """uv is the resolver behind every venv here, so an unpinned uv makes every
        pin downstream of it provisional."""
        text = path.read_text()
        assert _assign(path, "UV_VERSION"), f"{path.name} does not pin UV_VERSION"
        unpinned = [line.strip() for line in text.splitlines() if "astral.sh/uv/install.sh" in line]
        assert not unpinned, f"{path.name} fetches uv from the floating installer URL:\n  " + "\n  ".join(unpinned)

    def test_both_installers_agree_on_the_pins_they_share(self):
        """A pin that differs between the platforms is a pin nobody is reading."""
        for name in ("ATOMWORKS_VERSION", "ESM2QUINOX_VERSION", "UV_VERSION", "PXDESIGN_COMMIT"):
            x86, arm = _assign(X86, name), _assign(ARM, name)
            assert x86 == arm, f"{name}: install.sh={x86!r} install_aarch.sh={arm!r}"
