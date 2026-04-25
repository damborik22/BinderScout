import csv
import json
import os
import re
import signal
import sys
import uuid
from pathlib import Path

import equinox as eqx
import gemmi
import jax
import jax.numpy as jnp
import mosaic.losses.structure_prediction as sp
import numpy as np
from mosaic.common import TOKENS
from mosaic.models.boltz2 import Boltz2
from mosaic.structure_prediction import TargetChain

# ============================
# CONFIGURATION
# ============================

OUTPUT_DIR = "refold_structures"

_interrupt_state = {
    "results": [],
    "checkpoint_path": None,
}


# ============================
# HELPER FUNCTIONS
# ============================


def _check_gpu():
    devices = jax.devices()
    if all(d.platform == "cpu" for d in devices):
        print("WARNING: No GPU detected — JAX is running on CPU only.")
        print("         This will be very slow. Consider running on a GPU machine.")
    else:
        print(f"GPU detected: {[str(d) for d in devices]}")


def _merge_aux_entries(aux):
    merged = {}
    for entry in aux:
        if not isinstance(entry, dict):
            continue
        for key, value in entry.items():
            merged.setdefault(key, []).append(value)
    return merged


def _flatten_numeric_values(value):
    if value is None:
        return []
    stack = [value]
    out = []
    while stack:
        item = stack.pop()
        if item is None:
            continue
        if isinstance(item, dict):
            stack.extend(item.values())
            continue
        if isinstance(item, (list, tuple)):
            stack.extend(item)
            continue
        arr = np.asarray(item)
        if arr.dtype == object:
            stack.extend(arr.tolist())
            continue
        for x in np.ravel(arr):
            try:
                v = float(x)
            except (TypeError, ValueError):
                continue
            if np.isfinite(v):
                out.append(v)
    return out


def _mean_aux_metric(aux_dict, key, aliases=()):
    for candidate_key in (key, *aliases):
        values = _flatten_numeric_values(aux_dict.get(candidate_key))
        if values:
            return float(np.mean(values)), candidate_key, len(values)
    return float("nan"), None, 0


def _extract_prediction_metrics(prediction, binder_length):
    """Slice PAE and pLDDT arrays into binder/target regions and compute statistics."""
    plddt = np.array(prediction.plddt)
    pae = np.array(prediction.pae)

    L_b = binder_length
    plddt_b = plddt[:L_b]
    plddt_t = plddt[L_b:]
    pae_bb = pae[:L_b, :L_b]
    pae_bt = pae[:L_b, L_b:]
    pae_tb = pae[L_b:, :L_b]
    pae_tt = pae[L_b:, L_b:]

    return {
        "iptm": float(prediction.iptm),
        "plddt_binder_mean": float(plddt_b.mean()),
        "plddt_binder_min": float(plddt_b.min()),
        "plddt_binder_max": float(plddt_b.max()),
        "plddt_binder_std": float(plddt_b.std()),
        "plddt_target_mean": float(plddt_t.mean()) if len(plddt_t) > 0 else float("nan"),
        "plddt_target_min": float(plddt_t.min()) if len(plddt_t) > 0 else float("nan"),
        "pae_bb_mean": float(pae_bb.mean()),
        "pae_bt_mean": float(pae_bt.mean()),
        "pae_tb_mean": float(pae_tb.mean()),
        "pae_tt_mean": float(pae_tt.mean()) if pae_tt.size > 0 else float("nan"),
        "pae_overall_mean": float(pae.mean()),
        "pae_max": float(pae.max()),
    }


def _nan_safe(obj):
    """Recursively replace float nan/inf with None for JSON serialisation."""
    if isinstance(obj, float):
        if obj != obj or obj == float("inf") or obj == float("-inf"):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _nan_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_nan_safe(x) for x in obj]
    return obj


def _save_checkpoint(path, data):
    with open(path, "w") as f:
        json.dump(_nan_safe(data), f, indent=2)
    print(f"  [checkpoint] Saved → {path}")


