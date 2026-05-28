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
