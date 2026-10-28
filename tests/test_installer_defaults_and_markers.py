"""What a default install gives you, and whether the install-state markers work.

Three classes of defect this pins, all found by auditing install.sh against
install_aarch.sh:

* **Engines.** `--tool all` installed two of the three refold engines, because AF3
  was held out for its gated weights. The report's gate defaults to three engines,
  so a default install produced a pool where EVERY design failed the cross-engine
  gate and was ranked last. install_af3 never fails on absent weights -- it builds
  the env and prints where to request them -- so holding it out bought nothing.

* **The interactive menu drifts.** It is five hand-maintained parallel places per
  tool (`sel_*`, `tools=()`/`descs=()`, the `for i in ...` index list, a `case` with
  hardcoded numbers, and the final `DO_*` assignments), none derived from the table
  `--tool all` uses. ESMFold2 (`f0658a0`) and SoluProt (`9ec023d`) were each added
  with their DO_ flag, their `--tool all` entry and their post-menu summary line --
  and no menu entry, so the menu could not install the DEFAULT refold engine. Both
  commits show zero additions to `tools=()`.

* **Markers.** The whole mechanism was x86-only, so on aarch64 nothing was ever
  written and that platform kept the behaviour the markers exist to prevent.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
X86 = REPO / "install" / "install.sh"
AARCH = REPO / "install" / "install_aarch.sh"
TEXTS = {"install.sh": X86.read_text(), "install_aarch.sh": AARCH.read_text()}
INSTALLERS = pytest.mark.parametrize("name", sorted(TEXTS))


def shell_function(text: str, name: str) -> str | None:
    m = re.search(rf"^{re.escape(name)}\(\) \{{\n(.*?)^\}}$", text, re.S | re.M)
    return m.group(1) if m else None


def tool_all_flags(text: str) -> set[str]:
    """DO_* flags that `--tool all` sets."""
    m = re.search(r"\ball\)\n(.*?)\s*;;\n", text, re.S)
    assert m, "no `all)` branch"
    return set(re.findall(r"DO_([A-Z0-9_]+)=true", m.group(1)))


def menu_flags(text: str) -> set[str]:
    """DO_* flags the interactive menu can set."""
    body = shell_function(text, "select_tools_interactive")
    assert body, "no select_tools_interactive()"
    return set(re.findall(r'DO_([A-Z0-9_]+)="\$sel_', body))


class TestADefaultInstallGivesEveryEngine:
    """The engines have to match the gate the report applies by default."""

    @INSTALLERS
    def test_tool_all_installs_all_three_refold_engines(self, name):
        flags = tool_all_flags(TEXTS[name])
        # Boltz-2 runs out of the Mosaic venv; there is no separate boltz2 env.
        for engine, why in (
            ("MOSAIC", "Boltz-2 refolding runs in the Mosaic venv"),
            ("AF3", "the canonical 2nd engine"),
            ("ESMFOLD2", "the default engine"),
        ):
            assert engine in flags, (
                f"{name}: `--tool all` does not install {engine} ({why}). The report's "
                f"cross-engine gate defaults to 3 engines, so a default install that "
                f"provides fewer produces a report in which every design fails the gate "
                f"and is ranked last."
            )

    @INSTALLERS
    def test_af3_is_not_fatal_without_its_gated_weights(self, name):
        """AF3 is only safe in `all` because missing weights are a warning."""
        body = shell_function(TEXTS[name], "install_af3")
        if body is None:
            pytest.skip(f"{name} does not install AF3")
        tail = body[body.rindex("Shortcut") :] if "Shortcut" in body else body
        assert "print_warn" in tail and "return 1" not in tail, (
            f"{name}'s install_af3 now fails when the weights are absent. That makes "
            f"`--tool all` fail on every machine without gated weights -- put AF3 back "
            f"behind an opt-in if this is deliberate."
        )


class TestTheMenuCanInstallWhatAllInstalls:
    @INSTALLERS
    def test_every_tool_in_all_is_selectable_in_the_menu(self, name):
        missing = tool_all_flags(TEXTS[name]) - menu_flags(TEXTS[name])
        assert not missing, (
            f"{name}: `--tool all` installs {sorted(missing)} but the interactive menu "
            f"cannot select them. That made the beginner-facing path strictly worse than "
            f"the flag: ticking everything still left out the default refold engine."
        )

    @INSTALLERS
    def test_the_menus_parallel_arrays_agree(self, name):
        """Five hand-maintained places; this is what keeps them the same length."""
        body = shell_function(TEXTS[name], "select_tools_interactive")
        n_tools = len(re.findall(r'"[^"]+"', re.search(r"local tools=\((.*?)\)", body, re.S).group(1)))
        n_descs = len(re.findall(r'^\s+"', re.search(r"local descs=\(\n(.*?)\n\s*\)", body, re.S).group(1), re.M))
        n_states = len(re.findall(r'"\$sel_\w+"', re.search(r"local states=\((.*?)\)", body, re.S).group(1)))
        n_inst = len(re.findall(r'"\$inst_\w+"', re.search(r"local inst_states=\((.*?)\)", body, re.S).group(1)))
        n_idx = len(re.search(r"for i in ([\d ]+); do", body).group(1).split())
        n_case = len(re.findall(r"^\s+\d+\) \[\[ \"\$sel_", body, re.M))
        counts = {
            "tools": n_tools,
            "descs": n_descs,
            "states": n_states,
            "inst_states": n_inst,
            "for-index": n_idx,
            "case-branches": n_case,
        }
        assert len(set(counts.values())) == 1, f"{name}: menu arrays disagree: {counts}"


class TestMarkersWorkOnBothPlatforms:
    @INSTALLERS
    def test_every_install_step_is_wrapped(self, name):
        """A step that bypasses _install_step writes no marker on success."""
        text = TEXTS[name]
        # NB \s+ on BOTH sides: three of these lines pad with two spaces, and a
        # one-space pattern silently passed them -- the same near-miss that made
        # the first attempt at wrapping them skip those three.
        bare = re.findall(r'\}";\s+(install_[a-z0-9_]+)\s+\|\|', text)
        assert not bare, (
            f"{name}: these install steps bypass _install_step, so a successful install "
            f"records nothing: {sorted(set(bare))}"
        )

    @INSTALLERS
    def test_the_backfill_runs(self, name):
        """Without it the FIRST install makes every other working tool read absent."""
        text = TEXTS[name]
        assert re.search(r"^\s+backfill_install_markers$", text, re.M), (
            f"{name} defines backfill_install_markers but never calls it. The first "
            f"install then writes one marker, enforcement switches on, and every tool "
            f"installed before markers existed reads as not-installed."
        )

    @INSTALLERS
    def test_uninstall_clears_the_marker(self, name):
        body = shell_function(TEXTS[name], "uninstall_tool")
        assert body and "clear_tool_mark" in body, (
            f"{name}'s uninstall_tool does not clear the marker, so a removed tool keeps "
            f"a record saying its install finished successfully."
        )

    @INSTALLERS
    def test_the_reader_requires_marker_and_probe(self, name):
        """One rule across the installer, the configurator and the TUI."""
        body = shell_function(TEXTS[name], "print_tool_status")
        assert body and "_tool_is_installed" in body, (
            f"{name}'s status table does not use _tool_is_installed. It used to say "
            f"marker-OR-probe, which disagreed with configurator.detect_installs and "
            f"tui/app.py about the same box."
        )


class TestToolchainGateCoversEverySourceBuild:
    @INSTALLERS
    def test_the_gate_names_both_source_builds(self, name):
        body = shell_function(TEXTS[name], "preflight")
        assert body
        for flag, tool in (("DO_SOLUPROT", "SoluProt"), ("DO_AF3", "AlphaFold 3")):
            assert flag in body, (
                f"{name}'s preflight does not consider {tool}, which compiles from "
                f"source and is in `--tool all` -- so a box with no compiler finds out "
                f"at that step instead of in one second."
            )


class TestEsmfold2DefaultIsFull:
    """Quality over speed: the default must be the accurate model, and say so."""

    def test_the_code_defaults_to_full(self):
        src = (REPO / "Evaluator" / "scripts" / "refold_esmfold2.py").read_text()
        assert 'model_name: str = "full"' in src
        assert 'default="full"' in src

    def test_evaluate_sh_defaults_to_full(self):
        assert 'ESMFOLD2_MODEL="full"' in (REPO / "Evaluator" / "evaluate.sh").read_text()

    @INSTALLERS
    def test_the_installer_does_not_advertise_fast_as_the_default(self, name):
        text = TEXTS[name]
        assert "Default model: fast" not in text and "Default model: ${BOLD}fast" not in text, (
            f"{name} advertises `fast` as the ESMFold2 default while the code defaults to "
            f"`full`, steering the operator into the LESS accurate engine."
        )
