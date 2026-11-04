"""Two generated scripts died within seconds on an aarch64 host, found by running them there.

* run_pxdesign.sh forced CUDA_HOME to the conda env. deepspeed (reached through protenix) asks for
  $CUDA_HOME/bin/nvcc at import, and the aarch64 env has none (CUDA is system-wide), so the run died in
  8 s with FileNotFoundError. The CPATH/LIBRARY_PATH lines also hard-coded targets/x86_64-linux, a
  directory that is targets/sbsa-linux on aarch64.
* run_proteina_complexa.sh is `set -u` and sourced env.sh, which reads ${SC_EXEC} unguarded when the
  install's .env does not define it: "SC_EXEC: unbound variable", rc 1 after 0 s.

These run the GENERATED text, so the heredoc quoting and brace doubling are exercised.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))
import configurator as conf


def _cfg(tmp_path):
    run_dir = tmp_path / "runs" / "t"
    run_dir.mkdir(parents=True)
    pdb = tmp_path / "t.pdb"
    pdb.write_text(
        "".join(
            f"ATOM  {i:5d}  CA  ALA A {i:3d}       {i * 3.8:.3f}   0.000   0.000  1.00  0.00           C\n"
            for i in range(1, 6)
        )
    )
    return {
        "name": "t",
        "run_dir": run_dir,
        "target_pdb": pdb,
        "target_pdb_src": str(pdb),
        "target_sequence": "AAAAA",
        "chains": "A",
        "hotspots": "1,3",
        "min_length": 65,
        "max_length": 150,
        "pxdesign_binder_length": 80,
        "pxdesign_n_samples": 10,
        "pxdesign_preset": "preview",
        "pxdesign_hotspots": "1,3",
        "pxdesign_chains": "A",
    }


def _between(text, first, last):
    lines = text.splitlines()
    a = next(i for i, ln in enumerate(lines) if ln.startswith(first))
    b = next(i for i in range(a, len(lines)) if lines[i].startswith(last))
    return "\n".join(lines[a : b + 1])


def _run_block(block, env_extra, tmp_path, prelude=""):
    script = tmp_path / "block.sh"
    script.write_text("set -euo pipefail\n" + prelude + block + '\necho "CUDA_HOME=$CUDA_HOME"\n')
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), **env_extra}
    return subprocess.run(["/bin/bash", str(script)], capture_output=True, text=True, env=env, check=False)


def _pxdesign_text(tmp_path):
    path = tmp_path / "run_pxdesign.sh"
    conf.write_run_pxdesign(path, _cfg(tmp_path))
    return path.read_text()


def test_pxdesign_uses_the_system_cuda_when_the_env_has_no_nvcc(tmp_path):
    text = _pxdesign_text(tmp_path)
    block = _between(text, 'export CUDA_HOME="$CONDA_PREFIX"', "# Surface CUDA dev headers")
    prefix = tmp_path / "env"
    (prefix / "targets" / "sbsa-linux" / "include").mkdir(parents=True)
    sysbin = tmp_path / "syscuda" / "bin"
    sysbin.mkdir(parents=True)
    nvcc = sysbin / "nvcc"
    nvcc.write_text("#!/bin/sh\n")
    nvcc.chmod(0o755)
    proc = _run_block(
        block + '\necho "TARGET=$CUDA_TARGET_DIR"',
        {"CONDA_PREFIX": str(prefix), "PATH": f"{sysbin}:/usr/bin:/bin"},
        tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    assert f"CUDA_HOME={tmp_path / 'syscuda'}" in proc.stdout, "CUDA_HOME stayed on an env with no nvcc"
    assert f"TARGET={prefix / 'targets' / 'sbsa-linux'}" in proc.stdout, "the aarch64 target dir was not found"


def test_pxdesign_keeps_the_env_cuda_when_it_has_an_nvcc(tmp_path):
    text = _pxdesign_text(tmp_path)
    block = _between(text, 'export CUDA_HOME="$CONDA_PREFIX"', "# Surface CUDA dev headers")
    prefix = tmp_path / "env"
    (prefix / "bin").mkdir(parents=True)
    nvcc = prefix / "bin" / "nvcc"
    nvcc.write_text("#!/bin/sh\n")
    nvcc.chmod(0o755)
    proc = _run_block(block + '\necho "TARGET=$CUDA_TARGET_DIR"', {"CONDA_PREFIX": str(prefix)}, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert f"CUDA_HOME={prefix}" in proc.stdout
    assert f"TARGET={prefix / 'targets' / 'x86_64-linux'}" in proc.stdout, "x86_64 fallback changed"


def test_pxdesign_no_longer_hardcodes_the_x86_target_dir_in_its_paths(tmp_path):
    text = _pxdesign_text(tmp_path)
    for line in text.splitlines():
        if line.strip().startswith("export CPATH=") or line.strip().startswith("export LIBRARY_PATH="):
            assert "x86_64-linux" not in line, line


def test_complexa_sources_env_sh_with_unset_variables_allowed(tmp_path):
    path = tmp_path / "run_proteina_complexa.sh"
    conf.write_run_proteina_complexa(path, _cfg(tmp_path))
    block = _between(path.read_text(), "# env.sh reads", "set -u")
    (tmp_path / "env.sh").write_text('export SC_EXEC="${UV_SC_EXEC:-$SC_EXEC}"\n')
    # env.sh is sourced relative to the working directory in the generated script
    script = tmp_path / "block2.sh"
    script.write_text("set -euo pipefail\ncd " + str(tmp_path) + "\n" + block + "\necho SOURCED_OK\n")
    proc = subprocess.run(
        ["/bin/bash", str(script)], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"}, check=False
    )
    assert proc.returncode == 0 and "SOURCED_OK" in proc.stdout, proc.stderr
