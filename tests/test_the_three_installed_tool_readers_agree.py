"""A conda env directory is not an install, and three readers believed it was.

Conda creates the env directory when it STARTS solving and leaves it behind when
the solve fails. So a half-built or outright failed tool reported as installed:
the wizard printed `BindCraft [installed]`, defaulted "Enable BindCraft?" to Y,
defaulted "Run the pipeline now?" to Y, and the run died with
`ModuleNotFoundError: No module named 'pyrosetta'` -- an install problem arriving
as a confusing run-time one. Tightening the probe to bin/python does not help;
that symlink exists just as early.

Two people hit it: anyone configuring in a second terminal while installing,
which is natural when the installer says 45-90 min, and anyone whose install
failed at all. The second form is PERMANENT, not a race -- a `--tool all` run
that failed at SoluProt had already created binder-eval-soluprot, so the
configurator offered the solubility screen forever after.

Measured over a tree of EMPTY env directories before the fix: the configurator
called 8 of 14 tools installed, and tui/app.py additionally called PXDesign and
Protein-Hunter installed from files of the UPSTREAM CLONE, with no env at all.

The fix is one mechanism and three consumers: the installer records success per
tool, and each reader requires a marker AND its own probe.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
X86 = REPO / "install" / "install.sh"
ARM = REPO / "install" / "install_aarch.sh"
INSTALLERS = [X86, ARM]
IDS = [p.name for p in INSTALLERS]

sys.path.insert(0, str(REPO / "configurator"))
sys.path.insert(0, str(REPO))
import configurator as conf  # noqa: E402
from tui.app import TOOL_SEQUENCE as TUI_TOOLS  # noqa: E402
from tui.app import _detect_tools  # noqa: E402

# ───────────────────────────────────────── the installer writes the markers


@pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
def test_the_installer_marks_every_tool_it_installs(path):
    """Every install step must go through run_install_step.

    Called directly, a tool's installer leaves no marker, and a marker-aware
    reader then reports a perfectly good install as absent -- the opposite error,
    and just as silent.
    """
    text = path.read_text()
    steps = [ln for ln in text.splitlines() if "failed_tools+=(" in ln and "step++" in ln]
    assert len(steps) >= 13, f"{path.name}: found only {len(steps)} install steps"
    unwrapped = [ln.strip() for ln in steps if "run_install_step " not in ln]
    assert not unwrapped, f"{path.name}: install steps that write no marker:\n" + "\n".join(unwrapped)


@pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
def test_the_marker_key_is_the_flag_name_lowercased(path):
    """One mechanical rule, so the readers can derive the key instead of listing it."""
    text = path.read_text()
    for ln in text.splitlines():
        if "run_install_step " not in ln or "failed_tools+=(" not in ln:
            continue
        flag = re.search(r"\$\{(DO_[A-Z0-9_]+)\}", ln).group(1)
        key = re.search(r"run_install_step ([a-z0-9_]+) ", ln).group(1)
        assert key == flag[3:].lower(), f"{path.name}: {flag} marked as {key!r}"


@pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
def test_the_marker_is_cleared_before_the_install_not_after(path):
    """A re-install that fails must not leave the previous run's marker standing
    as evidence for an env it has just half-rebuilt."""
    body = re.search(r"^run_install_step\(\) \{\n(.*?)^\}\n", path.read_text(), re.S | re.M).group(1)
    assert body.index("clear_tool_mark") < body.index('"${fn}"'), "clear before running, or a failed re-install lies"
    assert body.index('"${fn}"') < body.index("mark_tool_installed"), "mark only after success"
    assert "|| return 1" in body, "a failed install must not be marked"


@pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
def test_uninstall_and_repair_maintain_the_marker(path):
    """Otherwise `--uninstall --tool rfd3` becomes a new way to get a tool that
    claims to be installed and is not, and a repaired tool stays "broken"."""
    text = path.read_text()
    assert re.search(r"clear_tool_mark \"\$\{_?key,,\}\"", text), f"{path.name}: uninstall does not clear the marker"
    repair = re.search(r"^repair_tools\(\) \{\n(.*?)^\}\n", text, re.S | re.M)
    assert repair, f"{path.name} has no repair_tools()"
    assert "run_install_step" in repair.group(1), "a repair is an install — it must re-mark"


class TestTheInstallerMarkerMechanism:
    """Execute the four helpers rather than reading them."""

    def _run(self, tmp_path, path: Path, script: str) -> tuple[int, str]:
        src = path.read_text()

        def _fn(name: str) -> str:
            # Two shapes in these files: a one-liner (clear_tool_mark, is_tool_marked)
            # and a multi-line body. Match either, or the extraction silently drops
            # the helper and every behavioural test below fails for the wrong reason.
            for pat in (rf"^{name}\(\) \{{.*?\}}\n", rf"^{name}\(\) \{{\n.*?^\}}\n"):
                m = re.search(pat, src, re.S | re.M)
                if m and m.group(0).count("\n") <= 12:
                    return m.group(0)
            raise AssertionError(f"{path.name} does not define {name}()")

        helpers = "".join(
            _fn(name) for name in ("clear_tool_mark", "mark_tool_installed", "is_tool_marked", "run_install_step")
        )
        harness = tmp_path / "m.sh"
        harness.write_text(
            "#!/usr/bin/env bash\nset -uo pipefail\n"
            f'BINDERSCOUT_DIR="{tmp_path}"\n'
            f'INSTALL_STATE_DIR="{tmp_path}/.install_state"\n' + helpers + script
        )
        proc = subprocess.run(["bash", str(harness)], capture_output=True, text=True)
        return proc.returncode, proc.stdout + proc.stderr

    @pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
    def test_a_successful_install_is_marked(self, tmp_path, path):
        rc, out = self._run(tmp_path, path, "ok() { true; }\nrun_install_step bindcraft ok\n")
        assert rc == 0, out
        marker = tmp_path / ".install_state" / "bindcraft"
        assert marker.is_file()
        stamp, sha = marker.read_text().strip().split("\t")
        assert stamp.startswith("20"), f"no ISO timestamp in the marker: {stamp!r}"
        assert sha, "the marker should record which checkout installed it"

    @pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
    def test_a_failed_install_is_not_marked(self, tmp_path, path):
        rc, out = self._run(tmp_path, path, "bad() { return 1; }\nrun_install_step bindcraft bad\n")
        assert rc == 1, out
        assert not (tmp_path / ".install_state" / "bindcraft").exists()

    @pytest.mark.parametrize("path", INSTALLERS, ids=IDS)
    def test_a_failed_REinstall_clears_the_earlier_success(self, tmp_path, path):
        """The case the ordering exists for: install, then re-install and fail.

        The env has just been half-rebuilt, so the old marker is no longer
        evidence of anything -- and it is exactly the permanent form of the bug.
        """
        script = "ok() { true; }\nbad() { return 1; }\nrun_install_step soluprot ok\nrun_install_step soluprot bad\n"
        rc, out = self._run(tmp_path, path, script)
        assert rc == 1, out
        assert not (tmp_path / ".install_state" / "soluprot").exists(), "the stale success marker survived"


# ───────────────────────────────────────────── the readers consult the markers


def _point_at(root: Path, monkeypatch):
    for name, value in {
        "CONDA_ENVS_DIR": root / "conda" / "envs",
        "EVALUATOR_DIR": root / "Evaluator",
        "MOSAIC_VENV": root / "Mosaic" / ".venv",
        "PROTEINA_COMPLEXA_VENV": root / "Proteina-Complexa" / ".venv",
        "BINDCRAFT2_VENV": root / "BindCraft2" / ".venv",
        "RFD4_VENV": root / "RFD4-Proteina" / ".venv",
        "FOUNDRY_WEIGHTS_DIR": root / "weights" / "foundry",
        "PROTEIN_HUNTER_DIR": root / "Protein-Hunter",
        "INSTALL_STATE_DIR": root / ".install_state",
    }.items():
        monkeypatch.setattr(conf, name, value)


def _half_built_repo(tmp_path: Path) -> Path:
    """What conda leaves behind after a failed solve, plus two upstream clones."""
    root = tmp_path / "repo"
    (root / "conda" / "etc" / "profile.d").mkdir(parents=True)
    (root / "conda" / "etc" / "profile.d" / "conda.sh").touch()
    for env in (
        "BindCraft",
        "BoltzGen",
        "binder-eval",
        "binderscout_pxdesign",
        "binder-eval-af3",
        "binder-eval-esmfold2",
        "binder-eval-soluprot",
        "binder-eval-tmprot",
    ):
        (root / "conda" / "envs" / env).mkdir(parents=True)
    (root / "Evaluator").mkdir()
    (root / "Evaluator" / "evaluate.sh").touch()
    # The two the TUI probed with a file of the upstream CLONE.
    (root / "PXDesign").mkdir()
    (root / "PXDesign" / "pxdesign").touch()
    (root / "Protein-Hunter" / "boltz_ph").mkdir(parents=True)
    (root / "Protein-Hunter" / "boltz_ph" / "design.py").touch()
    return root


def test_with_no_markers_the_probes_still_decide(tmp_path, monkeypatch):
    """Every env on this fleet predates the markers, so requiring one
    unconditionally would report a working installation as absent and refuse to
    configure any of it. The marker directory is a one-way upgrade, not a
    migration."""
    root = _half_built_repo(tmp_path)
    _point_at(root, monkeypatch)
    assert conf.detect_installs()["bindcraft"] is True
    assert _detect_tools(root)["BindCraft"] is True


def test_once_markers_exist_an_unmarked_tool_is_not_installed(tmp_path, monkeypatch):
    """The bug, from both readers: empty env directories must stop counting."""
    root = _half_built_repo(tmp_path)
    _point_at(root, monkeypatch)
    (root / ".install_state").mkdir()
    (root / ".install_state" / "bindcraft").write_text("2026-10-28T08:00:00+01:00\tdeadbee\n")

    cfg = conf.detect_installs()
    assert cfg["bindcraft"] is True, "the one tool that finished must still count"
    for key in ("boltzgen", "evaluator", "pxdesign_local", "af3", "esmfold2", "soluprot", "tmprot"):
        assert cfg[key] is False, f"{key} reported installed from an empty env directory"

    tui = _detect_tools(root)
    assert tui["BindCraft"] is True
    assert tui["PXDesign"] is False, "an upstream clone file is not an install"
    assert tui["Protein-Hunter"] is False, "an upstream clone file is not an install"


def test_a_marker_alone_is_not_enough(tmp_path, monkeypatch):
    """AND, not OR: an env deleted after a successful install must stop counting."""
    root = _half_built_repo(tmp_path)
    _point_at(root, monkeypatch)
    (root / ".install_state").mkdir()
    (root / ".install_state" / "rfd3").write_text("2026-10-28T08:00:00+01:00\tdeadbee\n")
    # rfd3's probe wants the env AND the checkpoint; neither exists here.
    assert conf.detect_installs()["rfd3"] is False


def test_an_empty_marker_directory_does_not_switch_enforcement_on(tmp_path, monkeypatch):
    """`mkdir -p` runs before the first marker is written, and an empty directory
    must not flip every tool to uninstalled for the whole fleet."""
    root = _half_built_repo(tmp_path)
    _point_at(root, monkeypatch)
    (root / ".install_state").mkdir()
    assert conf.detect_installs()["bindcraft"] is True
    assert _detect_tools(root)["BindCraft"] is True


# ─────────────────────────────────────────────── the three readers use one key


def test_the_tui_and_the_configurator_use_the_installers_marker_keys():
    """One vocabulary across all three, or a reader looks for a file that is never
    written and silently reports everything as uninstalled."""
    installer_keys = {
        re.search(r"run_install_step ([a-z0-9_]+) ", ln).group(1)
        for ln in X86.read_text().splitlines()
        if "run_install_step " in ln and "failed_tools+=(" in ln
    }
    assert len(installer_keys) == 14, sorted(installer_keys)

    tui_keys = {key for key, _label, _marker in TUI_TOOLS}
    assert tui_keys <= installer_keys, (
        f"the TUI reads markers the installer never writes: {sorted(tui_keys - installer_keys)}"
    )

    # The configurator's dict keys, minus the one deliberate rename.
    cfg_keys = set(conf.detect_installs()) - {"pxdesign_local"} | {"pxdesign"}
    assert cfg_keys <= installer_keys, (
        f"the configurator reads markers the installer never writes: {sorted(cfg_keys - installer_keys)}"
    )


def test_the_state_directory_is_gitignored():
    """It is machine state: whether THIS checkout finished installing a tool says
    nothing about any other checkout, and a committed marker would make a fresh
    clone claim tools it has never built."""
    assert ".install_state/" in (REPO / ".gitignore").read_text()
    out = subprocess.run(["git", "check-ignore", "-q", ".install_state/bindcraft"], cwd=REPO).returncode
    assert out == 0, ".install_state/ is not actually ignored by git"
