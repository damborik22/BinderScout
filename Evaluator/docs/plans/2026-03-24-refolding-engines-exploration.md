# Refolding Engines Exploration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add standalone scripts for Protenix (AF3) refolding and Boltz-2 CLI template-mode refolding, for exploratory comparison against existing Boltz-2/AF2 results. NOT integrated into the Evaluator reporting pipeline.

**Architecture:** Two new standalone Python scripts in `Evaluator/scripts/`, each accepting FASTA + target PDB, running predictions, and outputting a CSV + structure files. No changes to `binder-compare` CLI, merger, scoring, or report generation.

**Tech Stack:** Protenix v0.5.0 (in Mosaic `.venv`), Boltz-2 CLI (`boltz predict`), gemmi, numpy

**Environment:** Both scripts run in `Mosaic/.venv` (Python 3.12, has both protenix and boltz installed)

---

## File Structure

| File | Purpose |
|------|---------|
| `Evaluator/scripts/refold_protenix.py` | Standalone Protenix refolding script |
| `Evaluator/scripts/refold_boltz2_cli.py` | Standalone Boltz-2 CLI template-mode script |

No other files created or modified.

---

### Task 1: Protenix Refolding Script

**Files:**
- Create: `Evaluator/scripts/refold_protenix.py`

**What it does:**
- Accepts: `--sequences FASTA`, `--target-seq SEQ`, `--target-pdb PDB` (optional template), `--output-dir DIR`, `--seeds` (default: `101`), `--num-diffusion-samples` (default: 5)
- For each binder sequence:
  1. Generate Protenix input JSON (binder chain + target chain)
  2. If `--target-pdb` provided, include it as template
  3. Run `protenix.inference.infer_predict()` or call CLI
  4. Parse confidence JSON: extract `ranking_score`, `pair_chains_iptm`, `chains_ptm`
  5. Save structure CIF
  6. Append row to output CSV
- Output CSV columns: `idx, sequence, binder_length, ranking_score, iptm, binder_ptm, target_ptm, cif_path, confidence_json_path`
- Supports `--resume` (skip already-completed indices)

- [ ] **Step 1: Create script skeleton with argparse and FASTA parsing**

```python
#!/usr/bin/env python3
"""Standalone Protenix (AF3) refolding script.

Predicts binder-target complexes using Protenix and extracts confidence metrics.
Runs in the Mosaic .venv (Python 3.12).

Usage:
    Mosaic/.venv/bin/python Evaluator/scripts/refold_protenix.py \
        --sequences seqs.fasta \
        --target-seq "APFRS..." \
        --output-dir ./refold_protenix \
        [--target-pdb target.pdb]
"""

import argparse
import csv
import json
import os
import re
import sys
import uuid
from pathlib import Path


def parse_fasta(path: str) -> list[tuple[str, str]]:
    """Parse FASTA file, return list of (header, sequence) tuples."""
    entries = []
    header, seq_parts = None, []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith(">"):
                if header is not None:
                    entries.append((header, "".join(seq_parts)))
                header = line[1:].strip()
                seq_parts = []
            elif line:
                seq_parts.append(line.upper())
    if header is not None:
        entries.append((header, "".join(seq_parts)))
    return entries


def load_completed_indices(csv_path: Path) -> set[int]:
    """Read existing CSV and return set of completed 1-based indices."""
    if not csv_path.exists():
        return set()
    try:
        indices = set()
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                idx = row.get("idx")
                if idx is not None:
                    indices.add(int(idx))
        return indices
    except Exception:
        return set()


def main():
    parser = argparse.ArgumentParser(description="Protenix (AF3) Refolding Tool")
    parser.add_argument("--sequences", "-s", required=True, help="Input FASTA file")
    parser.add_argument("--target-seq", required=True, help="Target protein sequence")
    parser.add_argument("--target-pdb", default=None, help="Target PDB for template mode")
    parser.add_argument("--output-dir", "-o", default="./refold_protenix", help="Output directory")
    parser.add_argument("--seeds", type=int, nargs="+", default=[101], help="Random seeds (default: 101)")
    parser.add_argument("--resume", action="store_true", help="Skip completed binders")
    args = parser.parse_args()

    entries = parse_fasta(args.sequences)
    sequences = [seq for _, seq in entries]
    print(f"Loaded {len(sequences)} binder sequences")
    print(f"Target: {len(args.target_seq)} aa")
    if args.target_pdb:
        print(f"Template mode: {args.target_pdb}")
    else:
        print("Sequence-only mode (no template)")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    skip_indices = set()
    csv_path = output_dir / "protenix_results.csv"
    if args.resume:
        skip_indices = load_completed_indices(csv_path)
        if skip_indices:
            print(f"Resuming — skipping {len(skip_indices)} completed binders")

    refold_batch_protenix(
        sequences, args.target_seq, output_dir, csv_path,
        target_pdb=args.target_pdb, seeds=args.seeds,
        skip_indices=skip_indices,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Implement Protenix input JSON generation**

Build the input JSON for each binder-target complex. Two chains: binder (chain A) and target (chain B). Protenix expects the AlphaFold3 JSON format.

```python
def build_protenix_input_json(
    binder_seq: str,
    target_seq: str,
    sample_name: str,
    output_path: Path,
) -> Path:
    """Create Protenix input JSON for a binder-target complex."""
    input_data = [
        {
            "name": sample_name,
            "sequences": [
                {"proteinChain": {"sequence": binder_seq, "count": 1}},
                {"proteinChain": {"sequence": target_seq, "count": 1}},
            ],
        }
    ]
    with open(output_path, "w") as f:
        json.dump(input_data, f, indent=2)
    return output_path
