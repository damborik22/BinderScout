"""The opt-in Protenix installer option (`--tool protenix`, `--second-engine protenix`).

Protenix v1.x is the one engine that can take AF3's slot as the report's second refold engine. It is
OPT-IN and never part of `--tool all`, because installing it means (a) a licence the operator must see
and accept before anything is fetched (Apache-2.0 v1.x code and parameters, proprietary v2 weights that
are never used, a weight host whose terms were not read, NVIDIA cuEquivariance wheels that pip installs
but the adapter never runs) and (b) a package that builds `scikit-learn-extra` from source and so needs
a C compiler.

What is pinned here, for BOTH installers, with nothing downloaded and no environment touched:

* the registry row, its absence from `--tool all`, and the `--second-engine` vocabulary;
* the licence gate: the printed text IS the marked block of Evaluator/docs/second_engine_licences.md
  (read from the doc, never retyped), shown before the first download, refused when it cannot be shown,
  refused without a terminal unless `--yes`, and a refusal leaves nothing behind;
* the compiler check, which refuses before anything is created;
* the install flow against a fake conda: env, pins, weights, the exact checkpoint size, and a state
  marker that exists only after all of it held and records the licence text and a UTC date.
"""

from __future__ import annotations

import os
import pty
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.shell_helpers import INSTALLERS, REPO, extract_functions, fake_base, run_bash, system_conda_present

DOC = REPO / "Evaluator" / "docs" / "second_engine_licences.md"
START = "<!-- install-licence:protenix:start -->"
END = "<!-- install-licence:protenix:end -->"
CKPT_BYTES = 1475950125
ENV = "binder-eval-protenix"

# These runs never reach a real conda, but the ones that do not use a fake base would try to fetch a
# Miniforge on a box with none (and the fake curl below records that instead).
pytestmark = pytest.mark.skipif(bool(system_conda_present()), reason="a conda under /opt would be found")


def doc_block() -> str:
    """The Protenix install-time licence block, read from the doc."""
    text = DOC.read_text()
    assert text.count(START) == 1 and text.count(END) == 1, "the doc must carry exactly one marked block"
    return text.split(START, 1)[1].split(END, 1)[0].strip("\n")


@pytest.fixture(scope="module")
def no_cc_path(tmp_path_factory) -> str:
    """A PATH that holds every ordinary tool and no C compiler, whatever this box has installed."""
    d = tmp_path_factory.mktemp("nocc")
    skip = re.compile(
        r"^(cc|c89|c99|gcc|g\+\+|c\+\+|cpp|.*-(gcc|g\+\+|cc|c\+\+)(-[0-9.]+)?|(gcc|g\+\+|cc)-.*|tcc|clang.*)$"
    )
    for src in ("/usr/bin", "/bin"):
        if not os.path.isdir(src):
            continue
        for name in os.listdir(src):
            if skip.match(name) or (d / name).exists():
                continue
            os.symlink(os.path.join(src, name), d / name)
    assert not any((d / n).exists() for n in ("cc", "gcc")), "the stand-in PATH still has a compiler"
    return str(d)


def _sandbox(tmp_path: Path, platform: str, no_cc_path: str, *, doc_text: str | None = None, cc: bool = True):
    """A copy of one installer in an otherwise empty checkout, with the licence doc beside it."""
    repo = tmp_path / "checkout"
    (repo / "install").mkdir(parents=True)
    script = repo / "install" / INSTALLERS[platform].name
    shutil.copy(INSTALLERS[platform], script)
    (repo / "Evaluator" / "docs").mkdir(parents=True)
    (repo / "Evaluator" / "docs" / DOC.name).write_text(DOC.read_text() if doc_text is None else doc_text)

    calls = tmp_path / "network-calls"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("curl", "wget"):
        fake = bin_dir / name
        fake.write_text(
            f'#!/bin/sh\necho "{name} $*" >> "{calls}"\n'
            'while [ $# -gt 0 ]; do [ "$1" = "-o" ] && out="$2"; shift; done\n'
            '[ -n "$out" ] && printf "#!/bin/sh\\nexit 1\\n" > "$out"\nexit 0\n'
        )
        fake.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home), "PATH": f"{bin_dir}:{no_cc_path}", "LC_ALL": "C"}
    if cc:
        env["CC"] = "/bin/true"  # a compiler that exists; the install itself is faked
    return repo, script, env, calls


