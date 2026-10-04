"""A blank refold row must never pass for a score, at any of the four places it could.

THE FAILURE
-----------
ESMFold2 and AF3 catch a per-design CUDA OOM, write a row with ``idx`` and ``sequence``
filled in and every score blank, and continue.  Boltz-2 omits the row entirely.  Either
way the design loses an engine, so ``consensus_iptm_mean`` is taken over the survivors
and the design drops below the ``>=3``-engine gate -- and in ``metrics.csv`` that is
indistinguishable from three engines having disliked it.  A design demoted for a
hardware reason is reported as a quality judgement.

Measured: a 24 GB card at 900 tokens produced "Wrote 1 row(s)" with rc=0
(docs/data/gpu_benchmark_2026-09-18/README.md), and a 12 GB RTX 3060 cannot run
ESMFold2 at any size -- 14,248 MiB at 150 tokens on a 3090, 13,781 on GB10, a floor
rather than a slope, because the number is resident-weight cost.

Each engine already refused when *every* design failed.  None refused when some did,
and the four ways that stayed silent are each pinned below:

  1. the engines ran at all on a card that cannot hold the weights   -> device floor
  2. a partial failure exited 0                                      -> PartialRefoldFailure
  3. ``--resume`` treated a blank row as completed, so the retry
     skipped exactly the designs it existed to repair               -> resume on the score
  4. ``evaluate.sh`` asked "did the CSV gain rows?", and a blank
     row is a row                                                    -> count scored rows

(1) and (3) are tested by calling the real functions.  (2) is static for the reason
``test_af3_bucket_has_a_floor.py`` gives: executing a refold costs a GPU.  (4) runs the
shell function's own text, extracted from the shipped script rather than copied.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "Evaluator" / "scripts"
sys.path.insert(0, str(REPO / "Evaluator"))

from binder_comparison.refolding import af3_runner, boltz2_runner, esmfold2_runner  # noqa: E402
from binder_comparison.refolding import memory_policy as mp  # noqa: E402
from binder_comparison.refolding.errors import PartialRefoldFailure as PackagePartialRefoldFailure  # noqa: E402

# ---------------------------------------------------------------------------
# 1. The device floor -- refuse before loading weights
# ---------------------------------------------------------------------------


def test_only_esmfold2_has_a_floor_and_the_absences_are_deliberate():
    """Pinned as a literal, so deleting the entry or adding a guessed one fails.

    Boltz-2 and AF3 are absent on purpose.  Boltz-2's demand scales hard AND
    card-dependently (8,518 MiB at 150 tokens on a 3090, 16,712 at 300, failure at 600,
    while GB10 needs ~1.5x a discrete card for identical work), so any static floor
    would either refuse a card that can fold a 60-token complex -- CALCA is 60 -- or
    pass one that cannot do 300.  AF3 never exceeded 5,224 MiB anywhere.  A floor is
    only honest for a cost that does not fall with input size.
    """
    assert mp.ENGINE_MIN_DEVICE_MIB == {"esmfold2": 14248}


def test_a_card_below_the_floor_is_refused(monkeypatch):
    monkeypatch.setattr(mp, "device_total_mib", lambda: 12288)  # RTX 3060
    with pytest.raises(mp.InsufficientDeviceMemory) as exc:
        mp.require_device_memory("esmfold2", env={})
    msg = str(exc.value)
    assert "12288" in msg and "14248" in msg
    # The refusal must hand over a way forward, or it just blocks the operator.
    assert mp.ALLOW_SMALL_GPU_ENV in msg
    assert "--min-engines 2" in msg


def test_a_card_at_or_above_the_floor_is_allowed(monkeypatch):
    for total in (14248, 24576, 122000):
        monkeypatch.setattr(mp, "device_total_mib", lambda t=total: t)
        assert mp.require_device_memory("esmfold2", env={}) == total


def test_the_override_proceeds_but_says_the_output_is_not_authoritative(monkeypatch, capsys):
    monkeypatch.setattr(mp, "device_total_mib", lambda: 12288)
    assert mp.require_device_memory("esmfold2", env={mp.ALLOW_SMALL_GPU_ENV: "1"}) == 12288
    err = capsys.readouterr().err
    assert "NOT AUTHORITATIVE" in err, "the override must say what it is buying, or it is a silent downgrade"


def test_an_engine_with_no_floor_is_not_refused(monkeypatch):
    monkeypatch.setattr(mp, "device_total_mib", lambda: 1024)
    for engine in ("boltz2", "af3"):
        assert mp.require_device_memory(engine, env={}) == 1024


def test_an_unmeasurable_pool_is_not_refused(monkeypatch):
    """CPU-only CI and containers without the NVIDIA stack must still import and run.

    Refusing here would be refusing on an assumption about size rather than a
    measurement, which is the error this whole file is about.
    """
    monkeypatch.setattr(mp, "device_total_mib", lambda: 0)
    assert mp.require_device_memory("esmfold2", env={}) == 0


def test_esmfold2_actually_calls_the_floor_check_before_spending_anything():
    """A real call inside refold_batch, ordered before the MSA fetch and the weight load.

    Checked as AST, not as a substring: commenting the call out
    (``pass  # require_device_memory("esmfold2")``) left a substring assertion green,
    so the guard was verifiable as text while being absent as behaviour.
    """
    tree = ast.parse((SCRIPTS / "refold_esmfold2.py").read_text())
    fn = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "refold_batch"),
        None,
    )
    assert fn is not None, "refold_batch not found in refold_esmfold2.py"

    def _call_lines(name):
        return [
            n.lineno
            for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name
        ]

    floor = _call_lines("require_device_memory")
    assert floor, "refold_batch does not call require_device_memory -- the floor is unenforced"

    msa = _call_lines("prepare_target_msa")
    load = _call_lines("_load_model_and_builder")
    assert msa, "prepare_target_msa call not found -- this ordering test has gone stale"
    assert load, "_load_model_and_builder call not found -- this ordering test has gone stale"
    assert min(floor) < min(msa), "the floor must be checked before the MSA fetch"
    assert min(floor) < min(load), "the floor must be checked before the multi-GB weight load"


# ---------------------------------------------------------------------------
# 2. A partial failure must exit non-zero
# ---------------------------------------------------------------------------

_PARTIAL = {
    # script                counter      the all-failed guard it sits beside
    "refold_esmfold2.py": ("n_failed", "n_failed == len(jobs)"),
    "refold_af3.py": ("n_failed", "n_failed == len(jobs)"),
    "refold_boltz2.py": ("n_skipped", "n_skipped == n_todo"),
}


@pytest.mark.parametrize("script", sorted(_PARTIAL))
def test_every_refold_script_defines_the_partial_failure_type(script):
    tree = ast.parse((SCRIPTS / script).read_text())
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    assert "PartialRefoldFailure" in names, f"{script} has no PartialRefoldFailure to raise"


@pytest.mark.parametrize("script", sorted(_PARTIAL))
def test_every_refold_script_raises_on_a_partial_failure(script):
    """`if <counter>:` must raise -- not warn, not print, not pass."""
    counter, _ = _PARTIAL[script]
    tree = ast.parse((SCRIPTS / script).read_text())
    guards = [
        n for n in ast.walk(tree) if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == counter
    ]
    assert guards, f"{script} has no bare `if {counter}:` guard"
    raises = [
        r
        for g in guards
        for r in ast.walk(g)
        if isinstance(r, ast.Raise)
        and isinstance(r.exc, ast.Call)
        and isinstance(r.exc.func, ast.Name)
        and r.exc.func.id == "PartialRefoldFailure"
    ]
    assert raises, (
        f"{script}: `if {counter}:` exists but does not raise PartialRefoldFailure. "
        "A partial pool that exits 0 is the defect this guard was added for."
    )


@pytest.mark.parametrize("script", sorted(_PARTIAL))
def test_the_all_failed_guard_still_exists(script):
    """The earlier guard must not be *replaced* by the partial one.

    They say different things: all-failed is an environment fault with engine-specific
    advice, partial is "re-run these indices".  Collapsing them loses the advice.
    """
    _, all_failed = _PARTIAL[script]
    assert all_failed in (SCRIPTS / script).read_text(), f"{script} lost its all-failed guard"


@pytest.mark.parametrize("script", sorted(_PARTIAL))
def test_the_partial_failure_names_which_designs_failed(script):
    """Without the indices the operator cannot re-run only the gap."""
    src = (SCRIPTS / script).read_text()
    assert re.search(r"(failed_idx|skipped_idx)\.append\(idx\)", src), (
        f"{script} counts failures without recording which ones, so its message cannot name them"
    )
    assert "indices:" in src


@pytest.mark.parametrize("script", sorted(_PARTIAL))
def test_a_partial_failure_exits_3_not_1(script):
    """3 means "rows are on disk, re-run these indices"; 1 means "this env is broken"."""
    src = (SCRIPTS / script).read_text()
    m = re.search(r"except PartialRefoldFailure as exc:(.{0,400})", src, re.S)
    assert m, f"{script}'s main() does not handle PartialRefoldFailure"
    assert re.search(r"(sys\.exit\(3\)|SystemExit\(3\))", m.group(1)), (
        f"{script} handles PartialRefoldFailure without exiting 3"
    )


# ---------------------------------------------------------------------------
# 2b. ...and the CLI, which is the path production uses
# ---------------------------------------------------------------------------
#
# The checks above read the scripts' own main(), which `binder-compare refold-<engine>`
# never calls. The console script is binder_comparison.main:main, where the exception
# used to escape uncaught -- so the exit-3 contract was pinned only on a dead path and
# every real run exited 1 with a traceback.


@pytest.mark.parametrize(
    ("subcommand", "cli_module", "entry"),
    [
        ("refold-af3", "refold_af3", "run_af3_refold"),
        ("refold-esmfold2", "refold_esmfold2", "run_esmfold2_refold"),
        ("refold-boltz2", "refold_boltz2", "run_boltz2_refold"),
    ],
)
def test_the_cli_maps_a_partial_failure_to_exit_3(monkeypatch, tmp_path, subcommand, cli_module, entry):
    import importlib

    from binder_comparison import main as main_mod
    from binder_comparison.refolding.errors import PartialRefoldFailure

    mod = importlib.import_module(f"binder_comparison.cli.{cli_module}")

    def _partial(**kwargs):
        raise PartialRefoldFailure("2 of 5 binder(s) failed -- indices: 3, 4")

    monkeypatch.setattr(mod, entry, _partial)

    fasta = tmp_path / "seqs.fasta"
    fasta.write_text(">d_0001 tool=mosaic\nAAAWWWAAA\n")

    with pytest.raises(SystemExit) as excinfo:
        main_mod.main(
            [
                subcommand,
                "--sequences",
                str(fasta),
                "--target-seq",
                "TTTTTT",
                "--output",
                str(tmp_path / "engine.csv"),
            ]
        )
    assert excinfo.value.code == 3, (
        f"`binder-compare {subcommand}` exited {excinfo.value.code!r} on a partial failure; "
        "3 means 'rows are on disk, re-run these indices' and 1 means 'this env is broken'"
    )


# ---------------------------------------------------------------------------
# 3. Resume must key on the score, not on the row
# ---------------------------------------------------------------------------

_SCORED = "run_id,idx,sequence,target_sequence,binder_length,iptm,ptm\n"


@pytest.mark.parametrize(
    "runner",
    [esmfold2_runner, af3_runner, boltz2_runner],
    ids=lambda m: m.__name__.rsplit(".", 1)[-1],
)
def test_resume_does_not_treat_a_blank_row_as_completed(runner, tmp_path):
    """The whole point of a retry is to re-run the blanks.

    Keying on ``idx`` skipped them -- a blank row has an idx -- so the re-run after a
    partial OOM reproduced the gap exactly and reported success.
    """
    csv = tmp_path / "r.csv"
    csv.write_text(_SCORED + "a,1,AAA,TTT,3,0.81,0.70\n" + "b,2,BBB,TTT,3,,\n" + "c,3,CCC,TTT,3,0.44,0.50\n")
    assert runner._load_completed_indices(csv) == {1, 3}, (
        "design 2 folded to a blank row; resume must retry it, not skip it"
    )


@pytest.mark.parametrize(
    "runner",
    [esmfold2_runner, af3_runner, boltz2_runner],
    ids=lambda m: m.__name__.rsplit(".", 1)[-1],
)
def test_resume_still_skips_rows_that_really_are_complete(runner, tmp_path):
    """The fix must not turn every resume into a full re-run."""
    csv = tmp_path / "r.csv"
    csv.write_text(_SCORED + "a,1,AAA,TTT,3,0.81,0.70\n" + "b,2,BBB,TTT,3,0.62,0.60\n")
    assert runner._load_completed_indices(csv) == {1, 2}


@pytest.mark.parametrize(
    "runner",
    [esmfold2_runner, af3_runner, boltz2_runner],
    ids=lambda m: m.__name__.rsplit(".", 1)[-1],
)
def test_a_wholly_blank_csv_resumes_nothing(runner, tmp_path):
    csv = tmp_path / "r.csv"
    csv.write_text(_SCORED + "a,1,AAA,TTT,3,,\n" + "b,2,BBB,TTT,3,,\n")
    assert runner._load_completed_indices(csv) == set()


# ---------------------------------------------------------------------------
# 3b. The runner boundary -- where production actually lives
# ---------------------------------------------------------------------------
#
# `binder-compare refold-<engine>` calls the runner, not the script's main(), so a
# runner that swallows PartialRefoldFailure restores the entire defect: the engine
# exits 0 with a half-blank CSV and evaluate.sh reports a complete pool. Mutation
# M14 (replacing `raise partial` with `pass`) passed every other test in this file.
#
# Tested by injecting a stub into sys.modules under the name the runner imports, so
# the real boundary runs without torch, JAX or a GPU.

_RUNNERS = {
    "refold_esmfold2": (esmfold2_runner, "run_esmfold2_refold"),
    "refold_af3": (af3_runner, "run_af3_refold"),
    "refold_boltz2": (boltz2_runner, "run_boltz2_refold"),
}


def _install_stub(monkeypatch, script_name: str, output_csv: Path, boltz2_dir: Path | None):
    """A fake refold script that writes one scored row, one blank row, then raises."""

    class PartialRefoldFailure(RuntimeError):
        pass

    def refold_batch(**kwargs):
        # Boltz-2's runner publishes from refold_designs.csv in CWD; the other two are
        # handed output_csv directly. Write wherever this engine really writes.
        dest = boltz2_dir / "refold_designs.csv" if boltz2_dir else output_csv
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_SCORED + "a,1,AAA,TTT,3,0.81,0.70\n" + "b,2,BBB,TTT,3,,\n")
        raise PartialRefoldFailure("2 of 2 binder(s) failed")

    import types

    mod = types.ModuleType(script_name)
    mod.PartialRefoldFailure = PartialRefoldFailure
    mod.refold_batch = refold_batch
    monkeypatch.setitem(sys.modules, script_name, mod)


@pytest.mark.parametrize("script_name", sorted(_RUNNERS))
def test_the_runner_re_raises_a_partial_failure(monkeypatch, tmp_path, script_name):
    runner, entry = _RUNNERS[script_name]
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    csv = tmp_path / "engine.csv"
    _install_stub(monkeypatch, script_name, csv, out_dir if "boltz2" in script_name else None)

    # The canonical class, not the stub's: the runners translate the script's own
    # PartialRefoldFailure into binder_comparison.refolding.errors' one so the CLI has a
    # single class to map to exit 3 whichever way the script was loaded.
    with pytest.raises(PackagePartialRefoldFailure):
        getattr(runner, entry)(
            sequences=["AAA", "BBB"],
            target_sequence="TTT",
            output_dir=out_dir,
            output_csv=csv,
        )


@pytest.mark.parametrize("script_name", sorted(_RUNNERS))
def test_the_runner_keeps_the_rows_that_did_fold(monkeypatch, tmp_path, script_name):
    """Exiting non-zero must not throw away finished work.

    The scored rows are what let an operator re-run only the gap, and for Boltz-2 and
    ESMFold2/AF3 alike the publish/absolutise step sits AFTER the call -- so letting the
    exception fly straight through stranded them.
    """
    runner, entry = _RUNNERS[script_name]
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    csv = tmp_path / "engine.csv"
    _install_stub(monkeypatch, script_name, csv, out_dir if "boltz2" in script_name else None)

    # The canonical class, not the stub's: the runners translate the script's own
    # PartialRefoldFailure into binder_comparison.refolding.errors' one so the CLI has a
    # single class to map to exit 3 whichever way the script was loaded.
    with pytest.raises(PackagePartialRefoldFailure):
        getattr(runner, entry)(
            sequences=["AAA", "BBB"],
            target_sequence="TTT",
            output_dir=out_dir,
            output_csv=csv,
        )

    assert csv.exists(), f"{script_name}: the partial failure stranded the rows that folded"
    assert "0.81" in csv.read_text()


# ---------------------------------------------------------------------------
# 4. evaluate.sh must count scored rows, not rows
# ---------------------------------------------------------------------------

EVALUATE_SH = REPO / "Evaluator" / "evaluate.sh"


def _csv_rows_fn() -> str:
    """Extract the shipped csv_rows() so this tests the real text, not a copy."""
    src = EVALUATE_SH.read_text()
    m = re.search(r"^csv_rows \(\) \{.*?^\}", src, re.S | re.M)
    assert m, "csv_rows() not found in evaluate.sh -- the guard it feeds cannot be verified"
    return m.group(0)


def _count(tmp_path: Path, body: str) -> int:
    csv = tmp_path / "e.csv"
    csv.write_text(body)
    out = subprocess.run(
        ["bash", "-c", _csv_rows_fn() + f'\ncsv_rows "{csv}"'],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(out.stdout.strip())


def test_a_csv_of_blank_rows_counts_as_zero(tmp_path):
    """This is the measured failure: 50 blanks reported as "ok -- 50 new row(s)"."""
    assert _count(tmp_path, _SCORED + "a,1,AAA,TTT,3,,\n" * 1 + "b,2,BBB,TTT,3,,\n") == 0


def test_scored_rows_are_counted(tmp_path):
    assert _count(tmp_path, _SCORED + "a,1,AAA,TTT,3,0.81,0.7\nb,2,BBB,TTT,3,0.62,0.6\n") == 2


def test_a_half_blank_csv_counts_only_the_scored_half(tmp_path):
    assert _count(tmp_path, _SCORED + "a,1,AAA,TTT,3,0.81,0.7\nb,2,BBB,TTT,3,,\nc,3,C,TTT,1,0.4,0.5\n") == 2


def test_a_header_only_csv_counts_as_zero(tmp_path):
    assert _count(tmp_path, _SCORED) == 0


def test_the_count_finds_iptm_by_name_not_by_position(tmp_path):
    """The three engines' CSVs have different column orders.

    A hard-coded field index would read a different column per engine and silently
    count the wrong thing -- which is the same class of defect as counting rows.
    """
    reordered = "idx,iptm,run_id\n1,0.81,a\n2,,b\n"
    assert _count(tmp_path, reordered) == 1


def test_the_guard_says_it_counts_scored_rows():
    """The operator reads this message when a run aborts; it must not say "rows"."""
    src = EVALUATE_SH.read_text()
    assert "no new SCORED rows" in src


# ---------------------------------------------------------------------------
# 5. The installer must not declare success on a card that cannot fold
# ---------------------------------------------------------------------------
#
# The runtime refusal is correct but late: the installer verified that
# `binder-compare refold-esmfold2 --help` parses and then printed "ESMFold2 refolder
# installation complete" on a 12 GB box. That is the pattern this project has already paid
# for twice -- CLAUDE.md records BindCraft 1 and PXDesign both reporting themselves healthy
# while being unusable on Spark. A warning, not a refusal: installing on a small box is
# legitimate (CI, development, an env that will be used elsewhere).

INSTALLERS = [REPO / "install" / "install.sh", REPO / "install" / "install_aarch.sh"]


@pytest.mark.parametrize("installer", INSTALLERS, ids=lambda p: p.name)
def test_both_installers_check_the_device_floor(installer):
    """Parity: test_installers_do_not_drift compares --tool vocabulary, not this."""
    src = installer.read_text()
    assert "_esm_floor_check" in src, f"{installer.name} installs ESMFold2 without checking the card"
    i_check = src.index("_esm_floor_check()")
    i_done = src.index('print_ok "ESMFold2 refolder installation complete"')
    assert i_check < i_done, "the check must run before the success message, not after"


@pytest.mark.parametrize("installer", INSTALLERS, ids=lambda p: p.name)
def test_the_installer_reads_the_floor_instead_of_repeating_it(installer):
    """A second copy of 14248 is a second thing to forget to update.

    The installer imports ENGINE_MIN_DEVICE_MIB, so the installer and the runtime cannot
    disagree about what the floor is.
    """
    src = installer.read_text()
    assert "ENGINE_MIN_DEVICE_MIB" in src
    block = src[src.index("_esm_floor_check()") : src.index('print_ok "ESMFold2 refolder installation complete"')]
    assert "14248" not in block, "the installer hard-codes the floor instead of reading it"


def _floor_warning_block() -> str:
    """The shipped shell logic, extracted rather than copied."""
    src = INSTALLERS[0].read_text()
    start = src.index("    if _esm_card=$(_esm_floor_check); then :; else")
    end = src.index('print_ok "ESMFold2 refolder installation complete"', start)
    return src[start:end]


@pytest.mark.parametrize(
    ("rc", "stdout", "expect_warning"),
    [
        (7, "12288 14248", True),  # a 3060: below the floor
        (0, "", False),  # a big card, or unmeasurable
        (1, "", False),  # the probe itself broke -- must not warn about memory
    ],
)
def test_the_floor_warning_fires_only_when_the_card_is_too_small(tmp_path, rc, stdout, expect_warning):
    """Reading `$?` inside an `else` branch is fragile enough to be worth executing."""
    script = tmp_path / "t.sh"
    script.write_text(
        'print_warn () { echo "WARN: $*"; }\n'
        f'_esm_floor_check () {{ printf "%s" "{stdout}"; return {rc}; }}\n' + _floor_warning_block()
    )
    out = subprocess.run(["bash", str(script)], capture_output=True, text=True, check=False)
    warned = "WARN:" in out.stdout
    assert warned is expect_warning, f"rc={rc} stdout={stdout!r} -> warned={warned}, stdout={out.stdout!r}"
    if expect_warning:
        assert "12288" in out.stdout and "14248" in out.stdout, "the warning must name both numbers"
        assert "--skip-esmfold2" in out.stdout, "the warning must give the operator a way forward"
