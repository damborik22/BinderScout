"""
PXDesign runner — subprocess-based adapter for BindMaster.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from bindmaster.tools.base import ToolAdapter, ToolResult
from bindmaster.tools.pxdesign.config import PXDesignConfig
from bindmaster.tools.pxdesign.msa_manager import MSAManager
from bindmaster.tools.pxdesign.results_parser import summarize_run


class PXDesignRunner(ToolAdapter):
    """Adapter for PXDesign (ByteDance de novo protein binder design)."""

    tool_name = "pxdesign"

    def __init__(self, msa_cache_dir: Path = Path("msa_cache")):
        self.msa_manager = MSAManager(msa_cache_dir)

    def validate_environment(self) -> bool:
        result = subprocess.run(
            ["conda", "env", "list"], capture_output=True, text=True
        )
        envs = [line.split()[0] for line in result.stdout.splitlines()
                if line and not line.startswith("#")]
        found = "bindmaster_pxdesign" in envs
        if not found:
            print(
                "[pxdesign] Conda env 'bindmaster_pxdesign' not found.\n"
                "   Run: bash scripts/install_pxdesign.sh"
            )
        return found

    def validate_weights(self) -> bool:
        result = subprocess.run(
            ["conda", "run", "-n", "bindmaster_pxdesign",
             "python", "-c", "import pxdesign; print('ok')"],
            capture_output=True, text=True, timeout=30,
        )
        ok = result.returncode == 0 and "ok" in result.stdout
        if not ok:
            print(f"[pxdesign] pxdesign import failed:\n{result.stderr}")
        return ok

    def run(
        self,
        config: PXDesignConfig,
        output_dir: Path,
        skip_msa: bool = False,
        dry_run: bool = False,
    ) -> ToolResult:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        design_id = f"pxdesign_{int(time.time())}"
        log_path = output_dir / "pxdesign_run.log"
        task_name = config.get_task_name()

        # MSA handling
        if not skip_msa and config.preset == "extended":
            if not self.msa_manager.is_cached(config):
                print(f"[pxdesign] MSA not cached — computing now (this takes ~10 min)...")
                try:
                    self.msa_manager.compute_msa(config, conda_env=config.conda_env)
                except RuntimeError as e:
                    return ToolResult(
                        success=False, tool_name=self.tool_name, design_id=design_id,
                        output_dir=output_dir, pdb_paths=[], log_path=log_path,
                        error_message=f"MSA computation failed: {e}",
                    )
            config = self.msa_manager.inject_msa_into_config(config)

        # Write YAML
        yaml_path = output_dir / f"{task_name}_input.yaml"
        config.to_yaml(yaml_path)
        print(f"[pxdesign] Input YAML written: {yaml_path}")

        # Validate YAML
        print("[pxdesign] Validating YAML...")
        check_result = subprocess.run(
            ["conda", "run", "-n", config.conda_env, "--no-capture-output",
             "pxdesign", "check-input", "--yaml", str(yaml_path)],
            capture_output=True, text=True,
        )
        if check_result.returncode != 0:
            print(f"[pxdesign] YAML validation failed:\n{check_result.stderr}")
            return ToolResult(
                success=False, tool_name=self.tool_name, design_id=design_id,
                output_dir=output_dir, pdb_paths=[], log_path=log_path,
                error_message=f"YAML validation failed: {check_result.stderr}",
            )
        print("[pxdesign] YAML valid")

        # Build command
        cmd = (
            ["conda", "run", "-n", config.conda_env, "--no-capture-output",
             "pxdesign", "pipeline"]
            + config.to_cli_args()
            + ["-i", str(yaml_path), "-o", str(output_dir)]
        )

        if dry_run:
            print("[pxdesign] DRY RUN — command:")
            print(" \\\n  ".join(cmd))
            return ToolResult(
                success=True, tool_name=self.tool_name, design_id=design_id,
                output_dir=output_dir, pdb_paths=[], log_path=log_path,
                metadata={"dry_run": True, "command": cmd},
            )

        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = str(config.gpu_device)

        print(
            f"[pxdesign] Starting campaign: {task_name}\n"
            f"   Mode: {config.preset} | Samples: {config.n_samples} | "
            f"Binder: {config.binder_length} AA"
        )

        t0 = time.time()
        with open(log_path, "w") as log_f:
            proc = subprocess.run(
                cmd, env=env, stdout=log_f, stderr=subprocess.STDOUT, text=True
            )
        elapsed = time.time() - t0

        # Parse results
        summary_csv = output_dir / "design_outputs" / task_name / "summary.csv"
        pdb_paths = []
        raw_scores = {}

        if summary_csv.exists():
            raw_scores = summarize_run(summary_csv)
            passing_dirs = [
                output_dir / "design_outputs" / task_name / "passing-Protenix-basic",
                output_dir / "design_outputs" / task_name / "passing-AF2-IG-easy",
            ]
            for d in passing_dirs:
                if d.exists():
                    pdb_paths.extend(d.glob("*.cif"))

        success = proc.returncode == 0 and summary_csv.exists()

        if success:
            print(
                f"[pxdesign] Done in {elapsed:.0f}s | "
                f"Protenix-basic pass: {raw_scores.get('passes_protenix_basic', '?')}"
            )
        else:
            print(f"[pxdesign] Run failed (rc={proc.returncode}). See: {log_path}")

        meta = {
            "design_id": design_id, "task_name": task_name,
            "preset": config.preset, "n_samples": config.n_samples,
            "binder_length": config.binder_length,
            "elapsed_seconds": elapsed, "returncode": proc.returncode,
            "summary_csv": str(summary_csv) if summary_csv.exists() else None,
            **raw_scores,
        }
        with open(output_dir / "pxdesign_metadata.json", "w") as f:
            json.dump(meta, f, indent=2, default=str)

        return ToolResult(
            success=success, tool_name=self.tool_name, design_id=design_id,
            output_dir=output_dir, pdb_paths=list(pdb_paths), log_path=log_path,
            error_message=None if success else f"rc={proc.returncode}",
            raw_scores=raw_scores, metadata=meta,
        )
