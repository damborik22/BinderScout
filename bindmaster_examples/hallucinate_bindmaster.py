import uuid
import os
import csv
import signal
import json
import sys

import jax
import jax.numpy as jnp
import equinox as eqx
import numpy as np

from mosaic.models.boltz2 import Boltz2
import mosaic.losses.structure_prediction as sp
from mosaic.common import TOKENS
from mosaic.losses.protein_mpnn import InverseFoldingSequenceRecovery
from mosaic.losses.transformations import NoCys
from mosaic.proteinmpnn.mpnn import load_mpnn_sol
from mosaic.structure_prediction import TargetChain
from mosaic.optimizers import simplex_APGM


# ============================
# BINDMASTER PARAMETERS
# ============================
# All values below are injected by BindMaster Configurator.
# Edit manually to override after generation.

TARGET_SEQUENCE = "REPLACE_ME"  # target protein sequence
N_DESIGNS = 100  # Stage 1: how many designs to generate per length
TOP_K = 5  # Stage 2: how many top designs to refold and export PDB
MIN_LENGTH = 65  # minimum binder length (aa)
MAX_LENGTH = 100  # maximum binder length (aa)
LENGTH_STEP = 5  # step between scanned lengths; set MIN=MAX for a single length


# ============================
# INTERNAL STATE
# ============================

