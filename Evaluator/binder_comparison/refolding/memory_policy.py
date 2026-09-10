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
    pool = _cuda_pool_gib() or _system_ram_gib()
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
    prealloc = (env.get("BINDMASTER_XLA_PREALLOCATE") or "").strip().lower()
    if prealloc in ("0", "false", "no"):
        env["XLA_PYTHON_CLIENT_PREALLOCATE"] = "false"
        print(
            f"  [{engine}] WARNING: BINDMASTER_XLA_PREALLOCATE=false -- no fail-fast ceiling. "
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
