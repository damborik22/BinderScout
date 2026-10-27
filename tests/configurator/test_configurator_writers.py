"""Tests for new configurator run script writers and config generators."""

import ast
import inspect
import json
import sys
from pathlib import Path
from typing import ClassVar

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))
import configurator as conf


@pytest.fixture
def base_cfg(tmp_path):
    """Minimal cfg dict for testing script writers."""
    run_dir = tmp_path / "runs" / "test"
    run_dir.mkdir(parents=True)
    target_pdb = tmp_path / "target.pdb"
    target_pdb.write_text("ATOM ...")
    return {
        "name": "test_target",
        "run_dir": run_dir,
        "target_pdb": target_pdb,
        "target_pdb_src": str(target_pdb),
        "target_sequence": "MAEVKLSYVL",
        "chains": "A",
        "hotspots": "10,20,30",
        "min_length": 65,
        "max_length": 150,
        "n_designs": 10,
        "pxdesign_binder_length": 80,
        "pxdesign_n_samples": 1000,
        "pxdesign_preset": "preview",
        "pxdesign_hotspots": "10,20,30",
        "pxdesign_chains": "A",
    }


class TestWriteRunPxdesign:
    def test_creates_executable_script(self, base_cfg, tmp_path):
        script = tmp_path / "run_pxdesign.sh"
        conf.write_run_pxdesign(script, base_cfg)
        assert script.exists()
        assert script.stat().st_mode & 0o111

    def test_script_contains_config_values(self, base_cfg, tmp_path):
        script = tmp_path / "run_pxdesign.sh"
        conf.write_run_pxdesign(script, base_cfg)
        content = script.read_text()
        assert "bindmaster_pxdesign" in content
        assert "--preset preview" in content
        assert "--N_sample 1000" in content


class TestWritePxdesignYaml:
    def test_generates_yaml(self, base_cfg, tmp_path):
        yaml_path = tmp_path / "input.yaml"
        conf.write_pxdesign_yaml(yaml_path, base_cfg)
        content = yaml_path.read_text()
        assert "binder_length: 80" in content
        assert "target:" in content
        assert "chains:" in content

    def test_yaml_includes_hotspots(self, base_cfg, tmp_path):
        yaml_path = tmp_path / "input.yaml"
        conf.write_pxdesign_yaml(yaml_path, base_cfg)
        content = yaml_path.read_text()
        assert "hotspots: [10, 20, 30]" in content

    def test_yaml_no_hotspots(self, base_cfg, tmp_path):
        base_cfg["pxdesign_hotspots"] = ""
        base_cfg["hotspots"] = ""
        yaml_path = tmp_path / "input.yaml"
        conf.write_pxdesign_yaml(yaml_path, base_cfg)
        content = yaml_path.read_text()
        # "hotspots:" key should not appear in YAML (file path may contain the word)
        assert "hotspots:" not in content
        assert "A: all" in content

    def test_yaml_multiple_chains(self, base_cfg, tmp_path):
        base_cfg["pxdesign_chains"] = "A,B"
        base_cfg["pxdesign_hotspots"] = ""
        base_cfg["hotspots"] = ""
        yaml_path = tmp_path / "input.yaml"
        conf.write_pxdesign_yaml(yaml_path, base_cfg)
        content = yaml_path.read_text()
        assert "A: all" in content
        assert "B: all" in content


class TestWriteRunAll:
    def test_includes_pxdesign_step(self, base_cfg, tmp_path):
        tools = {"pxdesign_local": True, "mosaic": False, "boltzgen": False, "bindcraft": False, "evaluator": False}
        script = tmp_path / "run_all.sh"
        conf.write_run_all(script, base_cfg, tools)
        content = script.read_text()
        assert "PXDesign" in content
        assert "run_pxdesign.sh" in content

    def test_correct_order(self, base_cfg, tmp_path):
        tools = {
            "mosaic": True,
            "boltzgen": True,
            "bindcraft": True,
            "pxdesign_local": True,
            "evaluator": True,
        }
        script = tmp_path / "run_all.sh"
        conf.write_run_all(script, base_cfg, tools)
        content = script.read_text()
        # Check order: BoltzGen before BindCraft before PXDesign before Evaluator
        pos_boltz = content.index("BoltzGen")
        pos_bc = content.index("BindCraft")
        pos_pxd = content.index("PXDesign")
        pos_eval = content.index("Evaluator")
        assert pos_boltz < pos_bc < pos_pxd < pos_eval


# ── Target sequence extraction (mmCIF chain selection) ────────────────────────

# Chain A is the SHORTER entity, chain B the longer one. `_entity_poly` returns the
# longest entity regardless of chain, so a correct implementation must not return
# chain B's sequence when chain A was requested.
_CHAIN_A_SEQ = "ACDEF"
_CHAIN_B_SEQ = "MKTAYIAKQR"

_ENTITY_POLY_BLOCK = f"""loop_
_entity_poly.entity_id
_entity_poly.type
_entity_poly.pdbx_seq_one_letter_code_can
1 'polypeptide(L)' {_CHAIN_A_SEQ}
2 'polypeptide(L)' {_CHAIN_B_SEQ}
#
"""


def _atom_site_block(chains: dict) -> str:
    """Build an _atom_site loop with one CA record per residue of each chain."""
    three = {
        "A": "ALA",
        "C": "CYS",
        "D": "ASP",
        "E": "GLU",
        "F": "PHE",
        "G": "GLY",
        "H": "HIS",
        "I": "ILE",
        "K": "LYS",
        "M": "MET",
        "Q": "GLN",
        "R": "ARG",
        "T": "THR",
        "Y": "TYR",
    }
    rows = []
    serial = 1
    for chain_id, seq in chains.items():
        for pos, aa in enumerate(seq, start=1):
            rows.append(f"ATOM {serial} CA {three[aa]} {chain_id} {pos}")
            serial += 1
    return (
        "loop_\n"
        "_atom_site.group_PDB\n"
        "_atom_site.id\n"
        "_atom_site.label_atom_id\n"
        "_atom_site.label_comp_id\n"
        "_atom_site.label_asym_id\n"
        "_atom_site.label_seq_id\n" + "\n".join(rows) + "\n#\n"
    )


@pytest.fixture
def cif_two_chains(tmp_path):
    """Two-chain mmCIF with BOTH _entity_poly and _atom_site (the normal PDB case)."""
    path = tmp_path / "two_chains.cif"
    path.write_text("data_TEST\n#\n" + _ENTITY_POLY_BLOCK + _atom_site_block({"A": _CHAIN_A_SEQ, "B": _CHAIN_B_SEQ}))
    return path


class TestExtractSequenceFromCif:
    def test_honours_requested_chain_not_longest_entity(self, cif_two_chains):
        """Regression: _entity_poly was tried first and returned the LONGEST entity,
        discarding the chain the user asked for."""
        assert conf.extract_sequence_from_cif(str(cif_two_chains), "A") == _CHAIN_A_SEQ

    def test_returns_other_chain_when_requested(self, cif_two_chains):
        assert conf.extract_sequence_from_cif(str(cif_two_chains), "B") == _CHAIN_B_SEQ

    def test_never_concatenates_chains(self, cif_two_chains):
        seq = conf.extract_sequence_from_cif(str(cif_two_chains), "A")
        assert seq is not None
        assert len(seq) == len(_CHAIN_A_SEQ)
        assert _CHAIN_B_SEQ not in seq

    def test_chain_is_case_insensitive(self, cif_two_chains):
        assert conf.extract_sequence_from_cif(str(cif_two_chains), "a") == _CHAIN_A_SEQ

    def test_falls_back_to_entity_poly_and_warns(self, tmp_path, capsys):
        """A sequence-only mmCIF has no coordinates; _entity_poly is the last resort but
        cannot honour the chain, so the fallback must be announced."""
        path = tmp_path / "seq_only.cif"
        path.write_text("data_TEST\n#\n" + _ENTITY_POLY_BLOCK)
        seq = conf.extract_sequence_from_cif(str(path), "A")
        assert seq == _CHAIN_B_SEQ  # longest entity — the only thing available
        assert "no CA records" in capsys.readouterr().out

    def test_no_warning_on_the_happy_path(self, cif_two_chains, capsys):
        conf.extract_sequence_from_cif(str(cif_two_chains), "A")
        assert "no CA records" not in capsys.readouterr().out

    def test_unknown_chain_falls_back_with_warning(self, cif_two_chains, capsys):
        seq = conf.extract_sequence_from_cif(str(cif_two_chains), "Z")
        assert seq == _CHAIN_B_SEQ
        assert "Chain Z has no CA records" in capsys.readouterr().out

    def test_dispatcher_routes_cif(self, cif_two_chains):
        assert conf.extract_sequence_from_structure(str(cif_two_chains), "A") == _CHAIN_A_SEQ