def _install_signal_handler(get_results_fn, checkpoint_path_fn):
    """Install SIGINT handler that saves partial results then exits cleanly."""

    def _handler(signum, frame):
        print("\n\nInterrupted! Saving checkpoint before exit...")
        results = get_results_fn()
        checkpoint_path = checkpoint_path_fn()
        if checkpoint_path and results is not None:
            _save_checkpoint(
                checkpoint_path,
                {
                    "interrupted": True,
                    "results": results,
                },
            )
        sys.exit(0)

    signal.signal(signal.SIGINT, _handler)


# ============================
# INPUT PARSING
# ============================


def _parse_fasta_like(lines: list[str]) -> list[str]:
    sequences = []
    current = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if current:
                sequences.append("".join(current))
                current = []
            continue
        current.append(line)
    if current:
        sequences.append("".join(current))
    return sequences


def _parse_batch_input(text: str) -> list[str]:
    lines = text.splitlines()
    has_header = any(line.strip().startswith(">") for line in lines)
    if has_header:
        return _parse_fasta_like(lines)
    tokens = re.split(r"[;,\s]+", text.strip())
    return [token for token in tokens if token]


def _read_binder_batch() -> list[str]:
    print("Paste binder sequences in batch, then press Enter on an empty line to run.")
    print("Supported formats: ';' separated, comma/newline/space separated, or FASTA.")
    lines = []
    while True:
        line = input().strip()
        if line == "":
            break
        lines.append(line)
    if not lines:
        return []
    return _parse_batch_input("\n".join(lines))


def _validate_sequence(seq: str, label: str) -> str:
    seq = seq.upper().strip()
    invalid = set(seq) - set(TOKENS)
    if invalid:
        raise ValueError(f"{label}: invalid amino acid characters: {invalid}")
    if not seq:
        raise ValueError(f"{label}: empty sequence")
    return seq


def _read_target_sequence() -> str:
    while True:
        raw = input("Target sequence: ").strip()
        try:
            return _validate_sequence(raw, "Target")
        except ValueError as e:
            print(f"  ✗ {e} — try again.")


# ============================
# REFOLD PIPELINE
# ============================


