"""Let Proteina-Complexa's vendored ColabDesign (1.1.1.1) and its AF2 reward run on jax >= 0.6.

On an aarch64 GB10 the AF2 reward needs jax 0.6.2: jaxlib 0.4.x cannot compile an AF2-class graph for
sm_121 (`LLVM ERROR: Unsupported rounding mode for conversion`). But 0.6 removed what Complexa's
vendored ColabDesign still calls, and the reward then died on the first score, with the real error
masked by a second one:

  * `jax.tree_map`, `jax.tree_flatten` and the rest of the `jax.tree_*` aliases -- removed in jax
    0.6.0 -- about a hundred call sites in the vendored ColabDesign. Each replacement
    `jax.tree_util.tree_<name>` is the same function, so this is a pure rename.
  * `jax.clear_backends()` -- removed -- called from the reward's `_cleanup_jax_state`, which runs from
    the `except` branch of `score()` and so replaced the real traceback with an AttributeError.
    It is guarded, not deleted: `jax.clear_caches()` on the line above still runs.

Applied by install_aarch.sh only (x86_64 stays on jax 0.4.29, where none of this is needed). Idempotent,
and it refuses (exit 1) if a pattern it expects is gone, so a changed upstream is noticed rather than
half-patched. Usage: pc_jax_compat.py <Proteina-Complexa dir> [--check]
"""

import re
import sys
from pathlib import Path

MARK = "BINDERSCOUT-PATCH: jax>=0.6 compat"
# The jax.tree_* aliases removed in 0.6.0, each the same function as jax.tree_util.tree_<name>.
REMOVED = ("map", "flatten", "unflatten", "leaves", "structure", "transpose", "reduce", "all")
RENAME = re.compile(r"\bjax\.tree_(" + "|".join(REMOVED) + r")\b")
CLEAR_OLD = "        jax.clear_backends()\n"
CLEAR_NEW = (
    f"        # {MARK}: jax.clear_backends was removed in 0.6\n"
    "        if hasattr(jax, 'clear_backends'):\n"
    "            jax.clear_backends()\n"
)


def main(argv):
    root = Path(argv[1])
    check = "--check" in argv[2:]
    cd = root / "community_models" / "colabdesign"
    reward = root / "src" / "proteinfoundation" / "rewards" / "alphafold2_reward.py"
    if not cd.is_dir() or not reward.is_file():
        print(f"NOT-FOUND {cd if not cd.is_dir() else reward}")
        return 0

    todo = []  # (path, new_text)
    n_renamed = 0
    for py in sorted(cd.rglob("*.py")):
        text = py.read_text()
        new, n = RENAME.subn(r"jax.tree_util.tree_\1", text)
        if n:
            todo.append((py, new))
            n_renamed += n

    text = reward.read_text()
    clear_state = "done" if MARK in text else "todo"
    if clear_state == "todo":
        if CLEAR_OLD not in text:
            print("PATTERN-MISSING: jax.clear_backends() in alphafold2_reward.py")
            return 1
        todo.append((reward, text.replace(CLEAR_OLD, CLEAR_NEW, 1)))

    if check:
        print("NEEDS-PATCH" if todo else "ALREADY-PATCHED")
        return 1 if todo else 0
    if not todo:
        print("ALREADY-PATCHED")
        return 0
    for path, new in todo:
        path.write_text(new)
    print(
        f"PATCHED jax.tree_* x{n_renamed} in {sum(1 for p, _ in todo if p != reward)} file(s); clear_backends {clear_state}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