class TestHotspotsToEpitopeIdx:
    """Regression for the chain key: the wizard writes cfg["chains"], but the lookup
    read cfg["target_chain"] / cfg["chain"] and so always resolved against chain A."""

    def _cfg(self, pdb_path, chains):
        return {
            "chains": chains,
            "hotspots": "2,3",
            "target_pdb": str(pdb_path),
            "target_sequence": "MKTAYIAKQR",
        }

    @pytest.fixture
    def two_chain_pdb(self, tmp_path):
        """Chain A and chain B with different residue numbering, so resolving against
        the wrong chain yields different indices."""
        lines = []
        serial = 1
        for chain_id, start in (("A", 1), ("B", 101)):
            for pos, aa3 in enumerate(["MET", "LYS", "THR", "ALA", "TYR"]):
                lines.append(
                    f"ATOM  {serial:5d}  CA  {aa3} {chain_id}{start + pos:4d}"
                    f"      0.000   0.000   0.000  1.00  0.00           C"
                )
                serial += 1
        path = tmp_path / "two_chain.pdb"
        path.write_text("\n".join(lines) + "\nEND\n")
        return path

    def test_uses_first_chain_from_chains_key(self, two_chain_pdb):
        cfg = self._cfg(two_chain_pdb, "A")
        assert conf.hotspots_to_epitope_idx(cfg) == [1, 2]

    def test_respects_a_non_default_chain(self, two_chain_pdb):
        """Hotspots 2,3 are not residue numbers in chain B (101-105), so nothing resolves —
        proving chain B was actually consulted instead of silently falling back to A."""
        cfg = self._cfg(two_chain_pdb, "B")
        assert conf.hotspots_to_epitope_idx(cfg) is None

    def test_multi_chain_selection_uses_the_primary(self, two_chain_pdb):
        cfg = self._cfg(two_chain_pdb, "B,A")
        assert conf.hotspots_to_epitope_idx(cfg) is None

    def test_returns_none_without_hotspots(self, two_chain_pdb):
        cfg = self._cfg(two_chain_pdb, "A")
        cfg["hotspots"] = ""
        assert conf.hotspots_to_epitope_idx(cfg) is None


# ── All seven tools reachable from every UI surface ───────────────────────────


_ALL_SEVEN = {
    "mosaic": True,
    "boltzgen": True,
    "bindcraft": True,
    "pxdesign_local": True,
    "proteina_complexa": True,
    "rfd3": True,
    "protein_hunter": True,
    "evaluator": True,
}


class TestToolSequenceCoverage:
    """Regression: the preview tree, the 'To run later' list and run_pipeline() were
    three independently maintained if-chains. The tree knew 4 of the 7 tools and the
    other two knew 5, so enabling RFD3 or Protein-Hunter produced a run script the
    user was never told about and that 'Run the pipeline now?' silently skipped."""

    def test_sequence_covers_every_design_tool(self):
        keys = {key for key, _script, _label, _subdir in conf.TOOL_SEQUENCE}
        assert keys == {
            "mosaic",
            "boltzgen",
            "bindcraft",
            "pxdesign_local",
            "proteina_complexa",
            "rfd3",
            "protein_hunter",
        }

    def test_enabled_tools_preserves_execution_order(self):
        got = [key for key, _s, _l, _d in conf.enabled_tools(_ALL_SEVEN)]
        assert got == [key for key, _s, _l, _d in conf.TOOL_SEQUENCE]

    def test_enabled_tools_filters_disabled(self):
        only = dict.fromkeys(_ALL_SEVEN, False)
        only["rfd3"] = True
        assert [k for k, *_ in conf.enabled_tools(only)] == ["rfd3"]

    def test_preview_tree_lists_every_generated_script(self, base_cfg, capsys):
        conf.print_tree(base_cfg["run_dir"], _ALL_SEVEN, base_cfg)
        out = capsys.readouterr().out
        for _key, script, _label, _subdir in conf.TOOL_SEQUENCE:
            assert script in out, f"{script} missing from the Step 7 preview tree"
        assert "run_all.sh" in out
        assert "run_evaluate.sh" in out

    def test_run_all_covers_every_enabled_tool(self, base_cfg, tmp_path):
        script = tmp_path / "run_all.sh"
        conf.write_run_all(script, base_cfg, _ALL_SEVEN)
        content = script.read_text()
        for _key, run_script, _label, _subdir in conf.TOOL_SEQUENCE:
            assert run_script in content, f"{run_script} missing from run_all.sh"

    def test_run_all_runs_mosaic_instead_of_skipping_it(self, base_cfg, tmp_path):
        """run_all.sh is the documented one-command path, so it must run all the tools.

        The Mosaic block used to print "needs interactive input and is being SKIPPED"
        and continue, so an overnight campaign silently produced 6 of 7 tools' designs.
        run_mosaic.sh needs no stdin: it runs mosaic/hallucinate.py, every parameter of
        which write_mosaic_hallucinate injects at generation time.

        The block must still not `exit 1` — it is emitted first, and aborting there used
        to stop the whole run before any other tool had started.
        """
        script = tmp_path / "run_all.sh"
        conf.write_run_all(script, base_cfg, _ALL_SEVEN)
        content = script.read_text()
        mosaic_block = content[content.index("=== Step: Mosaic ===") :]
        mosaic_block = mosaic_block[: mosaic_block.index("\nfi")]
        assert "exit 1" not in mosaic_block
        assert "SKIPPED" not in mosaic_block
        assert 'run_tool "Mosaic" "$RUN_DIR/run_mosaic.sh"' in mosaic_block


