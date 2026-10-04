"""Make three local edits to the Proteina-Complexa checkout reproducible, and drop a fourth.

These were found as uncommitted edits in BM5's PC checkout on 2026-10-04, predating the current
installer. Unreproducible state on a shared machine is how a result becomes unexplainable, so
each is either applied here or reverted:

1. KEEP, aarch64 only -- `[tool.uv] extra-index-url` cu126 -> cu130. There is no aarch64 torch
   build on the cu126 index. x86 must stay on cu126, which is upstream's choice, so this is
   applied only when --torch-index is passed.

2. KEEP, both platforms -- the `apoe4_ntd` target (6NCO, A1-185, hotspots A54/A55/A173). A real
   campaign target; without it those configs cannot be reproduced.

3. REVERT, both platforms -- a try/except around `jax.devices("gpu")` that fell back to
   `jax.devices("cpu")` on RuntimeError, commented "Blackwell/aarch64 (sm_121): JAX-CUDA
   unavailable". That silently moves the AF2 reward onto the CPU, which is precisely the ~130x
   slowdown the tool's deprecation rests on -- and makes it invisible. jax 0.6.2 reports `gpu` on
   GB10, so the fallback should never fire; if it ever does, failing loudly is the only safe
   behaviour. Restored to upstream's single line, which raises.

Idempotent: re-running reports what was already in place.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

APOE4 = """
  apoe4_ntd:
    target_input: "A1-185"
    source: custom_targets
    target_filename: 6NCO_AF3
    hotspot_residues: ["A54", "A55", "A173"]
    binder_length: [60, 100]
    pdb_id: 6NCO
"""

CPU_FALLBACK = """        try:
            self.device = jax.devices("gpu")[device_id]
        except RuntimeError:
            # Blackwell/aarch64 (sm_121): JAX-CUDA unavailable → AF2 reward on CPU
            self.device = jax.devices("cpu")[0]
"""
UPSTREAM = '        self.device = jax.devices("gpu")[device_id]\n'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pc_dir")
    ap.add_argument("--torch-index", help="e.g. cu130; aarch64 only. Omit to leave the index alone.")
    a = ap.parse_args()
    root = pathlib.Path(a.pc_dir)
    rc = 0

    # 1. torch wheel index
    if a.torch_index:
        f = root / "pyproject.toml"
        if not f.is_file():
            print(f"MISSING {f}")
            rc = 1
        else:
            t = f.read_text()
            want = f"https://download.pytorch.org/whl/{a.torch_index}"
            if want in t:
                print(f"index: already {a.torch_index}")
            else:
                import re

                t2 = re.sub(r"https://download\.pytorch\.org/whl/cu\d+", want, t)
                if t2 == t:
                    print("index: no pytorch index line found — left alone")
                else:
                    f.write_text(t2)
                    print(f"index: -> {a.torch_index}")

    # 2. apoe4_ntd target
    f = root / "configs/targets/targets_dict.yaml"
    if not f.is_file():
        print(f"MISSING {f}")
        rc = 1
    else:
        t = f.read_text()
        if "apoe4_ntd:" in t:
            print("target apoe4_ntd: already present")
        else:
            f.write_text(t.rstrip("\n") + "\n" + APOE4)
            print("target apoe4_ntd: added")

    # 3. remove the silent CPU fallback
    f = root / "src/proteinfoundation/rewards/alphafold2_reward.py"
    if not f.is_file():
        print(f"MISSING {f}")
        rc = 1
    else:
        t = f.read_text()
        if CPU_FALLBACK in t:
            f.write_text(t.replace(CPU_FALLBACK, UPSTREAM, 1))
            print("cpu fallback: REMOVED (a silent CPU reward is the deprecation's own failure)")
        elif UPSTREAM in t:
            print("cpu fallback: already absent")
        else:
            print("cpu fallback: neither form found — inspect by hand")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