def refold_batch(
    binder_sequences: list[str],
    target_sequence: str,
    output_dir: str = OUTPUT_DIR,
    *,
    target_pdb: str | None = None,
    num_samples: int = 6,
    recycling_steps: int = 3,
    checkpoint_path: str | None = None,
    skip_indices: set[int] | None = None,
):
    """Refold a batch of binder sequences against a target.

    For each binder:
      - Runs full metrics_loss (all 13 aux terms)
      - Runs folder.predict for PDB / PAE / pLDDT outputs
      - Appends to refold_designs.txt and refold_designs.csv

    Args:
        target_pdb:      Optional path to target PDB/CIF. When provided, the target
                         backbone is constrained via Boltz-2 ``force: true`` template.
                         Useful for targets that misfold from sequence alone.
        num_samples:     Number of Boltz-2 samples for metrics (default: 6).
        recycling_steps: Number of recycling steps (default: 3).
        skip_indices:    Set of 1-based binder indices to skip (already completed).
                         When resuming, pass indices read from existing CSV.
    """
    if skip_indices is None:
        skip_indices = set()
    run_id = str(uuid.uuid4())[:8]
    os.makedirs(output_dir, exist_ok=True)

    if checkpoint_path is None:
        checkpoint_path = f"checkpoint_refold_{run_id}.json"

    results_ref = _interrupt_state["results"]
    _interrupt_state["checkpoint_path"] = checkpoint_path

    # Load target template if --target-pdb provided (forced template mode)
    target_template_chain = None
    if target_pdb:
        st = gemmi.read_structure(target_pdb)
        target_template_chain = st[0][0]  # first model, first chain
        n_res = sum(1 for _ in target_template_chain)
        print(f"Target template: {target_pdb} ({n_res} residues, force=True)")

    folder = Boltz2()

    # Cache target MSA across all binders. Mosaic's load_features_and_structure_writer
    # keeps processed/msa/ (CSVs keyed by sequence hash) and wipes the per-complex dirs
    # (manifest.json, processed/structures, etc.) on each call, so the target's MSA is
    # fetched once and reused for every binder. Without this, large refold runs flood
    # api.colabfold.com and hit RATELIMIT, sleeping seconds between every binder.
    _processing_dir = Path(output_dir) / "boltz_msa_cache"
    _processing_dir.mkdir(parents=True, exist_ok=True)
    print(f"Boltz-2 MSA cache : {_processing_dir}")

    @eqx.filter_jit
    def evaluate_loss(loss_fn, pssm, key):
        return loss_fn(pssm, key=key)

    print(f"\nRun ID: {run_id}")
    print(f"Target length: {len(target_sequence)} aa")
    if target_pdb:
        print("Mode: template-constrained (target backbone forced from PDB)")
    else:
        print("Mode: sequence-only (target predicted de novo)")
    print(f"Samples: {num_samples}, recycling steps: {recycling_steps}")
    print(f"Binders to refold: {len(binder_sequences)}")
    print(f"Output directory: {output_dir}\n")

    csv_path = "refold_designs.csv"
    csv_columns = [
        "run_id",
        "idx",
        "sequence",
        "target_sequence",
        "binder_length",
        "iptm_aux",
        "bt_ipsae",
        "tb_ipsae",
        "ipsae_min",
        "ipsae_valid",
        "bt_iptm",
        "binder_ptm",
        "plddt_aux",
        "bb_pae",
        "bt_pae_aux",
        "tb_pae",
        "intra_contact",
        "target_contact",
        "pTMEnergy",
        "iptm",
        "plddt_binder_mean",
        "plddt_binder_min",
        "plddt_binder_max",
        "plddt_binder_std",
        "plddt_target_mean",
        "plddt_target_min",
        "pae_bb_mean",
        "pae_bt_mean",
        "pae_tb_mean",
        "ipae",
        "pae_tt_mean",
        "pae_overall_mean",
        "pae_max",
        "pdb",
        "pae_file",
        "plddt_file",
    ]
    write_header = (not os.path.exists(csv_path)) or os.path.getsize(csv_path) == 0
    csv_file = open(csv_path, "a", newline="")
    try:
        csv_writer = csv.DictWriter(csv_file, fieldnames=csv_columns)
        if write_header:
            csv_writer.writeheader()
            csv_file.flush()
        fasta_lines = []

        # Sort binders by length to minimize JIT recompilations.
        # Same-length binders reuse compiled kernels; clear caches on length change.
        indexed_seqs = list(enumerate(binder_sequences, start=1))  # (1-based idx, seq)
        indexed_seqs.sort(key=lambda x: len(x[1]))
        n_todo = sum(1 for idx, _ in indexed_seqs if idx not in skip_indices)
        n_done = 0
        prev_length = -1

        for idx, seq_str in indexed_seqs:
            if idx in skip_indices:
                continue

            binder_length = len(seq_str)

            # Skip binders whose sequence matches the target — Boltz-2 requires
            # same-sequence chains to share MSA settings, which conflicts with
            # binder(no MSA) + target(MSA) setup
            if seq_str.upper() == target_sequence.upper():
                print(f"[SKIP] Binder #{idx} has same sequence as target — skipping")
                continue

            n_done += 1

            # Clear JAX caches when binder length changes — prevents GPU memory
            # fragmentation from accumulating JIT-compiled kernels for many shapes
            if binder_length != prev_length and prev_length > 0:
                jax.clear_caches()
            prev_length = binder_length

            print(f"{'─' * 55}")
            print(f"[{n_done}/{n_todo}] (idx={idx}) length={binder_length} aa  seq={seq_str}")

            seq = jnp.array([TOKENS.index(c) for c in seq_str])
            pssm = jax.nn.one_hot(seq, 20)

            boltz_features, boltz_writer = folder.target_only_features(
                chains=[
                    TargetChain(sequence=seq_str, use_msa=False),  # binder: de novo, no MSA
                    TargetChain(
                        sequence=target_sequence,
                        use_msa=True,
                        template_chain=target_template_chain,
                        force_template=target_template_chain is not None,
                    ),
                ],
                processing_dir=_processing_dir,
            )

            # ---- Comprehensive aux metrics — all 13 loss terms ----
            metrics_loss = folder.build_multisample_loss(
                loss=(
                    sp.IPTMLoss()
                    + sp.BinderTargetIPSAE()
                    + sp.TargetBinderIPSAE()
                    + sp.IPSAE_min()
                    + sp.BinderTargetIPTM()
                    + sp.BinderPTMLoss()
                    + sp.PLDDTLoss()
                    + sp.WithinBinderPAE()
                    + sp.BinderTargetPAE()
                    + sp.TargetBinderPAE()
                    + sp.WithinBinderContact()
                    + sp.BinderTargetContact()
                    + sp.pTMEnergy()
                ),
                features=boltz_features,
                recycling_steps=recycling_steps,
                num_samples=num_samples,
            )
            _, aux = evaluate_loss(metrics_loss, pssm, key=jax.random.key(0))

            aux_dict = _merge_aux_entries(aux)
            if idx == 1:
                print(f"  [debug] aux keys: {sorted(aux_dict.keys())}")

            iptm_aux, _, _ = _mean_aux_metric(aux_dict, "iptm")
            bt_ipsae, bt_key, bt_n = _mean_aux_metric(aux_dict, "bt_ipsae", aliases=("binder_target_ipsae",))
            tb_ipsae, tb_key, tb_n = _mean_aux_metric(aux_dict, "tb_ipsae", aliases=("target_binder_ipsae",))
            ipsae_min, _, _ = _mean_aux_metric(aux_dict, "ipsae_min")
            bt_iptm, _, _ = _mean_aux_metric(aux_dict, "bt_iptm")
            binder_ptm, _, _ = _mean_aux_metric(aux_dict, "binder_ptm")
            plddt_aux, _, _ = _mean_aux_metric(aux_dict, "plddt")
            bb_pae, _, _ = _mean_aux_metric(aux_dict, "bb_pae")
            bt_pae_aux, _, _ = _mean_aux_metric(aux_dict, "bt_pae")
            tb_pae, _, _ = _mean_aux_metric(aux_dict, "tb_pae")
            intra_contact, _, _ = _mean_aux_metric(aux_dict, "intra_contact")
            target_contact, _, _ = _mean_aux_metric(aux_dict, "target_contact")
            pTMEnergy_val, _, _ = _mean_aux_metric(aux_dict, "pTMEnergy")

            if idx == 1:
                print(f"  [debug] bt source={bt_key} n={bt_n}  tb source={tb_key} n={tb_n}")

            # Change 3: ipsae_valid flag
            ipsae_valid = 1 if (not np.isnan(ipsae_min) and ipsae_min > 0.0) else 0

            # Change 2: Diagnose ipsae=0 cases
            if bt_ipsae == 0.0 and tb_ipsae == 0.0:
                print("  [WARNING] ipsae=0 for this binder — dumping aux_dict values for diagnosis:")
                for k, v in sorted(aux_dict.items()):
                    vals = _flatten_numeric_values(v)
                    print(f"    {k}: {vals[:6]}")

            # ---- Full prediction → structure files ----
            prediction = folder.predict(
                PSSM=pssm,
                features=boltz_features,
                writer=boltz_writer,
                recycling_steps=recycling_steps,
                key=jax.random.key(0),
            )

            pred_metrics = _extract_prediction_metrics(prediction, binder_length)
            iptm = pred_metrics["iptm"]
            plddt_binder_mean = pred_metrics["plddt_binder_mean"]
            plddt_binder_min = pred_metrics["plddt_binder_min"]
            plddt_binder_max = pred_metrics["plddt_binder_max"]
            plddt_binder_std = pred_metrics["plddt_binder_std"]
            plddt_target_mean = pred_metrics["plddt_target_mean"]
            plddt_target_min = pred_metrics["plddt_target_min"]
            pae_bb_mean = pred_metrics["pae_bb_mean"]
            pae_bt_mean = pred_metrics["pae_bt_mean"]
            pae_tb_mean = pred_metrics["pae_tb_mean"]
            pae_tt_mean = pred_metrics["pae_tt_mean"]
            pae_overall_mean = pred_metrics["pae_overall_mean"]
            pae_max = pred_metrics["pae_max"]

            # Change 1: ipae derived metric
            ipae = (pae_bt_mean + pae_tb_mean) / 2.0

            pdb_path = f"{output_dir}/refold{idx}_{run_id}.pdb"
            pae_file = f"{output_dir}/refold{idx}_{run_id}_pae.npy"
            plddt_file = f"{output_dir}/refold{idx}_{run_id}_plddt.csv"

            with open(pdb_path, "w") as f:
                f.write(prediction.st.make_pdb_string())

            np.save(pae_file, np.array(prediction.pae))

            plddt_full = np.array(prediction.plddt)
            with open(plddt_file, "w", newline="") as f:
                plddt_writer = csv.writer(f)
                plddt_writer.writerow(["residue_idx", "chain", "residue_in_chain", "plddt"])
                for i, v in enumerate(plddt_full):
                    chain = "binder" if i < binder_length else "target"
                    res_in_chain = i if i < binder_length else i - binder_length
                    plddt_writer.writerow([i, chain, res_in_chain, f"{v:.6f}"])

            # Console summary
            print(
                f"  Interface:       iptm={iptm:.4f}  bt_ipsae={bt_ipsae:.4f}  tb_ipsae={tb_ipsae:.4f}  ipsae_min={ipsae_min:.4f}  ipsae_valid={ipsae_valid}  bt_iptm={bt_iptm:.4f}"
            )
            print(
                f"  Binder quality:  binder_ptm={binder_ptm:.4f}  plddt_mean={plddt_binder_mean:.4f}  plddt_min={plddt_binder_min:.4f}  pae_bb={pae_bb_mean:.4f}  intra_contact={intra_contact:.4f}"
            )
            print(
                f"  PAE overview:    pae_bt={pae_bt_mean:.4f}  pae_tb={pae_tb_mean:.4f}  ipae={ipae:.4f}  pae_bb={pae_bb_mean:.4f}  pae_overall={pae_overall_mean:.4f}  pae_max={pae_max:.4f}"
            )
            print(f"  Energy/contacts: pTMEnergy={pTMEnergy_val:.4f}  target_contact={target_contact:.4f}")
            print(f"  Files:  pdb={pdb_path}  pae={pae_file}  plddt={plddt_file}")

            row = {
                "run_id": run_id,
                "idx": idx,
                "sequence": seq_str,
                "target_sequence": target_sequence,
                "binder_length": binder_length,
                # Aux-based metrics
                "iptm_aux": iptm_aux,
                "bt_ipsae": bt_ipsae,
                "tb_ipsae": tb_ipsae,
                "ipsae_min": ipsae_min,
                "ipsae_valid": ipsae_valid,
                "bt_iptm": bt_iptm,
                "binder_ptm": binder_ptm,
                "plddt_aux": plddt_aux,
                "bb_pae": bb_pae,
                "bt_pae_aux": bt_pae_aux,
                "tb_pae": tb_pae,
                "intra_contact": intra_contact,
                "target_contact": target_contact,
                "pTMEnergy": pTMEnergy_val,
                # Prediction-based metrics
                "iptm": iptm,
                "plddt_binder_mean": plddt_binder_mean,
                "plddt_binder_min": plddt_binder_min,
                "plddt_binder_max": plddt_binder_max,
                "plddt_binder_std": plddt_binder_std,
                "plddt_target_mean": plddt_target_mean,
                "plddt_target_min": plddt_target_min,
                "pae_bb_mean": pae_bb_mean,
                "pae_bt_mean": pae_bt_mean,
                "pae_tb_mean": pae_tb_mean,
                "ipae": ipae,
                "pae_tt_mean": pae_tt_mean,
                "pae_overall_mean": pae_overall_mean,
                "pae_max": pae_max,
                # Files
                "pdb": pdb_path,
                "pae_file": pae_file,
                "plddt_file": plddt_file,
            }
            results_ref.append(row)
            csv_writer.writerow(row)
            csv_file.flush()

            # Enriched FASTA header
            header = (
                f">refold{idx}_{run_id}"
                f"  binder_length={binder_length}"
                f"  iptm={iptm:.4f}"
                f"  bt_ipsae={bt_ipsae:.4f}"
                f"  tb_ipsae={tb_ipsae:.4f}"
                f"  ipsae_min={ipsae_min:.4f}"
                f"  ipsae_valid={ipsae_valid}"
                f"  bt_iptm={bt_iptm:.4f}"
                f"  binder_ptm={binder_ptm:.4f}"
                f"  plddt_mean={plddt_binder_mean:.4f}"
                f"  plddt_min={plddt_binder_min:.4f}"
                f"  pae_bb={pae_bb_mean:.4f}"
                f"  ipae={ipae:.4f}"
                f"  pTMEnergy={pTMEnergy_val:.4f}"
                f"  intra_contact={intra_contact:.4f}"
                f"  target_contact={target_contact:.4f}"
                f"  pdb={pdb_path}"
            )
            fasta_lines.append(f"{header}\n{seq_str}")

    except Exception:
        if checkpoint_path:
            _save_checkpoint(
                checkpoint_path,
                {
                    "interrupted": True,
                    "exception": True,
                    "results": list(results_ref),
                },
            )
        raise
    finally:
        csv_file.close()

    # ---- Write refold_designs.txt ----
    txt_path = "refold_designs.txt"
    with open(txt_path, "a") as f:
        if os.path.exists(txt_path) and os.path.getsize(txt_path) > 0:
            f.write("\n")
        f.write("\n".join(fasta_lines) + "\n")

    print(f"\n{'=' * 55}")
    print("=== Run Complete ===")
    print(f"Processed {len(results_ref)} binder(s).")
    print(f"Results  → {txt_path}, {csv_path}")
    print(f"PDB      → {output_dir}/refold*_{run_id}.pdb")
    print(f"PAE      → {output_dir}/refold*_{run_id}_pae.npy")
    print(f"pLDDT    → {output_dir}/refold*_{run_id}_plddt.csv")
    print(f"Run ID: {run_id} (for tracking this session)")


