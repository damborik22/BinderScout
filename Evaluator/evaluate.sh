#!/usr/bin/env bash
# BinderScout Evaluator — run a full evaluation
#
# Usage:
#   bash evaluate.sh --sequences sequences.fasta \
#                    --target-seq "MGFQKFSPF..." \
#                    --output ./results
#
# Required:
#   --sequences    path to FASTA (or CSV / one-per-line) with binder sequences
#   --target-seq   full target amino acid sequence (for complex assembly)
#   --output       output directory
#
# Optional:
#   --allow-no-msa         proceed even if the shared target MSA cannot be fetched.
#                          Default: abort. An engine folding single-sequence while the
#                          others use an MSA produces scores that are NOT comparable,
#                          and consensus_iptm_mean averages across engines.
#   --skip-boltz2          skip Boltz-2 refolding (use existing boltz2_results.csv)
#   --skip-af3             skip AF3 refolding (default: auto-detect binder-eval-af3 env)
#   --af3-env ENV          conda env for AF3 (default: binder-eval-af3)
#   --skip-esmfold2        skip ESMFold2 refolding (default: auto-detect binder-eval-esmfold2 env)
#   --esmfold2-env ENV     conda env for ESMFold2 (default: binder-eval-esmfold2)
#   --esmfold2-model V     ESMFold2 checkpoint: full | fast (default: full)
#   --skip-soluprot        skip SoluProt solubility screen (default: auto-detect binder-eval-soluprot env)
#   --soluprot-env ENV     conda env for SoluProt (default: binder-eval-soluprot)
#   --soluprot-threshold N pass threshold for soluprot_score (default: 0.5; paper value)
#   --skip-tmprot          skip TmProt melting-temperature screen (default: auto-detect binder-eval-tmprot env)
#   --tmprot-env ENV       conda env for TmProt (default: binder-eval-tmprot)
#   --tmprot-threshold N   Tm (°C) at or above which a design is flagged thermostable
#                          (default: 60.0). Advisory only -- never drops or re-ranks.
#   --soluprot-filter      drop sequences scoring below the threshold from FASTA BEFORE
#                          refolding — saves GPU time on designs we wouldn't pursue.
#                          Off by default; the score still lands in the report either way.
#   --concurrent           run the refold engines SIMULTANEOUSLY instead of one after
#                          another, with staggered starts. Requires the CUDA MPS ceiling
#                          (tools/gpu_mem_guard.sh) and refuses to run without it, because
#                          concurrency without a hard per-client cap is exactly what took
#                          BM5 down. Per-engine output goes to $OUTPUT/refold_<engine>.log.
#   --stagger N            seconds between concurrent engine starts (default: 30). The
#                          measured peak is the simultaneous COLD START -- all engines
#                          preallocating at once -- not steady state.
#   --gpu-cap-boltz2 N     per-engine GPU ceiling, e.g. 24G (default: 24G)
#   --gpu-cap-af3 N        default: 12G
#   --gpu-cap-esmfold2 N   default: 24G
#   --no-gpu-guard         do NOT apply the MPS ceiling (unsafe on unified memory)
#   --primary-engine ENG   primary ranking engine: boltz | af3 | esmfold2 (default: boltz)
#   --min-engines N        how many independent engines must have refolded a design for it
#                          to be eligible for the ranking (default 3 = all of Boltz-2 / AF3 /
#                          ESMFold2; floor 2). Designs below the gate are ranked LAST, not
#                          dropped. On a host without AF3 — the common case, it needs >100 GB
#                          of GPU memory — only two engines run and the default gate fails
#                          EVERY design, so this script says so up front and names the flag.
#                          The gate is never lowered automatically: that would make two
#                          operators with the same designs produce different rankings
#                          depending on what happens to be installed.
#   --epitope-residues L   intended hotspot residues (e.g. '15,18,232,263' or 'A15,A18'). Computes
#                          epitope_match_fraction INLINE in the report from each design's refolded
#                          structure (selectivity signal for multi-pocket targets, e.g. ApoE4). Cheap.
#   --with-affinity        opt-in: after the report, run the |dG/dSASA| affinity ranking (Rosetta
#                          InterfaceAnalyzer, in the BindCraft env) on the top-20 structures, then
#                          re-generate the report with the affinity_energy_density column. Off by default.
#   --bindcraft-env ENV    conda env with PyRosetta for --with-affinity (default: BindCraft)
#   --monomer-dir DIR      opt-in: directory of binder-ALONE refolded structures (named by binder_id).
#                          Runs the context-dependent-fold check vs the in-complex structures and
#                          re-generates the report with the fold_robust column. Off by default.
#   --resume               resume interrupted run

set -euo pipefail

# Initialise conda — prefer local standalone install, then system locations
_BINDERSCOUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for _conda_sh in \
    "${_BINDERSCOUT_DIR}/conda/etc/profile.d/conda.sh" \
    "${HOME}/miniforge3/etc/profile.d/conda.sh" \
    "${HOME}/mambaforge/etc/profile.d/conda.sh" \
    "${HOME}/miniconda3/etc/profile.d/conda.sh" \
    "${HOME}/anaconda3/etc/profile.d/conda.sh" \
    "/opt/conda/etc/profile.d/conda.sh" \
    "/opt/miniforge3/etc/profile.d/conda.sh"; do
    # shellcheck source=/dev/null
    [[ -f "$_conda_sh" ]] && { source "$_conda_sh"; break; }
done

