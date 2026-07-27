"""Every tool run script must persist a settings.json before the design step.

CLAUDE.md > Conventions > "Per-run settings.json" makes this a hard project rule:
`runs/<name>/<tool>/settings.json` is how a future session answers "what params
produced these designs" without grepping run.log or trusting a run script that may
have been edited since. Three of the seven writers (bindcraft, boltzgen, mosaic)
silently skipped it, so those three tools' runs were unauditable.

The writers under test are derived from `conf.TOOL_SEQUENCE`, so a newly added tool
is covered automatically: add it to TOOL_SEQUENCE and these tests immediately demand
a settings.json block from its writer.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))
import configurator as conf

HEREDOC_MARKER = "SETTINGS_JSON_EOF"
CAT_RE = re.compile(r'^cat > "\$\{?\w+\}?/settings\.json" <<' + HEREDOC_MARKER + r"$")

# Required by CLAUDE.md. Nested entries are the sub-keys each object must carry.
REQUIRED_TOP = ("tool", "started_at", "version", "target", "design_params", "env")
REQUIRED_VERSION = ("bindmaster_git_sha", "bindmaster_git_branch")
REQUIRED_TARGET = ("sequence", "length")
REQUIRED_ENV = ("conda_env", "python", "gpu_id", "gpu_name", "gpu_memory_mib")

# Bash assignments the settings block leans on (RUN_DIR, SETTINGS_DIR, TARGET_SEQ, ...).
# Kept in source order; command substitutions and conda env exports are dropped because
# they need a live conda/tool install that a unit test has no business requiring.
_LITERAL_ASSIGNMENT = re.compile(r"^[A-Z_][A-Z0-9_]*=")


def _writers():
    """(tool_key, script_name, writer_fn) for every tool in the pipeline sequence."""
    out = []
    for key, script, _label, _subdir in conf.TOOL_SEQUENCE:
        fn_name = "write_" + script.removesuffix(".sh")
        fn = getattr(conf, fn_name, None)
        out.append(pytest.param(key, script, fn, id=key))
    return out


@pytest.fixture
def full_cfg(tmp_path):
    """A cfg populated for *every* writer, so no tool is skipped for missing keys."""
    run_dir = tmp_path / "runs" / "test"
    run_dir.mkdir(parents=True)
    target_pdb = tmp_path / "target.pdb"
    target_pdb.write_text(
        "ATOM      1  CA  MET A   1       0.000   0.000   0.000  1.00  0.00           C\n"
        "ATOM      2  CA  ALA A   2       3.800   0.000   0.000  1.00  0.00           C\n"
        "ATOM      3  CA  GLU A   3       7.600   0.000   0.000  1.00  0.00           C\n"
    )
    return {
        "name": "test_target",
        "run_dir": run_dir,
        "target_pdb": target_pdb,
        "target_pdb_src": str(target_pdb),
        "target_sequence": "MAE",
        "chains": "A",
        "hotspots": "1,3",
        "min_length": 65,
        "max_length": 150,
        "n_designs": 10,
        "boltzgen_mode": "protein",
        "boltzgen_intermediate": 10000,
        "filter_preset": "default_filters",
        "advanced_preset": "default_4stage_multimer",
        "pxdesign_binder_length": 80,
        "pxdesign_n_samples": 1000,
        "pxdesign_preset": "preview",
        "pxdesign_hotspots": "1,3",
        "pxdesign_chains": "A",
    }


def _emit(writer, cfg, script_name):
    path = cfg["run_dir"] / script_name
    writer(path, cfg)
    return path.read_text().splitlines()


def _block_bounds(lines, script_name):
    """Index of the `cat > .../settings.json <<EOF` line and its terminator."""
    starts = [i for i, line in enumerate(lines) if CAT_RE.match(line)]
    assert starts, (
        f"{script_name} never writes settings.json. CLAUDE.md requires every run script to "
        f"persist runs/<name>/<tool>/settings.json before the design step "
        f"(see bindmaster_examples/run_rfd3.sh.template)."
    )
    assert len(starts) == 1, f"{script_name} writes settings.json {len(starts)} times"
    start = starts[0]
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == HEREDOC_MARKER)
    return start, end


class TestEveryWriterPersistsSettingsJson:
    def test_a_writer_exists_for_every_tool_in_the_sequence(self):
        """A tool added to TOOL_SEQUENCE without a write_run_* function would otherwise
        slip past every other test in this file."""
        for key, script, fn in [p.values for p in _writers()]:
            assert callable(fn), f"TOOL_SEQUENCE has {key!r} but no write_{script.removesuffix('.sh')}()"

    @pytest.mark.parametrize(("key", "script", "writer"), _writers())
    def test_emits_a_settings_json_heredoc(self, key, script, writer, full_cfg):
        lines = _emit(writer, full_cfg, script)
        _block_bounds(lines, script)

    @pytest.mark.parametrize(("key", "script", "writer"), _writers())
    def test_block_precedes_the_design_step(self, key, script, writer, full_cfg):
        """The point of the convention is provenance for work that is about to run:
        a settings.json written after (or instead of) the workload records nothing."""
        lines = _emit(writer, full_cfg, script)
        _, end = _block_bounds(lines, script)
        last_command = max(i for i, line in enumerate(lines) if line.strip() and not line.lstrip().startswith("#"))
        assert end < last_command, f"{script} writes settings.json after its design step"

    @pytest.mark.parametrize(("key", "script", "writer"), _writers())
    def test_gpu_probes_are_guarded(self, key, script, writer, full_cfg):
        """Generated scripts run under `set -euo pipefail`: an unguarded nvidia-smi
        command substitution exits 127 on a CPU host, killing the run in the
        provenance block that exists to make runs reproducible."""
        lines = _emit(writer, full_cfg, script)
        probes = [ln for ln in lines if ln.startswith(("GPU_NAME=", "GPU_MEM="))]
        assert len(probes) == 2, f"{script} is missing the GPU provenance probes"
        for line in probes:
            assert "|| echo" in line, f"unguarded GPU probe in {script}: {line}"

    @pytest.mark.parametrize(("key", "script", "writer"), _writers())
    def test_emitted_json_is_valid_and_complete_without_nvidia_smi(self, key, script, writer, full_cfg, tmp_path):
        """Run the emitted heredoc for real, on a host with no nvidia-smi and no tool
        install, and parse what it produces."""
        lines = _emit(writer, full_cfg, script)
        cat_idx, end = _block_bounds(lines, script)

        # The block starts above the `cat >` line: GIT_SHA / GPU_NAME / GPU_MEM / PY_VER
        # are resolved first. Walk back over the contiguous comment/assignment run.
        start = cat_idx
        while start > 0 and (
            not lines[start - 1].strip()
            or lines[start - 1].lstrip().startswith("#")
            or _LITERAL_ASSIGNMENT.match(lines[start - 1])
        ):
            start -= 1

        prelude = [
            ln
            for ln in lines[:start]
            if (_LITERAL_ASSIGNMENT.match(ln) and "$(" not in ln and "CONDA_PREFIX" not in ln)
            or ln.startswith("mkdir -p ")
        ]
        runner = tmp_path / f"{key}_block.sh"
        runner.write_text(
            "\n".join(["#!/usr/bin/env bash", "set -euo pipefail", *prelude, *lines[start : end + 1]]) + "\n"
        )

        env_path = f"{tmp_path}:/usr/bin:/bin"  # deliberately excludes any nvidia-smi
        assert shutil.which("nvidia-smi", path=env_path) is None
        proc = subprocess.run(
            ["bash", str(runner)], capture_output=True, text=True, env={"PATH": env_path, "HOME": str(tmp_path)}
        )
        assert proc.returncode == 0, f"{script} settings block failed without nvidia-smi:\n{proc.stderr}"

        written = list(full_cfg["run_dir"].rglob("settings.json"))
        assert len(written) == 1, f"{script} wrote {len(written)} settings.json files"
        doc = json.loads(written[0].read_text())  # raises if the heredoc emitted invalid JSON

        for field in REQUIRED_TOP:
            assert field in doc, f"{script} settings.json missing required key {field!r}"
        assert doc["tool"], f"{script} settings.json has an empty 'tool'"
        for field in REQUIRED_VERSION:
            assert field in doc["version"], f"{script} settings.json missing version.{field}"
        for field in REQUIRED_TARGET:
            assert field in doc["target"], f"{script} settings.json missing target.{field}"
        for field in REQUIRED_ENV:
            assert field in doc["env"], f"{script} settings.json missing env.{field}"
        assert doc["design_params"], f"{script} settings.json has empty design_params"
        # The guards must degrade to placeholders, not crash or emit bare `null`/``.
        assert doc["env"]["gpu_name"] == "unknown"
        assert doc["env"]["gpu_memory_mib"] == 0