def _run(script: Path, args: str, env: dict[str, str], repo: Path) -> tuple[int, str]:
    r = run_bash(f'bash "{script}" {args} </dev/null', env, repo)
    return r.returncode, r.stdout + r.stderr


def _run_tty(script: Path, args: str, env: dict[str, str], repo: Path, *answers: str) -> tuple[int, str]:
    """Run with a real terminal on stdin, so the installer sees an operator, and answer each
    `[y/N]` prompt in turn when it appears (typing ahead is not reliable across a pty)."""
    import select
    import time

    from tests.shell_helpers import _arch_override

    master, slave = pty.openpty()
    p = subprocess.Popen(
        ["bash", "-c", f'bash "{script}" {args}'],
        stdin=slave,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=_arch_override(env),
        cwd=str(repo),
    )
    out = b""
    answered = 0
    deadline = time.monotonic() + 90
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([p.stdout], [], [], 0.5)
            if ready:
                chunk = os.read(p.stdout.fileno(), 65536)
                if not chunk:
                    break
                out += chunk
                if out.count(b"[y/N]: ") > answered and answered < len(answers):
                    os.write(master, answers[answered].encode())
                    answered += 1
            elif p.poll() is not None:
                break
        else:
            p.kill()
            raise AssertionError("the installer did not finish:\n" + out.decode(errors="replace"))
        p.wait(timeout=30)
    finally:
        os.close(master)
        os.close(slave)
    return p.returncode, out.decode(errors="replace")


def _nothing_was_created(repo: Path, tmp_path: Path, calls: Path) -> None:
    assert not calls.exists(), f"something was fetched: {calls.read_text()}"
    assert not (repo / ".install_state").exists(), "a state marker was written"
    assert not (repo / "weights").exists(), "a weights directory was created"
    assert not (repo / "conda").exists(), "a conda was provisioned"


# ─── registry and vocabulary ────────────────────────────────────────────────────────────────


def _registry(src: str) -> dict[str, list[str]]:
    block = re.search(r"TOOL_REGISTRY=\((.*?)\n\)", src, re.S)
    assert block
    rows = {}
    for line in block.group(1).splitlines():
        m = re.search(r'"([^"]+)"', line)
        if m:
            parts = m.group(1).split("|")
            rows[parts[0]] = parts
    return rows


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_protenix_is_a_registered_opt_in_tool(platform):
    row = _registry(INSTALLERS[platform].read_text()).get("DO_PROTENIX")
    assert row is not None, f"{platform}: no DO_PROTENIX registry row"
    assert row[1:4] == ["Protenix", "install_protenix", "false"], row


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_tool_all_does_not_include_protenix(platform):
    src = INSTALLERS[platform].read_text()
    arm = re.search(r"^ {16}all\)\n(.*?)^ {16}bindcraft\)", src, re.S | re.M)
    assert arm, "the `all)` arm of the --tool parser was not found"
    code = "\n".join(line.split("#", 1)[0] for line in arm.group(1).splitlines())
    assert "DO_PROTENIX" not in code, "`--tool all` must not pull in Protenix"
    # and the plain `--tool protenix` spelling is accepted
    assert re.search(r"^ {16}protenix\)", src, re.M), "--tool protenix is not parsed"
    assert "protenix" in re.search(r"Must be one of: ([^$\"]+)", src).group(1)


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_tool_all_lists_the_same_tools_as_before(platform, tmp_path, no_cc_path):
    """`--verify --tool all` names exactly the registry tools the `all)` arm turns on, no Protenix."""
    repo, script, env, _calls = _sandbox(tmp_path, platform, no_cc_path)
    env["BINDERSCOUT_CONDA"] = str(fake_base(tmp_path / "base"))
    src = INSTALLERS[platform].read_text()
    arm = re.search(r"^ {16}all\)\n(.*?)^ {16}bindcraft\)", src, re.S | re.M).group(1)
    code = "\n".join(line.split("#", 1)[0] for line in arm.splitlines())
    names = {row[1] for flag, row in _registry(src).items() if re.search(rf"\b{flag}=true\b", code)}

    _rc, out = _run(script, "--verify --tool all --yes", env, repo)

    audited = re.sub(r"\x1b\[[0-9;]*m", "", out).split("Verifying installed tools", 1)[1]
    audited = re.split(r"Unusable:|All selected tools verified", audited)[0]
    listed = {m.group(1).strip() for m in re.finditer(r"^\s+[✓✗⚠]\s+(.+?)\s{2,}", audited, re.M)}
    assert listed == names, (listed ^ names, out)
    assert "Protenix" not in audited