# aarch64/Blackwell: PyTorch CUDA compilation target.
#
# `export JAX_PLATFORMS=cpu` used to live here (added 2026-04-07 in 3cd03c5 as an
# aarch64 "platform guard", copied from PXDesign where JAX-on-sm_121 genuinely
# failed at the time).  It was WRONG for the Evaluator and silently broke it for
# ~4.5 months: JAX_PLATFORMS=cpu hides the GPU from every JAX child, so
#   * Boltz-2 ran on CPU -- correct numbers, ~2.7x slower, and it says nothing;
#   * AF3 died on EVERY binder with "Unknown backend: 'gpu' requested, but no
#     platforms that are instances of gpu are present", wrote empty rows, and
#     still exited 0 -- silently removing a whole engine from consensus_iptm_mean
#     and from the >=3-engine gate.
# Measured 2026-08-20 on BM5: with it unset both engines report ['gpu'] and fold
# correctly (AF3 iptm 0.8900, Boltz-2 17.2 GiB on-GPU).  Do not re-add it.
# A machine that genuinely cannot run JAX on GPU can still export it externally;
# evaluate.sh inherits the environment.
if [[ "$(uname -m)" == "aarch64" ]]; then
    export TORCH_CUDA_ARCH_LIST="12.0"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MOSAIC_VENV_FILE="$SCRIPT_DIR/envs/mosaic_venv_path"

SEQUENCES=""
TARGET_SEQ=""
OUTPUT=""
ALLOW_NO_MSA=${BINDERSCOUT_ALLOW_NO_MSA:-0}
SKIP_BOLTZ2=0
SKIP_AF3=0
AF3_ENV="binder-eval-af3"
SKIP_ESMFOLD2=0
ESMFOLD2_ENV="binder-eval-esmfold2"
ESMFOLD2_MODEL="full"
SKIP_SOLUPROT=0
SOLUPROT_ENV="binder-eval-soluprot"
SOLUPROT_THRESHOLD=0.5
SOLUPROT_FILTER=0
# TmProt: sequence-only melting-temperature screen. Deliberately has NO filter
# mode, unlike SoluProt -- Tm predictors are out of domain on hyperstable de
# novo miniproteins, so the column is advisory and must never drop a design.
SKIP_TMPROT=0
TMPROT_ENV="binder-eval-tmprot"
TMPROT_THRESHOLD=60.0
PRIMARY_ENGINE="boltz"
CONCURRENT=0
STAGGER=${BINDERSCOUT_STAGGER_S:-30}
GPU_CAP_BOLTZ2=${BINDERSCOUT_GPU_CAP_BOLTZ2:-24G}
GPU_CAP_AF3=${BINDERSCOUT_GPU_CAP_AF3:-12G}
GPU_CAP_ESMFOLD2=${BINDERSCOUT_GPU_CAP_ESMFOLD2:-24G}
USE_GPU_GUARD=1
MIN_ENGINES=""          # empty = let binder-compare apply its own default (3)
EPITOPE_RESIDUES=""
WITH_AFFINITY=0
BINDCRAFT_ENV="BindCraft"
MONOMER_DIR=""
RESUME=0

# --- parse arguments -------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --sequences)      SEQUENCES="$2";    shift 2 ;;
        --target-seq)     TARGET_SEQ="$2";   shift 2 ;;
        --output|-o)      OUTPUT="$2";       shift 2 ;;
        --allow-no-msa)   ALLOW_NO_MSA=1;    shift ;;
        --skip-boltz2)    SKIP_BOLTZ2=1;     shift ;;
        --skip-af3)       SKIP_AF3=1;        shift ;;
        --af3-env)        AF3_ENV="$2";      shift 2 ;;
        --skip-esmfold2)  SKIP_ESMFOLD2=1;   shift ;;
        --esmfold2-env)   ESMFOLD2_ENV="$2"; shift 2 ;;
        --esmfold2-model) ESMFOLD2_MODEL="$2"; shift 2 ;;
        --skip-soluprot)     SKIP_SOLUPROT=1;          shift ;;
        --soluprot-env)      SOLUPROT_ENV="$2";        shift 2 ;;
        --soluprot-threshold) SOLUPROT_THRESHOLD="$2"; shift 2 ;;
        --soluprot-filter)   SOLUPROT_FILTER=1;        shift ;;
        --skip-tmprot)       SKIP_TMPROT=1;            shift ;;
        --tmprot-env)        TMPROT_ENV="$2";          shift 2 ;;
        --tmprot-threshold)  TMPROT_THRESHOLD="$2";    shift 2 ;;
        --concurrent)         CONCURRENT=1;              shift ;;
        --stagger)            STAGGER="$2";              shift 2 ;;
        --gpu-cap-boltz2)     GPU_CAP_BOLTZ2="$2";       shift 2 ;;
        --gpu-cap-af3)        GPU_CAP_AF3="$2";          shift 2 ;;
        --gpu-cap-esmfold2)   GPU_CAP_ESMFOLD2="$2";     shift 2 ;;
        --no-gpu-guard)       USE_GPU_GUARD=0;           shift ;;
        --primary-engine)
            PRIMARY_ENGINE="$2"
            case "$PRIMARY_ENGINE" in
                boltz|af3|esmfold2) ;;
                *) echo "Error: --primary-engine must be one of: boltz, af3, esmfold2 (got '$PRIMARY_ENGINE')" >&2; exit 1 ;;
            esac
            shift 2 ;;
        --min-engines)
            MIN_ENGINES="$2"
            [[ "$MIN_ENGINES" =~ ^[0-9]+$ ]] || {
                echo "Error: --min-engines takes an integer (got '$MIN_ENGINES')" >&2; exit 1; }
            (( MIN_ENGINES >= 2 )) || {
                echo "Error: --min-engines floor is 2 — a cross-engine consensus needs at least two engines." >&2
                exit 1; }
            shift 2 ;;
        --epitope-residues) EPITOPE_RESIDUES="$2"; shift 2 ;;
        --with-affinity)    WITH_AFFINITY=1;        shift ;;
        --bindcraft-env)    BINDCRAFT_ENV="$2";     shift 2 ;;
        --monomer-dir)      MONOMER_DIR="$2";       shift 2 ;;
        --resume)         RESUME=1;          shift ;;
        -h|--help)
            sed -n '2,/^set /p' "$0" | grep '^#' | sed 's/^# \?//'
            exit 0 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# --- validate ---------------------------------------------------------------
