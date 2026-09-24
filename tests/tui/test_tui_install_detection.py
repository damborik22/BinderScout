"""The TUI's installed/not-installed markers must mean what the installer means.

This menu is what README offers to people who prefer not to use flags, so it is
a front door. Two of its markers pointed at files that exist in NEITHER upstream
checkout — `BoltzGen/boltzgen/__init__.py` and
`BindCraft/bindcraft_environment.yml` — so it reported both tools as "not
installed" on every machine, including ones where `install.sh --verify` says
they are usable.

Pointing them at a path inside the clone would just invert the error: a cloned
but unbuilt tool would read as installed. install.sh requires clone AND env, so
`env:<name>` markers check the env.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tui"))
import app  # noqa: E402

sys.path.insert(0, str(REPO / "configurator"))
import configurator as conf  # noqa: E402


def test_the_tui_and_the_configurator_list_the_same_tools():
    """Two menus disagreeing about which tools exist is how this drifted.

    Compared on the RUN-OUTPUT SUBDIR, which is what both structures carry --
    the TUI's first field and the configurator's fourth. They are deliberately
    not the same as the tools_enabled KEY: PXDesign's key is `pxdesign_local`
    while its subdir is `pxdesign`, and conflating the two is its own trap
    (a config with `"pxdesign": true` enables nothing and exits 1).
    """
    tui_subdirs = [subdir for subdir, _label, _marker in app.TOOL_SEQUENCE]
    conf_subdirs = [subdir for _k, _script, _label, subdir in conf.TOOL_SEQUENCE]
    assert tui_subdirs == conf_subdirs, f"TUI {tui_subdirs} vs configurator {conf_subdirs}"

    tui_labels = [label for _subdir, label, _marker in app.TOOL_SEQUENCE]
    conf_labels = [label for _k, _script, label, _subdir in conf.TOOL_SEQUENCE]
    assert tui_labels == conf_labels


@pytest.mark.parametrize(("key", "label", "marker"), app.TOOL_SEQUENCE, ids=lambda x: x if isinstance(x, str) else "")
def test_no_marker_points_at_a_path_that_cannot_exist(key, label, marker):
    """A file marker must name something the installer actually creates.

    Checked by shape rather than by presence, so this holds on a clean checkout:
    an `env:` marker is always valid, and a path marker must live under a
    directory the installer creates or fetches.
    """
    if marker.startswith("env:"):
        assert marker[4:], f"{label}: empty env name"
        return
    top = marker.split("/", 1)[0]
    known = {
        "Mosaic",
        "BoltzGen",
        "BindCraft",
        "BindCraft2",
        "PXDesign",
        "Proteina-Complexa",
        "Protein-Hunter",
        "weights",
    }
    assert top in known, f"{label}: marker {marker!r} is not under an installer-created directory"


def test_detection_agrees_with_the_installer_on_this_box():
    """Local cross-check. Skips where nothing is installed, so CI stays green."""
    conda_base = app._find_conda_base(REPO)
    if conda_base is None or not (conda_base / "envs" / "BindCraft").is_dir():
        pytest.skip("no local install to cross-check against")
    detected = app._detect_tools(REPO)
    assert detected.get("BindCraft"), "BindCraft env exists but the TUI reports it missing"
    if (conda_base / "envs" / "BoltzGen").is_dir():
        assert detected.get("BoltzGen"), "BoltzGen env exists but the TUI reports it missing"
