"""Tests for RFAA config validation — no GPU required."""

from pathlib import Path
from unittest.mock import patch

import pytest

from bindmaster.tools.rfaa.config import RFAAConfig, RFAAContigConfig, RFAAInferenceConfig


def test_ligand_ccd_validation():
    """CCD code must be exactly 3 letters."""
    with pytest.raises(ValueError, match="3 letters"):
        RFAAInferenceConfig(
            input_pdb=Path("nonexistent.pdb"),
            output_prefix="out",
            ligand="TOOLONG",
        )


def test_ligand_ccd_uppercase():
    """CCD code should be normalized to uppercase."""
    with patch("pathlib.Path.exists", return_value=True):
        cfg = RFAAInferenceConfig(
            input_pdb=Path("test.pdb"),
            output_prefix="out",
            ligand="oqo",
        )
    assert cfg.ligand == "OQO"


def test_hydra_overrides_ligand():
    """Hydra overrides should include ligand when specified."""
    with patch("pathlib.Path.exists", return_value=True):
        config = RFAAConfig(
            inference=RFAAInferenceConfig(
                input_pdb=Path("test.pdb"),
                output_prefix="out/sample",
                ligand="OQO",
                num_designs=5,
            ),
            contigmap=RFAAContigConfig(contigs="150-150"),
        )
    overrides = config.to_hydra_overrides()
    assert any("inference.ligand=OQO" in o for o in overrides)
    assert any("inference.num_designs=5" in o for o in overrides)


def test_contig_validation():
    from bindmaster.tools.rfaa.ligand_prep import validate_contig_string

    valid, msg = validate_contig_string("150-150")
    assert valid and msg == ""
    valid, msg = validate_contig_string("10-120,A84-87,10-120")
    assert valid
    valid, msg = validate_contig_string("")
    assert not valid


def test_dry_run_does_not_execute(tmp_path):
    """Dry run should build command but not execute RFAA."""
    with patch("pathlib.Path.exists", return_value=True):
        config = RFAAConfig(
            inference=RFAAInferenceConfig(
                input_pdb=Path("test.pdb"),
                output_prefix=str(tmp_path / "sample"),
                num_designs=1,
            ),
        )

    from bindmaster.tools.rfaa.runner import RFAARunner

    runner = object.__new__(RFAARunner)
    runner.rfaa_root = Path("/fake/rfaa")

    with patch("subprocess.run") as mock_run:
        result = runner.run(config=config, output_dir=tmp_path, dry_run=True)
        mock_run.assert_not_called()
    assert result.metadata["dry_run"] is True