[[ -z "$SEQUENCES" ]]  && { echo "Error: --sequences required"; exit 1; }
[[ -z "$TARGET_SEQ" ]] && { echo "Error: --target-seq required"; exit 1; }
[[ -z "$OUTPUT" ]]     && { echo "Error: --output required"; exit 1; }
[[ -f "$SEQUENCES" ]]  || { echo "Error: sequences file not found: $SEQUENCES"; exit 1; }

# --- locate Mosaic venv (written by install.sh) ----------------------------
# Resolved AFTER argument parsing, and only when Boltz-2 will actually run. It used to
# be resolved at the top, unconditionally, so `evaluate.sh --help` could not print the
# help without a Mosaic install, and an AF3 + ESMFold2 evaluation (`--skip-boltz2`) was
# refused on a host that legitimately has no Mosaic.
if [[ $SKIP_BOLTZ2 -eq 0 ]]; then
    if [[ -f "$MOSAIC_VENV_FILE" ]]; then
        MOSAIC_VENV="$(cat "$MOSAIC_VENV_FILE")"
    else
        echo "Error: Mosaic venv path not found — Boltz-2 refolding runs in the Mosaic venv." >&2
        echo "       Run 'binderscout install --tool mosaic', or pass --skip-boltz2." >&2
        exit 1
    fi
    [[ -f "$MOSAIC_VENV/bin/binder-compare" ]] || {
        echo "Error: binder-compare not found in $MOSAIC_VENV. Run bash install.sh again," >&2
        echo "       or pass --skip-boltz2 to evaluate without Boltz-2." >&2
        exit 1
    }
fi

mkdir -p "$OUTPUT"
SEQUENCES="$(realpath "$SEQUENCES")"
OUTPUT="$(realpath "$OUTPUT")"

echo "=== BinderScout Evaluator ==="
echo "Sequences : $SEQUENCES"
echo "Output    : $OUTPUT"
echo ""

# Auto-detect AF3 availability unless user skipped it
if [[ $SKIP_AF3 -eq 0 ]]; then
    if ! conda env list 2>/dev/null | awk '{print $1}' | grep -qx "${AF3_ENV}"; then
        echo "[note] conda env '${AF3_ENV}' not found — AF3 refolding will be skipped."
        echo "        (install with 'binderscout install --tool af3'; runs on 24 GB GPUs — see Evaluator/envs/binder-eval-af3.yml)"
        echo ""
        SKIP_AF3=1
    fi
fi

# Auto-detect ESMFold2 availability unless user skipped it
if [[ $SKIP_ESMFOLD2 -eq 0 ]]; then
    if ! conda env list 2>/dev/null | awk '{print $1}' | grep -qx "${ESMFOLD2_ENV}"; then
        echo "[note] conda env '${ESMFOLD2_ENV}' not found — ESMFold2 refolding will be skipped."
        echo "        (install with: binderscout install --tool esmfold2; see Evaluator/envs/binder-eval-esmfold2.yml)"
        echo ""
        SKIP_ESMFOLD2=1
    fi
fi

# Auto-detect SoluProt availability unless user skipped it
if [[ $SKIP_SOLUPROT -eq 0 ]]; then
    if ! conda env list 2>/dev/null | awk '{print $1}' | grep -qx "${SOLUPROT_ENV}"; then
        echo "[note] conda env '${SOLUPROT_ENV}' not found — SoluProt solubility screen will be skipped."
        echo "        (install with: binderscout install --tool soluprot)"
        echo ""
        SKIP_SOLUPROT=1
    fi
fi

# Auto-detect TmProt availability unless the user skipped it
if [[ $SKIP_TMPROT -eq 0 ]]; then
    if ! conda env list 2>/dev/null | awk '{print $1}' | grep -qx "${TMPROT_ENV}"; then
        echo "[note] conda env '${TMPROT_ENV}' not found — TmProt melting-temperature screen will be skipped."
        echo "        (install with: binderscout install --tool tmprot)"
        echo ""
        SKIP_TMPROT=1
    fi
fi

# --- Step 0.6: TmProt melting-temperature screen ---------------------------
# Sequence-only, no GPU, and ADVISORY ONLY. Unlike SoluProt there is no filter
# mode and there must not be one: Tm predictors are trained on natural proteins
# and are out of domain on the hyperstable de novo miniproteins this pipeline
# produces (2.0 assessment item D1 -- "proceed as a screen, never a ranking
# term"). The column lands in the report; it never drops a design and never
# enters rank_designs().
#
# binder-compare is installed inside ${TMPROT_ENV}, so this runs there directly
# rather than shelling out the way SoluProt has to.
if [[ $SKIP_TMPROT -eq 0 ]]; then
    echo "[step ${STEP}/${N_STEPS}] TmProt screen       (env: ${TMPROT_ENV}, thermostable >= ${TMPROT_THRESHOLD} C)..."
    if conda run -n "${TMPROT_ENV}" binder-compare screen-tmprot \
            --sequences "$SEQUENCES" \
            -o          "$TMPROT_CSV" \
            --threshold "$TMPROT_THRESHOLD"; then
        TMPROT_OK=1
    else
        TMPROT_OK=0
        # Advisory screen: never take the evaluation down with it. There is no
        # --tmprot-filter, so unlike SoluProt nothing about the refold pool
        # changes when this fails -- only a report column goes missing.
        echo "[tmprot] WARNING: screen failed - continuing WITHOUT the Tm column." >&2
    fi
    STEP=$(( STEP + 1 ))
    echo ""
