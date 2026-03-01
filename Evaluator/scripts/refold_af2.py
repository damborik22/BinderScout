"""AF2 binder cross-evaluator using ColabDesign.

Run with:  conda run -n bindcraft_pr python run_v6_protenix.py
           conda run -n bindcraft_pr python run_v6_mosaic.py

Binder protocol: target first (indices 0:L_t), binder second (indices L_t:L_t+L_b).
"""

import csv
import os
import uuid

import numpy as np
from colabdesign import mk_af_model

OUTPUT_DIR = "af2_structures"
AF2_DATA_DIR = os.environ.get("AF2_DATA_DIR", "/opt/bindmaster/af2_params")
CSV_PATH = "af2_eval.csv"

CSV_COLUMNS = [
    "run_id",
    "idx",
    "sequence",
    "target_pdb",
    "binder_length",
    "af2_iptm",
    "af2_plddt_binder_mean",
    "af2_plddt_binder_min",
    "af2_plddt_binder_max",
    "af2_plddt_target_mean",
    "af2_pae_bt_mean",
    "af2_pae_tb_mean",
    "af2_ipae",
    "af2_pae_bb_mean",
    "af2_pae_tt_mean",
    "af2_pae_overall_mean",
    "af2_pae_max",
    "pdb",
    "af2_pae_file",  # path to saved PAE matrix (.npy); enables AF2 ipSAE computation
]


