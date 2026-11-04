"""`complexa target add` writes into the Proteina-Complexa CHECKOUT, and a failed run left it there.

The checkout can be shared, symlinked or read-only. The generated script now (1) refuses by name when
`configs/targets/targets_dict.yaml` cannot be written, (2) puts the file back when the design step
fails, and (3) keeps the entry when the run succeeds, because that is what makes a re-run reuse it.
These run the GENERATED text against a stand-in `complexa`.
"""

import os
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))
import configurator as conf
from tests.configurator.test_pxdesign_and_complexa_scripts_start_on_aarch64 import _cfg

FAKE = """#!/bin/bash
case "$1 $2" in
  "target show") exit 1 ;;
  "target add") echo "entry_for_this_run: 1" >> "$(dirname "$0")/../../configs/targets/targets_dict.yaml"; exit 0 ;;
esac
[[ "$1" == design ]] && exit "${FAKE_DESIGN_RC:-0}"
exit 0
"""


def _block(tmp_path):
    path = tmp_path / "run_proteina_complexa.sh"
    conf.write_run_proteina_complexa(path, _cfg(tmp_path))
    lines = path.read_text().splitlines()
    a = next(i for i, ln in enumerate(lines) if ln.startswith("_TD="))
    b = next(i for i in range(a, len(lines)) if lines[i] == "trap - EXIT")
    return "\n".join(lines[a : b + 2])  # the trap line and the backup cleanup after it


def _run(tmp_path, *, design_rc=0, writable=True):
    pc = tmp_path / "pc"
    (pc / ".venv" / "bin").mkdir(parents=True)
    (pc / "configs" / "targets").mkdir(parents=True)
    yaml = pc / "configs" / "targets" / "targets_dict.yaml"
    yaml.write_text("existing: 1\n")
    fake = pc / ".venv" / "bin" / "complexa"
    fake.write_text(FAKE)
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    if not writable:
        yaml.chmod(0o444)
    script = tmp_path / "block.sh"
    script.write_text(f'set -euo pipefail\nPROTEINA_COMPLEXA_DIR="{pc}"\n{_block(tmp_path)}\necho DONE\n')
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "FAKE_DESIGN_RC": str(design_rc), "TMPDIR": str(tmp_path)}
    proc = subprocess.run(["/bin/bash", str(script)], capture_output=True, text=True, env=env, check=False)
    return proc, yaml


def test_a_successful_run_keeps_the_registered_target(tmp_path):
    proc, yaml = _run(tmp_path)
    assert proc.returncode == 0 and "DONE" in proc.stdout, proc.stdout + proc.stderr
    assert "entry_for_this_run" in yaml.read_text(), "control: the stand-in did register the target"


def test_a_failed_design_step_puts_the_checkout_file_back(tmp_path):
    proc, yaml = _run(tmp_path, design_rc=3)
    assert proc.returncode == 3, "the failure must still be the script's exit status"
    assert "DONE" not in proc.stdout
    assert yaml.read_text() == "existing: 1\n", "a failed run left its target in the checkout"
    assert "removed the target this run registered" in proc.stdout
    assert not list(tmp_path.glob("tmp*")), "the backup file was left behind"


def test_a_read_only_checkout_is_refused_by_name_before_anything_runs(tmp_path):
    if os.geteuid() == 0:
        return  # root writes through 0444
    proc, yaml = _run(tmp_path, writable=False)
    assert proc.returncode == 1
    assert "is not writable" in proc.stderr and "targets_dict.yaml" in proc.stderr
    assert yaml.read_text() == "existing: 1\n"