fi

# --- Cross-engine gate vs. the engines that will actually run ---------------
# The ranking gates on how many INDEPENDENT engines refolded each design (default 3).
# AF3 is opt-in because its weights are DeepMind-gated, not because it is large:
# measured (docs/data/gpu_benchmark_2026-09-18/) it is the CHEAPEST engine here,
# 2.3-5.2 GB flat from 150 to 900 tokens. Boltz-2 is the memory-dominant one
# (44 GB at 600 tokens, 140 GB at 900), and ESMFold2 has a ~14 GB floor already
# at 150 tokens. So on most hosts only Boltz-2 + ESMFold2 run and
# every design fails a gate of 3 — ranked last, with an empty top of the list. The
# report warns after the fact; by then the GPU time is already spent, so say it here.
# Deliberately NOT auto-lowered: the gate is part of what the ranking means, and
# silently deriving it from the local install would make two operators with the same
# designs produce different rankings.
# Arithmetic ASSIGNMENT, not `(( n++ ))`: post-increment evaluates to the OLD value, so
# the first increment from 0 returns 0 — false — and `set -e` kills the script here.
_N_ENGINES=0
[[ $SKIP_BOLTZ2   -eq 0 ]] && _N_ENGINES=$(( _N_ENGINES + 1 ))
[[ $SKIP_AF3      -eq 0 ]] && _N_ENGINES=$(( _N_ENGINES + 1 ))
[[ $SKIP_ESMFOLD2 -eq 0 ]] && _N_ENGINES=$(( _N_ENGINES + 1 ))
if [[ -z "$MIN_ENGINES" ]] && (( _N_ENGINES < 3 )); then
    echo "[warn] ${_N_ENGINES} refold engine(s) will run, but the cross-engine gate defaults to 3."
    echo "       Every design will fail the gate and be ranked last, leaving no ranked shortlist."
    if (( _N_ENGINES >= 2 )); then
        echo "       To rank on the engines you have, re-run with:  --min-engines ${_N_ENGINES}"
    else
        echo "       A cross-engine ranking needs at least 2 engines; install another refold"
        echo "       engine (binderscout install --tool esmfold2) before trusting the ranking."
    fi
    echo ""
elif [[ -n "$MIN_ENGINES" ]] && (( _N_ENGINES < MIN_ENGINES )); then
    echo "[warn] --min-engines ${MIN_ENGINES} was requested but only ${_N_ENGINES} engine(s) will run —"
    echo "       every design will fail the gate."
    echo ""
fi

# --- Step 0: Normalise sequences to FASTA ----------------------------------
FASTA="$OUTPUT/sequences.fasta"
echo "[step 0] Parsing sequences → $FASTA"
conda run -n binder-eval binder-compare parse-seqs \
    --input  "$SEQUENCES" \
    --output "$FASTA"
SEQUENCES="$FASTA"

# --- Step 1: Boltz-2 refolding ---------------------------------------------
BOLTZ2_CSV="$OUTPUT/boltz2_results.csv"
AF3_CSV="$OUTPUT/af3_results.csv"
ESMFOLD2_CSV="$OUTPUT/esmfold2_results.csv"
SOLUPROT_CSV="$OUTPUT/soluprot_results.csv"
TMPROT_CSV="$OUTPUT/tmprot_results.csv"
TMPROT_OK=0
SOLUPROT_OK=1   # cleared if the optional screen fails; see Step 0.5

# Step counter: 1 (report) + 1 per engine not skipped + 1 each if SoluProt / TmProt ran
N_STEPS=1  # report
[[ $SKIP_TMPROT -eq 0 ]] && (( N_STEPS++ ))
if [[ $CONCURRENT -eq 1 ]]; then
    (( N_STEPS++ ))            # the engines run as a single concurrent step
else
    [[ $SKIP_BOLTZ2 -eq 0 ]]   && (( N_STEPS++ ))
    [[ $SKIP_AF3 -eq 0 ]]      && (( N_STEPS++ ))
    [[ $SKIP_ESMFOLD2 -eq 0 ]] && (( N_STEPS++ ))
fi
[[ $SKIP_SOLUPROT -eq 0 ]] && (( N_STEPS++ ))
STEP=1

