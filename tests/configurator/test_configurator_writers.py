"""Tests for new configurator run script writers and config generators."""

import sys
from pathlib import Path

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
