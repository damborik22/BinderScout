"""
Ligand binder design example using RFDiffusionAA.
Tests the complete RFAA integration without modifying existing BindMaster tools.

Usage:
    # Dry run (no GPU):
    BINDMASTER_ENABLE_RFAA=true python examples/ligand_binder_test.py --dry-run

    # Real run (GPU required):
    BINDMASTER_ENABLE_RFAA=true python examples/ligand_binder_test.py
"""

import argparse
import sys
from pathlib import Path

from bindmaster.feature_flags import flags

if not flags.rfaa_enabled:
    print("RFDiffusionAA is disabled.\n   Enable with: export BINDMASTER_ENABLE_RFAA=true")
    sys.exit(1)

from bindmaster.tools.rfaa.config import RFAAConfig, RFAAContigConfig, RFAADiffuserConfig, RFAAInferenceConfig
from bindmaster.tools.rfaa.postprocess import prepare_ligandmpnn_input
from bindmaster.tools.rfaa.runner import RFAARunner

# --- Benchmark target: PDB 7v11, ligand OQO ---
TARGET_PDB = Path("input/7v11.pdb")
LIGAND_CCD = "OQO"
OUTPUT_DIR = Path("runs/rfaa_7v11_test")


def main(dry_run: bool = False, n_designs: int = 1):
    print("=== RFDiffusionAA Ligand Binder Test ===\n")

    if not TARGET_PDB.exists():
        print(f"Target PDB not found: {TARGET_PDB}")
        print("   Download from PDB: https://www.rcsb.org/structure/7V11")
        print("   Place at: input/7v11.pdb")
        sys.exit(1)

    config = RFAAConfig(
        inference=RFAAInferenceConfig(
            input_pdb=TARGET_PDB,
            output_prefix=str(OUTPUT_DIR / "sample"),
            ligand=LIGAND_CCD,
            num_designs=n_designs,
            deterministic=True,
        ),
        diffuser=RFAADiffuserConfig(T=100),
        contigmap=RFAAContigConfig(contigs="150-150"),
    )

    runner = RFAARunner()
    if not dry_run:
        ok = runner.preflight()
        if not ok:
            print("\nPreflight failed -- see messages above.")
            sys.exit(1)

    result = runner.run(config=config, output_dir=OUTPUT_DIR, dry_run=dry_run)

    if dry_run:
        print("\nDry run complete -- no GPU used.")
        return

    if not result.success:
        print(f"\nRFAA run failed: {result.error_message}")
        sys.exit(1)

    for pdb_path in result.pdb_paths:
        spec = prepare_ligandmpnn_input(
            rfaa_pdb=pdb_path,
            ligand_ccd=LIGAND_CCD,
            output_dir=OUTPUT_DIR / "ligandmpnn_specs",
        )
        print(f"\nDesign: {pdb_path.name}")
        print(f"  Binder residues: {spec['n_binder_residues']}")
        print(f"  Ligand contacts: {spec['n_contact_residues']}")

    print(f"\nRFAA test complete. Outputs in: {OUTPUT_DIR}/")
    print("\nNext step: Run LigandMPNN on the backbone structures.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--n-designs", type=int, default=1)
    args = parser.parse_args()
    main(dry_run=args.dry_run, n_designs=args.n_designs)
