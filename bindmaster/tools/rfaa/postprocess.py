"""
RFDiffusionAA output postprocessing.
"""

import math
from pathlib import Path


def count_binder_residues(pdb_path: Path) -> int:
    """Count designed (non-motif) residues in an RFAA output PDB."""
    residues = set()
    with open(pdb_path) as f:
        for line in f:
            if line.startswith(("ATOM", "HETATM")):
                chain = line[21]
                res_num = line[22:26].strip()
                if chain == "A":
                    residues.add(res_num)
    return len(residues)


def extract_ligand_contact_residues(
    pdb_path: Path,
    ligand_ccd: str,
    distance_cutoff: float = 5.0,
) -> list[int]:
    """Find protein residue numbers within distance_cutoff Angstroms of a ligand."""
    ligand_atoms: list[tuple[float, float, float]] = []
    protein_residues: dict[int, list[tuple[float, float, float]]] = {}

    with open(pdb_path) as f:
        for line in f:
            if not line.startswith(("ATOM", "HETATM")):
                continue
            res_name = line[17:20].strip()
            res_num = int(line[22:26].strip())
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])

            if line.startswith("HETATM") and res_name == ligand_ccd:
                ligand_atoms.append((x, y, z))
            elif line.startswith("ATOM"):
                protein_residues.setdefault(res_num, []).append((x, y, z))

    contact_residues = []
    for res_num, protein_atoms in protein_residues.items():
        for px, py, pz in protein_atoms:
            for lx, ly, lz in ligand_atoms:
                dist = math.sqrt((px - lx) ** 2 + (py - ly) ** 2 + (pz - lz) ** 2)
                if dist <= distance_cutoff:
                    contact_residues.append(res_num)
                    break
            else:
                continue
            break

    return sorted(set(contact_residues))


def prepare_ligandmpnn_input(
    rfaa_pdb: Path,
    ligand_ccd: str,
    output_dir: Path,
) -> dict:
    """Prepare input for LigandMPNN from an RFAA output PDB."""
    import json

    contact_residues = extract_ligand_contact_residues(rfaa_pdb, ligand_ccd)
    n_binder_residues = count_binder_residues(rfaa_pdb)

    spec = {
        "pdb_path": str(rfaa_pdb),
        "ligand_ccd": ligand_ccd,
        "contact_residues": contact_residues,
        "n_contact_residues": len(contact_residues),
        "n_binder_residues": n_binder_residues,
        "ligandmpnn_args": {
            "--pdb_path": str(rfaa_pdb),
            "--ligand_mpnn_use_side_chain_context": "1",
            "--number_of_batches": "5",
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    spec_path = output_dir / f"{rfaa_pdb.stem}_ligandmpnn_spec.json"
    with open(spec_path, "w") as f:
        json.dump(spec, f, indent=2)

    print(
        f"[rfaa/postprocess] LigandMPNN spec written to {spec_path}\n"
        f"   Binder residues: {n_binder_residues}\n"
        f"   Ligand contacts: {len(contact_residues)} residues"
    )
    return spec
