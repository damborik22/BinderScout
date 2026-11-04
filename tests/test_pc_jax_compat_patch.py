"""Proteina-Complexa's AF2 reward could not run on jax 0.6, which an aarch64 GB10 needs.

jaxlib 0.4.x cannot compile AF2 for sm_121, so the aarch64 install uses jax 0.6.2 -- which removed the
`jax.tree_*` aliases Complexa's vendored ColabDesign (1.1.1.1) calls ~100 times, and `jax.clear_backends`,
which the reward's cleanup path calls and which therefore masked the real error. `pc_jax_compat.py` renames
the first and guards the second. Verified live on a GB10 (2026-11-04): with it, the generated
run_proteina_complexa.sh ran best-of-n to the end and the AF2 reward returned four distinct non-zero scores.

These run the real script against a synthetic tree, so no GPU, jax or Complexa checkout is needed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "install" / "patches" / "pc_jax_compat.py"
X86 = REPO / "install" / "install.sh"
ARM = REPO / "install" / "install_aarch.sh"

CD_SRC = """\
import jax
import jax.numpy as jnp
a = jax.tree_map(lambda x: x, 1)
b = jax.tree_flatten(a)
c = jax.tree_unflatten(*b[::-1])
d = jax.tree_leaves(a), jax.tree_structure(a), jax.tree_transpose(1, 2, 3), jax.tree_reduce(f, a), jax.tree_all(a)
e = jax.tree_util.tree_map(f, a)   # already the new spelling: must stay exactly as it is
g = jax.tree.map(f, a)
h = my_jax.tree_map(f, a)          # not jax's
"""
REWARD_SRC = """\
import jax
class R:
    def _cleanup_jax_state(self):
        jax.clear_caches()
        jax.clear_backends()
"""


def _tree(tmp_path, reward=REWARD_SRC):
    cd = tmp_path / "community_models" / "colabdesign" / "af"
    cd.mkdir(parents=True)
    (cd / "m.py").write_text(CD_SRC)
    rw = tmp_path / "src" / "proteinfoundation" / "rewards"
    rw.mkdir(parents=True)
    (rw / "alphafold2_reward.py").write_text(reward)
    return cd / "m.py", rw / "alphafold2_reward.py"


def _run(root, *extra):
    return subprocess.run([sys.executable, str(SCRIPT), str(root), *extra], capture_output=True, text=True)


def test_every_removed_alias_is_renamed_and_nothing_else_is_touched(tmp_path):
    m, _ = _tree(tmp_path)
    proc = _run(tmp_path)
    assert proc.returncode == 0 and "PATCHED" in proc.stdout, proc.stdout + proc.stderr
    out = m.read_text()
    code = out.replace("my_jax.tree_map", "")  # the lookalike is checked separately below
    for name in ("map", "flatten", "unflatten", "leaves", "structure", "transpose", "reduce", "all"):
        assert f"jax.tree_{name}(" not in code, f"jax.tree_{name} survived"
        assert f"jax.tree_util.tree_{name}(" in out
    assert "e = jax.tree_util.tree_map(f, a)   # already the new spelling: must stay exactly as it is" in out
    assert "g = jax.tree.map(f, a)" in out
    assert "my_jax.tree_map(f, a)" in out, "a lookalike that is not jax must not be rewritten"


def test_clear_backends_is_guarded_not_deleted(tmp_path):
    _, rw = _tree(tmp_path)
    assert _run(tmp_path).returncode == 0
    text = rw.read_text()
    assert "jax.clear_caches()" in text, "the cache clear on the line above must still run"
    assert "if hasattr(jax, 'clear_backends'):\n            jax.clear_backends()" in text
    ns: dict = {}
    # Executes on a jax that no longer has clear_backends: the old text raised AttributeError here.
    fake_jax = type("J", (), {"clear_caches": staticmethod(lambda: None)})
    exec(compile(text.replace("import jax\n", "", 1), "r.py", "exec"), {"jax": fake_jax}, ns)
    ns["R"]()._cleanup_jax_state()


def test_it_is_idempotent_and_check_reports_the_state(tmp_path):
    m, rw = _tree(tmp_path)
    assert _run(tmp_path, "--check").returncode == 1, "--check must say an unpatched tree needs patching"
    assert _run(tmp_path).returncode == 0
    before = (m.read_text(), rw.read_text())
    again = _run(tmp_path)
    assert again.returncode == 0 and "ALREADY-PATCHED" in again.stdout
    assert (m.read_text(), rw.read_text()) == before
    assert _run(tmp_path, "--check").returncode == 0


def test_it_refuses_when_upstream_changed_rather_than_half_patching(tmp_path):
    m, _ = _tree(tmp_path, reward="import jax\nclass R:\n    pass\n")
    proc = _run(tmp_path)
    assert proc.returncode == 1 and "PATTERN-MISSING" in proc.stdout
    assert "jax.tree_map(" in m.read_text(), "nothing may be written when a pattern is missing"


def test_a_missing_checkout_is_a_noop_not_a_crash(tmp_path):
    proc = _run(tmp_path / "nothing-here")
    assert proc.returncode == 0 and "NOT-FOUND" in proc.stdout


def test_only_the_aarch64_installer_applies_it():
    """Mutating the CALL SITE. x86_64 stays on jax 0.4.29, where none of this is needed."""
    arm, x86 = ARM.read_text(), X86.read_text()
    assert 'install/patches/pc_jax_compat.py" "${PROTEINA_COMPLEXA_DIR}"' in arm
    assert "pc_jax_compat" not in x86
    # after the reward patch, inside install_proteina_complexa, before the next step runs
    i = arm.index("pc_reward_refuses_when_every_model_fails.py")
    j = arm.index("pc_jax_compat.py")
    assert 0 < j - i < 2500
