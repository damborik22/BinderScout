"""
MSA caching manager for PXDesign.
"""

from __future__ import annotations

import datetime
import json
import subprocess
import time
from pathlib import Path

from bindmaster.tools.pxdesign.config import ChainConfig, PXDesignConfig


class MSAManager:
    """Manages MSA computation and caching for PXDesign targets."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def cache_key(self, config: PXDesignConfig) -> str:
        return config.target_hash()

    def is_cached(self, config: PXDesignConfig) -> bool:
        key = self.cache_key(config)
        cache_path = self.cache_dir / key
        if not cache_path.exists():
            return False
        return all((cache_path / chain_id).exists() for chain_id in config.target.chains)

    def get_msa_paths(self, config: PXDesignConfig) -> dict[str, Path]:
        key = self.cache_key(config)
        cache_path = self.cache_dir / key
        paths = {}
        for chain_id in config.target.chains:
            chain_msa = cache_path / chain_id
            if not chain_msa.exists():
                raise FileNotFoundError(
                    f"MSA not cached for chain {chain_id} (target_hash={key}). Run compute_msa() first."
                )
            paths[chain_id] = chain_msa
        return paths

    def compute_msa(
        self,
        config: PXDesignConfig,
        conda_env: str = "bindmaster_pxdesign",
        force: bool = False,
    ) -> dict[str, Path]:
        key = self.cache_key(config)
        cache_path = self.cache_dir / key

        if not force and self.is_cached(config):
            print(f"[pxdesign/msa] Cache hit: {key[:8]}...")
            return self.get_msa_paths(config)

        print(f"[pxdesign/msa] Computing MSA (hash={key[:8]}...)...")
        cache_path.mkdir(parents=True, exist_ok=True)

        tmp_yaml = cache_path / "prepare_msa_input.yaml"
        config.to_yaml(tmp_yaml)

        t0 = time.time()
        proc = subprocess.run(
            [
                "conda",
                "run",
                "-n",
                conda_env,
                "--no-capture-output",
                "pxdesign",
                "prepare-msa",
                "--yaml",
                str(tmp_yaml),
            ],
            capture_output=True,
            text=True,
        )

        if proc.returncode != 0:
            print(f"[pxdesign/msa] MSA computation failed:\n{proc.stderr}")
            raise RuntimeError(f"pxdesign prepare-msa failed: {proc.stderr}")

        elapsed = time.time() - t0
        print(f"[pxdesign/msa] MSA computed in {elapsed:.0f}s")

        meta = {
            "target_hash": key,
            "target_file": str(config.target.file),
            "chains": list(config.target.chains.keys()),
            "created_at": datetime.datetime.now().isoformat(),
            "elapsed_seconds": elapsed,
        }
        with open(cache_path / "metadata.json", "w") as f:
            json.dump(meta, f, indent=2)

        return self.get_msa_paths(config)

    def inject_msa_into_config(self, config: PXDesignConfig) -> PXDesignConfig:
        from dataclasses import replace

        msa_paths = self.get_msa_paths(config)
        new_chains = {}

        for chain_id, chain_cfg in config.target.chains.items():
            if isinstance(chain_cfg, ChainConfig) and chain_id in msa_paths:
                new_chains[chain_id] = ChainConfig(
                    crop=chain_cfg.crop,
                    hotspots=chain_cfg.hotspots,
                    msa=msa_paths[chain_id],
                )
            else:
                new_chains[chain_id] = chain_cfg

        new_target = replace(config.target, chains=new_chains)
        return replace(config, target=new_target)