_interrupt_state = {
    "candidates": [],
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


def _hamming_distance(seq_a, seq_b):
    """Character-wise Hamming distance between two equal-length strings."""
    return sum(a != b for a, b in zip(seq_a, seq_b))


def _diversity_filter(candidates, min_hamming):
    """Greedy diversity filter: keep a candidate only if it is at least
    min_hamming away (Hamming distance) from every already-accepted candidate.
    Input list is assumed to be sorted best→worst (lower loss first).
    """
    accepted = []
    for seq, loss_val in candidates:
        if all(_hamming_distance(seq, acc_seq) >= min_hamming for acc_seq, _ in accepted):
            accepted.append((seq, loss_val))
    return accepted


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


def _load_checkpoint(path):
    with open(path) as f:
        data = json.load(f)
    raw_candidates = data.get("candidates", [])
    candidates = []
    for item in raw_candidates:
        seq, lv = item
        if lv is None:
            lv = float("nan")
        candidates.append((seq, float(lv)))
    data["candidates"] = candidates
    return data


def _install_signal_handler(get_candidates_fn, checkpoint_path_fn):
    """Install SIGINT handler that saves a checkpoint then exits cleanly."""

    def _handler(signum, frame):
        print("\n\nInterrupted! Saving checkpoint before exit...")
        candidates = get_candidates_fn()
        checkpoint_path = checkpoint_path_fn()
        if checkpoint_path and candidates is not None:
            _save_checkpoint(
                checkpoint_path,
                {
                    "interrupted": True,
                    "candidates": candidates,
                },
            )
        sys.exit(0)

    signal.signal(signal.SIGINT, _handler)


def _print_length_summary(summary_rows):
    """Print a summary table after a multi-length scan."""
    print("\n" + "=" * 60)
    print("=== Length Scan Summary ===")
    print(f"{'Length':>8}  {'Best ranking_loss':>18}  {'N designs':>10}")
    print("-" * 60)
    for row in summary_rows:
        length = row["binder_length"]
        best = row["best_ranking_loss"]
        n = row["n_designs"]
        best_str = f"{best:.4f}" if best is not None else "  (filtered)"
        print(f"{length:>8}  {best_str:>18}  {n:>10}")
    print("=" * 60)


# ============================
# DESIGN LOOP
# ============================


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


def design(
    n_designs: int,
    top_k: int,
    binder_length: int,
    target_sequence: str,
    output_dir: str = "structures",
    *,
    checkpoint_path=None,
    resume_from=None,
    min_ranking_loss=None,
    min_hamming=0,
    epitope_idx=None,
    ss_bias="none",
    min_iptm_aux=None,
):
    """Run a binder design campaign for one binder_length.

    Returns a dict with keys:
        best_ranking_loss : float | None
        n_designs         : int
    """
    worker_id = str(uuid.uuid4())[:8]
    os.makedirs(output_dir, exist_ok=True)

    print(f"\nInitializing design run:")
    print(f"  Worker ID: {worker_id}")
    print(f"  Binder length: {binder_length} aa")
    print(f"  Target length: {len(target_sequence)} aa")
    print(f"  Designs requested: {n_designs}")
    print(f"  Top designs to refold: {top_k}")
    print(f"  Output directory: {output_dir}")
    if checkpoint_path:
        print(f"  Checkpoint path: {checkpoint_path}")
    if resume_from:
        print(f"  Resuming from: {resume_from}")
    if min_ranking_loss is not None:
        print(f"  Min ranking_loss threshold: {min_ranking_loss}")
    if min_hamming > 0:
        print(f"  Min Hamming distance (diversity): {min_hamming}")
    if epitope_idx is not None:
        print(f"  Epitope indices: {epitope_idx}")
    if ss_bias != "none":
        print(f"  SS bias: {ss_bias}")
    if min_iptm_aux is not None:
        print(f"  Min iptm_aux gate: {min_iptm_aux}")

    _checkpoint_file = checkpoint_path or f"checkpoint_{worker_id}.json"
    candidates_ref = []
    _interrupt_state["candidates"] = candidates_ref
    _interrupt_state["checkpoint_path"] = _checkpoint_file

    folder = Boltz2()
    mpnn = load_mpnn_sol(0.05)

    bias = jnp.zeros((binder_length, 20)).at[:binder_length, TOKENS.index("C")].set(-1e6)

    sp_loss = (
        sp.BinderTargetContact(epitope_idx=epitope_idx)
        + sp.WithinBinderContact()
        + 10.0 * InverseFoldingSequenceRecovery(mpnn, temp=jnp.array(0.001), bias=bias)
        + 0.05 * sp.TargetBinderPAE()
        + 0.05 * sp.BinderTargetPAE()
        + 0.025 * sp.IPTMLoss()
        + 0.4 * sp.WithinBinderPAE()
        + 0.025 * sp.pTMEnergy()
        + 0.1 * sp.PLDDTLoss()
    )

    if ss_bias == "helix":
        sp_loss = sp_loss + 0.1 * sp.HelixLoss()
    elif ss_bias == "compact":
        sp_loss = sp_loss + 0.1 * sp.DistogramRadiusOfGyration()

    features, _ = folder.binder_features(
        binder_length=binder_length,
        chains=[TargetChain(sequence=target_sequence, use_msa=False)],
    )

    loss = NoCys(
        folder.build_multisample_loss(
            loss=sp_loss,
            features=features,
            recycling_steps=1,
            num_samples=1,
        )
    )

    @eqx.filter_jit
    def evaluate_loss(loss, pssm, key):
        return loss(pssm, key=key)

    # --------------------------
    # Stage 1: optimize, rank
    # --------------------------
    def design_one(design_idx):
        print(f"[{design_idx + 1}/{n_designs}] designing...")
        _pssm = np.random.uniform(low=0.25, high=0.75) * jax.random.gumbel(
            key=jax.random.key(np.random.randint(10000000)),
            shape=(binder_length, 19),
        )
        _, pssm = simplex_APGM(
            loss_function=loss,
            x=jax.nn.softmax(_pssm),
            n_steps=100,
            stepsize=0.2 * np.sqrt(binder_length),
            momentum=0.3,
            scale=1.00,
            logspace=False,
            max_gradient_norm=1.0,
        )
        pssm, _ = simplex_APGM(
            loss_function=loss,
            x=jnp.log(pssm + 1e-5),
            n_steps=50,
            stepsize=0.5 * np.sqrt(binder_length),
            momentum=0.0,
            scale=1.25,
            logspace=True,
            max_gradient_norm=1.0,
        )
        pssm, _ = simplex_APGM(
            loss_function=loss,
            x=jnp.log(pssm + 1e-5),
            n_steps=15,
            stepsize=0.5 * np.sqrt(binder_length),
            momentum=0.0,
            scale=1.4,
            logspace=True,
            max_gradient_norm=1.0,
        )

        pssm = NoCys.sequence(pssm)
        seq = pssm.argmax(-1)
        seq_str = "".join(TOKENS[i] for i in seq)

        boltz_features, _ = folder.target_only_features(
            chains=[
                TargetChain(sequence=seq_str, use_msa=True),
                TargetChain(sequence=target_sequence, use_msa=True),
            ]
        )
        ranking_loss = folder.build_multisample_loss(
            loss=1.00 * sp.IPTMLoss() + 0.5 * sp.TargetBinderIPSAE() + 0.5 * sp.BinderTargetIPSAE(),
            features=boltz_features,
            recycling_steps=3,
            num_samples=6,
        )
        loss_value, _ = evaluate_loss(ranking_loss, jax.nn.one_hot(seq, 20), key=jax.random.key(0))

        print(f"  ranking_loss={loss_value.item():.4f}  seq={seq_str}")
        return seq_str, loss_value.item()

    print(f"\n=== Stage 1: Generating {n_designs} designs ===")

    if resume_from is not None:
        ckpt = _load_checkpoint(resume_from)
        candidates = ckpt["candidates"]
        print(f"  Loaded {len(candidates)} candidates from checkpoint: {resume_from}")
        for i, (seq, lv) in enumerate(candidates[:5]):
            print(f"    [{i + 1}] loss={lv:.4f}  seq={seq}")
        if len(candidates) > 5:
            print(f"    ... and {len(candidates) - 5} more")
    else:
        candidates = candidates_ref
        for i in range(n_designs):
            seq, loss_value = design_one(i)
            candidates.append((seq, loss_value))

        candidates = sorted(candidates, key=lambda x: x[1])
        _interrupt_state["candidates"] = candidates

        _save_checkpoint(
            _checkpoint_file,
            {
                "worker_id": worker_id,
                "binder_length": binder_length,
                "n_designs": n_designs,
                "top_k": top_k,
                "target_sequence": target_sequence,
                "output_dir": output_dir,
                "candidates": candidates,
                "interrupted": False,
            },
        )

    candidates = sorted(candidates, key=lambda x: x[1])

    print(f"\n=== Design ranking ===")
    for i, (seq, loss_val) in enumerate(candidates[: min(10, len(candidates))]):
        print(f"  Rank {i + 1}: loss={loss_val:.4f}  seq={seq}")
    if len(candidates) > 10:
        print(f"  ... and {len(candidates) - 10} more designs")

    if min_ranking_loss is not None:
        candidates = [(s, lv) for s, lv in candidates if lv <= min_ranking_loss]
        print(f"  Threshold gate (≤ {min_ranking_loss}): {len(candidates)} candidates pass")
        if not candidates:
            print("  No candidates passed the threshold gate — skipping Stage 2.")
            return {"best_ranking_loss": None, "n_designs": n_designs}

    if min_hamming > 0:
        before = len(candidates)
        candidates = _diversity_filter(candidates, min_hamming)
        print(f"  Diversity filter (Hamming ≥ {min_hamming}): {before} → {len(candidates)} candidates")

    # --------------------------
    # Stage 2: refold top-K
    # --------------------------
    top_k = max(0, min(top_k, len(candidates)))
    print(f"\n=== Stage 2: Refolding top {top_k} designs ===")

    final_lines = []
    csv_rows = []

    for rank, (seq_str, fast_loss) in enumerate(candidates):
        is_top = rank < top_k

        ranking_loss_value = float(fast_loss)
        iptm_aux = float("nan")
        bt_ipsae = float("nan")
        tb_ipsae = float("nan")
        ipsae_min = float("nan")
        bt_iptm = float("nan")
        binder_ptm = float("nan")
        plddt_aux = float("nan")
        bb_pae = float("nan")
        bt_pae_aux = float("nan")
        tb_pae = float("nan")
        intra_contact = float("nan")
        target_contact = float("nan")
        pTMEnergy_val = float("nan")
        iptm = float("nan")
        plddt_binder_mean = float("nan")
        plddt_binder_min = float("nan")
        plddt_binder_max = float("nan")
        plddt_binder_std = float("nan")
        plddt_target_mean = float("nan")
        plddt_target_min = float("nan")
        pae_bb_mean = float("nan")
        pae_bt_mean = float("nan")
        pae_tb_mean = float("nan")
        pae_tt_mean = float("nan")
        pae_overall_mean = float("nan")
        pae_max = float("nan")
        pdb_path = ""
        pae_file = ""
        plddt_file = ""

        if is_top:
            print(f"\n[Rank {rank + 1}] refolding  seq={seq_str}")

            seq = jnp.array([TOKENS.index(c) for c in seq_str])

            boltz_features, boltz_writer = folder.target_only_features(
                chains=[
                    TargetChain(sequence=seq_str, use_msa=True),
                    TargetChain(sequence=target_sequence, use_msa=True),
                ]
            )

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
                recycling_steps=3,
                num_samples=6,
            )
            _, aux = evaluate_loss(metrics_loss, jax.nn.one_hot(seq, 20), key=jax.random.key(0))

            aux_dict = _merge_aux_entries(aux)

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

            if rank == 0:
                print(f"  [debug] aux keys: {sorted(aux_dict.keys())}")
                print(f"  [debug] bt source={bt_key} n={bt_n}  tb source={tb_key} n={tb_n}")

            if min_iptm_aux is not None and iptm_aux < min_iptm_aux:
                print(f"  [gate] iptm_aux={iptm_aux:.4f} < {min_iptm_aux} — skipping full predict")
                is_top = False

        if is_top:
            prediction = folder.predict(
                PSSM=jax.nn.one_hot(seq, 20),
                features=boltz_features,
                writer=boltz_writer,
                recycling_steps=3,
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

            pdb_path = f"{output_dir}/top{rank + 1}_{worker_id}.pdb"
            pae_file = f"{output_dir}/top{rank + 1}_{worker_id}_pae.npy"
            plddt_file = f"{output_dir}/top{rank + 1}_{worker_id}_plddt.csv"

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

            print(
                f"  Interface:      iptm={iptm:.4f}  bt_ipsae={bt_ipsae:.4f}  tb_ipsae={tb_ipsae:.4f}  ipsae_min={ipsae_min:.4f}  bt_iptm={bt_iptm:.4f}"
            )
            print(
                f"  Binder quality: binder_ptm={binder_ptm:.4f}  plddt_mean={plddt_binder_mean:.4f}  plddt_min={plddt_binder_min:.4f}  pae_bb={pae_bb_mean:.4f}  intra_contact={intra_contact:.4f}"
            )
            print(
                f"  PAE overview:   pae_bt={pae_bt_mean:.4f}  pae_tb={pae_tb_mean:.4f}  pae_bb={pae_bb_mean:.4f}  pae_overall={pae_overall_mean:.4f}  pae_max={pae_max:.4f}"
            )
            print(f"  Energy/contacts: pTMEnergy={pTMEnergy_val:.4f}  target_contact={target_contact:.4f}")
            print(f"  Files:  pdb={pdb_path}  pae={pae_file}  plddt={plddt_file}")

            header = (
                f">rank{rank + 1}_{worker_id}"
                f"  binder_length={binder_length}"
                f"  ranking_loss={ranking_loss_value:.4f}"
                f"  iptm={iptm:.4f}"
                f"  bt_ipsae={bt_ipsae:.4f}"
                f"  tb_ipsae={tb_ipsae:.4f}"
                f"  ipsae_min={ipsae_min:.4f}"
                f"  bt_iptm={bt_iptm:.4f}"
                f"  binder_ptm={binder_ptm:.4f}"
                f"  plddt_mean={plddt_binder_mean:.4f}"
                f"  plddt_min={plddt_binder_min:.4f}"
                f"  pae_bb={pae_bb_mean:.4f}"
                f"  pTMEnergy={pTMEnergy_val:.4f}"
                f"  intra_contact={intra_contact:.4f}"
                f"  target_contact={target_contact:.4f}"
                f"  pdb={pdb_path}"
            )
        else:
            header = (
                f">rank{rank + 1}_{worker_id}  binder_length={binder_length}  ranking_loss={ranking_loss_value:.4f}"
            )

        final_lines.append(f"{header}\n{seq_str}")

        csv_rows.append(
            {
                "worker_id": worker_id,
                "rank": rank + 1,
                "is_top": int(is_top),
                "sequence": seq_str,
                "target_sequence": target_sequence,
                "binder_length": binder_length,
                "ranking_loss": ranking_loss_value,
                "iptm_aux": iptm_aux,
                "bt_ipsae": bt_ipsae,
                "tb_ipsae": tb_ipsae,
                "ipsae_min": ipsae_min,
                "bt_iptm": bt_iptm,
                "binder_ptm": binder_ptm,
                "plddt_aux": plddt_aux,
                "bb_pae": bb_pae,
                "bt_pae_aux": bt_pae_aux,
                "tb_pae": tb_pae,
                "intra_contact": intra_contact,
                "target_contact": target_contact,
                "pTMEnergy": pTMEnergy_val,
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
                "pae_tt_mean": pae_tt_mean,
                "pae_overall_mean": pae_overall_mean,
                "pae_max": pae_max,
                "pdb": pdb_path,
                "pae_file": pae_file,
                "plddt_file": plddt_file,
            }
        )

    with open("designs.txt", "a") as f:
        if os.path.exists("designs.txt") and os.path.getsize("designs.txt") > 0:
            f.write("\n")
        f.write("\n".join(final_lines) + "\n")

    csv_path = "designs.csv"
    csv_columns = [
        "worker_id",
        "rank",
        "is_top",
        "sequence",
        "target_sequence",
        "binder_length",
        "ranking_loss",
        "iptm_aux",
        "bt_ipsae",
        "tb_ipsae",
        "ipsae_min",
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
        "pae_tt_mean",
        "pae_overall_mean",
        "pae_max",
        "pdb",
        "pae_file",
        "plddt_file",
    ]
    write_header = (not os.path.exists(csv_path)) or os.path.getsize(csv_path) == 0
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_columns)
        if write_header:
            writer.writeheader()
        writer.writerows(csv_rows)

    print(f"\n=== Run Complete ===")
    print(f"Appended {n_designs} sequences to designs.txt and designs.csv.")
    print(f"PDB files       → {output_dir}/top*_{worker_id}.pdb")
    print(f"PAE matrices    → {output_dir}/top*_{worker_id}_pae.npy")
    print(f"pLDDT per-res   → {output_dir}/top*_{worker_id}_plddt.csv")
    print(f"Worker ID: {worker_id} (for tracking this run)")

    best_loss = candidates[0][1] if candidates else None
    return {"best_ranking_loss": best_loss, "n_designs": n_designs}


