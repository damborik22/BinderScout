"""
PXDesign configuration — generates the YAML files that PXDesign CLI consumes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class ChainConfig:
    """Configuration for a single target chain."""

    crop: list[str] | None = None
    hotspots: list[int] | None = None
    msa: Path | None = None


@dataclass
class PXDesignTargetConfig:
    """Target structure configuration."""

    file: Path
    chains: dict[str, ChainConfig | str]

    def __post_init__(self):
        if not Path(self.file).exists():
            raise FileNotFoundError(f"Target structure not found: {self.file}")


@dataclass
class PXDesignConfig:
    """
    Complete PXDesign run configuration.
    Generates a YAML file that pxdesign CLI consumes.
    """

    target: PXDesignTargetConfig
    binder_length: int
    n_samples: int = 1000
    preset: str = "extended"
    dtype: str = "bf16"
    use_fast_ln: bool = True
    use_deepspeed_evo_attention: bool = True

    # BindMaster-specific (not written to YAML)
    gpu_device: int = 0
    conda_env: str = "bindmaster_pxdesign"
    task_name: str | None = None

    def get_task_name(self) -> str:
        if self.task_name:
            return self.task_name
        return Path(self.target.file).stem

    def target_hash(self) -> str:
        """Compute a hash of the target structure path + crop/hotspot settings."""
        h = hashlib.sha256()
        h.update(str(self.target.file).encode())
        for chain_id, chain_cfg in sorted(self.target.chains.items()):
            h.update(chain_id.encode())
            if isinstance(chain_cfg, ChainConfig):
                h.update(str(chain_cfg.crop).encode())
        return h.hexdigest()[:16]

    def to_yaml(self, output_path: Path) -> Path:
        """Write the PXDesign input YAML file."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        doc: dict = {
            "binder_length": self.binder_length,
            "target": {
                "file": str(self.target.file),
                "chains": {},
            },
        }

        for chain_id, chain_cfg in self.target.chains.items():
            if chain_cfg == "all":
                doc["target"]["chains"][chain_id] = "all"
            elif isinstance(chain_cfg, ChainConfig):
                chain_doc: dict = {}
                if chain_cfg.crop:
                    chain_doc["crop"] = chain_cfg.crop
                if chain_cfg.hotspots:
                    chain_doc["hotspots"] = chain_cfg.hotspots
                if chain_cfg.msa:
                    chain_doc["msa"] = str(chain_cfg.msa)
                doc["target"]["chains"][chain_id] = chain_doc

        with open(output_path, "w") as f:
            yaml.dump(doc, f, default_flow_style=False, sort_keys=False)

        return output_path

    def to_cli_args(self) -> list[str]:
        """Generate the `pxdesign pipeline` CLI argument list."""
        args = [
            "--preset",
            self.preset,
            "--N_sample",
            str(self.n_samples),
            "--dtype",
            self.dtype,
        ]
        if self.use_fast_ln:
            args += ["--use_fast_ln", "True"]
        if self.use_deepspeed_evo_attention:
            args += ["--use_deepspeed_evo_attention", "True"]
        return args