# ─── --second-engine ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_second_engine_af3_is_refused_with_a_pointer(platform, tmp_path, no_cc_path):
    repo, script, env, calls = _sandbox(tmp_path, platform, no_cc_path)
    rc, out = _run(script, "--second-engine af3 --yes", env, repo)
    assert rc != 0, out
    assert "AF3 is installed with --tool af3" in out, out
    _nothing_was_created(repo, tmp_path, calls)


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_second_engine_with_an_unknown_name_names_the_valid_ones(platform, tmp_path, no_cc_path):
    repo, script, env, calls = _sandbox(tmp_path, platform, no_cc_path)
    rc, out = _run(script, "--second-engine bogus --yes", env, repo)
    assert rc != 0, out
    assert "bogus" in out and "protenix" in out, out
    _nothing_was_created(repo, tmp_path, calls)


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_the_valid_second_engines_come_from_one_constant(platform):
    src = INSTALLERS[platform].read_text()
    assert len(re.findall(r'^SECOND_ENGINE_VALID="protenix"$', src, re.M)) == 1
    # the error path reads the constant rather than spelling the list a second time
    assert "${SECOND_ENGINE_VALID}" in src


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_second_engine_protenix_selects_the_same_row_as_the_tool(platform, tmp_path, no_cc_path):
    """Both spellings reach the licence gate (no terminal, no --yes: refused there, nothing created)."""
    repo, script, env, calls = _sandbox(tmp_path, platform, no_cc_path)
    for args in ("--second-engine protenix", "--tool protenix"):
        rc, out = _run(script, args, env, repo)
        assert rc != 0, out
        assert doc_block() in out, args
        _nothing_was_created(repo, tmp_path, calls)


# ─── the licence gate ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_no_terminal_and_no_yes_prints_the_licence_and_refuses(platform, tmp_path, no_cc_path):
    repo, script, env, calls = _sandbox(tmp_path, platform, no_cc_path)
    rc, out = _run(script, "--tool protenix", env, repo)
    assert rc != 0, out
    assert doc_block() in out, "the licence text printed is not the doc's marked block"
    assert "--yes" in out, "the refusal must say how to accept"
    _nothing_was_created(repo, tmp_path, calls)


