"""A refold engine that fails must stop evaluate.sh before it writes a report.

`check_engine_rows` is the per-engine guard, and it returns 1 for each way an engine has failed: it
crashed; it exited 0 and wrote no row (ESMFold2, 2026-09-16, a TypeError from an unpinned model
revision -- the same shape as the AF3 empty-rows incident of 2026-08-21); or it wrote rows and none of
them is a design in the pool (Boltz-2, 2026-10-28, PD-L1: a stale 1003-row CSV copied into place for a
65-design pool and reported as "ok -- 1003 new row(s)").

A return code protects nobody until the caller acts on it, and no test in the repo exercised that link.
test_evaluate_sh_pool_coverage.py runs the `pool_coverage` awk and asserts, from the source text, that
`check_engine_rows` consults it and contains `return 1`; none reads what `run_engine_checked` or the
--concurrent loop DO with that 1, and the wrong answer only exists if they do nothing. With the
`|| exit 1` in `run_engine_checked` edited to `|| true` the full error still prints; then evaluate.sh
refolds the rest of the pool on the other engines, hands `binder-compare report` the CSV of the engine
that refolded none of it, prints "=== Done ===" and exits 0. The scientist gets a report.html and a
metrics.csv ranked on a primary engine whose rows are not from this campaign.

So these tests run the real evaluate.sh start to finish. Only the tools it shells out to are replaced:
a fake `conda`, and a fake `binder-compare` that logs every call and writes whatever CSV each engine has
been told to write. What is under test is the bash itself -- argument parsing, engine auto-detection, the
guards, and the decision to call the report -- and the assertions are about what the script DID (its exit
code, which engines it started, whether the report was ever called), not about its text. The one text
check per case only proves the guard fired for the reason the case set up.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EVALUATE_SH = REPO_ROOT / "Evaluator" / "evaluate.sh"

pytestmark = [
    pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available"),
    pytest.mark.skipif(shutil.which("awk") is None, reason="awk not available"),
]

# The refold engines, in the order evaluate.sh runs them when it runs them one after another.
ENGINES = ["boltz2", "af3", "esmfold2"]

POOL = ["MKTAYIAKQRQISFVKSHFSRQ", "GSDEVQLVESGGGLVQPGGSLR", "WYTRNMDQPAEKSLHCIVFGTY"]

# How an engine can fail without looking like it, and the sentence evaluate.sh gives for refusing it.
FAILURES = {
    "off_pool": "Rows from another pool cannot rank this one",  # PD-L1: rows, but none from this pool
    "empty": "wrote no new rows",  # ESMFold2: exit 0 and an empty CSV
    "crash": "refolding failed (rc=3)",  # a non-zero exit
}

# A fake `binder-compare`. Every call is logged. Each refold subcommand writes the CSV it was asked for
# (-o) in the shape $FAKE_<engine> names: ok (one row per pool design, the default), off_pool, empty, crash.
_BINDER_COMPARE = r"""#!/usr/bin/env bash
printf 'CALL %s\n' "$*" >> "$CALL_LOG"
sub=$1; shift
out=""; seqs=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -o|--output)         out=$2;  shift 2 ;;
        --sequences|--input) seqs=$2; shift 2 ;;
        *)                   shift ;;
    esac
done
case "$sub" in
    parse-seqs) cp "$seqs" "$out" ;;
    refold-boltz2|refold-af3|refold-esmfold2)
        engine=${sub#refold-}
        mode_var="FAKE_$engine"; mode=${!mode_var:-ok}
        [[ -f $out ]] || printf 'run_id,idx,sequence,target_sequence,binder_length,iptm\n' > "$out"
        case "$mode" in
            ok)
                i=0
                while read -r seq; do
                    i=$((i + 1)); printf 'r%d,%d,%s,TARGET,%d,0.80\n' "$i" "$i" "$seq" "${#seq}" >> "$out"
                done < <(grep -v '^>' "$seqs") ;;
            off_pool)
                for i in 1 2 3; do printf 's%d,%d,STALEDESIGN%d,TARGET,12,0.99\n' "$i" "$i" "$i" >> "$out"; done ;;
            empty) ;;
            crash) echo "$engine: CUDA out of memory" >&2; exit 3 ;;
        esac ;;
    report)
        mkdir -p "$out"; printf 'rank,sequence\n' > "$out/metrics.csv"; : > "$out/report.html" ;;
    *)  echo "binder-compare stub: unexpected subcommand '$sub'" >&2; exit 97 ;;
