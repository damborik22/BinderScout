"""Make Proteina-Complexa's composite reward REFUSE instead of silently scoring 0.0.

`CompositeRewardModel.score()` wraps each reward model in `try/except Exception` and
reports failures with `warnings.warn`. Two things then combine:

* PC's own CLI runs python with `-W ignore -W ignore::UserWarning`, so the warning is
  suppressed outright and never reaches the log;
* `total_reward` keeps its initial `torch.tensor(0.0)`, and a complete-looking result dict
  is returned.

So when the AF2 reward cannot execute, a search runs to completion against an all-zero
reward, writes its rows, and exits 0. Measured on BM5 2026-10-04: a 112 s MCTS reported
nine reward evaluations, every one 0.0, and the GPU and CPU runs produced byte-identical
sequences because nothing was steering them. That was initially read as a 25x throughput
win and had to be retracted.

This patch:
  1. records each failure in a per-call list;
  2. logs it with `logger.error(..., exc_info=True)` instead of `warnings.warn`, so `-W
     ignore` cannot hide it and the real traceback is kept;
  3. raises if EVERY model failed -- a partial failure can still degrade gracefully, but a
     composite of zero successful models is not a reward.

Applied by both installers after PC's editable install. Idempotent: re-running is a no-op.
Shared rather than inlined twice because the defect is upstream and platform-independent.
"""

import os
import sys

TARGET = os.path.join(sys.argv[1], "src/proteinfoundation/rewards/base_reward.py")
MARK = "BINDERSCOUT-PATCH: a reward that cannot be computed is not 0.0"

if not os.path.isfile(TARGET):
    print(f"NOT-FOUND {TARGET}")
    sys.exit(0)
t = open(TARGET).read()
if MARK in t:
    print("ALREADY-PATCHED")
    sys.exit(0)

subs = [
    # 1. a per-score list of failures
    (
        "        total_reward = torch.tensor(0.0, dtype=torch.float32)\n",
        "        total_reward = torch.tensor(0.0, dtype=torch.float32)\n"
        f"        # {MARK}\n"
        "        _bs_failed: list[tuple[str, str]] = []\n",
    ),
    # 2+3. loud, unsuppressable logging instead of a swallowed warning
    (
        "            except Exception as e:\n"
        "                warnings.warn(f\"Error computing reward from folding model '{name}': {e}\")\n",
        "            except Exception as e:\n"
        "                _bs_failed.append((name, repr(e)))\n"
        '                logger.error("reward model %r FAILED: %s", name, e, exc_info=True)\n',
    ),
    (
        "            except Exception as e:\n"
        "                warnings.warn(f\"Error computing reward from model '{name}': {e}\")\n",
        "            except Exception as e:\n"
        "                _bs_failed.append((name, repr(e)))\n"
        '                logger.error("reward model %r FAILED: %s", name, e, exc_info=True)\n',
    ),
    # 4. refuse when nothing succeeded
    (
        "        return {\n            REWARD_KEY: combined_reward_dict,\n",
        "        if _bs_failed and not model_results:\n"
        '            _d = "; ".join(f"{n}: {e}" for n, e in _bs_failed)\n'
        "            raise RuntimeError(\n"
        '                "EVERY reward model failed, so this composite reward would be 0.0 for a "\n'
        '                "reason unrelated to the design. Refusing rather than returning it: a "\n'
        '                "search driven by an all-zero reward runs to completion and looks healthy. "\n'
        '                f"Failures -- {_d}"\n'
        "            )\n"
        "        return {\n            REWARD_KEY: combined_reward_dict,\n",
    ),
]
for old, new in subs:
    if old not in t:
        print(f"PATTERN-MISSING: {old.strip().splitlines()[0][:60]}")
        sys.exit(1)
    t = t.replace(old, new, 1)
open(TARGET, "w").write(t)
print("PATCHED")
