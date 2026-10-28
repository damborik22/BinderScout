"""The install-marker store must survive the migration onto it.

`install.sh` records a marker per tool under `.install_state/`; the configurator's
`detect_installs()` reads them. The switch from the old path probes to the markers
was a cliff: it keyed on the marker *directory* existing, and ignored the probe once
it did. Two failures came out of that, and both were live.

1. **The migration gap.** One `install --tool X` on a fully-populated box wrote one
   marker, and every other working tool went dark. Because Step 9's refold-engine
   list is gated on the same dict, the engines printed "skipped" and the wizard
   ended on "No refolding engine selected — Evaluator disabled". Measured on this
   box on 2026-10-28: 2 markers present, 9 working tools reported not-installed,
   and the only engine still offered (AF3) prompts default-no — so pressing Enter
   through the wizard disabled the evaluator with all three engines installed.

2. **The emptied store.** `clear_tool_mark` is `rm -f`, so `--uninstall --tool all`
   leaves the directory in place and empty. Keyed on `is_dir()` that reads as
   "markers exist, none set" and reports everything uninstalled, rather than
   falling back to the probes.

The bash is extracted from install.sh and executed, not asserted about, because the
previous round of this work proved that a test which never reaches the shell cannot
see an ordering bug.
"""

from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install" / "install.sh"
INSTALL_TEXT = INSTALL_SH.read_text()

TOOL_KEYS = [
    "bindcraft",
    "boltzgen",
    "mosaic",
    "evaluator",
    "pxdesign",
    "proteina_complexa",
    "protein_hunter",
    "rfd3",
    "af3",
    "esmfold2",
    "soluprot",
]


def bash_function(name: str) -> str:
    """Extract `name() { ... }` from install.sh by its column-zero braces."""
    match = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}$", INSTALL_TEXT, re.S | re.M)
    assert match, f"{name}() not found in install.sh"
    return match.group(0)


def run_backfill(
    tmp_path: Path,
    passing: list[str],
    *,
    preexisting: dict[str, str] | None = None,
    migrated: bool = False,
):
    """Execute the real backfill_install_markers() against stub probes.

    *passing* names the tools whose `is_<key>_installed` stub returns 0.
    *preexisting* seeds the marker store before the function runs.
    *migrated* writes the sentinel, i.e. "this box has already been migrated".
    """
    state = tmp_path / ".install_state"
    if migrated:
        (tmp_path / ".install_state.migrated").touch()
    if preexisting is not None:
        state.mkdir(parents=True, exist_ok=True)
        for key, body in preexisting.items():
            (state / key).write_text(body)

    stubs = "\n".join(
        f"is_{key}_installed() {{ return {0 if key in passing else 1}; }}" for key in TOOL_KEYS
    )
    script = textwrap.dedent(
        f"""
        set -u
        INSTALL_STATE_DIR="{state}"
        BINDMASTER_DIR="{tmp_path}"
        print_ok() {{ echo "OK: $*"; }}
        {stubs}
        {bash_function("backfill_install_markers")}
        backfill_install_markers
        """
    )
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"backfill failed: {proc.stderr}"
    written = sorted(p.name for p in state.iterdir() if p.is_file()) if state.is_dir() else []
    return written, proc.stdout