# --- Step 0.5: SoluProt solubility screen (optional, runs before refolding) ─
# Runs before any refold engine so --soluprot-filter can drop sub-threshold
# sequences and save GPU time. The score lands in the report either way.
if [[ $SKIP_SOLUPROT -eq 0 ]]; then
    echo "[step ${STEP}/${N_STEPS}] SoluProt screen     (soluprot env: ${SOLUPROT_ENV}, threshold: ${SOLUPROT_THRESHOLD})..."
    # binder-compare runs in binder-eval (py3.10); SoluProt's soluprot.py runs in
    # the py3.7 ${SOLUPROT_ENV} via $SOLUPROT_PYTHON. The two envs are mutually
    # exclusive — SoluProt needs scikit-learn 0.20.x / py3.7, binder-comparison
    # needs py3.10+ — so we cannot run binder-compare inside ${SOLUPROT_ENV}.
    SOLUPROT_PYTHON="$(conda run -n "${SOLUPROT_ENV}" python -c 'import sys; print(sys.executable)' 2>/dev/null)"
    export SOLUPROT_PYTHON
    # SoluProt is an OPTIONAL pre-screen, so a failure must not take the whole
    # evaluation down with it (it did: a missing USEARCH binary aborted the run
    # before any refold engine started).  The one exception is --soluprot-filter:
    # that flag changes WHICH sequences get refolded, so silently continuing
    # would produce a different pool than was asked for.
    if conda run -n binder-eval binder-compare filter-soluprot \
            --sequences "$SEQUENCES" \
            -o          "$SOLUPROT_CSV" \
            --threshold "$SOLUPROT_THRESHOLD"; then
        SOLUPROT_OK=1
    else
        SOLUPROT_OK=0
        if [[ $SOLUPROT_FILTER -eq 1 ]]; then
            echo "Error: --soluprot-filter was requested but the SoluProt screen failed." >&2
            echo "       Continuing would refold a DIFFERENT pool than you asked for." >&2
            exit 1
        fi
        echo "[soluprot] WARNING: screen failed — continuing WITHOUT the solubility" >&2
        echo "[soluprot]          column. Refolding is unaffected. See the error above." >&2
    fi

    if [[ $SOLUPROT_FILTER -eq 1 ]]; then
        # Hard filter: rewrite the FASTA, keeping only sequences whose
        # soluprot_passes==1 row in the CSV. Saves refold time downstream.
        FILTERED_FASTA="$OUTPUT/sequences.soluble.fasta"
        conda run -n binder-eval python - "$SOLUPROT_CSV" "$SEQUENCES" "$FILTERED_FASTA" <<'PY'
import csv, sys
csv_path, fasta_in, fasta_out = sys.argv[1], sys.argv[2], sys.argv[3]
soluble: set[str] = set()
with open(csv_path) as fh:
    for row in csv.DictReader(fh):
        if row.get("soluprot_passes") in ("1", "True", "true"):
            seq = (row.get("sequence") or "").strip().upper()
            if seq:
                soluble.add(seq)
n_in = n_kept = 0
header, body = None, []
def flush(out):
    global n_in, n_kept
    if header is None:
        return
    n_in += 1
    seq = "".join(body).strip().upper()
    if seq in soluble:
        out.write(header)
        for line in body:
            out.write(line)
        n_kept += 1
with open(fasta_in) as fh_in, open(fasta_out, "w") as fh_out:
    for line in fh_in:
        if line.startswith(">"):
            flush(fh_out)
            header = line
            body = []
        else:
            body.append(line)
    flush(fh_out)
print(f"[soluprot-filter] kept {n_kept} of {n_in} sequences (threshold {soluble and 'configured' or 'n/a'})", file=sys.stderr)
PY
        SEQUENCES="$FILTERED_FASTA"
        echo "[soluprot-filter] downstream refolding will run on $SEQUENCES"
    fi
    (( STEP++ ))
fi

# --- Step 0.9: pre-warm the shared target MSA ──────────────────────────────
# Fetch ONCE, before any engine loads a model, so all three read the same cached
# a3m. Each engine also enforces this itself, so correctness does not depend on
# this step -- but without it a cold-cache failure surfaces only after the first
# engine has loaded its weights, which on AF3 is minutes of GPU time.
if [[ $SKIP_BOLTZ2 -eq 0 || $SKIP_AF3 -eq 0 || $SKIP_ESMFOLD2 -eq 0 ]]; then
    echo "[msa] Pre-warming shared target MSA cache..."
    if conda run -n binder-eval python -m binder_comparison.refolding.target_msa \
            --target-seq "$TARGET_SEQ" >/dev/null 2>&1; then
        echo "[msa] Target MSA ready — all engines will read the same cached a3m."
    elif [[ $ALLOW_NO_MSA -eq 1 ]]; then
        echo "[msa] WARNING: could not obtain the target MSA; --allow-no-msa given, so engines"
        echo "[msa]          will fold the target single-sequence. Their scores are NOT directly"
        echo "[msa]          comparable to an MSA run, and this is recorded in target_msa_mode.json."
        export BINDERSCOUT_ALLOW_NO_MSA=1
    else
        echo "Error: could not obtain the target MSA, and engines would otherwise disagree on" >&2
        echo "       whether they used one. The MSA drives target fold confidence, so an" >&2
        echo "       MSA-less engine is systematically penalised and silently drags" >&2
        echo "       consensus_iptm_mean down." >&2
        echo "" >&2
        echo "  Pre-warm once (also works for copying to an air-gapped node):" >&2
        echo "    conda run -n binder-eval python -m binder_comparison.refolding.target_msa \\" >&2
        echo "        --target-seq '<TARGET_SEQ>'" >&2
        echo "" >&2
        echo "  Or proceed single-sequence on every engine (recorded in the report):" >&2
        echo "    $0 --allow-no-msa ...   (or BINDERSCOUT_ALLOW_NO_MSA=1)" >&2
        exit 2
    fi
fi