def test_the_block_says_what_the_brief_requires():
    block = doc_block()
    for needle in (
        "Apache-2.0",
        "v1.x only",
        "protenix.tos-cn-beijing.volces.com",
        "cuEquivariance",
        "2026-11-05",
        "https://github.com/bytedance/Protenix/blob/v1.1.0/README.md",
    ):
        assert needle in block, needle
    assert re.search(r"Protenix-v2 weights are proprietary", block)
    assert "never installed or used" in block


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
@pytest.mark.parametrize("variant", ["no_markers", "no_end", "empty_block"])
def test_a_licence_block_that_cannot_be_found_refuses_even_with_yes(platform, variant, tmp_path, no_cc_path):
    text = DOC.read_text()
    if variant == "no_markers":
        text = text.replace(START, "").replace(END, "")
    elif variant == "no_end":
        text = text.replace(END, "")
    else:
        text = text.split(START, 1)[0] + START + "\n\n" + END + text.split(END, 1)[1]
    repo, script, env, calls = _sandbox(tmp_path, platform, no_cc_path, doc_text=text)
    rc, out = _run(script, "--tool protenix --yes", env, repo)
    assert rc != 0, out
    assert "licence" in out.lower(), out
    _nothing_was_created(repo, tmp_path, calls)


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_a_missing_doc_refuses_too(platform, tmp_path, no_cc_path):
    repo, script, env, calls = _sandbox(tmp_path, platform, no_cc_path)
    (repo / "Evaluator" / "docs" / DOC.name).unlink()
    rc, out = _run(script, "--tool protenix --yes", env, repo)
    assert rc != 0, out
    _nothing_was_created(repo, tmp_path, calls)


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_declining_at_the_prompt_downloads_nothing_and_writes_no_marker(platform, tmp_path, no_cc_path):
    repo, script, env, calls = _sandbox(tmp_path, platform, no_cc_path)
    rc, out = _run_tty(script, "--tool protenix", env, repo, "n\n")
    assert rc != 0, out
    assert doc_block() in out
    assert "Accept and download? [y/N]" in out, out
    _nothing_was_created(repo, tmp_path, calls)


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_a_bare_enter_declines(platform, tmp_path, no_cc_path):
    repo, script, env, calls = _sandbox(tmp_path, platform, no_cc_path)
    rc, out = _run_tty(script, "--tool protenix", env, repo, "\n")
    assert rc != 0, out
    _nothing_was_created(repo, tmp_path, calls)


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_yes_prints_the_licence_before_the_first_download(platform, tmp_path, no_cc_path):
    """With --yes and no conda, the first thing fetched is the Miniforge: the licence is already on screen."""
    repo, script, env, calls = _sandbox(tmp_path, platform, no_cc_path)
    _rc, out = _run(script, "--tool protenix --yes --skip-preflight", env, repo)
    block_end = out.find(doc_block()) + len(doc_block())
    assert block_end > len(doc_block()) - 1, out
    assert calls.exists(), "the run never got as far as its first download"
    first_download = out.find("Miniforge")
    assert first_download > block_end, "a download line came before the licence text"


# ─── the compiler check ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_no_c_compiler_refuses_up_front_naming_the_fix(platform, tmp_path, no_cc_path):
    repo, script, env, calls = _sandbox(tmp_path, platform, no_cc_path, cc=False)
    rc, out = _run(script, "--tool protenix --yes --skip-preflight", env, repo)
    assert rc != 0, out
    assert "C compiler" in out and "CC" in out and "scikit-learn-extra" in out, out
    _nothing_was_created(repo, tmp_path, calls)


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_cc_pointing_at_nothing_is_not_a_compiler(platform, tmp_path, no_cc_path):
    repo, script, env, calls = _sandbox(tmp_path, platform, no_cc_path, cc=False)
    env["CC"] = "/nonexistent/compiler"
    rc, out = _run(script, "--tool protenix --yes --skip-preflight", env, repo)
    assert rc != 0, out
    _nothing_was_created(repo, tmp_path, calls)


