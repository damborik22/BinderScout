"""CONTRIBUTING.md's environment table must match the environments that exist.

It drifted both ways at once: it listed `binder-eval-af2`, deleted with AF2
refolding in Part I, while omitting `binderscout_protein_hunter`,
`binderscout_rfd3`, `binder-eval-af3`, `binder-eval-esmfold2`,
`binder-eval-soluprot` and later `binder-eval-tmprot`.

Both directions matter and they fail differently. A missing row makes a real
environment undiscoverable to a new developer. A phantom row is worse: someone
following CONTRIBUTING on a fresh box creates a dead environment and only finds
out later that nothing uses it.

Ground truth is `Evaluator/envs/*.yml` — a spec file is what the installer
actually builds from.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONTRIBUTING = REPO / "CONTRIBUTING.md"
ENV_DIR = REPO / "Evaluator" / "envs"


def _table_envs() -> set[str]:
    """Backtick-quoted names in the 'Conda environments' table."""
    text = CONTRIBUTING.read_text()
    start = text.index("## Conda environments")
    end = text.find("\n## ", start + 1)
    block = text[start : end if end != -1 else len(text)]
    return {m for m in re.findall(r"`([A-Za-z0-9_.-]+)`", block) if m.startswith(("binder-eval", "binderscout_"))}


def _spec_envs() -> set[str]:
    return {p.stem for p in ENV_DIR.glob("*.yml")}


def test_every_env_spec_is_documented():
    missing = _spec_envs() - _table_envs()
    assert not missing, (
        f"Evaluator/envs/ ships specs for {sorted(missing)} but CONTRIBUTING.md's "
        "environment table does not list them — a new developer cannot discover them."
    )


def test_the_table_invents_no_environment():
    """A phantom row sends someone off to create a dead env.

    Only `binder-eval*` names are checked against specs; the `binderscout_*`
    envs are created imperatively by the installer, not from a yml.
    """
    documented = {e for e in _table_envs() if e.startswith("binder-eval")}
    phantom = documented - _spec_envs()
    assert not phantom, (
        f"CONTRIBUTING.md documents {sorted(phantom)}, which has no spec in "
        "Evaluator/envs/ — binder-eval-af2 sat there for two releases after "
        "Part I deleted it."
    )


def test_installer_created_envs_are_documented():
    """The binderscout_* envs have no yml, so check them against install.sh."""
    src = (REPO / "install" / "install.sh").read_text()
    created = set(re.findall(r"\b(binderscout_[a-z0-9_]+)\b", src))
    # Only names the installer actually builds an environment for.
    created = {e for e in created if f"-n {e}" in src or f"create -n {e}" in src}
    missing = created - _table_envs()
    assert not missing, f"install.sh creates {sorted(missing)} but CONTRIBUTING.md does not list them."