# --- GPU memory ceiling ----------------------------------------------------
# On unified-memory hosts (GB10 / DGX Spark) the GPU pool IS system RAM:
# cudaMemGetInfo total == SC_PHYS_PAGES == 121.7 GiB. An engine sizing itself as a
# fraction of "device total" therefore reserves a fraction of the WHOLE MACHINE and
# starves the kernel -- that is what hard-rebooted BM5 on 2026-08-18.
#
# Each engine also computes its own absolute-GiB fraction
# (binder_comparison.refolding.memory_policy), but that is COOPERATIVE. The hard
# ceiling is a CUDA MPS per-client limit; cgroups do not contain NVIDIA allocations
# on driver 580.x (measured). See docs/PLAN_bm5_unified_memory.md.
GUARD="$SCRIPT_DIR/../tools/gpu_mem_guard.sh"
MPS_ACTIVE=0
MPS_WE_STARTED=0

gpu_guard_up () {
    [[ $USE_GPU_GUARD -eq 1 ]] || { echo "[gpu-guard] disabled by --no-gpu-guard"; return 1; }
    [[ -x "$GUARD" ]] || { echo "[gpu-guard] $GUARD not executable — cooperative caps only" >&2; return 1; }
    if "$GUARD" is-up 2>/dev/null; then
        MPS_ACTIVE=1; echo "[gpu-guard] MPS already running — reusing it"; return 0
    fi
    if "$GUARD" start "$GPU_CAP_BOLTZ2" >/dev/null 2>&1 && "$GUARD" is-up 2>/dev/null; then
        MPS_ACTIVE=1; MPS_WE_STARTED=1
        echo "[gpu-guard] MPS started (fallback cap $GPU_CAP_BOLTZ2; each engine sets its own)"
        return 0
    fi
    echo "[gpu-guard] WARNING: could not start MPS — no hard memory ceiling this run." >&2
    return 1
}
gpu_guard_down () { if [[ $MPS_WE_STARTED -eq 1 ]]; then "$GUARD" stop >/dev/null 2>&1 || true; fi; }
# EXIT alone is not enough: a SIGTERM (timeout, Ctrl-C, a scheduler) can leave the MPS
# daemon running and holding machine-wide state. Re-raise as an exit so EXIT fires.
trap gpu_guard_down EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Emit the per-client cap as an env assignment, or nothing when MPS is not active.
cap_env () { if [[ $MPS_ACTIVE -eq 1 ]]; then printf 'CUDA_MPS_PINNED_DEVICE_MEM_LIMIT=0=%s' "$1"; fi; }

gpu_guard_up || true

# --- engine definitions (one place; sequential and concurrent both use these) --
# shellcheck disable=SC2046  # cap_env deliberately expands to 0 or 1 words
engine_boltz2 () {
    local f=""; [[ $RESUME -eq 1 ]] && f="--resume"
    env $(cap_env "$GPU_CAP_BOLTZ2") "$MOSAIC_VENV/bin/binder-compare" refold-boltz2 \
        --sequences "$SEQUENCES" --target-seq "$TARGET_SEQ" -o "$BOLTZ2_CSV" $f
}
# shellcheck disable=SC2046
engine_af3 () {
    local f=""; [[ $RESUME -eq 1 ]] && f="--resume"
    env $(cap_env "$GPU_CAP_AF3") conda run -n "${AF3_ENV}" binder-compare refold-af3 \
        --sequences "$SEQUENCES" --target-seq "$TARGET_SEQ" -o "$AF3_CSV" \
        --output-dir "$OUTPUT/refold_af3" $f
}
# shellcheck disable=SC2046
engine_esmfold2 () {
    local f=""; [[ $RESUME -eq 1 ]] && f="--resume"
    env $(cap_env "$GPU_CAP_ESMFOLD2") conda run -n "${ESMFOLD2_ENV}" binder-compare refold-esmfold2 \
        --sequences "$SEQUENCES" --target-seq "$TARGET_SEQ" -o "$ESMFOLD2_CSV" \
        --output-dir "$OUTPUT/refold_esmfold2" --model "${ESMFOLD2_MODEL}" $f
}

# --- engine result guards ---------------------------------------------------
# 2026-09-16 ESMFold2 died on Clara with a TypeError from an unpinned model
# revision, wrote 0 rows, and evaluate.sh printed REFOLD_DONE and exited 0 -- an
# entire engine contributing nothing to a >=3-engine gate, invisibly. An engine
# that exits 0 and writes nothing is the same failure wearing a success code
# (cf. the AF3 empty-rows incident of 2026-08-21), so rc alone is not enough:
# the CSV must actually gain rows.
csv_rows () { if [[ -f "$1" ]]; then tail -n +2 "$1" | wc -l; else echo 0; fi; }

engine_csv () {
    case "$1" in
        boltz2)   echo "$BOLTZ2_CSV" ;;
        af3)      echo "$AF3_CSV" ;;
        esmfold2) echo "$ESMFOLD2_CSV" ;;
        *)        echo "" ;;
    esac
}

# $1=label  $2=csv  $3=rows before  $4=rc
check_engine_rows () {
    local name=$1 csv=$2 before=$3 rc=$4 after
    after=$(csv_rows "$csv")
    if [[ $rc -ne 0 ]]; then
        echo "Error: $name refolding failed (rc=$rc). Refusing to report a partial pool." >&2
        return 1
    fi
    if [[ "$after" -le "$before" ]]; then
        echo "Error: $name exited 0 but wrote no new rows to $csv ($before -> $after)." >&2
        echo "       A missing engine silently breaks the cross-engine gate -- aborting." >&2
        return 1
    fi
    echo "    [$name] ok -- $((after - before)) new row(s)"
    return 0
}