```

- [ ] **Step 3: Implement Protenix prediction call**

Use Protenix CLI (`protenix predict`) or Python API. CLI is simpler and more robust:

```python
import subprocess

def run_protenix_prediction(
    input_json: Path,
    output_dir: Path,
    seeds: list[int],
    use_msa: bool = True,
) -> Path:
    """Run Protenix prediction via CLI. Returns path to predictions directory."""
    cmd = [
        sys.executable, "-m", "protenix.predict",
        input_json.as_posix(),
        "--dump_dir", output_dir.as_posix(),
        "--seeds", ",".join(str(s) for s in seeds),
    ]
    if not use_msa:
        cmd.append("--no_msa")

    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  STDERR: {result.stderr[-500:]}")
        raise RuntimeError(f"Protenix prediction failed (exit {result.returncode})")
    return output_dir
```

Note: The exact CLI invocation for Protenix needs testing. The API might be `protenix.inference.main()` or `protenix predict` CLI. Test during implementation and adjust.

- [ ] **Step 4: Implement confidence metric extraction**

Parse the Protenix confidence JSON to extract ranking_score, per-chain pTM, and inter-chain ipTM:

```python
def extract_protenix_metrics(
    predictions_dir: Path,
    sample_name: str,
    seed: int,
    binder_chain_idx: int = 0,
    target_chain_idx: int = 1,
) -> dict:
    """Extract confidence metrics from Protenix output."""
    # Find confidence JSON
    pattern = f"{sample_name}_seed_{seed}_summary_confidence_sample_0.json"
    conf_path = predictions_dir / pattern
    if not conf_path.exists():
        # Try alternative naming patterns
        candidates = list(predictions_dir.glob(f"*summary_confidence*sample_0*"))
        if candidates:
            conf_path = candidates[0]
        else:
            return {"ranking_score": float("nan"), "iptm": float("nan")}

    with open(conf_path) as f:
        conf = json.load(f)

    # Extract metrics
    ranking_score = conf.get("ranking_score", float("nan"))

    # Per-chain pTM
    chains_ptm = conf.get("chains_ptm", {})
    binder_ptm = float(chains_ptm.get(str(binder_chain_idx), float("nan")))
    target_ptm = float(chains_ptm.get(str(target_chain_idx), float("nan")))

    # Inter-chain ipTM (binder → target)
    pair_iptm = conf.get("pair_chains_iptm", {})
    iptm_bt = float("nan")
    iptm_tb = float("nan")
    if str(binder_chain_idx) in pair_iptm:
        iptm_bt = float(pair_iptm[str(binder_chain_idx)].get(str(target_chain_idx), float("nan")))
    if str(target_chain_idx) in pair_iptm:
        iptm_tb = float(pair_iptm[str(target_chain_idx)].get(str(binder_chain_idx), float("nan")))
    iptm = min(iptm_bt, iptm_tb) if not (iptm_bt != iptm_bt or iptm_tb != iptm_tb) else float("nan")

    return {
        "ranking_score": ranking_score,
        "iptm_bt": iptm_bt,
        "iptm_tb": iptm_tb,
        "iptm": iptm,
        "binder_ptm": binder_ptm,
        "target_ptm": target_ptm,
        "confidence_json": str(conf_path),
    }