# ============================
# MAIN
# ============================


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Boltz2 Refolding Tool (Version 6)")
    parser.add_argument("--target-seq", metavar="SEQ", help="Target protein sequence (skip interactive prompt)")
    parser.add_argument("--sequences", metavar="FILE", help="FASTA file of binder sequences (skip interactive prompt)")
    parser.add_argument(
        "--target-pdb",
        metavar="PDB",
        help="Target PDB/CIF for forced template mode. Constrains target backbone "
        "while binder is predicted de novo. Use for targets that misfold from sequence.",
    )
    parser.add_argument(
        "--num-samples", type=int, default=6, metavar="N", help="Number of Boltz-2 samples (default: 6)"
    )
    parser.add_argument("--recycling-steps", type=int, default=3, metavar="N", help="Recycling steps (default: 3)")
    parser.add_argument(
        "--output-dir", default=OUTPUT_DIR, metavar="DIR", help=f"Output directory (default: {OUTPUT_DIR})"
    )
    parser.add_argument("--resume", action="store_true", help="Skip binders already present in existing CSV")
    args = parser.parse_args()

    print("=== Boltz2 Refolding Tool (Version 6) ===\n")

    _check_gpu()
    print()

    # Target sequence: from CLI or interactive
    if args.target_seq:
        target_seq = _validate_sequence(args.target_seq, "Target")
    else:
        target_seq = _read_target_sequence()

    # Binder sequences: from file or interactive
    if args.sequences:
        with open(args.sequences) as f:
            binder_candidates = _parse_batch_input(f.read())
    else:
        binder_candidates = _read_binder_batch()

    if not binder_candidates:
        print("\nNo binder sequences provided — exiting.")
        return

    binder_sequences = []
    for idx, seq in enumerate(binder_candidates, start=1):
        try:
            binder_sequences.append(_validate_sequence(seq, f"Binder#{idx}"))
        except ValueError as e:
            print(f"  ✗ {e} — skipping binder #{idx}.")

    if not binder_sequences:
        print("\nNo valid binder sequences — exiting.")
        return

    _install_signal_handler(
        get_results_fn=lambda: _interrupt_state["results"],
        checkpoint_path_fn=lambda: _interrupt_state["checkpoint_path"],
    )

    refold_batch(
        binder_sequences,
        target_seq,
        output_dir=args.output_dir,
        target_pdb=args.target_pdb,
        num_samples=args.num_samples,
        recycling_steps=args.recycling_steps,
    )


if __name__ == "__main__":
    main()