# Sequential wrapper. `"$fn"; rc=$?` would abort under `set -e` before the
# message could be printed, so the call is guarded by an if.
run_engine_checked () {   # $1=label  $2=fn  $3=csv
    local name=$1 fn=$2 csv=$3 before rc
    before=$(csv_rows "$csv")
    if "$fn"; then rc=0; else rc=$?; fi
    check_engine_rows "$name" "$csv" "$before" "$rc" || exit 1
}

if [[ $SKIP_BOLTZ2 -eq 1 && ! -f "$BOLTZ2_CSV" ]]; then
    echo "Error: --skip-boltz2 given but $BOLTZ2_CSV not found"; exit 1
fi

if [[ $CONCURRENT -eq 1 ]]; then
    # Concurrency without a hard per-client ceiling is precisely the configuration
    # that took this box down. Refuse rather than warn.
    if [[ $MPS_ACTIVE -ne 1 ]]; then
        echo "Error: --concurrent requires the CUDA MPS ceiling, which is not active." >&2
        echo "       Fix the guard ($GUARD verify) or drop --concurrent." >&2
        exit 2
    fi
    echo "[step ${STEP}/${N_STEPS}] Refolding — ${STAGGER}s staggered starts, caps ${GPU_CAP_BOLTZ2}/${GPU_CAP_AF3}/${GPU_CAP_ESMFOLD2}"
    # Stagger exists because the measured peak is the simultaneous COLD START -- all
    # engines preallocating at once -- not steady state. On 2026-08-20 a simultaneous
    # launch peaked at 56.2 GiB and logged one NVRM NV_ERR_NO_MEMORY; 40 s later usage
    # had fallen to 37.9 GiB. Serialising the startup costs nothing, because the
    # engines do not finish together anyway.
    E_PIDS=(); E_NAMES=(); E_BEFORE=(); DELAY=0
    launch_engine () {
        local name=$1 fn=$2
        local log="$OUTPUT/refold_${name}.log"
        E_BEFORE+=("$(csv_rows "$(engine_csv "$name")")")
        ( sleep "$DELAY"; "$fn" ) > "$log" 2>&1 &
        E_PIDS+=("$!"); E_NAMES+=("$name")
        echo "    [$name] queued at +${DELAY}s → $log"
        DELAY=$(( DELAY + STAGGER ))
    }
    [[ $SKIP_BOLTZ2 -eq 0 ]]   && launch_engine boltz2   engine_boltz2
    [[ $SKIP_AF3 -eq 0 ]]      && launch_engine af3      engine_af3
    [[ $SKIP_ESMFOLD2 -eq 0 ]] && launch_engine esmfold2 engine_esmfold2

    ENGINE_FAIL=0
    for i in "${!E_PIDS[@]}"; do
        if wait "${E_PIDS[$i]}"; then rc=0; else rc=$?; fi
        if ! check_engine_rows "${E_NAMES[$i]}" \
                "$(engine_csv "${E_NAMES[$i]}")" "${E_BEFORE[$i]}" "$rc"; then
            echo "    [${E_NAMES[$i]}] last 15 lines:" >&2
            tail -15 "$OUTPUT/refold_${E_NAMES[$i]}.log" | sed 's/^/      /' >&2
            ENGINE_FAIL=1
        fi
    done
    [[ $ENGINE_FAIL -eq 0 ]] || { echo "Error: at least one refold engine failed." >&2; exit 1; }
    (( STEP++ ))
else
    if [[ $SKIP_BOLTZ2 -eq 1 ]]; then
        echo "[step ${STEP}/${N_STEPS}] Boltz-2 refolding — skipped (using existing $BOLTZ2_CSV)"
    else
        echo "[step ${STEP}/${N_STEPS}] Boltz-2 refolding  (Mosaic venv, cap ${GPU_CAP_BOLTZ2})..."
        run_engine_checked "Boltz-2" engine_boltz2 "$BOLTZ2_CSV"
    fi
    (( STEP++ ))

    if [[ $SKIP_AF3 -eq 0 ]]; then
        echo "[step ${STEP}/${N_STEPS}] AF3 refolding       (conda env: ${AF3_ENV}, cap ${GPU_CAP_AF3})..."
        run_engine_checked "AF3" engine_af3 "$AF3_CSV"
        (( STEP++ ))
    fi

    if [[ $SKIP_ESMFOLD2 -eq 0 ]]; then
        echo "[step ${STEP}/${N_STEPS}] ESMFold2 refolding  (conda env: ${ESMFOLD2_ENV}, cap ${GPU_CAP_ESMFOLD2})..."
        run_engine_checked "ESMFold2" engine_esmfold2 "$ESMFOLD2_CSV"
        (( STEP++ ))
    fi
fi

# --- Report ----------------------------------------------------------------
echo "[step ${STEP}/${N_STEPS}] Generating report   (binder-eval)..."
REPORT_ARGS=(
    --boltz2-results "$BOLTZ2_CSV"
    --sequences      "$SEQUENCES"
    -o               "$OUTPUT/report"
)
if [[ $SKIP_AF3 -eq 0 && -f "$AF3_CSV" ]]; then
    REPORT_ARGS+=(--af3-results "$AF3_CSV")
fi
if [[ $SKIP_ESMFOLD2 -eq 0 && -f "$ESMFOLD2_CSV" ]]; then
    REPORT_ARGS+=(--esmfold2-results "$ESMFOLD2_CSV")
fi
if [[ $SKIP_SOLUPROT -eq 0 && $SOLUPROT_OK -eq 1 && -f "$SOLUPROT_CSV" ]]; then
    REPORT_ARGS+=(--soluprot-results "$SOLUPROT_CSV")