class TestRunAllIsolatesToolFailures:
    """One tool dying must not cost the campaign the other six.

    These tools run for hours to days and fail independently (OOM, missing weights,
    a bad checkpoint). Under `set -e` plus a per-tool `check_outputs … exit 1`, a
    BoltzGen crash at hour 2 aborted the script: RFD3 and Protein-Hunter never
    started, and the Evaluator never ran on the designs that HAD finished. The same
    reasoning already fixed the Mosaic block above; it applies to every step.
    """

    def _content(self, base_cfg, tmp_path):
        script = tmp_path / "run_all.sh"
        conf.write_run_all(script, base_cfg, _ALL_SEVEN)
        return script.read_text()

    @staticmethod
    def _code(text):
        """Executable lines only — the rationale comments talk *about* `exit 1`."""
        return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))

    def test_no_set_e(self, base_cfg, tmp_path):
        content = self._content(base_cfg, tmp_path)
        assert "set -euo pipefail" not in content
        assert "set -uo pipefail" in content

    def test_no_step_exits_early(self, base_cfg, tmp_path):
        """The only `exit 1` left is the final summary, after every step has run."""
        code = self._code(self._content(base_cfg, tmp_path))
        body, _, tail = code.rpartition("if [ ${#FAILED[@]} -gt 0 ]; then")
        assert "exit 1" not in body, "a step still aborts the pipeline"
        assert "exit 1" in tail, "the script must still exit non-zero when a step failed"

    def test_every_tool_runs_through_the_isolating_helper(self, base_cfg, tmp_path):
        content = self._content(base_cfg, tmp_path)
        for label in ("BoltzGen", "BindCraft", "PXDesign", "Proteina-Complexa", "RFD3", "Protein-Hunter"):
            assert f'run_tool "{label}"' in content, f"{label} is not failure-isolated"
        assert "check_outputs" not in content, "the aborting helper should be gone"

    def test_helper_records_failures_instead_of_exiting(self, base_cfg, tmp_path):
        content = self._content(base_cfg, tmp_path)
        helper = content[content.index("run_tool() {") : content.index("\n}\n")]
        assert not [ln for ln in helper.splitlines() if ln.strip().startswith("exit")]
        assert 'FAILED+=("$label")' in helper

    def test_evaluator_still_runs_after_a_tool_failed(self, base_cfg, tmp_path):
        content = self._content(base_cfg, tmp_path)
        evaluator_block = content[content.index("=== Step: Evaluator ===") :]
        # Not guarded by a success condition — it reports on whatever completed.
        assert 'if ! "$RUN_DIR/run_evaluate.sh"; then' in evaluator_block
        assert "BINDMASTER_ALLOW_EMPTY=1" in evaluator_block

    def test_exits_non_zero_naming_the_failed_steps(self, base_cfg, tmp_path):
        content = self._content(base_cfg, tmp_path)
        assert "${FAILED[*]}" in content
        assert content.rstrip().endswith('echo "=== Pipeline complete! ==="')


class TestRunEvaluateAllowsEmptyOnlyWhenToldTo:
    """`extract` errors on a tool directory that yields nothing, so a mistyped path
    cannot silently shrink the pool before hours of GPU refolding. Correct standalone;
    wrong when run_all.sh already knows a tool died and wants the rest reported on."""

    def test_extract_honours_the_env_var(self, base_cfg, tmp_path):
        script = tmp_path / "run_evaluate.sh"
        conf.write_run_evaluate(script, base_cfg, _ALL_SEVEN)
        assert "${BINDMASTER_ALLOW_EMPTY:+--allow-empty}" in script.read_text()

    def test_strict_by_default(self, base_cfg, tmp_path):
        """Unset means no flag: the guard stays on for a hand-run evaluation."""
        script = tmp_path / "run_evaluate.sh"
        conf.write_run_evaluate(script, base_cfg, _ALL_SEVEN)
        content = script.read_text()
        assert "--allow-empty \\" not in content
        assert "\n        --allow-empty\n" not in content


class TestRunEvaluateRfd3Path:
    def test_rfd3_extractor_points_at_the_dir_run_rfd3_writes(self, base_cfg, tmp_path):
        """run_rfd3.sh writes rfd3/sequences.csv; the flag used to point at
        rfd3/outputs/, an empty directory, so RFD3 designs never reached the report."""
        script = tmp_path / "run_evaluate.sh"
        conf.write_run_evaluate(script, base_cfg, _ALL_SEVEN)
        content = script.read_text()
        run_dir = base_cfg["run_dir"]
        assert f"--rfd3 {run_dir}/rfd3 " in content or f'--rfd3 "{run_dir}/rfd3"' in content or "/rfd3 \\" in content
        assert "rfd3/outputs" not in content

    def test_extract_is_given_the_target_sequence(self, base_cfg, tmp_path):
        """F44: the generated script holds the target three lines below, hands it to
        evaluate.sh, and used to pass nothing to extract — where Proteina-Complexa
        needs it to cut the binder out of the encoded complex."""
        script = tmp_path / "run_evaluate.sh"
        conf.write_run_evaluate(script, base_cfg, _ALL_SEVEN)
        content = script.read_text()
        extract_block = content[content.index("binder-compare extract") : content.index("# Step 2")]
        assert "--target-seq" in extract_block


class TestSettingsJsonSurvivesMissingNvidiaSmi:
    def test_gpu_probes_are_guarded(self, base_cfg, tmp_path):
        """Every generated script runs under `set -euo pipefail`; with pipefail an
        unguarded nvidia-smi command substitution exits 127 before the design step."""
        script = tmp_path / "run_rfd3.sh"
        conf.write_run_rfd3(script, base_cfg)
        content = script.read_text()
        for line in content.splitlines():
            if line.startswith(("GPU_NAME=", "GPU_MEM=")):
                assert "|| echo" in line, f"unguarded GPU probe: {line}"


# ── Headless replay: config.json round-trip (CLAUDE.md deferred item F2) ──────


class TestRunConfigRoundTrip:
    """The wizard's ~80 answers used to be discarded the moment the scripts were
    written: reproducing a campaign meant re-typing every one, and nothing recorded
    what a run was configured with. `cfg` already was the full description."""

    def test_generate_writes_a_config(self, base_cfg, tmp_path):
        tools = {"rfd3": True, "evaluator": True}
        conf.generate(base_cfg, tools)
        written = base_cfg["run_dir"] / conf.CONFIG_FILENAME
        assert written.is_file()
        payload = json.loads(written.read_text())
        assert payload["config_version"] == 1
        assert payload["tools_enabled"]["rfd3"] is True
        assert payload["cfg"]["name"] == base_cfg["name"]

    def test_paths_survive_the_round_trip_as_paths(self, base_cfg, tmp_path):
        conf.write_run_config(tmp_path / "c.json", base_cfg, {"rfd3": True})
        cfg, tools = conf.load_run_config(tmp_path / "c.json")
        assert isinstance(cfg["run_dir"], Path)
        assert cfg["run_dir"] == base_cfg["run_dir"]
        assert tools == {"rfd3": True}

    def test_replay_reproduces_identical_scripts(self, base_cfg, tmp_path):
        """The load-bearing property: --config must generate exactly what the wizard did."""
        tools = {"rfd3": True, "evaluator": True}
        conf.generate(base_cfg, tools)
        first = (base_cfg["run_dir"] / "run_rfd3.sh").read_text()

        cfg2, tools2 = conf.load_run_config(base_cfg["run_dir"] / conf.CONFIG_FILENAME)
        second_dir = tmp_path / "replay"
        cfg2["run_dir"] = second_dir
        second_dir.mkdir(parents=True)
        conf.generate(cfg2, tools2)
        second = (second_dir / "run_rfd3.sh").read_text()

        # Only the run directory should differ.
        assert first.replace(str(base_cfg["run_dir"]), "RUNDIR") == second.replace(str(second_dir), "RUNDIR")

    def test_every_enabled_tool_is_recorded(self, base_cfg):
        tools = dict.fromkeys([k for k, *_ in conf.TOOL_SEQUENCE], True)
        tools["evaluator"] = True
        conf.write_run_config(base_cfg["run_dir"] / "c.json", base_cfg, tools)
        payload = json.loads((base_cfg["run_dir"] / "c.json").read_text())
        assert set(payload["tools_enabled"]) == set(tools)


class TestRunConfigValidation:
    def test_missing_file_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            conf.load_run_config(tmp_path / "nope.json")

    def test_wrong_shape_exits(self, tmp_path):
        p = tmp_path / "c.json"
        p.write_text('{"hello": "world"}')
        with pytest.raises(SystemExit):
            conf.load_run_config(p)

    def test_missing_target_structure_exits(self, base_cfg, tmp_path):
        cfg = dict(base_cfg)
        cfg["target_pdb_src"] = str(tmp_path / "absent.pdb")
        p = tmp_path / "c.json"
        conf.write_run_config(p, cfg, {"rfd3": True})
        with pytest.raises(SystemExit):
            conf.load_run_config(p)

    def test_missing_required_key_exits(self, base_cfg, tmp_path):
        cfg = dict(base_cfg)
        del cfg["name"]
        p = tmp_path / "c.json"
        conf.write_run_config(p, cfg, {"rfd3": True})
        with pytest.raises(SystemExit):
            conf.load_run_config(p)


