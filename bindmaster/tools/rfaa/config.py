"""
RFDiffusionAA configuration — Pydantic model for all Hydra parameters.
Maps to config/inference/*.yaml in the RFAA repo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, validator


class RFAADiffuserConfig(BaseModel):
    """Diffuser settings — maps to diffuser.* Hydra keys."""
    T: int = Field(100, ge=10, le=500, description="Number of denoising steps")


class RFAAInferenceConfig(BaseModel):
    """Inference settings — maps to inference.* Hydra keys."""
    input_pdb: Path
    output_prefix: str
    ligand: Optional[str] = Field(
        None,
        description="3-letter PDB CCD code (e.g. OQO, HEM, ATP). "
                    "Required for ligand binder design. "
                    "Must match a HETATM residue in input_pdb."
    )
    num_designs: int = Field(1, ge=1, le=1000)
    design_startnum: int = Field(0, ge=0)
    deterministic: bool = True

    @validator("input_pdb")
    def pdb_must_exist(cls, v):
        if not Path(v).exists():
            raise ValueError(f"Input PDB not found: {v}")
        return Path(v)

    @validator("ligand")
    def ligand_must_be_three_letters(cls, v):
        if v is not None and len(v) != 3:
            raise ValueError(
                f"Ligand CCD code must be exactly 3 letters (e.g. 'OQO'), got: '{v}'"
            )
        return v.upper() if v else v


class RFAAContigConfig(BaseModel):
    """Contig map settings — maps to contigmap.* Hydra keys."""
    contigs: str = Field(
        "150-150",
        description="Contig string specifying binder length and motif. "
                    "Examples: '150-150' (free binder 150 AA), "
                    "'10-120,A84-87,10-120' (motif A84-87 with flanking regions)"
    )
    length: Optional[str] = Field(
        None,
        description="Optional override for total length, e.g. '150-150'"
    )


class RFAAConfig(BaseModel):
    """
    Top-level RFDiffusionAA configuration.
    This is the single object passed to RFAARunner.run().
    """
    inference: RFAAInferenceConfig
    diffuser: RFAADiffuserConfig = Field(default_factory=RFAADiffuserConfig)
    contigmap: RFAAContigConfig = Field(default_factory=RFAAContigConfig)

    # BindMaster-specific (not passed to RFAA)
    gpu_device: int = Field(0, ge=0, description="CUDA device index")
    conda_env: str = Field("bindmaster_rfaa", description="Conda env name for RFAA")
    rfaa_root: Optional[Path] = Field(
        None,
        description="Path to rf_diffusion_all_atom clone. "
                    "Defaults to BINDMASTER_RFAA_ROOT env var."
    )
    use_apptainer: bool = Field(
        False,
        description="Use Apptainer container instead of native conda env"
    )
    apptainer_sif: Optional[Path] = Field(
        None,
        description="Path to rf_se3_diffusion.sif (required if use_apptainer=True)"
    )

    def to_hydra_overrides(self) -> list[str]:
        """Convert config to Hydra override strings for CLI."""
        overrides = [
            f"inference.input_pdb={self.inference.input_pdb}",
            f"inference.output_prefix={self.inference.output_prefix}",
            f"inference.num_designs={self.inference.num_designs}",
            f"inference.design_startnum={self.inference.design_startnum}",
            f"inference.deterministic={str(self.inference.deterministic).lower()}",
            f"diffuser.T={self.diffuser.T}",
            f"contigmap.contigs=[\\'{self.contigmap.contigs}\\']",
        ]
        if self.inference.ligand:
            overrides.append(f"inference.ligand={self.inference.ligand}")
        if self.contigmap.length:
            overrides.append(f"contigmap.length={self.contigmap.length}")
        return overrides