class TestBackfillClosesTheMigrationGap:
    def test_every_passing_probe_gets_a_marker(self, tmp_path):
        written, out = run_backfill(tmp_path, TOOL_KEYS)
        assert written == sorted(TOOL_KEYS), "a working tool was left unmarked"
        assert "11 pre-existing install(s)" in out

    def test_failing_probes_get_no_marker(self, tmp_path):
        written, _ = run_backfill(tmp_path, ["mosaic", "evaluator"])
        assert written == ["evaluator", "mosaic"]

    def test_this_boxs_actual_shortfall_would_be_closed(self, tmp_path):
        """The 2026-10-28 state: 9 tools working, only af3 + soluprot marked.

        Seeded as the *pre-marker* case (empty store) because that is what the
        migration is for; the point is that all nine come back, not just the two
        that happened to be installed through the new installer.
        """
        working = [k for k in TOOL_KEYS if k not in ()]
        written, _ = run_backfill(tmp_path, working)
        for key in ("bindcraft", "boltzgen", "mosaic", "evaluator", "esmfold2"):
            assert key in written, f"{key} works but would still read not-installed"

    def test_marker_records_that_it_was_back_filled(self, tmp_path):
        """A back-filled marker asserts "the probe passed", not "install finished"."""
        state = tmp_path / ".install_state"
        run_backfill(tmp_path, ["mosaic"])
        assert "backfill" in (state / "mosaic").read_text()

    def test_an_earned_marker_is_not_tagged_backfill(self):
        """mark_tool_installed writes two fields; the migration adds a third."""
        earned = bash_function("mark_tool_installed")
        assert "backfill" not in earned

    def test_a_partially_marked_box_still_migrates(self, tmp_path):
        """The case a contents-based trigger gets wrong, and this box really was.

        It carried markers for af3 and soluprot while nine older tools had none.
        "Run once when the store is empty" would have declared the migration done
        and left those nine reading not-installed forever.
        """
        written, out = run_backfill(
            tmp_path,
            TOOL_KEYS,
            preexisting={
                "af3": "2026-10-27T19:43\tabc1234\n",
                "soluprot": "2026-10-26T06:26\tabc1234\n",
            },
        )
        assert written == sorted(TOOL_KEYS), "a half-marked box was left half-dark"
        assert "9 pre-existing install(s)" in out

    def test_an_earned_marker_is_never_overwritten(self, tmp_path):
        """The earned marker is the stronger claim; migration must not downgrade it."""
        earned = "2026-10-27T19:43\tabc1234\n"
        run_backfill(tmp_path, TOOL_KEYS, preexisting={"af3": earned})
        assert (tmp_path / ".install_state" / "af3").read_text() == earned

    def test_migration_is_skipped_once_the_sentinel_exists(self, tmp_path):
        written, out = run_backfill(tmp_path, TOOL_KEYS, migrated=True)
        assert written == [], "migration re-ran after it had already completed"
        assert "pre-existing install" not in out

    def test_the_sentinel_lands_outside_the_marker_store(self, tmp_path):
        """Inside the store it would read as "markers exist", i.e. nothing installed."""
        run_backfill(tmp_path, ["mosaic"])
        assert (tmp_path / ".install_state.migrated").is_file()
        assert sorted(p.name for p in (tmp_path / ".install_state").iterdir()) == ["mosaic"]

    def test_an_empty_box_is_still_recorded_as_migrated(self, tmp_path):
        """Otherwise every later run re-probes, and a passing probe mints its own
        marker — which collapses `marker AND probe` back to `probe`."""
        written, _ = run_backfill(tmp_path, [])
        assert written == []
        assert (tmp_path / ".install_state.migrated").is_file()

    def test_an_emptied_store_does_not_block_migration(self, tmp_path):
        """`--uninstall --tool all` leaves the directory behind, empty."""
        state = tmp_path / ".install_state"
        state.mkdir(parents=True)
        assert state.is_dir() and not any(state.iterdir())
        written, _ = run_backfill(tmp_path, ["rfd3"])
        assert written == ["rfd3"], "an empty directory blocked the migration"

    def test_runs_before_the_status_table_and_any_install(self):
        """Ordering: after detect_conda (probes need CONDA_BASE), before any marker read.

        Comment lines are stripped first — prose naming these functions is not a call,
        and matching it made this assertion pass or fail on where a comment sat.
        """
        code = [
            ln for ln in bash_function("main").splitlines()
            if not ln.lstrip().startswith("#")
        ]

        def line_of(token: str) -> int:
            for i, ln in enumerate(code):
                if token in ln:
                    return i
            raise AssertionError(f"{token} is never called in main()")

        pos_backfill = line_of("backfill_install_markers")
        assert line_of("detect_conda") < pos_backfill, "probes run before conda is located"
        assert pos_backfill < line_of("print_tool_status"), "status table read pre-migration markers"


class TestEveryToolKeyHasAProbe:
    @pytest.mark.parametrize("key", TOOL_KEYS)
    def test_probe_function_exists(self, key):
        """A key with no probe is silently skipped by the migration."""
        assert re.search(rf"^is_{key}_installed\(\) \{{", INSTALL_TEXT, re.M), (
            f"is_{key}_installed() is missing, so {key} can never be back-filled"
        )

    def test_migration_covers_every_key_the_installer_can_mark(self):
        """The migration's list must not fall behind the tools install.sh marks."""
        marked = set(re.findall(r"_install_step\s+(\w+)", INSTALL_TEXT))
        covered = set(re.search(
            r"for _key in (.*?); do", bash_function("backfill_install_markers"), re.S
        ).group(1).split())
        missing = marked - covered - {"$1"}
        assert not missing, f"install.sh marks {sorted(missing)} but the migration skips them"
