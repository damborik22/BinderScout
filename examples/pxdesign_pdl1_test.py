"""
PXDesign binder design example using PDL1 (PDB 5o45).
This is the same target used in the PXDesign README quick-start.

Usage:
    # Preview mode (faster, less filtering, GPU required):
    BINDMASTER_ENABLE_PXDESIGN=true python examples/pxdesign_pdl1_test.py --preset preview --n 50

    # Full extended mode (production quality):
    BINDMASTER_ENABLE_PXDESIGN=true python examples/pxdesign_pdl1_test.py --preset extended --n 1000
"""

import argparse
import sys
from pathlib import Path

from bindmaster.feature_flags import flags

if not flags.pxdesign_enabled:
    print("PXDesign is disabled.\n   Enable with: export BINDMASTER_ENABLE_PXDESIGN=true")
    sys.exit(1)

from bindmaster.scoring.unified import from_pxdesign_record
from bindmaster.tools.pxdesign.config import ChainConfig, PXDesignConfig, PXDesignTargetConfig
from bindmaster.tools.pxdesign.results_parser import get_passing_designs
from bindmaster.tools.pxdesign.runner import PXDesignRunner

TARGET_CIF = Path("examples/5o45.cif")
OUTPUT_DIR = Path("runs/pxdesign_pdl1_test")
MSA_CACHE = Path("msa_cache")


def main(preset: str = "preview", n_samples: int = 50):
    print(f"=== PXDesign PDL1 Test ({preset} mode, {n_samples} samples) ===\n")

    if not TARGET_CIF.exists():
        print(f"Target CIF not found: {TARGET_CIF}")
        print("   Copy from PXDesign repo: cp /tmp/pxdesign_src/examples/5o45.cif examples/")
        sys.exit(1)

    config = PXDesignConfig(
        target=PXDesignTargetConfig(
            file=TARGET_CIF,
            chains={
                "A": ChainConfig(
                    crop=["1-116"],
                    hotspots=[40, 99, 107],
                )
            },
        ),
        binder_length=80,
        n_samples=n_samples,
        preset=preset,
        dtype="bf16",
        use_fast_ln=True,
        use_deepspeed_evo_attention=(preset == "extended"),
        task_name="PDL1_test",
    )

    runner = PXDesignRunner(msa_cache_dir=MSA_CACHE)

    if not runner.preflight():
        print("\nPreflight failed -- see messages above.")
        sys.exit(1)

    result = runner.run(config=config, output_dir=OUTPUT_DIR)

    if not result.success:
        print(f"\nPXDesign run failed: {result.error_message}")
        sys.exit(1)

    summary_csv = OUTPUT_DIR / "design_outputs" / "PDL1_test" / "summary.csv"
    if summary_csv.exists():
        passing = get_passing_designs(summary_csv, filter_name="Protenix-basic")
        print("\nTop designs (Protenix-basic pass, ranked by ptx_iptm):")

        scores = [from_pxdesign_record(r, f"pdl1_{i}", "PDL1", 80) for i, r in enumerate(passing)]
        scores.sort(key=lambda s: s.composite_score or 0, reverse=True)

        for i, s in enumerate(scores[:5]):
            print(
                f"  {i + 1}. composite={s.composite_score:.3f} | "
                f"ipTM={s.iptm:.2f} | pLDDT={s.plddt_binder:.2f} | "
                f"ipAE={s.ipae:.1f}"
            )

    print(f"\nPXDesign test complete. Outputs in: {OUTPUT_DIR}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--preset", default="preview", choices=["preview", "extended", "infer"])
    parser.add_argument("--n", type=int, default=50, dest="n_samples")
    args = parser.parse_args()
    main(preset=args.preset, n_samples=args.n_samples)
