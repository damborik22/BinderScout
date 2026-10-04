"""Pick a JAX GPU memory cap that is safe on unified-memory hosts.

WHY THIS EXISTS
---------------
On a discrete card, "reserve 75% of device memory" is harmless: the OS needs none
of the GPU's RAM, and an over-allocation kills the process, not the machine.

On NVIDIA GB10 (DGX Spark) there is no device.  ``cudaMemGetInfo`` returns
total == ``SC_PHYS_PAGES`` == 121.69 GiB -- measured 2026-08-19.  So every
"fraction of device total" knob is a fraction *of the whole machine*, and the
allocator takes it out from under the kernel, the NVRM driver and sshd:

  2026-08-18  AF3 at a hard-coded 0.8    -> 97.4 GiB reserved -> 17 min of
              ``NVRM: Out of memory [NV_ERR_NO_MEMORY]`` -> hard reboot.
  2026-08-19  Boltz-2 with NO policy set -> JAX's default 0.75 -> 91.3 GiB.

Neither ran out of memory.  Both were told to take most of the computer.

There is no absolute-bytes cap in JAX: ``XLA_PYTHON_CLIENT_MEM_FRACTION`` is the
only lever, and jax-ml/jax#4310 asked for a bytes option in 2020 and it never
shipped.  XLA *has* the capability internally (``gpu_system_memory_size`` in
``CreateBFCAllocator``) but exposes no env var reaching it.  So we compute the
fraction ourselves from an absolute GiB target and the real pool size.

This is defense in depth, NOT the primary guard.  The hard ceiling is a CUDA MPS
per-client limit -- see ``tools/gpu_mem_guard.sh`` and
``docs/PLAN_bm5_unified_memory.md``.  This module covers the case where MPS is
not running, in which every client silently reverts to uncapped direct mode.
"""

from __future__ import annotations

import ctypes
import os
import sys

# Never leave a unified-memory host less than this.  40, not 24: the 2026-08-18
# reboot happened with ~24 GB nominally free, so 24 is a measured FAILURE point.
DEFAULT_MIN_OS_GIB = 40.0

_CUDART_CANDIDATES = ("libcudart.so", "libcudart.so.13", "libcudart.so.12")


def _system_ram_gib() -> float:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024**3)
    except (ValueError, OSError):
        return 0.0


