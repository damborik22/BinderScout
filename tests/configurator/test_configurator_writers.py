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

    def test_run_all_does_not_abort_when_mosaic_output_is_absent(self, base_cfg, tmp_path):
        """The Mosaic block is emitted first; `exit 1` there aborted the whole run
        before any other tool started."""
        script = tmp_path / "run_all.sh"
        conf.write_run_all(script, base_cfg, _ALL_SEVEN)
        content = script.read_text()
        mosaic_block = content[content.index("=== Step: Mosaic ===") :]
        mosaic_block = mosaic_block[: mosaic_block.index("fi")]
        assert "exit 1" not in mosaic_block
        assert "SKIPPED" in mosaic_block


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

    def test_uninstalled_tool_exits_cleanly_instead_of_raising(self, tmp_path, capsys):
        cfg = self._cfg(tmp_path)
        with pytest.raises(SystemExit) as exc:
            conf.preflight(cfg, {"bindcraft": True})
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "not installed" in out
        assert "bindmaster install --tool bindcraft" in out, "the error must say how to fix it"

    def test_reports_every_problem_at_once(self, tmp_path, capsys):
        """One run, one list — not a traceback per attempt."""
        cfg = self._cfg(tmp_path)
        with pytest.raises(SystemExit):
            conf.preflight(cfg, {"bindcraft": True, "mosaic": True, "boltzgen": True})
        out = capsys.readouterr().out
        assert "BindCraft" in out and "Mosaic" in out
        assert "boltzgen_intermediate" in out, "the missing cfg key must be listed too"

    def test_missing_cfg_key_is_named_not_a_keyerror(self, tmp_path, capsys):
        """Regression: a hand-edited --config died with `KeyError: 'boltzgen_intermediate'`
        partway through generation. load_run_config validates only three keys."""
        cfg = self._cfg(tmp_path)
        with pytest.raises(SystemExit):
            conf.preflight(cfg, {"boltzgen": True})
        out = capsys.readouterr().out
        assert "boltzgen_intermediate" in out
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
        "boltzgen": ("copy_nanobody_scaffolds", "write_boltzgen_yaml", "write_run_boltzgen"),
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