def refold_batch_af2(
    binder_sequences: list,
    target_pdb_path: str,
    *,
    models: list | None = None,
    num_recycles: int = 3,
    output_dir: str = OUTPUT_DIR,
    csv_path: str = CSV_PATH,
    skip_indices: set | None = None,
):
    """Evaluate a batch of binder sequences with AF2 multimer (ColabDesign binder protocol).

    For each binder:
      - Runs AF2 multimer prediction (target first, binder second ordering)
      - Extracts iptm, plddt, and pae metrics sliced into binder/target regions
      - Saves PDB and writes a CSV row immediately (incremental)

    Args:
        skip_indices: Set of 1-based binder indices to skip (already completed).
                      When resuming, pass indices read from existing CSV.
    """
    if skip_indices is None:
        skip_indices = set()
    if models is None:
        models = [1]

    run_id = str(uuid.uuid4())[:8]
    os.makedirs(output_dir, exist_ok=True)

    print("\n=== AF2 Binder Cross-Evaluator (Version 6) ===")
    print(f"Run ID: {run_id}")
    print(f"Target PDB: {target_pdb_path}")
    print(f"Binders to evaluate: {len(binder_sequences)}")
    print(f"AF2 models: {models}  num_recycles: {num_recycles}")
    print(f"Output directory: {output_dir}\n")

    # Load AF2 model weights once, reuse across all binders
    print("Loading AF2 model weights...")
    af = mk_af_model(protocol="binder", use_multimer=True, data_dir=AF2_DATA_DIR)
    print("AF2 model ready.\n")

    write_header = (not os.path.exists(csv_path)) or os.path.getsize(csv_path) == 0
    csv_file = open(csv_path, "a", newline="")
    try:
        csv_writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
        if write_header:
            csv_writer.writeheader()
            csv_file.flush()

        for idx, seq in enumerate(binder_sequences, start=1):
            if idx in skip_indices:
                print(f"[SKIP] Binder #{idx} already completed")
                continue

            L_b = len(seq)
            print(f"{'─' * 55}")
            print(f"[{idx}/{len(binder_sequences)}] length={L_b} aa  seq={seq}")

            af.prep_inputs(pdb_filename=target_pdb_path, chain="A", binder_len=L_b)
            af.set_seq(seq)
            af.predict(models=models, num_recycles=num_recycles)

            # Diagnostic dump on first binder to catch API surprises early
            if idx == 1:
                print(f"  [debug] af.aux keys: {sorted(af.aux.keys())}")
                log_val = af.aux.get("log", {})
                log_keys = sorted(log_val.keys()) if isinstance(log_val, dict) else type(log_val)
                print(f"  [debug] af.aux['log'] keys: {log_keys}")
                print(f"  [debug] af._inputs keys: {sorted(af._inputs.keys())}")

            # Determine target length — prefer explicit field, fall back to array arithmetic
            L_t = af._inputs.get("target_length", None)
            if L_t is None:
                total_len = len(af.aux["plddt"])
                L_t = total_len - L_b
            L_t = int(L_t)

            # Slice arrays: target [0:L_t], binder [L_t:L_t+L_b]
            plddt = np.array(af.aux["plddt"])
            pae = np.array(af.aux["pae"])

            plddt_t = plddt[:L_t]
            plddt_b = plddt[L_t:]
            pae_tt = pae[:L_t, :L_t]
            pae_bt = pae[L_t:, :L_t]  # binder rows → target cols
            pae_tb = pae[:L_t, L_t:]  # target rows → binder cols
            pae_bb = pae[L_t:, L_t:]

            # Interface iptm — prefer top-level key, fall back to log dict
            if "i_ptm" in af.aux:
                af2_iptm = float(af.aux["i_ptm"])
            else:
                log = af.aux.get("log", {})
                af2_iptm = (
                    float(log.get("i_ptm", log.get("iptm", float("nan")))) if isinstance(log, dict) else float("nan")
                )

            # pLDDT statistics
            af2_plddt_binder_mean = float(plddt_b.mean()) if plddt_b.size > 0 else float("nan")
            af2_plddt_binder_min = float(plddt_b.min()) if plddt_b.size > 0 else float("nan")
            af2_plddt_binder_max = float(plddt_b.max()) if plddt_b.size > 0 else float("nan")
            af2_plddt_target_mean = float(plddt_t.mean()) if plddt_t.size > 0 else float("nan")

            # PAE statistics
            af2_pae_bt_mean = float(pae_bt.mean()) if pae_bt.size > 0 else float("nan")
            af2_pae_tb_mean = float(pae_tb.mean()) if pae_tb.size > 0 else float("nan")
            af2_ipae = (af2_pae_bt_mean + af2_pae_tb_mean) / 2.0
            af2_pae_bb_mean = float(pae_bb.mean()) if pae_bb.size > 0 else float("nan")
            af2_pae_tt_mean = float(pae_tt.mean()) if pae_tt.size > 0 else float("nan")
            af2_pae_overall_mean = float(pae.mean())
            af2_pae_max = float(pae.max())

            # Save structure
            pdb_path = f"{output_dir}/af2_{idx}_{run_id}.pdb"
            af.save_pdb(pdb_path)

            # Save PAE matrix for downstream ipSAE computation.
            # Array is in native AF2 ordering: [target | binder].
            # binder_comparison/comparison/scoring.py reads this with ordering="target_binder".
            pae_path = f"{output_dir}/af2_{idx}_{run_id}_pae.npy"
            np.save(pae_path, pae)

            # Console summary
            print(
                f"  Interface:   iptm={af2_iptm:.4f}  ipae={af2_ipae:.4f}  pae_bt={af2_pae_bt_mean:.4f}  pae_tb={af2_pae_tb_mean:.4f}"
            )
            print(
                f"  Binder:      plddt_mean={af2_plddt_binder_mean:.4f}  plddt_min={af2_plddt_binder_min:.4f}  pae_bb={af2_pae_bb_mean:.4f}"
            )
            print(f"  Target:      plddt_mean={af2_plddt_target_mean:.4f}  pae_tt={af2_pae_tt_mean:.4f}")
            print(f"  PAE overall: mean={af2_pae_overall_mean:.4f}  max={af2_pae_max:.4f}")
            print(f"  PDB: {pdb_path}")
            print(f"  PAE: {pae_path}")

            row = {
                "run_id": run_id,
                "idx": idx,
                "sequence": seq,
                "target_pdb": target_pdb_path,
                "binder_length": L_b,
                "af2_iptm": af2_iptm,
                "af2_plddt_binder_mean": af2_plddt_binder_mean,
                "af2_plddt_binder_min": af2_plddt_binder_min,
                "af2_plddt_binder_max": af2_plddt_binder_max,
                "af2_plddt_target_mean": af2_plddt_target_mean,
                "af2_pae_bt_mean": af2_pae_bt_mean,
                "af2_pae_tb_mean": af2_pae_tb_mean,
                "af2_ipae": af2_ipae,
                "af2_pae_bb_mean": af2_pae_bb_mean,
                "af2_pae_tt_mean": af2_pae_tt_mean,
                "af2_pae_overall_mean": af2_pae_overall_mean,
                "af2_pae_max": af2_pae_max,
                "pdb": pdb_path,
                "af2_pae_file": pae_path,
            }
            csv_writer.writerow(row)
            csv_file.flush()

    finally:
        csv_file.close()

    print(f"\n{'=' * 55}")
    print("=== Run Complete ===")
    print(f"Processed {len(binder_sequences)} binder(s).")
    print(f"Results → {csv_path}")
    print(f"PDB     → {output_dir}/af2_*_{run_id}.pdb")
    print(f"PAE     → {output_dir}/af2_*_{run_id}_pae.npy  (for ipSAE computation)")
    print(f"Run ID: {run_id} (for tracking this session)")
