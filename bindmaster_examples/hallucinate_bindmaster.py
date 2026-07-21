import uuid
import os
import csv
import signal
import json
import sys

import gemmi
import jax
import jax.numpy as jnp
import equinox as eqx
import numpy as np

from mosaic.models.boltz2 import Boltz2
import mosaic.losses.structure_prediction as sp
from mosaic.common import TOKENS
from mosaic.losses.protein_mpnn import InverseFoldingSequenceRecovery
from mosaic.losses.transformations import ClippedLoss, NoCys
from mosaic.proteinmpnn.mpnn import load_mpnn_sol
from mosaic.structure_prediction import TargetChain
from mosaic.optimizers import batched_simplex_APGM

# Offline-only resolver for the cached target MSA (never contacts a server).
# Present when the Evaluator (binder_comparison) is installed in this venv;
# None otherwise so the template still runs standalone.
try:
    from binder_comparison.refolding.target_msa import target_msa_cache_path
except Exception:
    target_msa_cache_path = None

# ESM2 pseudolikelihood expressibility prior (guarded). Needs fair-esm +
# esm2quinox + the model weights; skips cleanly if any are missing (aarch64,
# offline without a pre-cached model) so the design still runs without it.
try:
    import esm as _fair_esm
    import esm2quinox as _esm2quinox

    from mosaic.losses.esm import ESM2PseudoLikelihood
except Exception:
    _fair_esm = None
    _esm2quinox = None
    ESM2PseudoLikelihood = None

# --- ESM2 expressibility-prior settings (edit to tune / disable) ---
ESM2_WEIGHT = 0.3  # weight of the ESM2 PLL term added to the design loss; 0.0 disables it
ESM2_MODEL = "esm2_t30_150M_UR50D"  # fair-esm model id (150M: balances signal vs per-step O(N) cost)
ESM2_CLIP = (2.0, 100.0)  # ClippedLoss bounds — guards against over-optimization into homopolymers

# --- Batched design settings ---
# Seeds optimized in parallel per GPU pass (one vmap'd batched_simplex_APGM call).
# GPU memory scales ~linearly with the batch; the ESM2 prior adds more pressure —
# drop to 2 (or disable ESM2) if you OOM on a 24 GB card.
DESIGN_BATCH_SIZE = 4


# ============================
# BINDMASTER PARAMETERS
# ============================
# All values below are injected by BindMaster Configurator.
# Edit manually to override after generation.

TARGET_SEQUENCE = "REPLACE_ME"  # target protein sequence
TARGET_PDB = ""  # path to target PDB (used as structural template; blank = predict from sequence)
N_DESIGNS = 100  # Stage 1: how many designs to generate per length
TOP_K = 5  # Stage 2: how many top designs to refold and export PDB
MIN_LENGTH = 65  # minimum binder length (aa)
MAX_LENGTH = 100  # maximum binder length (aa)
LENGTH_STEP = 5  # step between scanned lengths; set MIN=MAX for a single length
EPITOPE_IDX = None  # 0-based target-residue indices the binder must contact (hotspots); None = whole surface


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


def _load_template_chain(pdb_path: str, chain_id: str = "A") -> gemmi.Chain | None:
    """Load a gemmi Chain from a PDB file for use as structural template."""
    if not pdb_path:
        return None
    st = gemmi.read_structure(pdb_path)
    for chain in st[0]:
        if chain.name == chain_id:
            print(f"  Template loaded: {pdb_path} chain {chain_id} ({len(chain)} residues)")
            return chain
    # Fallback: use first chain
    chain = st[0][0]
    print(f"  Template loaded: {pdb_path} chain {chain.name} (requested {chain_id}, using first)")
    return chain


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