fi
if [[ $SKIP_TMPROT -eq 0 && $TMPROT_OK -eq 1 && -f "$TMPROT_CSV" ]]; then
    REPORT_ARGS+=(--tmprot-results "$TMPROT_CSV")
fi
REPORT_ARGS+=(--primary-engine "$PRIMARY_ENGINE")
if [[ -n "$MIN_ENGINES" ]]; then
    REPORT_ARGS+=(--min-engines "$MIN_ENGINES")
fi
# Inline epitope match (selectivity) — cheap, no extra pass or GPU.
if [[ -n "$EPITOPE_RESIDUES" ]]; then
    REPORT_ARGS+=(--epitope-residues "$EPITOPE_RESIDUES")
fi
conda run -n binder-eval binder-compare report "${REPORT_ARGS[@]}"

# --- Advisory post-steps (opt-in): affinity (Rosetta) + monomer fold check ----
# These need the report's structures + metrics.csv, so they run AFTER pass 1 and
# trigger a second report pass that threads their columns in. Both are advisory
# (never reorder/drop) and off by default.
STRUCT_DIR="$OUTPUT/report/top20_structures"
# Binder chain + Rosetta interface spec depend on the primary engine's chain layout
# (Boltz-2 = binder chain A; AF3/ESMFold2/Protenix = binder chain B).
if [[ "$PRIMARY_ENGINE" == "boltz" ]]; then
    BINDER_CHAIN="A"; ROSETTA_IFACE="A_B"
else
    BINDER_CHAIN="B"; ROSETTA_IFACE="B_A"
fi
EXTRA_REPORT_ARGS=()

if [[ $WITH_AFFINITY -eq 1 ]]; then
    if ! conda env list 2>/dev/null | awk '{print $1}' | grep -qx "${BINDCRAFT_ENV}"; then
        echo "[note] --with-affinity requested but conda env '${BINDCRAFT_ENV}' not found — skipping affinity."
    elif [[ ! -d "$STRUCT_DIR" ]]; then
        echo "[note] --with-affinity: no structures at $STRUCT_DIR — skipping affinity."
    else
        echo "[affinity] Rosetta |dG/dSASA| ranking on top-20 (env: ${BINDCRAFT_ENV}, interface ${ROSETTA_IFACE})…"
        # interface_energy.py keys designs by the structure stem; strip the report's
        # rank-prefix so design_id == binder_id and the affinity join lands.
        AFF_STRUCT_DIR="$OUTPUT/affinity_structures"
        rm -rf "$AFF_STRUCT_DIR"; mkdir -p "$AFF_STRUCT_DIR"
        for f in "$STRUCT_DIR"/rank*_*.pdb "$STRUCT_DIR"/rank*_*.cif; do
            [[ -e "$f" ]] || continue
            base="$(basename "$f")"; stem="${base#rank}"; stem="${stem#*_}"  # drop 'rank\d+_'
            cp "$f" "$AFF_STRUCT_DIR/$stem"
        done
        if conda run -n binder-eval binder-compare affinity \
                --metrics       "$OUTPUT/report/metrics.csv" \
                --structures-dir "$AFF_STRUCT_DIR" \
                --run-rosetta --interface "$ROSETTA_IFACE" --bindcraft-env "$BINDCRAFT_ENV" \
                --energy-out    "$OUTPUT/interface_energy.csv" \
                -o              "$OUTPUT/affinity.csv"; then
            EXTRA_REPORT_ARGS+=(--affinity-results "$OUTPUT/affinity.csv")
        else
            echo "[note] affinity step failed — report will render without the affinity column."
        fi
    fi
fi

if [[ -n "$MONOMER_DIR" ]]; then
    if [[ ! -d "$MONOMER_DIR" ]]; then
        echo "[note] --monomer-dir '$MONOMER_DIR' not a directory — skipping monomer check."
    elif [[ ! -d "$STRUCT_DIR" ]]; then
        echo "[note] --monomer-dir: no in-complex structures at $STRUCT_DIR — skipping monomer check."
    else
        echo "[monomer] context-dependent-fold check (complex vs alone; binder chain ${BINDER_CHAIN})…"
        # Match the monomer files by binder_id: rename complex structures to <binder_id>.pdb.
        CX_DIR="$OUTPUT/monomer_complex_structures"
        rm -rf "$CX_DIR"; mkdir -p "$CX_DIR"
        for f in "$STRUCT_DIR"/rank*_*.pdb; do
            [[ -e "$f" ]] || continue
            base="$(basename "$f")"; stem="${base#rank}"; stem="${stem#*_}"
            cp "$f" "$CX_DIR/$stem"
        done
        if conda run -n binder-eval binder-compare monomer \
                --complex-dir "$CX_DIR" \
                --monomer-dir "$MONOMER_DIR" \
                --binder-chain "$BINDER_CHAIN" \
                -o            "$OUTPUT/monomer_validation.csv"; then
            EXTRA_REPORT_ARGS+=(--monomer-results "$OUTPUT/monomer_validation.csv")
        else
            echo "[note] monomer step found no comparable pairs — report will render without fold_robust."
        fi
    fi
fi

if [[ ${#EXTRA_REPORT_ARGS[@]} -gt 0 ]]; then
    echo "[report] Re-generating report with advisory panels: ${EXTRA_REPORT_ARGS[*]}"
    conda run -n binder-eval binder-compare report "${REPORT_ARGS[@]}" "${EXTRA_REPORT_ARGS[@]}"
fi

echo ""
echo "=== Done ==="
echo "Report : $OUTPUT/report/report.html"
echo "Metrics: $OUTPUT/report/metrics.csv"
