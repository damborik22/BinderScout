"""SoluProt labels; it does not rank, gate, or delete.

Decision 2026-09-28, after measuring it against our own experimental results on two
targets: SoluProt is kept as a **label** only. It was never part of `rank` or
`consensus_iptm_mean`, but it had two other powers, and both have been removed.

**Why.** SoluProt is good at its real job — in the BindPred run it was the best available
predictor of whether a design yielded a measurement at all, which is expression and
solubility. But solubility and affinity are close to orthogonal on these pools: at the
paper threshold of 0.5 it failed **four of the ten tightest measured binders** on one
target, including a sub-0.1 nM design. So anything that lets SoluProt *withhold* or
*delete* a design loses top binders at a rate no threshold controls.

What it may still do: report its score and its pass/fail verdict, so a human weighing
what to order can see it. That is a label.

(Numbers live in the internal `Claude outputs/` folders — this repo is public and the
SPOC results are unpublished.)
"""

from __future__ import annotations

from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from binder_comparison.comparison.scoring import annotate_wetlab_recommended  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
EVALUATE = REPO / "Evaluator" / "evaluate.sh"
CONFIGURATOR = REPO / "configurator" / "configurator.py"


def _clean_pool(n=3):
    """A pool with nothing else wrong, so SoluProt is the only thing under test."""
    return pd.DataFrame(
        {
            "sequence": [f"{'A' * 30}{i}" for i in range(n)],
            "consensus_iptm_mean": [0.9] * n,
            "consensus_iptm_n": [3] * n,
            "passes_engine_gate": [True] * n,
            "agreement_count": [2] * n,
            "plddt_binder_min": [0.9] * n,
        }
    )


def test_a_soluprot_failure_does_not_withhold_the_wetlab_recommendation():
    d = _clean_pool(3)
    d["native_soluprot_passes"] = [True, False, None]
    out = annotate_wetlab_recommended(d)
    assert list(out["wetlab_recommended"]) == [True, True, True], (
        "a SoluProt failure must not set wetlab_recommended to False — it would withhold "
        "the recommendation from designs measured to be among the tightest binders"
    )


def test_the_soluprot_verdict_is_still_reported():
    """Removing the block must not remove the information."""
    d = _clean_pool(2)
    d["native_soluprot_passes"] = [True, False]
    out = annotate_wetlab_recommended(d)
    assert "soluprot" in str(out.loc[1, "wetlab_reason"]).lower(), (
        "the SoluProt verdict must still appear for the operator, just not as a blocker"
    )
    assert "soluprot" not in str(out.loc[0, "wetlab_reason"]).lower(), (
        "a passing design should not carry a SoluProt note"
    )