class TestPreflightFailsBeforeWritingAnything:
    """Enabling a tool that is not installed used to raise FileNotFoundError partway
    through `generate()` — and because config.json was written on the LAST line, the
    wizard's ~80 answers went with it, leaving a half-built run directory behind.
    """

    def _cfg(self, tmp_path):
        run_dir = tmp_path / "runs" / "t"
        run_dir.mkdir(parents=True)
        target = tmp_path / "target.pdb"
        target.write_text("ATOM\n")
        return {
            "name": "t",
            "run_dir": run_dir,
            "target_pdb": target,
            "target_pdb_src": str(target),
            "target_sequence": "MAEVKLSYVL",
            "chains": "A",
            "hotspots": "10",
            "min_length": 65,
            "max_length": 150,
            "n_designs": 10,
            "filter_preset": "default_filters",
            "advanced_preset": "default_4stage_multimer",
        }

    def _uninstall(self, monkeypatch, tmp_path):
        """Point the tool-asset probes at an empty tree.

        `_missing_tool_assets` asks the real filesystem — FILTERS_DIR/<preset>.json,
        MOSAIC_VENV.is_dir(). So these tests used to pass only on a machine where the
        tools happen to be ABSENT, and failed on every machine that had run the
        installer, i.e. exactly the machines the configurator runs on. Simulate the
        uninstalled state instead of inheriting it.
        """
        empty = tmp_path / "not-installed"
        monkeypatch.setattr(conf, "FILTERS_DIR", empty / "settings_filters")
        monkeypatch.setattr(conf, "ADVANCED_DIR", empty / "settings_advanced")
        monkeypatch.setattr(conf, "MOSAIC_VENV", empty / "Mosaic" / ".venv")

    def test_uninstalled_tool_exits_cleanly_instead_of_raising(self, tmp_path, capsys, monkeypatch):
        self._uninstall(monkeypatch, tmp_path)
        cfg = self._cfg(tmp_path)
        with pytest.raises(SystemExit) as exc:
            conf.preflight(cfg, {"bindcraft": True})
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "not installed" in out
        assert "bindmaster install --tool bindcraft" in out, "the error must say how to fix it"

    def test_reports_every_problem_at_once(self, tmp_path, capsys, monkeypatch):
        """One run, one list — not a traceback per attempt."""
        self._uninstall(monkeypatch, tmp_path)
        cfg = self._cfg(tmp_path)
        with pytest.raises(SystemExit):
            conf.preflight(cfg, {"bindcraft": True, "mosaic": True, "pxdesign_local": True})
        out = capsys.readouterr().out
        assert "BindCraft" in out and "Mosaic" in out
        assert "pxdesign_binder_length" in out, "the missing cfg key must be listed too"

    def test_missing_cfg_key_is_named_not_a_keyerror(self, tmp_path, capsys):
        """Regression: a hand-edited --config died with a bare KeyError partway through
        generation. load_run_config validates only three keys.

        The vehicle used to be boltzgen_intermediate, which is no longer required —
        it is derived from the requested design count when absent, because a flat
        10 000 turned a 1-design campaign into a ~15 h BoltzGen run. PXDesign's
        binder length is the same shape of key and still mandatory.
        """
        cfg = self._cfg(tmp_path)
        with pytest.raises(SystemExit):
            conf.preflight(cfg, {"pxdesign_local": True})
        out = capsys.readouterr().out
        assert "pxdesign_binder_length" in out
        assert "config.json" in out, "point the operator at a config that is known-complete"

    def test_a_complete_config_for_installed_tools_passes(self, tmp_path):
        """Tools with no external assets and no extra keys must not be blocked."""
        conf.preflight(self._cfg(tmp_path), {"rfd3": True, "protein_hunter": True, "evaluator": True})

    def test_target_pdb_counts_as_present_when_the_source_is_given(self, tmp_path):
        """generate() derives target_pdb from target_pdb_src, so requiring both would
        reject every config the wizard writes for a fresh machine."""
        cfg = self._cfg(tmp_path)
        del cfg["target_pdb"]
        conf.preflight(cfg, {"rfd3": True})

    def test_generate_calls_preflight_before_touching_the_filesystem(self, tmp_path, monkeypatch):
        cfg = self._cfg(tmp_path)
        run_dir = cfg["run_dir"]
        monkeypatch.setattr(conf, "preflight", lambda c, t: (_ for _ in ()).throw(SystemExit(1)))
        with pytest.raises(SystemExit):
            conf.generate(cfg, {"rfd3": True})
        assert list(run_dir.iterdir()) == [], "generate() wrote files before validating"


class TestConfigJsonSurvivesAFailedGeneration:
    def test_config_written_before_the_tool_writers_run(self, tmp_path, monkeypatch):
        """The answers are the expensive part — ~80 wizard prompts. They must outlive
        any failure in the generators that follow."""
        run_dir = tmp_path / "runs" / "t"
        run_dir.mkdir(parents=True)
        target = tmp_path / "target.pdb"
        target.write_text("ATOM\n")
        cfg = {
            "name": "t",
            "run_dir": run_dir,
            "target_pdb": target,
            "target_pdb_src": str(target),
            "target_sequence": "MAEVKLSYVL",
            "chains": "A",
            "hotspots": "10",
            "min_length": 65,
            "max_length": 150,
            "n_designs": 10,
        }

        def boom(*_a, **_k):
            raise RuntimeError("generator exploded")

        monkeypatch.setattr(conf, "write_run_rfd3", boom)
        with pytest.raises(RuntimeError):
            conf.generate(cfg, {"rfd3": True})

        saved = run_dir / conf.CONFIG_FILENAME
        assert saved.is_file(), "the wizard session was lost to a generator failure"
        payload = json.loads(saved.read_text())
        assert payload["cfg"]["name"] == "t"
        assert payload["tools_enabled"] == {"rfd3": True}


class TestRequiredCfgKeysStayInSyncWithTheWriters:
    """The map is hand-written; the writers are the truth. Re-derive and compare, so a
    new cfg["..."] in a writer cannot reach a user as a KeyError.
    """

    # Read inside a `cfg.get(...)` guard, so absence is handled, not fatal.
    _GUARDED: ClassVar = {"pxdesign_output_dir"}
    # Provided by load_run_config's own validation, checked for every run.
    _ALWAYS_PRESENT: ClassVar = {"name", "run_dir", "target_pdb_src"}

    _WRITERS: ClassVar = {
        "bindcraft": ("write_bindcraft_target", "copy_bindcraft_preset", "write_run_bindcraft"),
        # boltzgen_budget is where cfg["n_designs"] is now read: --budget, settings.json's
        # "budget" and the YAML's run line all route through that one resolver instead of
        # indexing cfg themselves, so the derivation has to follow the read.
        "boltzgen": ("copy_nanobody_scaffolds", "write_boltzgen_yaml", "write_run_boltzgen", "boltzgen_budget"),
        "mosaic": ("write_mosaic_hallucinate", "write_run_mosaic", "hotspots_to_epitope_idx"),
        "pxdesign_local": ("write_pxdesign_yaml", "write_run_pxdesign"),
        "proteina_complexa": ("write_run_proteina_complexa",),
        "rfd3": ("write_run_rfd3",),
        "protein_hunter": ("write_run_protein_hunter",),
        "evaluator": ("write_run_evaluate",),
    }

    @staticmethod
    def _hard_indexed(fn_name):
        """cfg["literal"] READS in a writer — the accesses that raise KeyError."""
        tree = ast.parse(inspect.getsource(getattr(conf, fn_name)))
        return {
            node.slice.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "cfg"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
            and not isinstance(node.ctx, ast.Store)
        }

    def test_every_tool_is_covered(self):
        assert set(conf.REQUIRED_CFG_KEYS) == set(self._WRITERS)
        assert {k for k, *_ in conf.TOOL_SEQUENCE} <= set(conf.REQUIRED_CFG_KEYS)

    @pytest.mark.parametrize("tool", sorted(_WRITERS))
    def test_map_matches_what_the_writers_actually_read(self, tool):
        derived = set()
        for fn_name in self._WRITERS[tool]:
            derived |= self._hard_indexed(fn_name)
        derived -= self._ALWAYS_PRESENT | self._GUARDED
        assert set(conf.REQUIRED_CFG_KEYS[tool]) == derived, (
            f"REQUIRED_CFG_KEYS[{tool!r}] is out of sync with its writers: "
            f"missing {sorted(derived - set(conf.REQUIRED_CFG_KEYS[tool]))}, "
            f"stale {sorted(set(conf.REQUIRED_CFG_KEYS[tool]) - derived)}"
        )