esac
"""

# A fake `conda`: `env list` names the environments in $FAKE_ENVS and `run -n ENV cmd...` runs cmd.
_CONDA = r"""#!/usr/bin/env bash
if [[ $1 == env ]]; then
    for e in $FAKE_ENVS; do echo "$e /fake/$e"; done
    exit 0
fi
if [[ $1 == run ]]; then
    shift
    [[ $1 == -n ]] && shift 2
    # the only python on this path is the target-MSA pre-warm, which has to succeed
    [[ $1 == python ]] && exit 0
    exec "$@"
fi
echo "conda stub: unexpected call: $*" >&2
exit 98
"""

# `--concurrent` refuses to run unless the CUDA MPS ceiling reports itself up.
_MPS_IS_UP = '#!/bin/sh\n[ "$1" = is-up ]\n'


@dataclass
class Run:
    returncode: int
    output: str  # stdout + stderr
    log: list[str]  # every call the fakes saw, in order
    out_dir: Path

    @property
    def engines(self) -> list[str]:
        """The refold engines that were started, in the order they were started."""
        return [line.split()[1].removeprefix("refold-") for line in self.log if line.startswith("CALL refold-")]

    @property
    def reports(self) -> int:
        """How many times `binder-compare report` was called."""
        return sum(line.startswith("CALL report ") for line in self.log)

    @property
    def metrics_csv(self) -> Path:
        return self.out_dir / "report" / "metrics.csv"

    @property
    def transcript(self) -> str:
        return f"exit {self.returncode}\n{self.output}\n--- calls ---\n" + "\n".join(self.log)


def _executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


def _run(tmp_path: Path, *, concurrent: bool = False, **engine_modes: str) -> Run:
    """Run the real evaluate.sh over a three-design pool; `engine_modes` says which engines misbehave, and how."""
    assert set(engine_modes) <= set(ENGINES), f"not an engine: {sorted(set(engine_modes) - set(ENGINES))}"

    evaluator = tmp_path / "Evaluator"
    (evaluator / "envs").mkdir(parents=True)
    shutil.copy(EVALUATE_SH, evaluator / "evaluate.sh")

    # evaluate.sh sources the first conda.sh it finds, a standalone install under the repo first. An empty
    # one there stops it reaching for a real conda on the machine running the tests, whose `conda` shell
    # function would shadow the fake.
    conda_sh = tmp_path / "conda" / "etc" / "profile.d" / "conda.sh"
    conda_sh.parent.mkdir(parents=True)
    conda_sh.write_text("# nothing to initialise\n")

    # Boltz-2 runs from the Mosaic venv's own binder-compare; the other engines reach it through conda.
    venv = tmp_path / "mosaic_venv"
    stubs = tmp_path / "stubs"
    _executable(venv / "bin" / "binder-compare", _BINDER_COMPARE)
    _executable(stubs / "binder-compare", _BINDER_COMPARE)
    _executable(stubs / "conda", _CONDA)
    (evaluator / "envs" / "mosaic_venv_path").write_text(f"{venv}\n")
    if concurrent:
        _executable(tmp_path / "tools" / "gpu_mem_guard.sh", _MPS_IS_UP)

    # AF3 only counts as an engine when its gated weights are found, and that search ends at $HOME.
    home = tmp_path / "home"
    home.mkdir()
    models = tmp_path / "af3_models"
    models.mkdir()
    (models / "af3.bin").write_text("stub")

    pool = tmp_path / "pool.fasta"
    pool.write_text("".join(f">design_{k} source=mosaic length={len(s)}\n{s}\n" for k, s in enumerate(POOL, 1)))
    log = tmp_path / "calls.log"
    log.write_text("")

    env = {k: v for k, v in os.environ.items() if not k.startswith("BINDMASTER_") and k not in ("BASH_ENV", "ENV")}
    env.update(
        PATH=f"{stubs}{os.pathsep}{os.environ['PATH']}",
        HOME=str(home),
        AF3_MODEL_DIR=str(models),
        FAKE_ENVS="base binder-eval binder-eval-af3 binder-eval-esmfold2",
        CALL_LOG=str(log),
    )
    env.update({f"FAKE_{engine}": mode for engine, mode in engine_modes.items()})

    out = tmp_path / "out"
    argv = ["--sequences", str(pool), "--target-seq", "MKTAYIAKQRQ", "--output", str(out), "--skip-soluprot"]
    if concurrent:
        argv += ["--concurrent", "--stagger", "0"]  # all three engines start at once, with no wait
    proc = subprocess.run(
        ["bash", str(evaluator / "evaluate.sh"), *argv],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=120,
    )
    return Run(proc.returncode, proc.stdout + proc.stderr, log.read_text().splitlines(), out)


def _assert_stopped_before_the_report(run: Run, failure: str) -> None:
    """The run said why, exited non-zero, and never got as far as the report or the 'done' banner."""
    assert FAILURES[failure] in run.output, f"the guard did not fire for this case:\n{run.transcript}"
    assert run.returncode != 0, f"the run exited 0 after refusing an engine:\n{run.transcript}"
    assert run.reports == 0, f"binder-compare report was called on a pool an engine had failed:\n{run.transcript}"
    assert not run.metrics_csv.exists(), f"a metrics.csv was written:\n{run.transcript}"
    assert "=== Done ===" not in run.output, f"the run announced success:\n{run.transcript}"


class TestTheStubbedRunReachesTheReport:
    """Guards the guards: every 'never reached the report' below would pass for free on a harness that
    could not reach the report in the first place."""

    @pytest.mark.parametrize("concurrent", [False, True], ids=["sequential", "concurrent"])
    def test_a_healthy_run_refolds_on_all_three_engines_and_writes_the_report(self, tmp_path, concurrent):
        run = _run(tmp_path, concurrent=concurrent)
        assert run.returncode == 0, run.transcript
        assert sorted(run.engines) == sorted(ENGINES), run.transcript
        assert run.output.count("ok -- 3/3 pool design(s)") == len(ENGINES), (
            f"every engine should be judged to cover the pool:\n{run.transcript}"
        )
        assert run.reports == 1, run.transcript
        assert run.metrics_csv.exists(), run.transcript

    def test_the_sequential_run_starts_the_engines_in_the_documented_order(self, tmp_path):
        assert _run(tmp_path).engines == ENGINES


@pytest.mark.parametrize("failure", FAILURES)
@pytest.mark.parametrize("engine", ENGINES)
class TestTheSequentialRunStopsAtTheFirstBadEngine:
    """`run_engine_checked` must act on `check_engine_rows`: stop here, and spend nothing on the engines after."""

    def test_the_run_exits_nonzero_and_never_reaches_the_report(self, tmp_path, engine, failure):
        _assert_stopped_before_the_report(_run(tmp_path, **{engine: failure}), failure)

    def test_the_engines_after_it_are_never_started(self, tmp_path, engine, failure):
        run = _run(tmp_path, **{engine: failure})
        assert run.engines == ENGINES[: ENGINES.index(engine) + 1], run.transcript


@pytest.mark.parametrize("failure", FAILURES)
@pytest.mark.parametrize("engine", ENGINES)
class TestTheConcurrentRunStopsOnceAnyEngineIsJudgedBad:
    """The --concurrent loop is a second, separate copy of the same wiring (`ENGINE_FAIL`)."""

    def test_the_run_exits_nonzero_and_never_reaches_the_report(self, tmp_path, engine, failure):
        run = _run(tmp_path, concurrent=True, **{engine: failure})
        _assert_stopped_before_the_report(run, failure)
        # all three were launched up front, so it was the verdict that stopped the run
        assert sorted(run.engines) == sorted(ENGINES), run.transcript