def test_evaluate_sh_refuses_the_pre_refold_filter():
    """RUNS evaluate.sh with the flag rather than reading its text.

    Two text-scanning versions of this test were hollow. The first read a fixed character
    window that held only the explanatory comment. The second scanned lines until a bare
    `;;` -- so when a mutation collapsed the branch onto one line, the scan ran off the
    end of the file and matched an `exit 1` belonging to something else. Invoking the
    script cannot be fooled that way: either the flag is refused or it is not.
    """
    import subprocess

    r = subprocess.run(
        ["bash", str(EVALUATE), "--soluprot-filter"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO,
    )
    assert r.returncode != 0, (
        "--soluprot-filter must fail loudly. Silently accepting or ignoring it hands the "
        f"caller different data than they asked for. stdout={r.stdout[:200]!r}"
    )
    combined = (r.stderr + r.stdout).lower()
    assert "soluprot" in combined and ("removed" in combined or "label" in combined), (
        f"the refusal must explain itself. Got: {(r.stderr or r.stdout)[:300]!r}"
    )


def _load_configurator(name):
    """Import configurator.py by path. It is a script, not a package module."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, CONFIGURATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _captured(capsys):
    """One readouterr call: a second returns an empty buffer and hides the first."""
    c = capsys.readouterr()
    return (c.out + c.err).lower()


def _write_config(path, target, tmp_path, **extra):
    import json

    path.write_text(
        json.dumps(
            {
                "config_version": 1,
                "cfg": {
                    "run_dir": str(tmp_path / "run"),
                    "name": "t",
                    "target_pdb_src": str(target),
                    **extra,
                },
                "tools_enabled": {"mosaic": True, **extra},
            }
        )
    )
    return path


def test_the_configurator_never_emits_the_filter_flag(tmp_path):
    """GENERATES a run_evaluate.sh and reads it, rather than grepping the generator.

    The version this replaced was two negative greps over configurator.py source text
    (`"soluprot_filter = ask_yn" not in text`). Both keep passing if the wizard grows a
    differently-spelled question or builds the flag from a variable, and the sibling test
    above was rewritten for exactly that defect -- a grep for absence is the weakest
    assertion in the file, because every refactor makes it pass harder.
    """
    mod = _load_configurator("bs_cfg_emit")

    base = {
        "name": "t",
        "target_sequence": "MKTAYIAKQRQ",
        "use_soluprot": True,
        "soluprot_threshold": 0.5,
        "use_boltz": True,
        "use_af3": True,
        "use_esmfold2": True,
        "primary_engine": "boltz",
    }
    # Several shapes, not one. Pinning a single key name let the emission come back
    # behind a renamed key and the test still passed. These cover the stale key, a
    # plausible rename, and the clean case.
    variants = {
        "clean": {},
        "stale key": {"soluprot_filter": True},
        "renamed": {"soluprot_prefilter": True, "drop_insoluble": True},
    }
    for label, extra in variants.items():
        run_dir = tmp_path / label.replace(" ", "_")
        (run_dir / "evaluate").mkdir(parents=True)
        out = run_dir / "run_evaluate.sh"
        mod.write_run_evaluate(out, {**base, "run_dir": run_dir, **extra}, {"mosaic": True})
        script = out.read_text()

        assert "--soluprot-filter" not in script, (
            f"[{label}] the generated run script passes --soluprot-filter, which "
            f"evaluate.sh refuses with exit 1 — the run would die before any design was "
            f"refolded.\nGot:\n{script}"
        )
        # ...and the screen itself is still wired, or this would pass on a script that
        # simply dropped SoluProt altogether.
        assert "--soluprot-threshold" in script, (
            f"[{label}] SoluProt is still a label we want scored; only the filter was removed"
        )


def test_a_stale_config_says_so_and_the_key_does_not_round_trip(capsys, tmp_path):
    """An old config.json with soluprot_filter=true replays a LARGER pool than it ran.

    Three assertions, because the first version of this test had none of the teeth:
    matching ``"soluprot_filter" in output`` passed on *any* echo of the config, so
    deleting the warning entirely still passed. It also could not tell a conditional
    warning from ``if True:`` — a warning that fires on every load is one operators
    learn to skip.
    """
    mod = _load_configurator("bs_cfg_warn")
    target = tmp_path / "t.pdb"
    target.write_text("")

    stale = _write_config(tmp_path / "stale.json", target, tmp_path, soluprot_filter=True)
    cfg, tools_enabled = mod.load_run_config(stale)
    warned = _captured(capsys)

    # 1. the warning fires, and says the thing that matters (the pool CHANGES)
    assert "larger" in warned, f"the warning must say the replayed pool differs; got: {warned!r}"
    assert "soluprot" in warned

    # 2. the key is DROPPED, not just complained about. Left in cfg it is written
    #    straight back into the regenerated config.json, so it is never retired and the
    #    warning fires forever on every later replay.
    assert "soluprot_filter" not in cfg, "the stale key round-trips into the new config"
    assert "soluprot_filter" not in tools_enabled

    # 3. a CLEAN config must stay silent, or the warning is noise on every load
    clean = _write_config(tmp_path / "clean.json", target, tmp_path)
    mod.load_run_config(clean)
    assert "soluprot" not in _captured(capsys), "a clean config must not trigger the warning"


def test_the_wizard_and_the_writer_agree_on_the_cfg_keys():
    """The wizard writes cfg keys; ``write_run_evaluate`` reads them. Nothing checked
    that the two spellings match.

    Found by adversarial review 2026-09-29: renaming the wizard's ``"use_soluprot"``
    key makes ``write_run_evaluate``'s ``cfg.get("use_soluprot", False)`` fall through
    to False, so EVERY generated run script gets ``--skip-soluprot`` and SoluProt
    silently scores nothing — with the whole suite green, because both behavioural
    tests above hand-build their own cfg and never touch the wizard's dict.

    This reads the two sides out of the AST rather than executing the wizard, which is
    ~80 interactive prompts.
    """
    import ast

    tree = ast.parse(CONFIGURATOR.read_text())
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "wizard" in funcs and "write_run_evaluate" in funcs

    # Keys the writer reads off cfg.
    read = {
        n.args[0].value
        for n in ast.walk(funcs["write_run_evaluate"])
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "get"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "cfg"
        and n.args
        and isinstance(n.args[0], ast.Constant)
        and isinstance(n.args[0].value, str)
    }
    # Keys the wizard writes into the dict it calls `cfg` -- NOT every dict literal in
    # the function. `use_soluprot` is written into BOTH `tools_enabled` and `cfg`, so a
    # union over all dicts cannot see a rename of the cfg one: the tools_enabled copy
    # keeps the union satisfied while write_run_evaluate falls through to the default.
    # Note `cfg: dict = {...}` is an AnnAssign, not an Assign.
    written = set()
    for n in ast.walk(funcs["wizard"]):
        target = None
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            target = n.targets[0].id
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            target = n.target.id
        if target == "cfg" and isinstance(n.value, ast.Dict):
            written |= {k.value for k in n.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    assert written, "could not find the wizard's cfg dict literal — the test cannot work"

    # Only the evaluator contract — the writer also reads per-tool keys that live in
    # tools_enabled, and cfg keys set elsewhere, so this is deliberately scoped.
    contract = {"use_soluprot", "soluprot_threshold", "use_tmprot", "tmprot_threshold"}
    missing = sorted((contract & read) - written)
    assert not missing, (
        f"write_run_evaluate reads cfg keys the wizard never writes: {missing}. "
        "Every generated run script silently takes the default for these — for "
        "use_soluprot that means --skip-soluprot on every run and no solubility column."
    )