```

- [ ] **Step 5: Implement main refold loop with CSV output**

```python
CSV_COLUMNS = [
    "run_id", "idx", "sequence", "target_sequence", "binder_length",
    "ranking_score", "iptm", "iptm_bt", "iptm_tb",
    "binder_ptm", "target_ptm",
    "cif_path", "confidence_json",
]


def refold_batch_protenix(
    sequences: list[str],
    target_seq: str,
    output_dir: Path,
    csv_path: Path,
    *,
    target_pdb: str | None = None,
    seeds: list[int] = [101],
    skip_indices: set[int] | None = None,
):
    if skip_indices is None:
        skip_indices = set()
    run_id = str(uuid.uuid4())[:8]

    write_header = not csv_path.exists() or csv_path.stat().st_size == 0
    csv_file = open(csv_path, "a", newline="")
    writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
    if write_header:
        writer.writeheader()
        csv_file.flush()

    try:
        for idx, seq in enumerate(sequences, start=1):
            if idx in skip_indices:
                print(f"[SKIP] #{idx}")
                continue

            binder_length = len(seq)
            print(f"\n{'─'*50}")
            print(f"[{idx}/{len(sequences)}] length={binder_length} seq={seq[:40]}...")

            sample_name = f"refold{idx}_{run_id}"
            sample_dir = output_dir / sample_name
            sample_dir.mkdir(parents=True, exist_ok=True)

            # Build input JSON
            input_json = sample_dir / "input.json"
            build_protenix_input_json(seq, target_seq, sample_name, input_json)

            # Run prediction
            try:
                run_protenix_prediction(input_json, sample_dir, seeds=seeds)
            except RuntimeError as e:
                print(f"  ERROR: {e}")
                continue

            # Find predictions directory
            pred_dir = sample_dir / sample_name
            if not pred_dir.exists():
                # Try finding it
                candidates = list(sample_dir.glob("*/predictions"))
                pred_dir = candidates[0] if candidates else sample_dir

            # Extract metrics
            metrics = extract_protenix_metrics(pred_dir, sample_name, seeds[0])

            # Find CIF structure
            cif_files = list(sample_dir.rglob("*.cif"))
            cif_path = str(cif_files[0]) if cif_files else ""

            row = {
                "run_id": run_id,
                "idx": idx,
                "sequence": seq,
                "target_sequence": target_seq,
                "binder_length": binder_length,
                "cif_path": cif_path,
                **metrics,
            }
            writer.writerow(row)
            csv_file.flush()

            print(f"  ranking_score={metrics['ranking_score']:.4f}  iptm={metrics['iptm']:.4f}")
            print(f"  binder_ptm={metrics['binder_ptm']:.4f}  target_ptm={metrics['target_ptm']:.4f}")
    finally:
        csv_file.close()

    print(f"\n{'='*50}")
    print(f"Done. Results: {csv_path}")
```

- [ ] **Step 6: Test with 1 binder sequence to verify the pipeline works**

```bash
cd /home/david/BindMaster
Mosaic/.venv/bin/python Evaluator/scripts/refold_protenix.py \
    --sequences <(echo -e ">test\nPAELSERERRIIEDVWYPVVHSGKRYIEEFKPTEWEKRFWEEVAEEVREMLEDYFRWSRS") \
    --target-seq "APFRSALESSPADPATLSEDEARLLLAALVQDYVQMKASELEQEQEREGSSLDSPRSKRCGNLSTCMLGTYTQDFNKFHTFPQTAIGVGAPGKKRDMSSDLERDHRPHVSMPQNAN" \
    --target-pdb runs/CALCA_combined/target/CALCA_BindMaster_test_01.pdb \
    --output-dir /tmp/test_protenix
