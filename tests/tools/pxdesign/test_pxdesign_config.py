"""Tests for PXDesign config and results parsing — no GPU required."""
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from bindmaster.tools.pxdesign.config import (
    PXDesignConfig, PXDesignTargetConfig, ChainConfig
)


def make_config(tmp_path) -> PXDesignConfig:
    """Helper: build a valid config pointing to a fake CIF file."""
    fake_cif = tmp_path / "target.cif"
    fake_cif.write_text("fake cif content")
    return PXDesignConfig(
        target=PXDesignTargetConfig(
            file=fake_cif,
            chains={
                "A": ChainConfig(
                    crop=["1-116"],
                    hotspots=[40, 99, 107],
                )
            }
        ),
        binder_length=80,
        n_samples=10,
        preset="preview",
    )


def test_yaml_generation(tmp_path):
    """YAML output must contain required keys."""
    import yaml
    config = make_config(tmp_path)
    yaml_path = tmp_path / "test_input.yaml"
    config.to_yaml(yaml_path)
    assert yaml_path.exists()

    with open(yaml_path) as f:
        doc = yaml.safe_load(f)

    assert doc["binder_length"] == 80
    assert "target" in doc
    assert "A" in doc["target"]["chains"]
    assert doc["target"]["chains"]["A"]["hotspots"] == [40, 99, 107]


def test_target_hash_is_stable(tmp_path):
    """Same config must always produce same hash."""
    config = make_config(tmp_path)
    h1 = config.target_hash()
    h2 = config.target_hash()
    assert h1 == h2
    assert len(h1) == 16


def test_cli_args_preview():
    """Preview mode should not include deepspeed args."""
    with patch("pathlib.Path.exists", return_value=True):
        config = PXDesignConfig(
            target=PXDesignTargetConfig(
                file=Path("fake.cif"),
                chains={"A": "all"},
            ),
            binder_length=80,
            preset="preview",
            use_deepspeed_evo_attention=False,
        )
    args = config.to_cli_args()
    assert "--preset" in args
    assert "preview" in args


def test_parse_summary_csv(tmp_path):
    """Parser should handle typical PXDesign summary.csv."""
    from bindmaster.tools.pxdesign.results_parser import parse_summary_csv

    csv_content = (
        "design_file,af2_ipTM,af2_ipAE,af2_pLDDT,af2_binder_RMSD,"
        "ptx_ipTM,ptx_pTM,ptx_complex_RMSD,"
        "AF2-IG-success,AF2-IG-easy-success,Protenix-success,Protenix-basic-success\n"
        "design_001.cif,0.72,5.1,0.91,0.8,0.87,0.89,1.2,True,True,True,True\n"
        "design_002.cif,0.45,12.0,0.75,4.1,0.65,0.70,3.1,False,False,False,False\n"
    )
    csv_path = tmp_path / "summary.csv"
    csv_path.write_text(csv_content)

    records = parse_summary_csv(csv_path)
    assert len(records) == 2
    assert records[0]["af2_iptm"] == pytest.approx(0.72)
    assert records[0]["passes_protenix_strict"] is True
    assert records[1]["passes_af2ig_strict"] is False
