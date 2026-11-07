"""evaluate.sh drives the chosen second engine (Part 2, Task 18).

The panel has exactly one second engine, AF3 (the default) or Protenix, and `evaluate.sh`
decides which ONCE, after flag parsing and env/weights detection (R3):

* an explicit ``--second-engine X`` wins and is never swapped: if X is unusable it is skipped BY
  NAME, and the other engine does not take its place;
* with no flag the slot is AF3 when its env and weights are usable; otherwise Protenix, but only
  when neither ``--skip-af3`` nor ``--skip-second`` was given and Protenix's env AND its
  size-checked checkpoint are present (a notice names the panel); otherwise the slot is skipped by
  name exactly as before;
* never both engines.

Every `conda` call goes through a stub that logs its argv (one JSON line per call) and emulates
just enough (`parse-seqs`, `refold-*` writing a scored CSV) for the script to run end to end with
no env, no GPU and no model. Nothing here touches a real conda env or runs a refold.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EVALUATE_SH = REPO_ROOT / "Evaluator" / "evaluate.sh"

CKPT_BYTES = 1475950125
CKPT_REL = Path("weights/protenix/checkpoint/protenix_base_default_v1.0.0.pt")

ALL_ENVS = ["binder-eval", "binder-eval-af3", "binder-eval-esmfold2", "binder-eval-protenix"]
NO_PROTENIX = ["binder-eval", "binder-eval-af3", "binder-eval-esmfold2"]
NO_AF3 = ["binder-eval", "binder-eval-esmfold2", "binder-eval-protenix"]
NEITHER = ["binder-eval", "binder-eval-esmfold2"]

PANEL_NOTICE = (
    "second engine: Protenix (AF3 not available); panel Boltz-2 + Protenix + ESMFold2; "
    "scores from different panels are not on one scale."
)

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")

# The stub is a real executable: `env $(cap_env ...) conda run ...` execs `conda` from PATH, so a
# shell function alone would never be consulted for the engine calls.
_STUB = f"""#!{sys.executable}
import json, os, sys
a = sys.argv[1:]
root = os.environ["STUB_ROOT"]
if a[:1] == ["env"]:
    with open(os.path.join(root, "envs.txt")) as f:
        sys.stdout.write(f.read())
    sys.exit(0)
if a[:1] != ["run"]:
    sys.exit(0)
a = a[1:]
name = a[a.index("-n") + 1]
cmd = a[a.index("-n") + 2:]
with open(os.path.join(root, "calls.jsonl"), "a") as f:
    f.write(json.dumps({{"env": name, "cmd": cmd, "cap": os.environ.get("CUDA_MPS_PINNED_DEVICE_MEM_LIMIT")}}) + "\\n")
def opt(flag):
    return cmd[cmd.index(flag) + 1]
if cmd[:1] == ["binder-compare"]:
    sub = cmd[1]
    if sub == "parse-seqs":
        with open(opt("--input")) as src, open(opt("--output"), "w") as dst:
            dst.write(src.read())
    elif sub.startswith("refold-"):
        os.makedirs(os.path.dirname(opt("-o")) or ".", exist_ok=True)
        with open(opt("-o"), "w") as dst:
            dst.write("sequence,iptm,target_sequence\\nMKTAYIAKQRQ,0.8,MKTAYIAKQRQ\\n")