# ============================
# MAIN
# ============================


def main():
    print("=== Boltz2 Binder Design (BindMaster non-interactive) ===\n")

    _check_gpu()
    print()

    # All parameters come from injected constants — no interactive prompts
    target_sequence = TARGET_SEQUENCE
    n_designs = N_DESIGNS
    top_k = TOP_K

    if MIN_LENGTH == MAX_LENGTH:
        binder_lengths = [MIN_LENGTH]
    else:
        binder_lengths = list(range(MIN_LENGTH, MAX_LENGTH + 1, LENGTH_STEP))
        if MAX_LENGTH not in binder_lengths:
            binder_lengths.append(MAX_LENGTH)

    print(f"Parameters:")
    print(
        f"  Target sequence : {target_sequence[:60]}{'...' if len(target_sequence) > 60 else ''} ({len(target_sequence)} aa)"
    )
    print(f"  Designs (Stage 1): {n_designs}")
    print(f"  Refold (TOP_K)   : {top_k}")
    print(f"  Binder lengths   : {binder_lengths}")
    print()

    _install_signal_handler(
        get_candidates_fn=lambda: _interrupt_state["candidates"],
        checkpoint_path_fn=lambda: _interrupt_state["checkpoint_path"],
    )

    summary_rows = []
    for binder_length in binder_lengths:
        output_dir = f"structures_{binder_length}aa_{n_designs}_top{top_k}"
        ckpt_path = f"checkpoint_{binder_length}aa.json"

        result = design(
            n_designs,
            top_k,
            binder_length,
            target_sequence,
            output_dir,
            checkpoint_path=ckpt_path,
        )

        summary_rows.append(
            {
                "binder_length": binder_length,
                "best_ranking_loss": result["best_ranking_loss"] if result else None,
                "n_designs": result["n_designs"] if result else n_designs,
            }
        )

    if len(binder_lengths) > 1:
        _print_length_summary(summary_rows)


if __name__ == "__main__":
    main()
