"""The TUI read the tool CLONE and called that an install (BUG-06, third reader).

`_detect_tools` probed paths like `PXDesign/pxdesign` and
`Protein-Hunter/boltz_ph/design.py` — files of the upstream checkout. A bare clone
with no environment at all therefore showed as installed, and a conda env directory
left behind by a FAILED solve reads the same way. The wizard
(`configurator.detect_installs`) requires the installer's own marker, so the two
views disagreed about the same box.

Same rule in both places now: marker AND probe once any marker exists, probe alone
before then.

The TUI/configurator table agreement is guarded by tests/tui/test_tool_sequence.py,
which imports configurator/configurator.py as the TOP-LEVEL module `configurator`.
Do not import it as `configurator.configurator` from this directory: that caches the
namespace PACKAGE under the same name and the other test then fails with
AttributeError on TOOL_SEQUENCE depending on file order.
"""

import tui.app as app

# A probe path from TOOL_SEQUENCE, and the marker key that must accompany it.
MOSAIC_KEY, MOSAIC_LABEL, MOSAIC_PROBE = app.TOOL_SEQUENCE[0]


def _repo(tmp_path, *, probe: bool, markers: tuple[str, ...] = (), state_dir: bool = False):
    if probe:
        p = tmp_path / MOSAIC_PROBE
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()
    if state_dir or markers:
        state = tmp_path / ".install_state"
        state.mkdir(exist_ok=True)
        for key in markers:
            (state / key).write_text("2026-01-01\tdeadbee\n")
    return tmp_path


def test_with_no_markers_the_probe_still_decides(tmp_path):
    """Every box predating the markers must keep working, not read as empty."""
    tools = app._detect_tools(_repo(tmp_path, probe=True))
    assert tools[MOSAIC_LABEL] is True


def test_a_clone_without_a_marker_is_not_installed_once_markers_exist(tmp_path):
    """The actual bug: the clone is present, the install is not."""
    repo = _repo(tmp_path, probe=True, markers=("boltzgen",))
    assert app._detect_tools(repo)[MOSAIC_LABEL] is False


def test_a_marker_alone_is_not_enough(tmp_path):
    """A marker left behind by an env that was deleted afterwards must not count."""
    repo = _repo(tmp_path, probe=False, markers=(MOSAIC_KEY,))
    assert app._detect_tools(repo)[MOSAIC_LABEL] is False


def test_marker_plus_probe_is_installed(tmp_path):
    repo = _repo(tmp_path, probe=True, markers=(MOSAIC_KEY,))
    assert app._detect_tools(repo)[MOSAIC_LABEL] is True


def test_an_empty_marker_directory_does_not_switch_enforcement_on(tmp_path):
    """`clear_tool_mark` is `rm -f`, so --uninstall leaves the directory behind.

    Reading an empty store as "markers are authoritative, none are set" reports
    every tool uninstalled on a box where everything works.
    """
    repo = _repo(tmp_path, probe=True, state_dir=True)
    assert app._detect_tools(repo)[MOSAIC_LABEL] is True