def _load_esm2_pll(model_id: str):
    """Load an ESM2 pseudolikelihood loss term (guarded).

    Returns an ESM2PseudoLikelihood, or None when fair-esm / esm2quinox / the
    model weights are unavailable, so the design still runs without the prior.
    """
    if ESM2PseudoLikelihood is None or _fair_esm is None or _esm2quinox is None:
        print("  ESM2 prior: fair-esm/esm2quinox unavailable — expressibility term OFF")
        return None
    try:
        torch_model, _ = getattr(_fair_esm.pretrained, model_id)()
        pll = ESM2PseudoLikelihood(_esm2quinox.from_torch(torch_model))
        print(f"  ESM2 prior: loaded {model_id} (expressibility term ON)")
        return pll
    except Exception as exc:
        print(f"  ESM2 prior: load failed ({exc}) — expressibility term OFF")
        return None


def design(
    n_designs: int,
    top_k: int,
    binder_length: int,
    target_sequence: str,
    output_dir: str = "structures",
    *,
    template_chain: gemmi.Chain | None = None,
    checkpoint_path=None,
    resume_from=None,
    min_ranking_loss=None,
    min_hamming=0,
    epitope_idx=None,
    ss_bias="none",
    min_iptm_aux=None,
    esm2_pll=None,
    esm2_weight=0.0,
    esm2_clip=(2.0, 100.0),
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

    # Stage-2 refold uses the target's MSA when a precomputed .a3m is cached
    # (offline-safe: this resolver never contacts a server). Binder stays MSA-free
    # and Stage-1 ranking stays MSA-free; this only affects the Stage-2 target.
    # Falls back to template/single-sequence when no cached MSA is present.
    # Mirrors the Evaluator's refold_boltz2 offline-MSA handling.
    target_msa_path = None
    if target_msa_cache_path is not None:
        try:
            _cached = target_msa_cache_path(target_sequence)
            if _cached is not None and os.path.exists(_cached):
                target_msa_path = str(_cached)
                print(f"  Target MSA (cached, offline): {target_msa_path}")
            else:
                print("  Target MSA: no cached .a3m — Stage-2 target uses template/single-seq")
        except Exception as exc:
            print(f"  Target MSA cache lookup failed ({exc}); using template/single-seq")

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

    target_tc = TargetChain(
        sequence=target_sequence,
        use_msa=False,
        template_chain=template_chain,
    )

    features, _ = folder.binder_features(
        binder_length=binder_length,
        chains=[target_tc],
    )

    model_loss = folder.build_multisample_loss(
        loss=sp_loss,
        features=features,
        recycling_steps=1,
        num_samples=1,
    )
    if esm2_pll is not None and esm2_weight > 0:
        # Clipped ESM2 pseudolikelihood: bias toward expressible sequences.
        # Composed OUTSIDE build_multisample_loss so it runs once per step (not
        # per sample); NoCys feeds it the same 20-dim binder sequence.
        model_loss = model_loss + esm2_weight * ClippedLoss(esm2_pll, esm2_clip[0], esm2_clip[1])
    loss = NoCys(model_loss)

    @eqx.filter_jit
    def evaluate_loss(loss, pssm, key):
        return loss(pssm, key=key)

    # --------------------------
    # Stage 1: optimize, rank
    # --------------------------
    def _optimize_batch(batch_size):
        """Optimize `batch_size` seeds in parallel (one GPU pass, vmap'd) through the
        3-phase simplex schedule. Returns a list of binder sequence strings.

        GPU memory scales with batch_size (each seed holds a live Boltz-2 forward
        pass, and the ESM2 prior adds more) — tune DESIGN_BATCH_SIZE, not this call.
        """
        keys = jax.random.split(jax.random.key(np.random.randint(10000000)), batch_size)
        scales = np.random.uniform(low=0.25, high=0.75, size=(batch_size, 1, 1))
        _pssm = scales * jax.vmap(lambda k: jax.random.gumbel(k, shape=(binder_length, 19)))(keys)
        x = jax.nn.softmax(_pssm, axis=-1)
        _, pssm = batched_simplex_APGM(
            loss_function=loss,
            x=x,
            n_steps=100,
            stepsize=0.2 * np.sqrt(binder_length),
            momentum=0.3,
            scale=1.00,
            logspace=False,
            max_gradient_norm=1.0,
        )
        pssm, _ = batched_simplex_APGM(
            loss_function=loss,
            x=jnp.log(pssm + 1e-5),
            n_steps=50,
            stepsize=0.5 * np.sqrt(binder_length),
            momentum=0.0,
            scale=1.25,
            logspace=True,
            max_gradient_norm=1.0,
        )
        pssm, _ = batched_simplex_APGM(
            loss_function=loss,
            x=jnp.log(pssm + 1e-5),
            n_steps=15,
            stepsize=0.5 * np.sqrt(binder_length),
            momentum=0.0,
            scale=1.4,
            logspace=True,
            max_gradient_norm=1.0,
        )
        seqs = []
        for b in range(batch_size):
            tokens = NoCys.sequence(pssm[b]).argmax(-1)
            seqs.append("".join(TOKENS[i] for i in tokens))
        return seqs

    def _rank_seq(seq_str):
        """Re-fold a designed sequence and score it for the Stage-1 relative sort."""
        seq = jnp.array([TOKENS.index(c) for c in seq_str])
        # Stage-1 ranking: MSA-free for binder AND target (free generation, cheap
        # relative sort; target anchored by the template when provided). To also use
        # the cached target MSA here (D1 toggle), mirror the Stage-2 target chain below.
        boltz_features, _ = folder.target_only_features(
            chains=[
                TargetChain(sequence=seq_str, use_msa=False),
                TargetChain(sequence=target_sequence, use_msa=False, template_chain=template_chain),
            ]
        )
        ranking_loss = folder.build_multisample_loss(
            loss=1.00 * sp.IPTMLoss() + 0.5 * sp.TargetBinderIPSAE() + 0.5 * sp.BinderTargetIPSAE(),
            features=boltz_features,
            recycling_steps=3,
            num_samples=6,
        )
        loss_value, _ = evaluate_loss(ranking_loss, jax.nn.one_hot(seq, 20), key=jax.random.key(0))
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
        n_done = 0
        while n_done < n_designs:
            this_batch = min(DESIGN_BATCH_SIZE, n_designs - n_done)
            print(f"\n[batch {n_done + 1}-{n_done + this_batch}/{n_designs}] optimizing {this_batch} seed(s) in parallel...")
            for seq_str in _optimize_batch(this_batch):
                seq_str, loss_value = _rank_seq(seq_str)
                candidates.append((seq_str, loss_value))
                print(f"  [{len(candidates)}/{n_designs}] ranking_loss={loss_value:.4f}  seq={seq_str}")
            n_done += this_batch

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

            # Stage-2 refold: binder MSA-free; target uses the cached MSA when
            # available (offline-safe via msa_path), else template/single-sequence.
            boltz_features, boltz_writer = folder.target_only_features(
                chains=[
                    TargetChain(sequence=seq_str, use_msa=False),
                    TargetChain(
                        sequence=target_sequence,
                        use_msa=template_chain is None,
                        template_chain=template_chain,
                        msa_path=target_msa_path,
                    ),
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

    # Load structural template if provided (locks target conformation)
    template_chain = _load_template_chain(TARGET_PDB) if TARGET_PDB else None
    if template_chain:
        print(f"  Using structural template: {TARGET_PDB}")
    else:
        print("  No structural template — target predicted from sequence only")

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

    # Load the ESM2 expressibility prior once (guarded); skipped if unavailable.
    esm2_pll = _load_esm2_pll(ESM2_MODEL) if ESM2_WEIGHT > 0 else None

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
            template_chain=template_chain,
            checkpoint_path=ckpt_path,
            epitope_idx=EPITOPE_IDX,
            esm2_pll=esm2_pll,
            esm2_weight=ESM2_WEIGHT,
            esm2_clip=ESM2_CLIP,
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