```

Verify: CSV written, CIF structure saved, metrics extracted.

- [ ] **Step 7: Commit**

```bash
git add Evaluator/scripts/refold_protenix.py
git commit -m "Add standalone Protenix (AF3) refolding script for exploratory evaluation"
```

---

### Task 2: Boltz-2 CLI Template-Mode Refolding Script

**Files:**
- Create: `Evaluator/scripts/refold_boltz2_cli.py`

**What it does:**
- Accepts: `--sequences FASTA`, `--target-seq SEQ`, `--target-pdb PDB`, `--output-dir DIR`, `--diffusion-samples` (default: 6), `--recycling-steps` (default: 3), `--sampling-steps` (default: 200)
- For each binder sequence:
  1. Generate Boltz YAML input (binder + target + template with `force: true`)
  2. Call `boltz predict` CLI with `--use_potentials --write_full_pae`
  3. Parse output: confidence JSON, PAE NPZ, pLDDT NPZ, structure CIF
  4. Compute ipSAE from PAE matrix using Dunbrack formula
  5. Append row to output CSV
- Output CSV columns: `idx, sequence, binder_length, iptm, ptm, bt_ipsae, tb_ipsae, ipsae_min, plddt_binder_mean, plddt_target_mean, pae_bt_mean, pae_tb_mean, cif_path, pae_file`
- Supports `--resume`

- [ ] **Step 1: Create script skeleton with argparse and YAML generation**

```python
#!/usr/bin/env python3
"""Standalone Boltz-2 CLI refolding script with template forcing.

Uses `boltz predict --use_potentials` for proper template-constrained
diffusion. Bypasses Mosaic's JAX wrapper entirely.

Runs in the Mosaic .venv (Python 3.12).

Usage:
    Mosaic/.venv/bin/python Evaluator/scripts/refold_boltz2_cli.py \
        --sequences seqs.fasta \
        --target-seq "APFRS..." \
        --target-pdb target.pdb \
        --output-dir ./refold_boltz2_template
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from tempfile import NamedTemporaryFile

import gemmi
import numpy as np


def parse_fasta(path: str) -> list[tuple[str, str]]:
    """Parse FASTA file, return list of (header, sequence) tuples."""
    entries = []
    header, seq_parts = None, []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith(">"):
                if header is not None:
                    entries.append((header, "".join(seq_parts)))
                header = line[1:].strip()
                seq_parts = []
            elif line:
                seq_parts.append(line.upper())
    if header is not None:
        entries.append((header, "".join(seq_parts)))
    return entries


def build_boltz_yaml(
    binder_seq: str,
    target_seq: str,
    target_pdb: str | None,
    output_path: Path,
) -> Path:
    """Generate Boltz-2 YAML input with optional forced template."""
    yaml_lines = [
        "version: 1",
        "sequences:",
        "  - protein:",
        "        id: [A]",
        f"        sequence: {binder_seq}",
        "        msa: empty",
        "  - protein:",
        "        id: [B]",
        f"        sequence: {target_seq}",
    ]

    if target_pdb:
        # Write template CIF from PDB
        st = gemmi.read_structure(target_pdb)
        chain = st[0][0]
        chain.name = "B"

        tmpl_st = gemmi.Structure()
        model = gemmi.Model("0")
        ent = gemmi.Entity("B")
        ent.entity_type = gemmi.EntityType.Polymer
        ent.polymer_type = gemmi.PolymerType.PeptideL
        ent.subchains = ["B"]
        ent.full_sequence = [r.name for r in chain]
        for r in chain:
            r.subchain = "B"
        model.add_chain(chain)
        tmpl_st.add_model(model)
        tmpl_st.entities = gemmi.EntityList([ent])
        tmpl_st.assign_subchains()
        tmpl_st.setup_entities()
        tmpl_st.ensure_entities()
        tmpl_st.assign_label_seq_id()

        cif_path = output_path.parent / "template.cif"
        doc = tmpl_st.make_mmcif_document()
        doc.write_file(str(cif_path))

        yaml_lines.extend([
            "",
            "templates:",
            f"  - cif: {cif_path}",
            "    chain_id: [B]",
            "    template_id: [B]",
            "    force: true",
            "    threshold: 2.0",
        ])

    with open(output_path, "w") as f:
        f.write("\n".join(yaml_lines) + "\n")
    return output_path
```

- [ ] **Step 2: Implement Boltz CLI invocation**

```python
def run_boltz_predict(
    yaml_path: Path,
    output_dir: Path,
    *,
    diffusion_samples: int = 6,
    recycling_steps: int = 3,
    sampling_steps: int = 200,
    use_potentials: bool = True,
    seed: int = 0,
) -> Path:
    """Run boltz predict CLI. Returns predictions output directory."""
    cmd = [
        sys.executable, "-m", "boltz.main", "predict",
        str(yaml_path),
        "--out_dir", str(output_dir),
        "--recycling_steps", str(recycling_steps),
        "--sampling_steps", str(sampling_steps),
        "--diffusion_samples", str(diffusion_samples),
        "--write_full_pae",
        "--output_format", "pdb",
        "--use_msa_server",
        "--seed", str(seed),
    ]
    if use_potentials:
        cmd.append("--use_potentials")

    print(f"  Running boltz predict (samples={diffusion_samples}, potentials={use_potentials})")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        print(f"  STDERR (last 500): {result.stderr[-500:]}")
        raise RuntimeError(f"boltz predict failed (exit {result.returncode})")
    return output_dir
```

Note: Exact CLI module path (`boltz.main` vs just `boltz`) needs verification during implementation. The executable might be `boltz` directly.

- [ ] **Step 3: Implement output parsing (confidence JSON + PAE NPZ)**

```python
def parse_boltz_outputs(predictions_dir: Path, binder_length: int) -> dict:
    """Parse Boltz-2 CLI output files and compute metrics."""
    # Find confidence JSON
    conf_files = list(predictions_dir.rglob("confidence_*.json"))
    pae_files = list(predictions_dir.rglob("pae_*.npz"))
    plddt_files = list(predictions_dir.rglob("plddt_*.npz"))
    structure_files = list(predictions_dir.rglob("*.pdb")) or list(predictions_dir.rglob("*.cif"))

    metrics = {
        "iptm": float("nan"), "ptm": float("nan"),
        "bt_ipsae": float("nan"), "tb_ipsae": float("nan"), "ipsae_min": float("nan"),
        "plddt_binder_mean": float("nan"), "plddt_target_mean": float("nan"),
        "pae_bt_mean": float("nan"), "pae_tb_mean": float("nan"),
        "structure_path": "", "pae_file": "",
    }

    # Confidence JSON
    if conf_files:
        with open(conf_files[0]) as f:
            conf = json.load(f)
        metrics["iptm"] = conf.get("iptm", conf.get("protein_iptm", float("nan")))
        metrics["ptm"] = conf.get("ptm", float("nan"))

    # PAE matrix
    if pae_files:
        pae_data = np.load(pae_files[0])
        pae = pae_data["pae"] if "pae" in pae_data else pae_data[list(pae_data.keys())[0]]
        metrics["pae_file"] = str(pae_files[0])

        L_b = binder_length
        # Boltz-2 ordering: [binder | target]
        pae_bt = pae[:L_b, L_b:]
        pae_tb = pae[L_b:, :L_b]
        metrics["pae_bt_mean"] = float(pae_bt.mean())
        metrics["pae_tb_mean"] = float(pae_tb.mean())

        # Compute ipSAE (Dunbrack formula, 10 Å cutoff)
        metrics.update(compute_ipsae(pae, L_b))

    # pLDDT
    if plddt_files:
        plddt_data = np.load(plddt_files[0])
        plddt = plddt_data["plddt"] if "plddt" in plddt_data else plddt_data[list(plddt_data.keys())[0]]
        metrics["plddt_binder_mean"] = float(plddt[:binder_length].mean())
        metrics["plddt_target_mean"] = float(plddt[binder_length:].mean())

    # Structure
    if structure_files:
        metrics["structure_path"] = str(structure_files[0])

    return metrics
```

- [ ] **Step 4: Implement ipSAE computation (Dunbrack formula)**

```python
def compute_ipsae(pae: np.ndarray, binder_length: int, cutoff: float = 10.0) -> dict:
    """Compute ipSAE from PAE matrix using DunbrackLab formula.

    PAE ordering: [binder | target] (Boltz-2 convention).
    """
    L_b = binder_length
    L_t = pae.shape[0] - L_b

    def _ipsae_one_direction(pae_block: np.ndarray) -> float:
        """Compute ipSAE for one direction (rows=query, cols=aligned)."""
        n_query, n_aligned = pae_block.shape
        if n_query == 0 or n_aligned == 0:
            return 0.0
        scores = []
        for i in range(n_query):
            row = pae_block[i]
            mask = row < cutoff
            n_cutoff = mask.sum()
            if n_cutoff == 0:
                scores.append(0.0)
                continue
            d0 = max(1.0, 1.24 * (n_cutoff - 15) ** (1.0 / 3.0) - 1.8)
            s = np.mean(1.0 / (1.0 + (row[mask] / d0) ** 2))
            scores.append(s)
        return max(scores) if scores else 0.0

    bt_ipsae = _ipsae_one_direction(pae[:L_b, L_b:])  # binder→target
    tb_ipsae = _ipsae_one_direction(pae[L_b:, :L_b])  # target→binder
    ipsae_min = min(bt_ipsae, tb_ipsae)

    return {
        "bt_ipsae": bt_ipsae,
        "tb_ipsae": tb_ipsae,
        "ipsae_min": ipsae_min,
    }
```

- [ ] **Step 5: Implement main refold loop and CSV output**

Similar structure to the Protenix script — iterate over sequences, call `run_boltz_predict`, parse outputs, write CSV incrementally. Include `--resume` support.

CSV columns: `run_id, idx, sequence, target_sequence, binder_length, iptm, ptm, bt_ipsae, tb_ipsae, ipsae_min, plddt_binder_mean, plddt_target_mean, pae_bt_mean, pae_tb_mean, structure_path, pae_file`

- [ ] **Step 6: Test with 1 binder**

```bash
cd /home/david/BindMaster
Mosaic/.venv/bin/python Evaluator/scripts/refold_boltz2_cli.py \
    --sequences <(echo -e ">test\nPAELSERERRIIEDVWYPVVHSGKRYIEEFKPTEWEKRFWEEVAEEVREMLEDYFRWSRS") \
    --target-seq "APFRSALESSPADPATLSEDEARLLLAALVQDYVQMKASELEQEQEREGSSLDSPRSKRCGNLSTCMLGTYTQDFNKFHTFPQTAIGVGAPGKKRDMSSDLERDHRPHVSMPQNAN" \
    --target-pdb runs/CALCA_combined/target/CALCA_BindMaster_test_01.pdb \
    --output-dir /tmp/test_boltz2_cli
```

Verify: Target RMSD < 3 Å, PAE file exists, ipSAE computed, CSV written.

- [ ] **Step 7: Commit**

```bash
git add Evaluator/scripts/refold_boltz2_cli.py
git commit -m "Add standalone Boltz-2 CLI refolding with template forcing (--use_potentials)"
```

---

### Task 3: Test Both Scripts on CALCA (3 binders)

- [ ] **Step 1: Run Protenix on 3 test binders (template mode)**

```bash
head -6 runs/CALCA_combined/evaluate/sequences_final.fasta > /tmp/test_3_binders.fasta
Mosaic/.venv/bin/python Evaluator/scripts/refold_protenix.py \
    --sequences /tmp/test_3_binders.fasta \
    --target-seq "APFRSALESSPADPATLSEDEARLLLAALVQDYVQMKASELEQEQEREGSSLDSPRSKRCGNLSTCMLGTYTQDFNKFHTFPQTAIGVGAPGKKRDMSSDLERDHRPHVSMPQNAN" \
    --target-pdb runs/CALCA_combined/target/CALCA_BindMaster_test_01.pdb \
    --output-dir /tmp/test_protenix_calca
```

- [ ] **Step 2: Run Boltz-2 CLI on same 3 binders (template mode)**

```bash
Mosaic/.venv/bin/python Evaluator/scripts/refold_boltz2_cli.py \
    --sequences /tmp/test_3_binders.fasta \
    --target-seq "APFRSALESSPADPATLSEDEARLLLAALVQDYVQMKASELEQEQEREGSSLDSPRSKRCGNLSTCMLGTYTQDFNKFHTFPQTAIGVGAPGKKRDMSSDLERDHRPHVSMPQNAN" \
    --target-pdb runs/CALCA_combined/target/CALCA_BindMaster_test_01.pdb \
    --output-dir /tmp/test_boltz2_cli_calca
```

- [ ] **Step 3: Compare results across all engines**

Check target RMSD for Boltz-2 CLI template mode. Compare ipSAE/ipTM across:
- Boltz-2 free (existing data)
- Boltz-2 template (new CLI script)
- AF2 (existing data)
- Protenix template (new script)

- [ ] **Step 4: Commit any fixes**