class TestBoltzgenIntermediatePoolTracksTheRequestedCount:
    """A `n_designs: 1` campaign carried `--num_designs 10000` — measured 14 h 53 m on an
    RTX 3090 for one requested design, while every other tool honoured the count.
    """

    def test_one_design_does_not_order_ten_thousand(self):
        assert conf.boltzgen_intermediate({"n_designs": 1}) == 100

    def test_a_nonsensical_count_still_leaves_something_to_filter(self):
        """The floor is why the derivation is max(50, 100 * n), not a bare product."""
        assert conf.boltzgen_intermediate({"n_designs": 0}) == 50

    def test_the_pool_scales_with_the_request(self):
        assert conf.boltzgen_intermediate({"n_designs": 10}) == 1000
        assert conf.boltzgen_intermediate({"n_designs": 100}) == 10000

    def test_the_per_tool_budget_wins_over_the_global_default(self):
        assert conf.boltzgen_intermediate({"n_designs": 1, "boltzgen_budget": 20}) == 2000

    def test_an_explicit_value_is_still_an_override(self):
        """A big pool on purpose must stay possible — BoltzGen really does over-generate."""
        assert conf.boltzgen_intermediate({"n_designs": 1, "boltzgen_intermediate": 10000}) == 10000

    def test_the_generated_script_carries_the_derived_pool(self, base_cfg, tmp_path):
        base_cfg["n_designs"] = 1
        base_cfg["boltzgen_mode"] = "protein"
        script = tmp_path / "run_boltzgen.sh"
        conf.write_run_boltzgen(script, base_cfg)
        content = script.read_text()
        assert "--num_designs 100" in content
        assert "--num_designs 10000" not in content

    def test_the_cost_is_stated_in_hours_before_the_gpu_is_committed(self):
        note = conf.boltzgen_cost_note(10000)
        assert "10,000 intermediate designs" in note
        assert "~15 h" in note
        assert "min" in conf.boltzgen_cost_note(100)


class TestPxdesignEnabledHeadlessActuallyGenerates:
    """`pxdesign: True` in a --config produced no run_pxdesign.sh while the summary still
    listed PXDesign as enabled: the generator is gated on the MODE key, which only the
    wizard's mode prompt ever set.
    """

    def test_the_switch_alone_defaults_to_a_local_run(self):
        tools = {"pxdesign": True}
        conf._default_pxdesign_mode(tools)
        assert tools["pxdesign_local"] is True
        assert [label for _k, _s, label, _d in conf.enabled_tools(tools)] == ["PXDesign"]

    def test_an_explicit_import_mode_is_not_overridden(self):
        tools = {"pxdesign": True, "pxdesign_import": True}
        conf._default_pxdesign_mode(tools)
        assert not tools.get("pxdesign_local")

    def test_the_wizard_mode_selection_is_untouched(self):
        tools = {"pxdesign": True, "pxdesign_local": True, "pxdesign_import": False}
        conf._default_pxdesign_mode(tools)
        assert tools["pxdesign_local"] is True

    def test_a_disabled_tool_stays_disabled(self):
        tools = {"pxdesign": False}
        conf._default_pxdesign_mode(tools)
        assert not tools.get("pxdesign_local")

    def test_a_tool_reported_as_enabled_without_a_run_script_is_an_error(self, tmp_path, capsys):
        """Belt and braces for the whole class: any future tool whose generate() branch
        drifts from its TOOL_SEQUENCE key fails loudly instead of going missing."""
        with pytest.raises(SystemExit) as exc:
            conf.verify_enabled_tools_generated(tmp_path, {"pxdesign_local": True})
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "PXDesign" in out and "run_pxdesign.sh" in out


def _atom(serial, name, res, chain, resnum, record="ATOM  "):
    """One fixed-format PDB atom record: altLoc blank at 17, resName 18-20, chain 22."""
    return (
        f"{record}{serial:5d}  {name:<3s}{res:>4s} {chain}{resnum:4d}    "
        f"{1.0:8.3f}{2.0:8.3f}{3.0:8.3f}{1.00:6.2f}{0.00:6.2f}          {name.strip()[0]:>2s}  "
    )


def _two_chain_pdb() -> str:
    """Chain A = GAH (H is the "tag"), chain B = a bound ligand peptide, plus a water,
    a heteroatom, SEQRES and a CONECT pointing at an atom that preparation removes."""
    lines = [
        "HEADER    TEST",
        "COMPND    2 CHAINS",
        "SEQRES   1 A    3  GLY ALA HIS",
        "SEQRES   1 B    1  TRP",
        "SSBOND   1 CYS A    1    CYS B    1",
        _atom(1, "N", "GLY", "A", 1),
        _atom(2, "CA", "GLY", "A", 1),
        _atom(3, "CA", "ALA", "A", 2),
        _atom(4, "CA", "HIS", "A", 3),
        _atom(5, "CA", "TRP", "B", 1),
        _atom(6, "O", "HOH", "A", 101, record="HETATM"),
        _atom(7, "C1", "9KK", "B", 201, record="HETATM"),
        "CONECT    7    5",
        "ANISOU    1  N   GLY A   1     1      1      1",
        "END",
    ]
    return "\n".join(lines) + "\n"


