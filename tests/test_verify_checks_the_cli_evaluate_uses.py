"""Every env `evaluate.sh` drives through `binder-compare` must be verified
through `binder-compare`, not through a bare `import`.

`--verify` exists so an operator learns an env is unusable before spending GPU
time, and an import check cannot deliver that: the refold steps are console-script
invocations (`conda run -n binder-eval-af3 binder-compare refold-af3`), and the
console script can be absent, or present but unable to start, while the engine's
own library imports perfectly.

Measured 2026-09-27 on a completed `--tool all` install: `binder-eval-af3`
imported `alphafold3` and `--verify` reported **usable**, while the env had no
`binder-compare` at all — the first real run would have died with
"command not found". The same env was also missing `build_data`'s CCD pickle,
which `import alphafold3` cannot see because the abort happens later, on
`alphafold3.constants.chemical_component_sets`.

The env list is PARSED FROM `evaluate.sh` rather than hardcoded, so adding a new
`binder-compare` step in a new env fails this test until its verifier follows.

Sibling guards: `test_installers_do_not_drift.py` (a tool on one platform only),
`test_referenced_conda_envs_exist.py` (an env that never existed).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EVALUATE = REPO / "Evaluator" / "evaluate.sh"
INSTALL = REPO / "install" / "install.sh"


def _envs_driven_through_binder_compare() -> dict[str, set[str]]:
    """{conda env: {subcommands}} for every `conda run -n ENV binder-compare SUB`."""
    text = EVALUATE.read_text()
    # Env names reach the call site as variables (AF3_ENV="binder-eval-af3").
    assignments = dict(re.findall(r'^([A-Z0-9_]+)="?([A-Za-z0-9._-]+)"?\s*$', text, re.M))

    found: dict[str, set[str]] = {}
    for env_ref, sub in re.findall(
        r'conda run -n "?(\$\{[A-Z0-9_]+\}|[A-Za-z0-9._-]+)"? binder-compare ([a-z0-9-]+)', text
    ):
        if env_ref.startswith("${"):
            env = assignments.get(env_ref[2:-1])
            if env is None:  # unresolvable variable: better to fail loudly
                raise AssertionError(f"could not resolve {env_ref} in evaluate.sh")
        else:
            env = env_ref
        found.setdefault(env, set()).add(sub)
    assert found, "parsed no `conda run -n ... binder-compare` calls out of evaluate.sh"
    return found


def test_every_binder_compare_env_is_verified_through_the_cli():
    problems = []
    install = INSTALL.read_text()
    for env in sorted(_envs_driven_through_binder_compare()):
        if f"_env_refold_cli_ok {env} " not in install:
            problems.append(
                f"evaluate.sh runs `binder-compare` in '{env}', but install.sh's verifier never "
                f"calls `_env_refold_cli_ok {env} <subcommand>` — an import check cannot see a "
                "missing or unstartable console script."
            )
    assert not problems, "\n".join(problems)


def test_the_cli_check_actually_runs_the_console_script():
    """A canary on the helper itself: if it degrades to a python import the test
    above keeps passing while verifying nothing."""
    body = INSTALL.read_text().split("_env_refold_cli_ok() {", 1)
    assert len(body) == 2, "install.sh no longer defines _env_refold_cli_ok"
    body = body[1].split("\n}", 1)[0]
    assert "/bin/binder-compare" in body, "_env_refold_cli_ok must invoke the binder-compare script"
    assert "--help" in body, "_env_refold_cli_ok must exercise the import chain (subcommand --help)"


def test_af3_verifier_checks_the_build_data_artifact():
    """`import alphafold3` succeeds without the CCD pickle; AF3 then aborts at run
    time. Verified by hiding the pickle on 2026-09-27 — verify must go red."""
    install = INSTALL.read_text()
    assert "_af3_ccd_built" in install, "install.sh lost the AF3 CCD (build_data) check"
    body = install.split("_af3_ccd_built() {", 1)[1].split("\n}", 1)[0]
    assert "chemical_component_sets.pickle" in body, "_af3_ccd_built must assert build_data's actual output file"