sys.exit(0)
"""

_GUARD = "#!/bin/sh\nexit 0\n"  # `is-up` succeeds: the MPS ceiling counts as active


class Result:
    def __init__(self, proc: subprocess.CompletedProcess, calls: list[dict], out_dir: Path):
        self.rc = proc.returncode
        self.out = proc.stdout + proc.stderr
        self.calls = calls
        self.out_dir = out_dir

    def refolds(self, sub: str) -> list[dict]:
        return [c for c in self.calls if c["cmd"][:2] == ["binder-compare", sub]]

    @property
    def report(self) -> list[str]:
        (call,) = [c for c in self.calls if c["cmd"][:2] == ["binder-compare", "report"]]
        return call["cmd"]


def _run(
    tmp_path: Path,
    envs: list[str],
    argv: list[str] | None = None,
    *,
    af3_weights: bool = True,
    protenix_weights: int | None = CKPT_BYTES,
    guard: bool = False,
    extra_env: dict[str, str] | None = None,
    af3_csv: bool = False,
) -> Result:
    """Run evaluate.sh in a sandbox. protenix_weights=None plants no checkpoint; an int plants one that size."""
    sandbox = tmp_path / "Evaluator"
    (sandbox / "envs").mkdir(parents=True, exist_ok=True)
    shutil.copy(EVALUATE_SH, sandbox / "evaluate.sh")

    stub_root = tmp_path / "stub"
    stub_root.mkdir(exist_ok=True)
    (stub_root / "envs.txt").write_text("".join(f"{n} /x\n" for n in envs))
    stub_bin = tmp_path / "stubbin"
    stub_bin.mkdir(exist_ok=True)
    conda = stub_bin / "conda"
    conda.write_text(_STUB)
    conda.chmod(0o755)
    # evaluate.sh sources the first conda.sh it finds and a shell FUNCTION beats a PATH entry, so
    # plant ours where the search looks first (`<checkout>/conda`) and have it forward to the stub.
    conda_sh = tmp_path / "conda" / "etc" / "profile.d" / "conda.sh"
    conda_sh.parent.mkdir(parents=True, exist_ok=True)
    conda_sh.write_text(f'conda() {{\n  "{conda}" "$@"\n}}\n')

    if guard:
        (tmp_path / "tools").mkdir(exist_ok=True)
        g = tmp_path / "tools" / "gpu_mem_guard.sh"
        g.write_text(_GUARD)
        g.chmod(0o755)

    out_dir = tmp_path / "out"
    out_dir.mkdir(exist_ok=True)
    # --skip-boltz2 needs its CSV on disk; the row is scored for the one pool design.
    (out_dir / "boltz2_results.csv").write_text("sequence,iptm,target_sequence\nMKTAYIAKQRQ,0.8,MKTAYIAKQRQ\n")
    if af3_csv:
        (out_dir / "af3_results.csv").write_text("sequence,iptm,target_sequence\nMKTAYIAKQRQ,0.8,MKTAYIAKQRQ\n")

    sequences = tmp_path / "seqs.fasta"
    sequences.write_text(">b1\nMKTAYIAKQRQ\n")
    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    models = tmp_path / "af3_models"
    models.mkdir(exist_ok=True)
    if af3_weights:
        (models / "af3.bin").write_text("stub")
    if protenix_weights is not None:
        ckpt = tmp_path / CKPT_REL
        ckpt.parent.mkdir(parents=True, exist_ok=True)
        with ckpt.open("wb") as fh:
            fh.truncate(protenix_weights)  # sparse: exact size without 1.4 GB on disk

    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CONDA_", "BASH_FUNC_", "BINDERSCOUT_", "CUDA_MPS"))
        and k not in {"BASH_ENV", "ENV", "AF3_MODEL_DIR"}
    }
    env.update(
        {
            "PATH": f"{stub_bin}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(fake_home),
            "AF3_MODEL_DIR": str(models),
            "STUB_ROOT": str(stub_root),
            **(extra_env or {}),
        }
    )
    proc = subprocess.run(
        [
            "bash",
            str(sandbox / "evaluate.sh"),
            "--skip-boltz2",
            "--sequences",
            str(sequences),
            "--target-seq",
            "MKTAYIAKQRQ",
            "--output",
            str(out_dir),
            *(argv or []),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    log = stub_root / "calls.jsonl"
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return Result(proc, calls, out_dir.resolve())


# ---------------------------------------------------------------- slot selection (R3)


def test_explicit_protenix_runs_protenix_and_not_af3(tmp_path):
    r = _run(tmp_path, ALL_ENVS, ["--second-engine", "protenix"])
    assert r.rc == 0, r.out
    assert len(r.refolds("refold-protenix")) == 1, r.out
    assert r.refolds("refold-af3") == [], r.out  # AF3 is ready, and still not in this panel
    assert "AF3" not in r.out.replace("--second-engine", ""), r.out
    assert "second engine: Protenix (--second-engine protenix); panel Boltz-2 + Protenix + ESMFold2;" in r.out, r.out


def test_explicit_af3_unusable_is_skipped_by_name_and_protenix_does_not_take_over(tmp_path):
    r = _run(tmp_path, ALL_ENVS, ["--second-engine", "af3"], af3_weights=False)
    assert "[skipped] AF3: no AF3 weights found" in r.out, r.out
    assert r.refolds("refold-protenix") == [], r.out  # Protenix is fully installed: still no silent switch
    assert r.refolds("refold-af3") == [], r.out
    assert "Protenix" not in r.out, r.out
    assert "--second-engine" not in r.report  # the AF3 slot is reported the AF3 way
    assert "--af3-results" not in r.report  # nothing ran, so no CSV exists


def test_explicit_protenix_unusable_is_skipped_by_name_and_af3_does_not_take_over(tmp_path):
    r = _run(tmp_path, ALL_ENVS[:-1], ["--second-engine", "protenix"])  # AF3 ready, Protenix env absent
    assert "[skipped] Protenix: conda env 'binder-eval-protenix' not found" in r.out, r.out
    assert "binderscout install --tool protenix" in r.out, r.out
    assert r.refolds("refold-af3") == [] and r.refolds("refold-protenix") == [], r.out
    assert "[skipped] AF3" not in r.out, r.out
    # the slot is still Protenix in the report: the panel records what was asked for
    assert r.report[r.report.index("--second-engine") + 1] == "protenix"
    assert "--second-results" not in r.report and "--af3-results" not in r.report
    # and the gate warning names the engine that is missing
    assert "2 refold engine(s) will reach the report" in r.out, r.out
    assert "The second slot is Protenix and it is not running" in r.out, r.out
    assert "--min-engines 2" in r.out, r.out


def test_no_flag_and_af3_ready_uses_af3_even_when_protenix_is_installed(tmp_path):
    r = _run(tmp_path, ALL_ENVS)
    assert r.rc == 0, r.out
    assert len(r.refolds("refold-af3")) == 1, r.out
    assert r.refolds("refold-protenix") == [], r.out
    assert "Protenix" not in r.out, r.out
    assert "--af3-results" in r.report
    assert str(r.out_dir / "af3_results.csv") == r.report[r.report.index("--af3-results") + 1]
    assert "--second-engine" not in r.report and "--second-results" not in r.report


def test_no_flag_af3_unusable_and_protenix_ready_falls_back_with_a_notice(tmp_path):
    r = _run(tmp_path, ALL_ENVS, af3_weights=False)
    assert r.rc == 0, r.out
    assert "[note] " + PANEL_NOTICE in r.out, r.out
    assert len(r.refolds("refold-protenix")) == 1, r.out
    assert r.refolds("refold-af3") == [], r.out
    # AF3 is still named as skipped: the operator sees why the panel changed
    assert "[skipped] AF3: no AF3 weights found" in r.out, r.out
    assert r.report[r.report.index("--second-engine") + 1] == "protenix"
    assert r.report[r.report.index("--second-results") + 1] == str(r.out_dir / "protenix_results.csv")
    assert "--af3-results" not in r.report
    assert "reach the report, but the cross-engine gate defaults to 3" not in r.out, r.out  # 3 engines


def test_no_flag_af3_env_missing_and_protenix_ready_also_falls_back(tmp_path):
    r = _run(tmp_path, NO_AF3)
    assert "[note] " + PANEL_NOTICE in r.out, r.out
    assert len(r.refolds("refold-protenix")) == 1, r.out


@pytest.mark.parametrize("flag", ["--skip-af3", "--skip-second"])
def test_a_user_skip_of_the_slot_never_falls_back_to_protenix(tmp_path, flag):
    r = _run(tmp_path, ALL_ENVS, [flag])
    assert r.refolds("refold-protenix") == [] and r.refolds("refold-af3") == [], r.out
    assert "Protenix" not in r.out, r.out
    assert "AF3" not in r.out.replace(flag, ""), r.out


def test_both_unusable_skips_the_slot_by_name_exactly_as_before(tmp_path):
    r = _run(tmp_path, NEITHER)
    assert "[skipped] AF3: conda env 'binder-eval-af3' not found" in r.out, r.out
    assert "Protenix" not in r.out, r.out  # nothing new is printed for an engine nobody asked for
    assert r.refolds("refold-protenix") == [] and r.refolds("refold-af3") == [], r.out


def test_skip_second_skips_an_explicit_protenix_too(tmp_path):
    r = _run(tmp_path, ALL_ENVS, ["--second-engine", "protenix", "--skip-second"])
    assert r.refolds("refold-protenix") == [] and r.refolds("refold-af3") == [], r.out
    assert "second engine: Protenix" not in r.out, r.out


def test_skip_af3_does_not_skip_an_explicit_protenix(tmp_path):
    r = _run(tmp_path, ALL_ENVS, ["--second-engine", "protenix", "--skip-af3"])
    assert len(r.refolds("refold-protenix")) == 1, r.out


def test_an_unknown_second_engine_is_refused(tmp_path):
    r = _run(tmp_path, ALL_ENVS, ["--second-engine", "rf3"])
    assert r.rc == 2, r.out
    assert "--second-engine must be one of: af3, protenix (got 'rf3')" in r.out, r.out
    assert r.calls == []


# ---------------------------------------------------------------- the Protenix weights check


def test_weights_of_the_wrong_size_are_refused_by_name_with_the_install_hint(tmp_path):
    r = _run(tmp_path, ALL_ENVS, ["--second-engine", "protenix"], protenix_weights=CKPT_BYTES - 1)
    assert f"[skipped] Protenix: Protenix checkpoint is {CKPT_BYTES - 1} bytes, expected {CKPT_BYTES}" in r.out, r.out
    assert "binderscout install --tool protenix" in r.out, r.out
    assert r.refolds("refold-protenix") == [], r.out


def test_missing_weights_are_refused_by_name_with_the_install_hint(tmp_path):
    r = _run(tmp_path, ALL_ENVS, ["--second-engine", "protenix"], protenix_weights=None)
    assert "[skipped] Protenix: no Protenix weights found (env 'binder-eval-protenix' is installed)" in r.out, r.out
    assert "weights/protenix/checkpoint/protenix_base_default_v1.0.0.pt" in r.out, r.out
    assert "binderscout install --tool protenix" in r.out, r.out
    assert r.refolds("refold-protenix") == [], r.out


def test_a_wrong_sized_checkpoint_blocks_the_automatic_fallback_too(tmp_path):
    r = _run(tmp_path, ALL_ENVS, af3_weights=False, protenix_weights=CKPT_BYTES + 1)
    assert "Protenix" not in r.out, r.out
    assert r.refolds("refold-protenix") == [], r.out
    assert "[skipped] AF3: no AF3 weights found" in r.out, r.out


# ---------------------------------------------------------------- the command line


def test_the_protenix_command_line_is_exactly_this_and_carries_no_kernel_option(tmp_path):
    r = _run(tmp_path, ALL_ENVS, ["--second-engine", "protenix"])
    (call,) = r.refolds("refold-protenix")
    assert call["env"] == "binder-eval-protenix"
    assert call["cmd"] == [
        "binder-compare",
        "refold-protenix",
        "--sequences",
        str(r.out_dir / "sequences.fasta"),
        "--target-seq",
        "MKTAYIAKQRQ",
        "-o",
        str(r.out_dir / "protenix_results.csv"),
        "--output-dir",
        str(r.out_dir / "refold_protenix"),
        "--model-dir",
        str(tmp_path / "weights" / "protenix"),
    ]
    assert not [t for t in call["cmd"] if "kernel" in t or "layernorm" in t]


def test_resume_is_forwarded_to_protenix(tmp_path):
    r = _run(tmp_path, ALL_ENVS, ["--second-engine", "protenix", "--resume"])
    (call,) = r.refolds("refold-protenix")
    assert call["cmd"][-1] == "--resume", call


def test_the_af3_command_line_is_unchanged(tmp_path):
    r = _run(tmp_path, ALL_ENVS)
    (call,) = r.refolds("refold-af3")
    assert call["env"] == "binder-eval-af3"
    assert call["cmd"] == [
        "binder-compare",
        "refold-af3",
        "--sequences",
        str(r.out_dir / "sequences.fasta"),
        "--target-seq",
        "MKTAYIAKQRQ",
        "-o",
        str(r.out_dir / "af3_results.csv"),
        "--output-dir",
        str(r.out_dir / "refold_af3"),
    ]


def test_a_protenix_env_name_override_reaches_conda_run(tmp_path):
    r = _run(tmp_path, [*NEITHER, "my-px"], ["--second-engine", "protenix", "--protenix-env", "my-px"])
    (call,) = r.refolds("refold-protenix")
    assert call["env"] == "my-px", r.out


# ---------------------------------------------------------------- GPU cap


def test_the_protenix_cap_defaults_to_24g_and_reaches_the_engine(tmp_path):
    r = _run(tmp_path, ALL_ENVS, ["--second-engine", "protenix"], guard=True)
    assert "cap 24G)" in r.out and "(conda env: binder-eval-protenix, cap 24G)" in r.out, r.out
    (call,) = r.refolds("refold-protenix")
    assert call["cap"] == "0=24G", call


def test_the_af3_cap_is_still_12g(tmp_path):
    r = _run(tmp_path, ALL_ENVS, guard=True)
    (call,) = r.refolds("refold-af3")
    assert call["cap"] == "0=12G", call


def test_the_protenix_cap_env_var_and_flag_override_the_default(tmp_path):
    env_run = _run(
        tmp_path / "a",
        ALL_ENVS,
        ["--second-engine", "protenix"],
        guard=True,
        extra_env={"BINDERSCOUT_GPU_CAP_PROTENIX": "30G"},
    )
    (call,) = env_run.refolds("refold-protenix")
    assert call["cap"] == "0=30G", call
    flag_run = _run(
        tmp_path / "b",
        ALL_ENVS,
        ["--second-engine", "protenix", "--gpu-cap-protenix", "16G"],
        guard=True,
        extra_env={"BINDERSCOUT_GPU_CAP_PROTENIX": "30G"},
    )
    (call,) = flag_run.refolds("refold-protenix")
    assert call["cap"] == "0=16G", call  # the flag beats the environment, as for every other engine


def test_the_default_is_pinned_in_the_source_and_the_help_says_it_is_non_default():
    src = EVALUATE_SH.read_text()
    assert "GPU_CAP_PROTENIX=${BINDERSCOUT_GPU_CAP_PROTENIX:-24G}" in src
    help_text = subprocess.run(["bash", str(EVALUATE_SH), "--help"], capture_output=True, text=True, timeout=60).stdout
    assert "--gpu-cap-protenix N   default: 24G (env BINDERSCOUT_GPU_CAP_PROTENIX)" in help_text
    assert "--second-engine ENG" in help_text and "--skip-second" in help_text and "--protenix-env ENV" in help_text


def test_concurrent_mode_launches_the_slot_engine_with_its_own_cap(tmp_path):
    r = _run(tmp_path, ALL_ENVS, ["--second-engine", "protenix", "--concurrent", "--stagger", "0"], guard=True)
    assert r.rc == 0, r.out
    assert "caps 24G/24G/24G" in r.out, r.out
    assert (r.out_dir / "refold_protenix.log").exists() and not (r.out_dir / "refold_af3.log").exists()
    assert len(r.refolds("refold-protenix")) == 1


def test_concurrent_mode_with_af3_shows_the_af3_cap(tmp_path):
    r = _run(tmp_path, ALL_ENVS, ["--concurrent", "--stagger", "0"], guard=True)
    assert "caps 24G/12G/24G" in r.out, r.out
    assert (r.out_dir / "refold_af3.log").exists()


# ---------------------------------------------------------------- the report call


def test_a_left_over_csv_of_the_engine_outside_the_slot_is_not_passed_to_the_report(tmp_path):
    r = _run(tmp_path, ALL_ENVS, ["--second-engine", "protenix"], af3_csv=True)
    assert "--af3-results" not in r.report, r.report
    assert "af3_results.csv: the second slot holds Protenix in this run" in r.out, r.out


# ---------------------------------------------------------------- --primary-engine vs the panel


def test_primary_protenix_is_refused_when_the_slot_is_af3(tmp_path):
    r = _run(tmp_path, ALL_ENVS, ["--primary-engine", "protenix"])
    assert r.rc == 2, r.out
    assert "--primary-engine protenix is not in this panel: the second slot holds af3" in r.out, r.out
    assert r.calls == [] or not r.refolds("refold-af3"), "a refused panel must not start any refold"


def test_primary_af3_is_refused_when_the_slot_is_protenix(tmp_path):
    r = _run(tmp_path, ALL_ENVS, ["--second-engine", "protenix", "--primary-engine", "af3"])
    assert r.rc == 2, r.out
    assert "--primary-engine af3 is not in this panel: the second slot holds protenix" in r.out, r.out
    assert not r.refolds("refold-protenix"), "a refused panel must not start any refold"


def test_primary_af3_is_refused_when_the_slot_fell_back_to_protenix(tmp_path):
    r = _run(tmp_path, ALL_ENVS, ["--primary-engine", "af3"], af3_weights=False)
    assert r.rc == 2, r.out
    assert "the second slot holds protenix" in r.out, r.out


def test_primary_protenix_is_accepted_with_the_protenix_slot_and_forwarded(tmp_path):
    r = _run(tmp_path, ALL_ENVS, ["--second-engine", "protenix", "--primary-engine", "protenix"])
    assert r.rc == 0, r.out
    assert r.report[r.report.index("--primary-engine") + 1] == "protenix"


def test_primary_af3_is_still_accepted_with_the_af3_slot(tmp_path):
    r = _run(tmp_path, ALL_ENVS, ["--primary-engine", "af3"])
    assert r.rc == 0, r.out
    assert r.report[r.report.index("--primary-engine") + 1] == "af3"


def test_min_engines_is_forwarded_beside_the_protenix_slot(tmp_path):
    r = _run(tmp_path, ALL_ENVS, ["--second-engine", "protenix", "--min-engines", "2"])
    assert r.report[r.report.index("--min-engines") + 1] == "2"