class TestTargetStructureIsPrepared:
    """A stock RCSB file is not a target. On 5O45 the deposited coordinates carry chain
    A's His6 tag AND chain B, an inhibitor peptide bound in the epitope a binder has to
    reach, so BindCraft / RFD3 contigs / BoltzGen's `file:` entity all designed against
    an occupied site. BUG-09 trimmed the SEQUENCE only; the structure was copied verbatim.
    """

    def _prepared(self, tmp_path, chains="A", seq="GA"):
        src = tmp_path / "t_original.pdb"
        src.write_text(_two_chain_pdb())
        dest = tmp_path / "t.pdb"
        report = conf.prepare_target_pdb(src, dest, chains, seq)
        return report, dest, dest.read_text()

    def test_unselected_chains_are_dropped(self, tmp_path):
        report, dest, _ = self._prepared(tmp_path)
        assert report["dropped_chains"] == {"B": 1}
        assert conf.extract_sequence_from_pdb(str(dest), "B") is None

    def test_the_structure_matches_the_trimmed_sequence_exactly(self, tmp_path):
        """The one invariant that matters: a tool reading the coordinates and a tool
        reading cfg["target_sequence"] must see the same protein."""
        report, dest, _ = self._prepared(tmp_path, seq="GA")
        assert report["trimmed"] == 1
        assert conf.extract_sequence_from_pdb(str(dest), "A") == "GA"

    def test_waters_and_ligands_are_dropped(self, tmp_path):
        report, _dest, text = self._prepared(tmp_path)
        assert report["waters"] == 1
        assert report["ligands"] == {"9KK": 1}
        assert "HETATM" not in text

    def test_header_records_naming_removed_atoms_are_gone(self, tmp_path):
        """A SEQRES declaring more residues than survive killed BoltzGen with
        `IndexError: list index out of range` at pdb_parser.py:39 (entity.subchains[0]),
        and LINK/CONECT pointed at deleted atoms. SEQRES is dropped, not regenerated, so
        the sequence can only come from the ATOM records."""
        _report, _dest, text = self._prepared(tmp_path)
        records = {line[:6].strip() for line in text.splitlines()}
        for record in ("SEQRES", "CONECT", "SSBOND", "ANISOU", "COMPND"):
            assert record not in records, f"{record} survived preparation"
        assert text.startswith("HEADER")
        assert "REMARK 999 PREPARED BY BINDMASTER CONFIGURATOR" in text

    def test_it_is_a_well_formed_pdb(self, tmp_path):
        _report, _dest, text = self._prepared(tmp_path)
        lines = text.splitlines()
        assert lines[-1] == "END"
        assert lines[-2].startswith("TER   ")
        serials = [int(line[6:11]) for line in lines if line[:4] == "ATOM"]
        assert serials == list(range(1, len(serials) + 1)), "serials must be renumbered"

    def test_residue_numbering_is_preserved_so_hotspots_still_resolve(self, tmp_path):
        """Hotspots are the deposited residue numbers the user typed in Step 3."""
        _report, dest, _text = self._prepared(tmp_path)
        assert conf.pdb_chain_residue_numbers(str(dest), "A") == [1, 2]

    def test_a_sequence_that_is_not_in_the_structure_is_reported_not_guessed(self, tmp_path):
        report, dest, _text = self._prepared(tmp_path, seq="WWWWW")
        assert report["trim_failed"] == "A"
        assert conf.extract_sequence_from_pdb(str(dest), "A") == "GAH"

    def test_nothing_is_written_when_nothing_would_survive(self, tmp_path):
        """generate() then falls back to copying the source verbatim rather than
        handing the tools an empty structure."""
        src = tmp_path / "x_original.pdb"
        src.write_text("ATOM\n")
        dest = tmp_path / "x.pdb"
        assert conf.prepare_target_pdb(src, dest, "A", "") is None
        assert not dest.exists()

    def test_generate_keeps_the_untouched_source_alongside(self, tmp_path):
        run_dir = tmp_path / "runs" / "t"
        run_dir.mkdir(parents=True)
        src = tmp_path / "deposited.pdb"
        src.write_text(_two_chain_pdb())
        cfg = {
            "name": "t",
            "run_dir": run_dir,
            "target_pdb_src": str(src),
            "target_sequence": "GA",
            "chains": "A",
            "hotspots": None,
        }
        conf.generate(cfg, {})
        assert (run_dir / "target" / "t_original.pdb").read_text() == _two_chain_pdb()
        assert cfg["target_pdb"] == run_dir / "target" / "t.pdb"
        assert conf.extract_sequence_from_pdb(str(cfg["target_pdb"]), "A") == "GA"


# ─── Expression-tag detection ─────────────────────────────────────────────────

# 5O45 (PD-L1)'s real C-terminus, which is the whole of BUG-09's miss. The depositor
# flags ELEVEN residues (135-145 = AAALE + His6) as EXPRESSION TAG; the old
# `[GSAL]{0,3}H{5,10}$` pattern stops at the 'E' of AAALE because E is not in [GSAL],
# so it trimmed 6 of 11 and five construct residues survived as designable surface and
# went into the shared target-MSA cache key.
_5O45_TAIL = "ITVKVNAPY" + "AAALE" + "HHHHHH"
_5O45_NATIVE = "ITVKVNAPY"
_5O45_FIRST = 126  # so the tag lands on 135-145, exactly as deposited

_ONE_TO_THREE: dict = {}
for _three, _one in conf.AA3TO1.items():
    _ONE_TO_THREE.setdefault(_one, _three)


def _seqadv(resname, chain, resnum, note="EXPRESSION TAG"):
    """One fixed-format SEQADV record: resName 13-15, chainID 17, seqNum 19-22,
    conflict 50-70 (1-based), matching the PDB format spec."""
    head = f"SEQADV TEST {resname:>3s} {chain} {resnum:4d} "
    return f"{head:<49s}{note:<21s}"


def _tagged_pdb(note="EXPRESSION TAG", tail=_5O45_TAIL, first=_5O45_FIRST, flag_from=135, flag_to=145):
    """5O45's shape: chain A's C-terminus plus its SEQADV records, and a chain B peptide."""
    head = ["HEADER    TEST"]
    atoms = []
    for i, one in enumerate(tail):
        num = first + i
        if flag_from <= num <= flag_to:
            head.append(_seqadv(_ONE_TO_THREE[one], "A", num, note))
        atoms.append(_atom(len(atoms) + 1, "CA", _ONE_TO_THREE[one], "A", num))
    atoms.append(_atom(len(atoms) + 1, "CA", "TRP", "B", 1))
    return "\n".join(head + atoms + ["END"]) + "\n"


def _tagged_cif(details="expression tag", strand="A", mon_override=None):
    """Minimal mmCIF with the same tag, annotated in _struct_ref_seq_dif."""
    lines = [
        "data_TEST",
        "loop_",
        "_atom_site.group_PDB",
        "_atom_site.id",
        "_atom_site.label_atom_id",
        "_atom_site.label_comp_id",
        "_atom_site.label_asym_id",
        "_atom_site.label_seq_id",
        "_atom_site.Cartn_x",
        "_atom_site.Cartn_y",
        "_atom_site.Cartn_z",
    ]
    for i, one in enumerate(_5O45_TAIL):
        lines.append(f"ATOM {i + 1} CA {_ONE_TO_THREE[one]} A {i + 1} 1.0 2.0 3.0")
    lines += [
        "#",
        "loop_",
        "_struct_ref_seq_dif.align_id",
        "_struct_ref_seq_dif.mon_id",
        "_struct_ref_seq_dif.pdbx_pdb_strand_id",
        "_struct_ref_seq_dif.seq_num",
        "_struct_ref_seq_dif.details",
        "_struct_ref_seq_dif.pdbx_auth_seq_num",
    ]
    for i, one in enumerate(_5O45_TAIL):
        if i + 1 <= len(_5O45_NATIVE):
            continue
        mon = mon_override or _ONE_TO_THREE[one]
        lines.append(f"1 {mon} {strand} {i + 1} '{details}' {_5O45_FIRST + i}")
    lines.append("#")
    return "\n".join(lines) + "\n"


@pytest.fixture
def always_yes(monkeypatch):
    monkeypatch.setattr(conf, "ask_yn", lambda *_a, **_k: True)


