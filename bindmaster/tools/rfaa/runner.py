"""
RFDiffusionAA runner — subprocess-based adapter for BindMaster.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from bindmaster.tools.base import ToolAdapter, ToolResult
from bindmaster.tools.rfaa.config import RFAAConfig
from bindmaster.tools.rfaa.ligand_prep import verify_ligand_in_pdb


class RFAARunner(ToolAdapter):
    """
    Adapter for RFDiffusionAA (Baker Lab all-atom diffusion).
    """

    tool_name = "rfaa"

    def __init__(self, rfaa_root: Optional[Path] = None):
        if rfaa_root is None:
            env_root = os.environ.get("BINDMASTER_RFAA_ROOT")
            if not env_root:
                raise EnvironmentError(
                    "RFAA root not specified. Set BINDMASTER_RFAA_ROOT env var "
                    "or pass rfaa_root to RFAARunner()."
                )
            rfaa_root = Path(env_root)

        self.rfaa_root = Path(rfaa_root)
        if not self.rfaa_root.exists():
            raise FileNotFoundError(f"RFAA root not found: {self.rfaa_root}")

    def validate_environment(self) -> bool:
        result = subprocess.run(
            ["conda", "env", "list"],
            capture_output=True, text=True
        )
        envs = [line.split()[0] for line in result.stdout.splitlines()
                if line and not line.startswith("#")]
        found = "bindmaster_rfaa" in envs
        if not found:
            print(
                "[rfaa] Conda env 'bindmaster_rfaa' not found.\n"
                "   Run: bash scripts/install_rfaa.sh"
            )
        return found

    def validate_weights(self) -> bool:
        weights_path = os.environ.get("BINDMASTER_RFAA_WEIGHTS")
        if not weights_path:
            print("[rfaa] BINDMASTER_RFAA_WEIGHTS env var not set.")
            return False
        p = Path(weights_path)
        if not p.exists():
            print(f"[rfaa] Weights not found at: {p}")
            return False
        if p.stat().st_size < 100_000_000:
            print(f"[rfaa] Weights file seems too small: {p.stat().st_size} bytes")
        return True

    def run(
        self,
        config: RFAAConfig,
        output_dir: Path,
        dry_run: bool = False,
    ) -> ToolResult:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        design_id = f"rfaa_{int(time.time())}"
        log_path = output_dir / "rfaa_run.log"

        # Pre-flight checks
        if config.inference.ligand:
            ligand_ok = verify_ligand_in_pdb(
                config.inference.input_pdb, config.inference.ligand
            )
            if not ligand_ok:
                return ToolResult(
                    success=False,
                    tool_name=self.tool_name,
                    design_id=design_id,
                    output_dir=output_dir,
                    pdb_paths=[],
                    log_path=log_path,
                    error_message=(
                        f"Ligand '{config.inference.ligand}' not found in "
                        f"{config.inference.input_pdb}"
                    ),
                )

        # Build command
        weights_path = os.environ.get("BINDMASTER_RFAA_WEIGHTS", "")
        hydra_overrides = config.to_hydra_overrides()
        if weights_path:
            hydra_overrides.append(f"inference.weights={weights_path}")

        if config.use_apptainer and config.apptainer_sif:
            cmd = [
                "/usr/bin/apptainer", "run", "--nv",
                str(config.apptainer_sif),
                "-u", str(self.rfaa_root / "run_inference.py"),
            ] + hydra_overrides
        else:
            cmd = [
                "conda", "run", "-n", config.conda_env, "--no-capture-output",
                "python", str(self.rfaa_root / "run_inference.py"),
            ] + hydra_overrides

        if dry_run:
            print("[rfaa] DRY RUN — command that would be executed:")
            print(" \\\n  ".join(cmd))
            return ToolResult(
                success=True,
                tool_name=self.tool_name,
                design_id=design_id,
                output_dir=output_dir,
                pdb_paths=[],
                log_path=log_path,
                metadata={"dry_run": True, "command": cmd},
            )

        # Execute
        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = str(config.gpu_device)

        print(f"[rfaa] Starting {config.inference.num_designs} designs...")
        print(f"[rfaa]    Target: {config.inference.input_pdb.name}")
        if config.inference.ligand:
            print(f"[rfaa]    Ligand: {config.inference.ligand}")
        print(f"[rfaa]    Contig: {config.contigmap.contigs}")
        print(f"[rfaa]    Log: {log_path}")

        t_start = time.time()
        with open(log_path, "w") as log_file:
            proc = subprocess.run(
                cmd,
                cwd=str(self.rfaa_root),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
            )
        elapsed = time.time() - t_start

        # Collect outputs
        output_prefix = Path(config.inference.output_prefix)
        pdb_paths = []
        for i in range(
            config.inference.design_startnum,
            config.inference.design_startnum + config.inference.num_designs
        ):
            pdb_candidate = Path(f"{output_prefix}_{i}.pdb")
            if pdb_candidate.exists():
                dest = output_dir / pdb_candidate.name
                shutil.copy2(pdb_candidate, dest)
                pdb_paths.append(dest)

        success = proc.returncode == 0 and len(pdb_paths) > 0

        if not success:
            print(
                f"[rfaa] Run failed (returncode={proc.returncode}, "
                f"pdbs_found={len(pdb_paths)}). See: {log_path}"
            )
        else:
            print(
                f"[rfaa] Done: {len(pdb_paths)} designs in {elapsed:.1f}s "
                f"({elapsed/len(pdb_paths):.1f}s/design)"
            )

        meta = {
            "design_id": design_id,
            "config": config.dict(exclude_none=True),
            "returncode": proc.returncode,
            "elapsed_seconds": elapsed,
            "pdbs_found": len(pdb_paths),
        }
        with open(output_dir / "rfaa_metadata.json", "w") as f:
            json.dump(meta, f, indent=2, default=str)

        return ToolResult(
            success=success,
            tool_name=self.tool_name,
            design_id=design_id,
            output_dir=output_dir,
            pdb_paths=pdb_paths,
            log_path=log_path,
            error_message=None if success else f"returncode={proc.returncode}",
            metadata=meta,
        )
