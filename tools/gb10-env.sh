# gb10-env.sh -- sourced by the bin/ tool wrappers. Not executable on its own.
#
# WHY THIS EXISTS, AND WHY IT IS NOT JUST `gpurun`:
# Most bin/ wrappers are INTERACTIVE ENV SHELLS -- they activate a conda/uv env and exec bash,
# and the user then launches the real job by hand inside. Wrapping that shell in a cgroup scope
# would be wrong twice over: the limit would apply to the whole session cumulatively across
# every job run in it, and the shell would die instead of the job. So for those, we export the
# framework ceilings into the shell environment (which any child job inherits and which JAX and
# PyTorch genuinely honour) and provide a `gpurun` function for the per-job path.
#
# Wrappers that take arguments and exec a real job directly (bindcraft2 <args>, esmfold2 <args>)
# should use `gpurun` instead -- see bin/bindcraft2.

# Repo root, derived from this file's location so nothing is hardcoded to one machine.
GB10_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---------------------------------------------------------------- budget table
# GiB of GPU memory per tool. PROVENANCE MATTERS -- read before changing a number:
#
#   JAX tools preallocate. The number is RESERVED IN FULL at import, so it must be the realistic
#   PEAK working set, not a padded ceiling. Padding here directly starves the host.
#   PyTorch tools do not preallocate. The number is a CEILING, so generosity is free.
#
# Anchors already in the repo: Evaluator Boltz-2 refold 24 GiB (refold_boltz2.py:28),
# Evaluator AF3 refold 12 GiB (refold_af3.py:370).
gb10_budget () {
    case "$1" in
        # --- JAX: RESERVED IN FULL at import. Sized to realistic peak; padding here starves the host.
        bindcraft)      echo 24 ;;   # N^2 scaling, ~8-14 GiB at N=415. colabdesign 1.1.3 uses bf16 AND
                                     # remat (use_bfloat16/use_remat True in af/model.py:35,41), so the
                                     # old vram_audit figure of "fp32, no checkpointing" overstated it.
                                     # Must cover max(lengths) in the target JSON, not the mean.
        bindcraft2)     echo 20 ;;
        mosaic)         echo 56 ;;   # EXCLUSIVE - see the note below. Pair carry alone was measured at
                                     # 24.61 GiB in one allocation (REPO_DIARY.md:1884-1886) and a 68.8 GiB
                                     # run left MemAvailable at 36 GiB, already under the 40 GiB floor.
        # --- PyTorch: a CEILING, not a reservation. Generosity is free until the job hits it.
        boltzgen)       echo 24 ;;   # its folding stage loads boltz2_conf_final.ckpt, i.e. a Boltz-2
                                     # model, measured on THIS box at 17,187 MiB (PLAN:78). Repo cap
                                     # convention is 1.3-1.5x measured peak -> 24, same as Boltz-2 refold.
        pxdesign)       echo 32 ;;
        protein-hunter) echo 48 ;;   # ~26-30 GiB at N=400. NOTE: spawns a LigandMPNN child every cycle
                                     # which INHERITS the MPS limit, so the worst-case allowance is 2x.
        rfaa)           echo 20 ;;
        *)              echo 20 ;;
    esac
}

# CAVEATS THAT THE NUMBERS ALONE DO NOT CONVEY
#
# 1. MPS caps PER CLIENT, not per job tree and not in aggregate. Any tool that spawns CUDA child
#    processes hands each child the SAME allowance, because CUDA_MPS_PINNED_DEVICE_MEM_LIMIT is
#    inherited through the environment. protein-hunter does this on every cycle. Budget accordingly
#    and do not read a cap as a guarantee about total footprint.
# 2. Allocatable budget is 121.69 - 40 (OS floor) = 81.7 GiB, and host RSS counts against it too:
#    one Evaluator job measured 7.6 GiB GPU against 14.1 GiB total host footprint (~1.8x).
# 3. mosaic at 56 GiB is effectively EXCLUSIVE - it reserves that at import, so nothing else of
#    consequence fits alongside it. Do not start a refold or a design campaign next to it.
# 4. bindcraft 24 + the full three-engine refold stack (Boltz-2 24 + AF3 12 + ESMFold2 24 = 60)
#    is 84 GiB > 81.7. Stagger them or drop an engine.

# Which framework does the GPU allocation on each tool. This is not cosmetic: it decides whether
# the budget is a RESERVATION (JAX preallocates it at import) or a CEILING (PyTorch grows into it),
# and therefore which knob actually enforces it. Naming an XLA fraction on a PyTorch tool implies a
# ceiling that variable does not provide -- there, only MPS enforces anything.
gb10_framework () {
    case "$1" in
        bindcraft|bindcraft2|mosaic)            echo jax ;;
        boltzgen|pxdesign|protein-hunter|rfaa)  echo pytorch ;;
        *)                                      echo unknown ;;
    esac
}

