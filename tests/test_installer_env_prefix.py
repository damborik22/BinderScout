"""The installers find a conda env wherever conda put it, not only at <base>/envs/<name>.

Every probe used to build `${CONDA_BASE}/envs/<name>` by hand: `env_exists`, the in-use
check, the verifiers that run `<env>/bin/python`. With `CONDA_ENVS_PATH` set, a condarc
`envs_dirs`, or envs under the per-user ~/.conda/envs, conda creates and finds the env
elsewhere, and the installer reported a working env as missing (then built a second one)
and `--verify` called it unusable.

These drive the real functions, extracted from each installer, in a subshell.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.shell_helpers import INSTALLERS, clean_env, extract_block, extract_functions, fake_base, run_bash

_PROBES = ("env_exists", "_env_python_ok", "_env_refold_cli_ok")


def _program(script: Path, body: str) -> str:
    return "\n".join(
        [
            "set -u",
            extract_block(script),
            extract_functions(script, *_PROBES),
            body,
        ]
    )


def _env_with_python(prefix: Path, marker: Path) -> None:
    (prefix / "bin").mkdir(parents=True)
    py = prefix / "bin" / "python"
    py.write_text(f'#!/bin/sh\necho "$0" > "{marker}"\nexit 0\n')
    py.chmod(0o755)


def _fake_base_listing(tmp_path: Path, listed: list[Path], envs_dirs: list[Path] | None) -> Path:
    """A base whose conda answers `env list --json`, and `config --show envs_dirs --json` unless None."""
    listing = json.dumps({"envs": [str(p) for p in listed]}, indent=2)
    script = f"#!/bin/sh\nif [ \"$1 $2\" = 'env list' ]; then cat <<'EOF'\n{listing}\nEOF\n"
    if envs_dirs is not None:
        dirs = json.dumps({"envs_dirs": [str(p) for p in envs_dirs]}, indent=2)
        script += f"elif [ \"$1 $2 $3\" = 'config --show envs_dirs' ]; then cat <<'EOF'\n{dirs}\nEOF\n"
    return fake_base(tmp_path / "base", conda_script=script + "fi\n")


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
class TestEnvLocation:
    def test_an_env_in_the_default_location_is_found(self, platform, tmp_path):
        base = fake_base(tmp_path / "base")
        (base / "envs" / "foo").mkdir(parents=True)
        r = run_bash(
            _program(INSTALLERS[platform], f'CONDA_BASE="{base}"; env_exists foo && echo FOUND'),
            clean_env(tmp_path / "home"),
            tmp_path,
        )
        assert "FOUND" in r.stdout, r.stderr

    def test_conda_envs_path_is_honoured(self, platform, tmp_path):
        base = fake_base(tmp_path / "base")
        custom = tmp_path / "elsewhere"
        (custom / "foo").mkdir(parents=True)
        r = run_bash(
            _program(INSTALLERS[platform], f'CONDA_BASE="{base}"; env_exists foo && echo "FOUND $BS_ENV_PREFIX"'),
            clean_env(tmp_path / "home", CONDA_ENVS_PATH=f"{tmp_path / 'nope'}:{custom}"),
            tmp_path,
        )
        assert f"FOUND {custom}/foo" in r.stdout, r.stderr

    def test_an_env_conda_itself_lists_is_found_without_jq(self, platform, tmp_path):
        """A condarc envs_dirs / ~/.conda/envs env: only `conda env list --json` knows."""
        per_user = tmp_path / "per-user"
        elsewhere = per_user / "foo"
        elsewhere.mkdir(parents=True)
        base = _fake_base_listing(tmp_path, [tmp_path / "base", elsewhere], [tmp_path / "base" / "envs", per_user])
        r = run_bash(
            _program(INSTALLERS[platform], f'CONDA_BASE="{base}"; env_exists foo && echo "FOUND $BS_ENV_PREFIX"'),
            clean_env(tmp_path / "home", PATH="/usr/bin:/bin"),
            tmp_path,
        )
        assert f"FOUND {elsewhere}" in r.stdout, r.stderr

    def test_a_same_named_env_outside_conda_envs_dirs_is_not_found(self, platform, tmp_path):
        """`conda env list` also lists other bases' envs (~/.conda/environments.txt) and `-p` prefix envs.

        Neither can be addressed with `-n foo` from this base, so the installer cannot use them; a
        match on basename alone made env_exists true for an env that then could not be activated.
        """
        other_checkout = tmp_path / "other-checkout" / "conda" / "envs" / "foo"
        prefix_env = tmp_path / "scratch" / "foo"
        other_checkout.mkdir(parents=True)
        prefix_env.mkdir(parents=True)
        base = _fake_base_listing(
            tmp_path, [tmp_path / "base", other_checkout, prefix_env], [tmp_path / "base" / "envs"]
        )
        (base / "envs").mkdir()
        r = run_bash(
            _program(INSTALLERS[platform], f'CONDA_BASE="{base}"; env_exists foo && echo "FOUND $BS_ENV_PREFIX"'),
            clean_env(tmp_path / "home", PATH="/usr/bin:/bin"),
            tmp_path,
        )
        assert "FOUND" not in r.stdout, r.stdout

    def test_an_unanswered_envs_dirs_query_accepts_no_listed_env(self, platform, tmp_path):
        """Without conda's envs_dirs nothing vouches for a listed prefix, so none is accepted."""
        elsewhere = tmp_path / "per-user" / "foo"
        elsewhere.mkdir(parents=True)
        base = _fake_base_listing(tmp_path, [tmp_path / "base", elsewhere], None)
        r = run_bash(
            _program(INSTALLERS[platform], f'CONDA_BASE="{base}"; env_exists foo && echo FOUND'),
            clean_env(tmp_path / "home", PATH="/usr/bin:/bin"),
            tmp_path,
        )
        assert "FOUND" not in r.stdout, r.stdout

    def test_a_missing_env_is_missing_and_the_old_path_is_the_fallback(self, platform, tmp_path):
        base = fake_base(tmp_path / "base")
        r = run_bash(
            _program(INSTALLERS[platform], f'CONDA_BASE="{base}"; env_exists nope || echo "MISSING $BS_ENV_PREFIX"'),
            clean_env(tmp_path / "home"),
            tmp_path,
        )
        assert f"MISSING {base}/envs/nope" in r.stdout, r.stderr

    def test_the_verifiers_run_the_python_of_the_env_that_was_found(self, platform, tmp_path):
        base = fake_base(tmp_path / "base")
        custom = tmp_path / "elsewhere"
        marker = tmp_path / "ran"
        _env_with_python(custom / "foo", marker)
        r = run_bash(
            _program(INSTALLERS[platform], f'CONDA_BASE="{base}"; _env_python_ok foo "pass" && echo OK'),
            clean_env(tmp_path / "home", CONDA_ENVS_PATH=str(custom)),
            tmp_path,
        )
        assert "OK" in r.stdout, r.stderr
        assert marker.read_text().strip() == str(custom / "foo" / "bin" / "python")

    def test_no_probe_still_hardcodes_the_default_env_path(self, platform):
        text = INSTALLERS[platform].read_text()
        offenders = [
            line.strip()
            for line in text.splitlines()
            if "${CONDA_BASE}/envs/" in line and not line.lstrip().startswith("#")
        ]
        # The only legitimate spelling is the documented fallback inside bs_env_lookup, which
        # is written with a local `base`, and the writability probe of the default envs dir.
        assert all("envs_dir" in line for line in offenders), offenders


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write a read-only directory")
@pytest.mark.parametrize("platform", sorted(INSTALLERS))
class TestSystemCondaWritable:
    """A shared read-only system conda with per-user envs is a normal setup, not 'no usable conda'.

    `_check_system_conda_writable` only looked at <base>/envs, so with CONDA_ENVS_PATH pointing at a
    writable directory the installer still decided the conda was unusable and downloaded a second one.
    """

    def _check(self, platform, tmp_path, **extra):
        base = fake_base(tmp_path / "base")
        (base / "envs").mkdir()
        (base / "envs").chmod(0o555)
        try:
            prog = _program(
                INSTALLERS[platform],
                "\n".join(
                    [
                        extract_functions(INSTALLERS[platform], "_check_system_conda_writable"),
                        'print_warn() { echo "WARN $*"; }',
                        f'CONDA_BASE="{base}"; STANDALONE=auto',
                        "if _check_system_conda_writable; then echo WRITABLE; else echo READONLY; fi",
                    ]
                ),
            )
            return run_bash(prog, clean_env(tmp_path / "home", **extra), tmp_path).stdout
        finally:
            (base / "envs").chmod(0o755)

    def test_a_read_only_base_is_not_writable(self, platform, tmp_path):
        assert "READONLY" in self._check(platform, tmp_path)

    def test_a_writable_conda_envs_path_makes_it_usable(self, platform, tmp_path):
        mine = tmp_path / "my-envs"
        mine.mkdir()
        assert "WRITABLE" in self._check(platform, tmp_path, CONDA_ENVS_PATH=f"{mine}:{tmp_path / 'other'}")

    def test_an_unwritable_conda_envs_path_does_not(self, platform, tmp_path):
        assert "READONLY" in self._check(platform, tmp_path, CONDA_ENVS_PATH=str(tmp_path / "does-not-exist"))