class TestExpressionTagTrimUsesTheDepositorsOwnAnnotation:
    """The construct residues are not guessable from the sequence, and they do not have
    to be guessed: the depositor named them, per residue, at deposition time (SEQADV in
    a PDB, _struct_ref_seq_dif in an mmCIF). Those records are in the lines the
    configurator already reads.
    """

    def test_the_whole_aaale_his6_tag_is_trimmed_not_just_the_his_run(self, tmp_path, always_yes):
        src = tmp_path / "5o45.pdb"
        src.write_text(_tagged_pdb())
        seq = conf.extract_sequence_from_pdb(str(src), "A")
        assert seq.endswith("ITVKVNAPYAAALE" + "HHHHHH")
        assert conf.warn_expression_tags(seq, str(src), "A") == _5O45_NATIVE

    def test_the_evidence_says_the_annotation_is_authoritative(self, tmp_path, always_yes, capsys):
        src = tmp_path / "5o45.pdb"
        src.write_text(_tagged_pdb())
        conf.warn_expression_tags(conf.extract_sequence_from_pdb(str(src), "A"), str(src), "A")
        out = capsys.readouterr().out
        assert "SEQADV" in out, "the user must be told this is the depositor's own record"
        assert "GUESS" not in out

    def test_the_mmcif_annotation_is_read_too(self, tmp_path, always_yes, capsys):
        src = tmp_path / "5o45.cif"
        src.write_text(_tagged_cif())
        seq = conf.extract_sequence_from_cif(str(src), "A")
        assert seq == _5O45_TAIL
        assert conf.warn_expression_tags(seq, str(src), "A") == _5O45_NATIVE
        assert "_struct_ref_seq_dif" in capsys.readouterr().out

    def test_declining_keeps_every_residue(self, tmp_path, monkeypatch):
        monkeypatch.setattr(conf, "ask_yn", lambda *_a, **_k: False)
        src = tmp_path / "5o45.pdb"
        src.write_text(_tagged_pdb())
        seq = conf.extract_sequence_from_pdb(str(src), "A")
        assert conf.warn_expression_tags(seq, str(src), "A") == seq

    @pytest.mark.parametrize("note", ["CLONING ARTIFACT", "LINKER"])
    def test_the_other_accepted_annotations(self, tmp_path, always_yes, note):
        src = tmp_path / "x.pdb"
        src.write_text(_tagged_pdb(note=note))
        seq = conf.extract_sequence_from_pdb(str(src), "A")
        assert conf.warn_expression_tags(seq, str(src), "A") == _5O45_NATIVE

    @pytest.mark.parametrize("note", ["CONFLICT", "ENGINEERED MUTATION", "VARIANT", "INSERTION", "DELETION"])
    def test_a_mutation_or_conflict_annotation_is_not_construct(self, tmp_path, always_yes, note):
        """Those residues are the protein that was crystallised, not added sequence.
        The pattern fallback may still offer the His run — but the annotation must not
        claim authority over AAALE."""
        src = tmp_path / "x.pdb"
        src.write_text(_tagged_pdb(note=note))
        lines = src.read_text().splitlines()
        assert conf._pdb_seqadv_construct(lines, "A") == {}

    def test_an_interior_annotation_is_never_excised(self):
        """An interior SEQADV is a point mutation, not a tag; removing it would splice
        two distant stretches of the chain together."""
        assert conf._terminal_construct_span({5}, 20) == (0, 20)
        assert conf._terminal_construct_span({0, 1, 5, 19}, 20) == (2, 19)

    def test_a_fully_flagged_chain_is_refused_rather_than_emptied(self):
        assert conf._terminal_construct_span({0, 1, 2}, 3) == (0, 3)

    def test_interior_flags_are_reported_as_kept(self, tmp_path, always_yes, capsys):
        src = tmp_path / "x.pdb"
        # Flag the terminal tag AND one interior residue (resnum 130, mid-chain).
        text = _tagged_pdb()
        # resnum 130 is index 4 of the chain, a VAL — the name must match or the
        # annotation is (correctly) refused as a chain mismatch.
        text = text.replace("HEADER    TEST\n", "HEADER    TEST\n" + _seqadv("VAL", "A", 130) + "\n")
        src.write_text(text)
        seq = conf.extract_sequence_from_pdb(str(src), "A")
        assert conf.warn_expression_tags(seq, str(src), "A") == _5O45_NATIVE
        out = capsys.readouterr().out
        assert "INTERIOR" in out and "KEPT" in out

    def test_a_chain_id_namespace_mismatch_is_refused_not_applied(self, tmp_path):
        """pdbx_pdb_strand_id is the AUTHOR chain id while the sequence extractor filters
        on label_asym_id. If the two denote different chains the annotated residue NAMES
        will not line up, and the annotation must be dropped, not applied blind."""
        src = tmp_path / "x.cif"
        src.write_text(_tagged_cif(mon_override="TRP"))
        seq = conf.extract_sequence_from_cif(str(src), "A")
        assert conf._annotated_construct_span(seq, str(src), "A") is None

    def test_an_annotation_for_another_chain_is_ignored(self, tmp_path):
        src = tmp_path / "x.cif"
        src.write_text(_tagged_cif(strand="B"))
        seq = conf.extract_sequence_from_cif(str(src), "A")
        assert conf._annotated_construct_span(seq, str(src), "A") is None


class TestTagPatternFallbackHandlesArbitraryLinkers:
    """For files with no per-residue annotation the pattern is all there is, so it must
    not assume the linker is made of G/S/A/L.
    """

    def _no_annotation(self, tmp_path, tail):
        src = tmp_path / "plain.pdb"
        src.write_text(_tagged_pdb(tail=tail, flag_from=10**6, flag_to=10**6))
        return str(src), conf.extract_sequence_from_pdb(str(src), "A")

    @pytest.mark.parametrize("linker", ["AAALE", "LE", "GSGS", "GGGGSGGGGS", "ENLYFQG", "LVPRGS", "GS", ""])
    def test_a_named_linker_in_front_of_the_his_run_goes_too(self, tmp_path, always_yes, linker):
        """AAALE is the one that mattered: [GSAL]{0,3} stopped at its 'E' on 5O45."""
        path, seq = self._no_annotation(tmp_path, _5O45_NATIVE + linker + "HHHHHH")
        assert conf.warn_expression_tags(seq, path, "A") == _5O45_NATIVE

    def test_an_unnamed_linker_costs_no_native_residues(self, tmp_path, always_yes):
        """The honest limit of a guess. "Up to 5 residues of anything" would catch RSVD
        here, but it also trims …ITVKVNAPY|HHHHHH down to …ITVK, because a pattern cannot
        tell a 0-residue linker from a 5-residue one. Over-trimming native protein is the
        worse failure, and the authoritative SEQADV path is what handles this properly."""
        path, seq = self._no_annotation(tmp_path, _5O45_NATIVE + "RSVD" + "HHHHHH")
        assert conf.warn_expression_tags(seq, path, "A") == _5O45_NATIVE + "RSVD"

    def test_a_plain_his_tag_never_eats_the_residues_in_front_of_it(self, tmp_path, always_yes):
        path, seq = self._no_annotation(tmp_path, _5O45_NATIVE + "HHHHHH")
        assert conf.warn_expression_tags(seq, path, "A") == _5O45_NATIVE

    def test_the_evidence_says_plainly_that_it_is_a_guess(self, tmp_path, always_yes, capsys):
        path, seq = self._no_annotation(tmp_path, _5O45_NATIVE + "AAALEHHHHHH")
        conf.warn_expression_tags(seq, path, "A")
        out = capsys.readouterr().out
        assert "GUESS" in out
        assert "SEQADV" not in out

    def test_a_native_sequence_with_no_his_run_is_left_alone(self, tmp_path, always_yes):
        path, seq = self._no_annotation(tmp_path, "ITVKVNAPYWKTVNDLGE")
        assert conf.warn_expression_tags(seq, path, "A") == seq

    def test_an_n_terminal_his_tag_is_still_found(self, always_yes):
        assert conf.warn_expression_tags("MGSSHHHHHHSSGLITVKVNAPY") == "ITVKVNAPY"