# ─── the marker ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_the_marker_keeps_the_commit_field_and_records_the_licence(platform, tmp_path):
    src = INSTALLERS[platform]
    funcs = extract_functions(src, "mark_tool_installed", "_protenix_append_licence", "marker_recorded_sha")
    prog = (
        f'BINDERSCOUT_DIR="{tmp_path}"; INSTALL_STATE_DIR="{tmp_path}/.install_state"\n'
        'PROTENIX_LICENCE_TEXT="Licence line one\nLicence line two"\n'
        f"{funcs}\n"
        "mark_tool_installed protenix || exit 11\n"
        "mark_tool_installed rfd3 || exit 12\n"
        'marker_recorded_sha protenix; echo "sha-rc=$?"\n'
    )
    r = subprocess.run(["bash", "-c", prog], capture_output=True, text=True, env={"PATH": os.environ["PATH"]})
    assert r.returncode == 0, r.stdout + r.stderr
    marker = (tmp_path / ".install_state" / "protenix").read_text()
    first, *rest = marker.splitlines()
    assert re.fullmatch(r"\S+\t\S+", first), first  # `date<TAB>sha`, as every other marker
    body = "\n".join(rest)
    assert "Licence line one\nLicence line two" in body
    assert re.search(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", body), body
    # another tool's marker is exactly what it always was
    assert len((tmp_path / ".install_state" / "rfd3").read_text().splitlines()) == 1


# ─── the install, against a fake conda ──────────────────────────────────────────────────────

FAKE_CONDA = r"""#!/bin/sh
echo "conda $*" >> "$FAKE_LOG"
BASE="$(dirname "$(dirname "$0")")"
case "$1" in
  --version) echo "conda 24.0.0" ;;
  env) echo '{"envs": []}' ;;
  config) echo '{"envs_dirs": []}' ;;
  create)
    while [ $# -gt 0 ]; do [ "$1" = "-n" ] && name="$2"; shift; done
    mkdir -p "$BASE/envs/$name/bin"
    cp "$FAKE_PY" "$BASE/envs/$name/bin/python"
    printf '#!/bin/sh\nexit 0\n' > "$BASE/envs/$name/bin/binder-compare"
    chmod +x "$BASE/envs/$name/bin/python" "$BASE/envs/$name/bin/binder-compare"
    ;;
  run)
    shift
    while [ $# -gt 0 ]; do case "$1" in --live-stream) shift ;; -n) shift 2 ;; *) break ;; esac; done
    echo "run $*" >> "$FAKE_LOG"
    ;;
esac
exit 0
"""

FAKE_PY = r"""#!/bin/sh
echo "python $*" >> "$FAKE_LOG"
if [ -n "$PROTENIX_ROOT_DIR" ]; then
  mkdir -p "$PROTENIX_ROOT_DIR/checkpoint" "$PROTENIX_ROOT_DIR/common"
  truncate -s "${FAKE_CKPT_BYTES:-1475950125}" "$PROTENIX_ROOT_DIR/checkpoint/$PROTENIX_MODEL.pt"
  for f in components.cif components.cif.rdkit_mol.pkl clusters-by-entity-40.txt obsolete_release_date.csv; do
    echo x > "$PROTENIX_ROOT_DIR/common/$f"
  done
fi
[ -n "$FAKE_IMPORT_FAIL" ] && case "$*" in *"import protenix"*|*"import importlib.metadata"*) exit 1 ;; esac
exit 0
"""


def _flow(tmp_path: Path, platform: str, no_cc_path: str, **extra: str):
    repo, script, env, calls = _sandbox(tmp_path, platform, no_cc_path)
    base = fake_base(tmp_path / "base", conda_script=FAKE_CONDA)
    fake_py = tmp_path / "fake_python"
    fake_py.write_text(FAKE_PY)
    log = tmp_path / "fake.log"
    env.update(BINDERSCOUT_CONDA=str(base), FAKE_LOG=str(log), FAKE_PY=str(fake_py), **extra)
    return repo, script, env, calls, log, base


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_install_builds_the_env_fetches_the_weights_and_only_then_marks(platform, tmp_path, no_cc_path):
    repo, script, env, calls, log, _base = _flow(tmp_path, platform, no_cc_path)

    rc, out = _run(script, "--tool protenix --yes --skip-preflight", env, repo)

    assert rc == 0, out
    assert not calls.exists(), "a curl/wget fetch happened; weights come from Protenix's own downloader"
    calls_log = log.read_text()
    steps = [
        f"conda create -n {ENV} -y python=3.12 pip",
        "run pip install -q torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 "
        "--index-url https://download.pytorch.org/whl/cu128",
        "run pip install -q protenix==1.1.0",
        f"run pip install -q -e {repo}/Evaluator[report]",
    ]
    at = [calls_log.find(s) for s in steps]
    assert all(i >= 0 for i in at), (steps, calls_log)
    assert at == sorted(at), "install steps ran out of order"
    fetch = calls_log.find("download_from_url")
    assert fetch > at[-1], "the weights were fetched before the env was complete"
    # the weights landed where Task 18 will point --model-dir, with the exact checkpoint size
    ckpt = repo / "weights" / "protenix" / "checkpoint" / "protenix_base_default_v1.0.0.pt"
    assert ckpt.stat().st_size == CKPT_BYTES
    # no assertion on torch.cuda: a login node has no GPU
    assert "cuda.is_available" not in calls_log
    # the marker exists, and carries the licence that was shown plus a UTC date
    marker = (repo / ".install_state" / "protenix").read_text()
    assert doc_block() in marker
    assert re.search(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", marker), marker
    assert doc_block() in out


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_install_accepted_at_the_prompt_completes(platform, tmp_path, no_cc_path):
    repo, script, env, _calls, log, _base = _flow(tmp_path, platform, no_cc_path)
    rc, out = _run_tty(script, "--second-engine protenix --skip-preflight", env, repo, "y\n", "y\n")
    assert rc == 0, out
    assert (repo / ".install_state" / "protenix").is_file()
    assert doc_block() in out and "Accept and download? [y/N]" in out
    assert f"conda create -n {ENV}" in log.read_text()


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_a_wrong_checkpoint_size_refuses_and_writes_no_marker(platform, tmp_path, no_cc_path):
    repo, script, env, _calls, _log, _base = _flow(tmp_path, platform, no_cc_path, FAKE_CKPT_BYTES="1234")
    rc, out = _run(script, "--tool protenix --yes --skip-preflight", env, repo)
    assert rc != 0, out
    assert str(CKPT_BYTES) in out and "1234" in out, out
    assert not (repo / ".install_state" / "protenix").exists()


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_an_env_that_cannot_import_protenix_writes_no_marker(platform, tmp_path, no_cc_path):
    repo, script, env, _calls, _log, _base = _flow(tmp_path, platform, no_cc_path, FAKE_IMPORT_FAIL="1")
    rc, out = _run(script, "--tool protenix --yes --skip-preflight", env, repo)
    assert rc != 0, out
    assert not (repo / ".install_state" / "protenix").exists()


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_verify_lists_protenix_and_reads_the_weights(platform, tmp_path, no_cc_path):
    repo, script, env, _calls, _log, _base = _flow(tmp_path, platform, no_cc_path)
    assert _run(script, "--tool protenix --yes --skip-preflight", env, repo)[0] == 0

    rc, out = _run(script, "--verify --tool protenix --yes", env, repo)
    out = re.sub(r"\x1b\[[0-9;]*m", "", out)
    assert rc == 0, out
    assert re.search(r"✓\s+Protenix\s+usable", out), out

    # truncate the checkpoint: the audit must see it
    ckpt = repo / "weights" / "protenix" / "checkpoint" / "protenix_base_default_v1.0.0.pt"
    ckpt.write_bytes(b"x")
    rc, out = _run(script, "--verify --tool protenix --yes", env, repo)
    out = re.sub(r"\x1b\[[0-9;]*m", "", out)
    assert rc != 0, out
    assert re.search(r"✗\s+Protenix", out) and str(CKPT_BYTES) in out, out


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_uninstall_removes_env_weights_and_marker(platform, tmp_path, no_cc_path):
    repo, script, env, _calls, log, _base = _flow(tmp_path, platform, no_cc_path)
    assert _run(script, "--tool protenix --yes --skip-preflight", env, repo)[0] == 0
    assert (repo / "weights" / "protenix").is_dir()

    rc, out = _run(script, "--uninstall --tool protenix --yes", env, repo)

    assert rc == 0, out
    assert f"conda env remove -n {ENV}" in log.read_text()
    assert not (repo / "weights" / "protenix").exists()
    assert not (repo / ".install_state" / "protenix").exists()


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_uninstall_of_everything_still_works_and_reaches_protenix(platform, tmp_path, no_cc_path):
    repo, script, env, _calls, _log, _base = _flow(tmp_path, platform, no_cc_path)
    assert _run(script, "--tool protenix --yes --skip-preflight", env, repo)[0] == 0

    rc, out = _run(script, "--uninstall --tool all --yes", env, repo)

    assert rc == 0, out
    assert not (repo / "weights" / "protenix").exists(), "`--uninstall --tool all` left Protenix's weights behind"
    assert "Unknown tool" not in out


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_a_repeat_install_keeps_the_weights_it_already_has(platform, tmp_path, no_cc_path):
    repo, script, env, _calls, _log, _base = _flow(tmp_path, platform, no_cc_path)
    assert _run(script, "--tool protenix --yes --skip-preflight", env, repo)[0] == 0
    ckpt = repo / "weights" / "protenix" / "checkpoint" / "protenix_base_default_v1.0.0.pt"
    before = ckpt.stat().st_ino

    rc, out = _run(script, "--tool protenix --yes --skip-preflight", env, repo)

    assert rc == 0, out
    assert ckpt.stat().st_size == CKPT_BYTES and ckpt.stat().st_ino == before
    assert doc_block() in (repo / ".install_state" / "protenix").read_text()