def _nvidia_smi_total_gib() -> float:
    """Device-0 total memory via nvidia-smi, in GiB.  0.0 if unavailable.

    Second opinion for when ``libcudart`` is not on the loader path.  That is not
    hypothetical: the Mosaic uv venv on the x86 fleet cannot dlopen libcudart at
    all, so ``_cuda_pool_gib()`` returns 0 there while the card is perfectly usable.
    """
    import shutil
    import subprocess

    exe = shutil.which("nvidia-smi")
    if not exe:
        return 0.0
    try:
        out = subprocess.run(
            [exe, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 0.0
    if out.returncode != 0:
        return 0.0
    first = (out.stdout or "").strip().splitlines()
    try:
        return float(first[0].strip()) / 1024 if first else 0.0
    except (ValueError, IndexError):
        return 0.0


def _cuda_pool_gib() -> float:
    """Total memory CUDA reports for device 0, in GiB.  0.0 if unreachable."""
    free, total = ctypes.c_size_t(), ctypes.c_size_t()
    for lib in _CUDART_CANDIDATES:
        try:
            rt = ctypes.CDLL(lib)
        except OSError:
            continue
        try:
            if rt.cudaMemGetInfo(ctypes.byref(free), ctypes.byref(total)) == 0 and total.value:
                return total.value / (1024**3)
        except (AttributeError, OSError):
            pass
        break
    return 0.0


def resolve_mem_fraction(
    target_gib: float,
    *,
    min_os_gib: float = DEFAULT_MIN_OS_GIB,
    discrete_floor: float = 0.5,
    hard_cap: float = 0.8,
) -> tuple[str, str]:
    """Return ``(fraction_string, human_explanation)`` for ``target_gib``.

    A fraction is the wrong unit on unified memory: an engine's working set is a
    constant regardless of host size, so a fixed fraction makes a *larger* host
    reserve *more* and therefore be *more* likely to die -- the opposite of what a
    safety cap should do.  We invert that: name the absolute target, derive the
    fraction from the pool we actually have.
    """
    # NEVER fall back to system RAM here.  A RAM-derived "pool" passes the unified
    # test below *by construction* (pool == ram), so an UNKNOWN pool was always
    # classified as unified and handed the OS floor.  On a discrete card that is the
    # wrong number entirely: BM2 (24 GB RTX 3090, 62.7 GiB RAM) could not dlopen
    # libcudart from the Mosaic venv, resolved "unified 62.7 GiB", applied the 40 GiB
    # floor for a fraction of 0.362, and JAX then took 0.362 of the *card* -- 8.5 GiB
    # of 23.6 -- so Boltz-2 OOMed at 9 GB and it read as "this target is too big".
    # Ask nvidia-smi for a real second opinion; if the pool is genuinely unknown, say
    # so and use the JAX-like default rather than inventing a size.
    pool = _cuda_pool_gib() or _nvidia_smi_total_gib()
    if pool <= 0:
        return f"{hard_cap:.3f}", "pool size unknown; falling back to the JAX-like default"

    ram = _system_ram_gib()
    # Unified == the GPU pool IS system RAM (GB10, Grace-Hopper).  Only then does
    # over-reserving starve the OS.  On a discrete card the OS needs none of the
    # GPU's RAM, and applying an OS floor there would drive the fraction to ~0.02
    # on a 24 GB card -- below the working set, OOM-ing every design.
    unified = ram > 0 and abs(pool - ram) / ram < 0.2

    frac = target_gib / pool
    if unified:
        ceiling = max(0.0, (pool - min_os_gib) / pool)
        frac = min(frac, ceiling)
        kind = f"unified {pool:.1f} GiB pool, leaving >= {min_os_gib:.0f} GiB for the OS"
    else:
        frac = max(frac, discrete_floor)
        kind = f"discrete {pool:.1f} GiB device (host RAM is separate; runaway is recoverable)"

    frac = max(0.02, min(frac, hard_cap))
    return f"{frac:.3f}", f"{kind}; target {target_gib:.0f} GiB -> fraction {frac:.3f} (~{frac * pool:.1f} GiB)"


def apply_jax_memory_policy(engine: str, target_gib: float, *, env=None, verbose: bool = True) -> str:
    """Set the XLA memory env vars for ``engine``.  MUST be called before ``import jax``.

    Precedence: ``<ENGINE>_XLA_MEM_FRACTION`` > ``XLA_PYTHON_CLIENT_MEM_FRACTION``
    > the pool-aware default.  Keeps ``PREALLOCATE=true``: with ``false`` and no
    device ceiling the allocator grows into the shared pool with no fail-fast,
    which is the slow-starve path rather than a clean error.
    """
    env = os.environ if env is None else env
    name = f"{engine.upper()}_XLA_MEM_FRACTION"

    explicit = (env.get(name) or "").strip()
    inherited = (env.get("XLA_PYTHON_CLIENT_MEM_FRACTION") or "").strip()
    if explicit:
        frac, why = explicit, f"explicit {name}"
    elif inherited:
        frac, why = inherited, "inherited XLA_PYTHON_CLIENT_MEM_FRACTION"
    else:
        frac, why = resolve_mem_fraction(target_gib)
        why = f"pool-aware default -- {why}"

    # PREALLOCATE stays "true" by default: with "false" and no device ceiling the
    # allocator grows into the shared pool with no fail-fast -- the slow-starve path.
    # The escape hatch exists for ONE purpose: measuring an engine's true demand
    # (preallocation hides it -- you measure supply, not demand). Only ever use it
    # under a CUDA MPS cap, which supplies the ceiling that "false" removes.
    prealloc = (env.get("BINDERSCOUT_XLA_PREALLOCATE") or "").strip().lower()
    if prealloc in ("0", "false", "no"):
        env["XLA_PYTHON_CLIENT_PREALLOCATE"] = "false"
        print(
            f"  [{engine}] WARNING: BINDERSCOUT_XLA_PREALLOCATE=false -- no fail-fast ceiling. "
            f"Run under tools/gpu_mem_guard.sh or this can starve the host.",
            file=sys.stderr,
        )
    else:
        env["XLA_PYTHON_CLIENT_PREALLOCATE"] = "true"
    env["XLA_PYTHON_CLIENT_MEM_FRACTION"] = frac
    # Setting both names is a jaxlib ValueError; keep only the legacy one.
    env.pop("XLA_CLIENT_MEM_FRACTION", None)

    if verbose:
        print(f"  [{engine}] XLA mem fraction {frac} ({why})")
    return frac


# ---------------------------------------------------------------------------
# Device floor: refuse BEFORE loading weights on a card that cannot run at all
# ---------------------------------------------------------------------------
#
# WHY A SEPARATE GUARD
# --------------------
# The functions above size a memory *cap*.  They say nothing about whether the
# card is large enough in the first place, and the failure when it is not is
# silent by construction: ESMFold2 catches a per-binder CUDA OOM, writes an EMPTY
# row and continues, so a 12 GB card produces a full-length CSV of blanks and
# exits 0.  Every one of those designs then drops to a 2-engine mean and fails the
# >=3-engine gate -- demoted for a hardware reason, reported as if it were a
# quality judgement.  Recorded in docs/data/gpu_benchmark_2026-09-18/README.md and
# in docs/PLAN_binderscout_v2.md, where it is the reason BM3 "cannot refold".
#
# ONLY ESMFOLD2 HAS A FLOOR, and the asymmetry is the point.
#   ESMFold2 is dominated by getting ESMC-6B onto the card, so its 150-token peak
#   IS the floor and does not fall with a smaller complex: 14,248 MiB on an RTX
#   3090 and 13,781 MiB on GB10 -- two architectures agreeing, because the number
#   is a weight-residency cost, not a graph cost.  "A floor, not a slope"
#   (docs/NEXT_STAGES.md).  A card that cannot hold the weights cannot run it at
#   any size, which is a prediction a static check can make honestly.
#
#   Boltz-2 gets NO floor on purpose.  It scales hard AND card-dependently: 8,518
#   MiB at 150 tokens on a 3090, 16,712 at 300, outright failure at 600 -- while
#   GB10 needs ~1.5x a discrete card for identical work.  The benchmark README
#   exists to stop precisely this inference ("predicting one card's requirement
#   from another's is what this file exists to stop").  A static floor would either
#   refuse a 12 GB card that can genuinely fold a 60-token complex -- CALCA is 60 --
#   or pass one that cannot do 300.  Boltz-2 is covered instead by the per-design
#   accounting in its runner, which MEASURES rather than predicts.
#
#   AF3 gets none because it never exceeded 5,224 MiB anywhere in the sweep, flat
#   across 150-900 tokens.  No card in the fleet is below that.
ENGINE_MIN_DEVICE_MIB: dict[str, int] = {"esmfold2": 14248}

ALLOW_SMALL_GPU_ENV = "BINDERSCOUT_ALLOW_SMALL_GPU"


class InsufficientDeviceMemory(RuntimeError):
    """This GPU cannot run the engine at any input size."""


def device_total_mib() -> int:
    """Total memory of device 0 in MiB, or 0 when it cannot be measured.

    Same two-source resolution as ``resolve_mem_fraction``: ``libcudart`` first,
    ``nvidia-smi`` as the second opinion (the Mosaic uv venv cannot dlopen
    libcudart at all, yet its card is perfectly usable).
    """
    gib = _cuda_pool_gib() or _nvidia_smi_total_gib()
    return int(gib * 1024) if gib > 0 else 0


def require_device_memory(engine: str, *, min_mib: int | None = None, env=None) -> int:
    """Raise ``InsufficientDeviceMemory`` if this card is below *engine*'s floor.

    Call this BEFORE loading weights.  Returns the measured device total in MiB
    (0 when unmeasurable).

    Three deliberate non-refusals, each of which must stay a non-refusal:

    * **No floor recorded** for the engine -- see the comment above; the absence is
      a measurement decision, not an oversight, so this is silent.
    * **Pool unmeasurable** (``libcudart`` absent and no ``nvidia-smi``).  Refusing
      here would break CPU-only test hosts and every container without the NVIDIA
      stack, and we would be refusing on an *assumption* about size.  Says so and
      proceeds.
    * ``BINDERSCOUT_ALLOW_SMALL_GPU=1`` -- the escape hatch for deliberately
      exercising the code path on a small card.  It warns that the output is NOT
      authoritative, because that is the whole content of the refusal: the engine
      will still write blank rows, and they must not be read as scores.
    """
    env = os.environ if env is None else env
    floor = ENGINE_MIN_DEVICE_MIB.get(engine) if min_mib is None else min_mib
    if not floor:
        return device_total_mib()

    total = device_total_mib()
    if total <= 0:
        print(
            f"  [{engine}] NOTE: device memory could not be measured, so the {floor} MiB floor was not checked.",
            file=sys.stderr,
        )
        return 0
    if total >= floor:
        return total

    override = (env.get(ALLOW_SMALL_GPU_ENV) or "").strip().lower()
    if override in ("1", "true", "yes"):
        print(
            f"  [{engine}] WARNING: {ALLOW_SMALL_GPU_ENV} is set and this card has "
            f"{total} MiB against a {floor} MiB floor. Proceeding, but the output is "
            f"NOT AUTHORITATIVE: {engine} writes a blank row on CUDA OOM, and a blank "
            f"row demotes a design below the cross-engine gate for a hardware reason. "
            f"Do not report these rows as scores.",
            file=sys.stderr,
        )
        return total

    raise InsufficientDeviceMemory(
        f"{engine} needs at least {floor} MiB of GPU memory and this device has {total} MiB. "
        f"This is a floor, not a slope -- the figure is the cost of resident weights, so a "
        f"smaller complex does not make it fit, and no input size will run here. Refusing "
        f"BEFORE loading weights, because the alternative is what this guard exists to stop: "
        f"{engine} catches the CUDA OOM per design, writes a BLANK row and exits 0, so the run "
        f"looks complete while every design silently drops an engine and fails the cross-engine "
        f"gate -- demoted for a hardware reason and reported as a quality judgement. "
        f"Run this engine on a larger card, pass --skip-{engine} to evaluate without it (and "
        f"--min-engines 2), or set {ALLOW_SMALL_GPU_ENV}=1 to proceed with output that is "
        f"explicitly not authoritative."
    )