class TestPreparedStructureWarnsAboutConstructResiduesItKeeps:
    """prepare_target_pdb reads the SEQADV lines anyway. A cheap backstop for exactly
    the class of miss above: if a residue it is KEEPING is flagged as construct, the
    sequence trim did not happen or did not reach far enough.
    """

    def test_a_kept_tag_residue_is_named(self, tmp_path, capsys):
        src = tmp_path / "t_original.pdb"
        src.write_text(_tagged_pdb())
        dest = tmp_path / "t.pdb"
        report = conf.prepare_target_pdb(src, dest, "A", "")  # no trim: tag kept
        assert report["construct_kept"]["A"] == [str(n) for n in range(135, 146)]
        conf.report_target_preparation(report, dest)
        out = capsys.readouterr().out
        assert "flagged as construct" in out
        assert "135" in out

    def test_an_accepted_trim_leaves_nothing_to_warn_about(self, tmp_path):
        src = tmp_path / "t_original.pdb"
        src.write_text(_tagged_pdb())
        dest = tmp_path / "t.pdb"
        report = conf.prepare_target_pdb(src, dest, "A", _5O45_NATIVE)
        assert report["construct_kept"] == {}
        assert report["trimmed"] == 11
        assert conf.extract_sequence_from_pdb(str(dest), "A") == _5O45_NATIVE
        assert conf.pdb_chain_residue_numbers(str(dest), "A") == list(range(126, 135))
        assert conf.extract_sequence_from_pdb(str(dest), "B") is None


class TestPxdesignImportConfigsStillWork:
    """Defaulting an unset mode to local broke the other hand-written shape:
    `{pxdesign: true}` + cfg["pxdesign_output_dir"] is unambiguously an IMPORT, and
    forcing it local then hard-failed preflight on local mode's required keys.
    """

    def test_an_output_dir_infers_import_not_local(self):
        tools = {"pxdesign": True}
        conf._default_pxdesign_mode(tools, {"pxdesign_output_dir": "/elsewhere/px"})
        assert tools["pxdesign_import"] is True
        assert not tools.get("pxdesign_local")

    def test_no_output_dir_still_defaults_to_local(self):
        tools = {"pxdesign": True}
        conf._default_pxdesign_mode(tools, {"n_designs": 1})
        assert tools["pxdesign_local"] is True

    def test_the_inferred_import_config_passes_preflight(self, base_cfg):
        cfg = {k: v for k, v in base_cfg.items() if k != "pxdesign_binder_length"}
        cfg["pxdesign_output_dir"] = "/elsewhere/px"
        tools = {"pxdesign": True}
        conf._default_pxdesign_mode(tools, cfg)
        conf.preflight(cfg, tools)  # must not SystemExit

    def test_the_imported_results_dir_reaches_run_evaluate(self, base_cfg, tmp_path):
        base_cfg["pxdesign_output_dir"] = "/elsewhere/px"
        tools = {"pxdesign": True, "evaluator": True}
        conf._default_pxdesign_mode(tools, base_cfg)
        conf.write_run_evaluate(tmp_path / "run_evaluate.sh", base_cfg, tools)
        assert '--pxdesign "/elsewhere/px"' in (tmp_path / "run_evaluate.sh").read_text()

    def test_the_inference_says_which_mode_and_why(self, capsys):
        conf._default_pxdesign_mode({"pxdesign": True}, {"pxdesign_output_dir": "/x"})
        out = capsys.readouterr().out
        assert "IMPORT" in out and "pxdesign_output_dir" in out


class TestEnabledToolWithoutAGeneratorFailsBeforeAnyWrite:
    """The guard used to be the last statement of generate(), so it exited 1 only AFTER
    every file and both config.json writes — the opposite of the preflight behaviour the
    rest of the project uses.
    """

    @pytest.fixture
    def _ghost(self, monkeypatch):
        monkeypatch.setattr(conf, "TOOL_SEQUENCE", [*conf.TOOL_SEQUENCE, ("ghost", "run_ghost.sh", "Ghost", "ghost")])

    def test_preflight_rejects_it(self, base_cfg, _ghost, capsys):
        with pytest.raises(SystemExit) as exc:
            conf.preflight(base_cfg, {"ghost": True})
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "Ghost" in out and "run_ghost.sh" in out

    def test_generate_leaves_no_half_built_run_directory(self, base_cfg, _ghost):
        run_dir = base_cfg["run_dir"]
        with pytest.raises(SystemExit):
            conf.generate(base_cfg, {"ghost": True})
        assert list(run_dir.iterdir()) == [], "the user was left a partial run dir to clean up"

    def test_the_registry_matches_the_keys_generate_actually_branches_on(self):
        tree = ast.parse(inspect.getsource(conf.generate))
        branched = {
            node.args[0].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "tools_enabled"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        }
        # "evaluator" is not a design tool and is deliberately not in TOOL_SEQUENCE.
        assert branched - {"evaluator"} == conf._SCRIPT_WRITER_KEYS

    def test_the_post_write_assertion_is_still_there(self, tmp_path):
        with pytest.raises(SystemExit):
            conf.verify_enabled_tools_generated(tmp_path, {"rfd3": True})


class TestRunAllPrintsOneStepBannerPerTool:
    def test_mosaic_does_not_print_its_header_twice(self, base_cfg, tmp_path):
        script = tmp_path / "run_all.sh"
        conf.write_run_all(script, base_cfg, _ALL_SEVEN)
        content = script.read_text()
        assert content.count('echo "=== Step: $label ==="') == 1, "run_tool's generic banner"
        for _key, _script, label, _subdir in conf.TOOL_SEQUENCE:
            assert content.count(f'echo "=== Step: {label} ==="') <= 1, f"{label} banner duplicated"

    def test_the_already_done_branch_still_announces_the_step(self, base_cfg, tmp_path):
        """run_tool is never called on that branch, so the banner has to live inside it."""
        script = tmp_path / "run_all.sh"
        conf.write_run_all(script, base_cfg, _ALL_SEVEN)
        content = script.read_text()
        block = content[content.index('if [[ -f "$RUN_DIR/mosaic/designs.csv" ]]') :]
        block = block[: block.index("\nfi")]
        assert 'echo "=== Step: Mosaic ==="' in block.split("else")[0]
        assert 'run_tool "Mosaic"' in block.split("else")[1]


class TestBoltzgenBudgetIsResolvedInOnePlace:
    """--budget and settings.json's "budget" read cfg["n_designs"] and ignored
    cfg["boltzgen_budget"], the per-tool override the wizard prompts for, while the
    intermediate-pool derivation did consult it. The two disagreed.
    """

    def test_the_per_tool_budget_reaches_the_generated_script(self, base_cfg, tmp_path):
        base_cfg["n_designs"] = 10
        base_cfg["boltzgen_budget"] = 20
        script = tmp_path / "run_boltzgen.sh"
        conf.write_run_boltzgen(script, base_cfg)
        content = script.read_text()
        assert "--budget 20" in content
        assert '"budget": 20' in content
        assert "--budget 10" not in content
        assert f"--num_designs {conf.boltzgen_intermediate(base_cfg)}" in content

    def test_the_yaml_run_line_agrees_with_the_script(self, base_cfg, tmp_path):
        base_cfg["n_designs"] = 10
        base_cfg["boltzgen_budget"] = 20
        yaml = tmp_path / "config.yaml"
        conf.write_boltzgen_yaml(yaml, base_cfg)
        assert "--budget 20" in yaml.read_text()

    def test_the_global_count_is_still_the_fallback(self):
        assert conf.boltzgen_budget({"n_designs": 7}) == 7

    def test_boltzgen_budget_is_not_newly_mandatory(self, base_cfg):
        assert "boltzgen_budget" not in conf.REQUIRED_CFG_KEYS["boltzgen"]
        base_cfg.pop("boltzgen_budget", None)
        conf.preflight(base_cfg, {"boltzgen": True})  # must not SystemExit

    def test_a_missing_design_count_stays_a_preflight_matter(self):
        """Resolving it to a silent 1 would turn an incomplete config into one binder."""
        with pytest.raises(KeyError):
            conf.boltzgen_budget({})