# ---------------------------------------------------------------- apply ceilings
gb10_apply () {
    local tool="$1" cap; cap="$(gb10_budget "$tool")"
    local pool free floor=40
    pool=$(awk '/^MemTotal:/ {printf "%.0f", $2/1048576}' /proc/meminfo)
    free=$(awk '/^MemFree:/  {printf "%.0f", $2/1048576}' /proc/meminfo)

    # JAX: PREALLOCATE stays true on purpose -- a fixed slab that fails at import is the failure
    # mode we want. PREALLOCATE=false removes the only ceiling. ALLOCATOR=platform bypasses BFC,
    # so the fraction would cap nothing. Both are dGPU habits and both are wrong here.
    export XLA_PYTHON_CLIENT_PREALLOCATE=true
    # Assigned separately from the export so the export does not mask the
    # substitution's exit status (SC2155).
    XLA_PYTHON_CLIENT_MEM_FRACTION="$(
        python3 - "$cap" "$GB10_REPO/Evaluator" <<'PY' 2>/dev/null || awk -v c="$cap" -v p="$pool" -v m=40 \
          'BEGIN{f=c/p; ce=(p-m)/p; if(f>ce)f=ce; if(f<0.02)f=0.02; if(f>0.8)f=0.8; printf "%.3f", f}'
import sys
sys.path.insert(0, sys.argv[2])
from binder_comparison.refolding.memory_policy import resolve_mem_fraction
print(resolve_mem_fraction(float(sys.argv[1]))[0])
PY
    )"
    export XLA_PYTHON_CLIENT_MEM_FRACTION
    unset XLA_PYTHON_CLIENT_ALLOCATOR

    # PyTorch does not preallocate; this is fragmentation control, not a ceiling. The ceiling for
    # torch tools has to come from MPS or torch.cuda.set_per_process_memory_fraction in the job.
    export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
    export GB10_TOOL="$tool" GB10_CAP_GIB="$cap"

    # Per-tool overrides where the tool has its OWN budget variable. Prefer driving that variable
    # over our raw fraction: memory_policy.apply_jax_memory_policy() gives an inherited
    # XLA_PYTHON_CLIENT_MEM_FRACTION precedence over its pool-aware per-engine default, so leaking
    # ours would override the tool's own resolver rather than cooperate with it.
    case "$tool" in
        mosaic)
            # hallucinate_bindmaster.py:19 defaults MOSAIC_TARGET_GIB to 64. That is above the
            # empirically safe footprint: a 68.8 GiB run left MemAvailable at 36 GiB, already under
            # the 40 GiB floor (REPO_DIARY.md:1889-1890). Drive it to the budget instead, and stand
            # down our own fraction so the engine's resolver is the single source of truth.
            export MOSAIC_TARGET_GIB="$cap"
            unset XLA_PYTHON_CLIENT_MEM_FRACTION
            ;;
    esac

    # Join the BindMaster MPS server if it is up -- see the isolation note in gpurun.
    export CUDA_MPS_PIPE_DIRECTORY="${BINDMASTER_MPS_DIR:-/tmp/bindmaster-mps}/pipe"
    local mps="down"
    if echo get_default_device_pinned_mem_limit 0 2>/dev/null \
       | timeout 5 nvidia-cuda-mps-control >/dev/null 2>&1; then
        export CUDA_MPS_PINNED_DEVICE_MEM_LIMIT="0=${cap}G"; mps="up (${cap}G enforced)"
    fi

    # Make this shell's children the designated OOM victim. Driver pages are charged to no task,
    # so oom_badness() scores the real offender at ~0 -- we have to say it out loud.
    echo 800 > /proc/self/oom_score_adj 2>/dev/null || true

    local fw; fw="$(gb10_framework "$tool")"
    printf '\n\033[1mGB10 memory policy\033[0m — %s (%s)\n' "$tool" "$fw"
    if [ "$fw" = jax ]; then
        printf '  budget        %s GiB  RESERVED at import (PREALLOCATE=true, fraction=%s)\n' \
               "$cap" "${XLA_PYTHON_CLIENT_MEM_FRACTION:-resolved by the engine}"
    else
        printf '  budget        %s GiB  CEILING, not reserved — enforced by MPS only\n' "$cap"
        printf '                (XLA_* vars are inert here; this tool allocates through PyTorch)\n'
    fi
    printf '  free now      %s GiB of %s GiB unified pool (OS floor %s GiB)\n' "$free" "$pool" "$floor"
    printf '  MPS           %s\n' "$mps"
    printf '  guard         %s\n' "$(systemctl is-active gb10-guard 2>/dev/null || echo unknown)"
    if [ "$free" -lt $((floor + cap)) ]; then
        printf '  \033[1;33mWARNING\033[0m  only %s GiB free; a %s GiB job leaves under the %s GiB floor.\n' \
               "$free" "$cap" "$floor"
        printf '           Something else is holding memory — check nvidia-smi before launching.\n'
    fi
    printf '  Per-job cap:  gpurun --cap %s -- <command>\n\n' "$cap"

    # Convenience so interactive work still routes through the refusal path.
    gpurun () { "$GB10_REPO/tools/gpurun" "$@"; }
    export -f gpurun 2>/dev/null || true
}
