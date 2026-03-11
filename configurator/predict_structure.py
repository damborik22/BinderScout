#!/usr/bin/env python3
"""
Predict a protein structure from sequence using Boltz-2 (Mosaic venv).

Called by the configurator as a subprocess:
    Mosaic/.venv/bin/python configurator/predict_structure.py SEQUENCE OUTPUT.pdb

Writes the predicted PDB to OUTPUT.pdb and prints pLDDT to stdout.
"""

import sys
from pathlib import Path


def predict(sequence: str, output_pdb: Path) -> float:
    import jax
    import numpy as np
    from mosaic.models.boltz2 import Boltz2
    from mosaic.structure_prediction import TargetChain

    folder = Boltz2()
    chains = [TargetChain(sequence=sequence, use_msa=True)]
    features, writer = folder.target_only_features(chains=chains)

    prediction = folder.predict(
        features=features,
        writer=writer,
        recycling_steps=3,
        key=jax.random.key(42),
    )

    plddt_mean = float(np.array(prediction.plddt).mean())
    pdb_string = prediction.st.make_pdb_string()

    output_pdb.parent.mkdir(parents=True, exist_ok=True)
    with open(output_pdb, "w") as f:
        f.write(pdb_string)

    return plddt_mean


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} SEQUENCE OUTPUT.pdb", file=sys.stderr)
        sys.exit(1)

    sequence = sys.argv[1].strip().upper()
    output_pdb = Path(sys.argv[2])

    # Validate sequence
    valid_aa = set("ACDEFGHIKLMNPQRSTVWY")
    invalid = set(sequence) - valid_aa
    if invalid:
        print(f"ERROR: Invalid amino acid characters: {invalid}", file=sys.stderr)
        sys.exit(1)

    if len(sequence) < 10:
        print("ERROR: Sequence too short (minimum 10 residues)", file=sys.stderr)
        sys.exit(1)

    print(f"Predicting structure for {len(sequence)} aa sequence with Boltz-2...")
    plddt = predict(sequence, output_pdb)
    print(f"pLDDT={plddt:.4f}")
    print(f"PDB written to {output_pdb}")


if __name__ == "__main__":
    main()
