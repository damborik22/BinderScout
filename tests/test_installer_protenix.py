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

import hashlib
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

# Only the one test that needs a box with NO conda (to see the Miniforge fetch that follows the licence)
# carries this; everything else runs against a fake base or refuses before conda is looked for, so it
# runs everywhere, Docker image (which has /opt/miniforge3) included.
needs_no_system_conda = pytest.mark.skipif(bool(system_conda_present()), reason="a conda under /opt would be found")

# The pins, spelled out: tests below assert the installers carry exactly these.
CKPT_SHA256 = "2b7d5a8b30494514fc47fd2271a16260528cdba170ba09cc112fdecd8f85ec04"
# The install-flow tests run the real installer text with these two constants rewritten to describe a
# tiny fake checkpoint (hashing 1.4 GB per test would add minutes); the real values are pinned statically.
FLOW_BYTES = 4096
FLOW_SHA256 = hashlib.sha256(bytes(FLOW_BYTES)).hexdigest()


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


def _sandbox(
    tmp_path: Path,
    platform: str,
    no_cc_path: str,
    *,
    doc_text: str | None = None,
    cc: bool = True,
    cxx: bool | None = None,
    arch: str = "auto",
):
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
    # install_aarch.sh asks "Continue anyway?" on any other architecture; these tests are about
    # Protenix, so the aarch64 script sees an aarch64 host unless a test asks for the real one.
    fake_arch = {"auto": "aarch64" if platform == "aarch64" else "", "native": ""}.get(arch, arch)
    if fake_arch:
        uname = bin_dir / "uname"
        uname.write_text(f'#!/bin/sh\n[ "$1" = "-m" ] && {{ echo {fake_arch}; exit 0; }}\nexec /usr/bin/uname "$@"\n')
        uname.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home), "PATH": f"{bin_dir}:{no_cc_path}", "LC_ALL": "C"}
    # compilers that exist; the install itself is faked. The gate wants a C AND a C++ compiler, so a
    # fixture that expects to get past it provides both (cxx follows cc unless a test says otherwise).
    if cc:
        env["CC"] = "/bin/true"
    if cc if cxx is None else cxx:
        env["CXX"] = "/bin/true"
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
    # Generous and tunable: a loaded machine (the whole suite, other jobs) can stretch a 3 s run a lot.
    budget = float(os.environ.get("BINDERSCOUT_TEST_TTY_DEADLINE", "300"))
    deadline = time.monotonic() + budget

    def _fail(what: str):
        p.kill()
        p.wait()
        tail = out.decode(errors="replace")[-1500:]
        raise AssertionError(f"{what} within {budget:.0f}s (BINDERSCOUT_TEST_TTY_DEADLINE). Last output:\n{tail}")

    try:
        while True:
            if time.monotonic() > deadline:
                _fail("the installer did not finish")
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
        try:
            p.wait(timeout=max(30.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            _fail("the installer closed its output but did not exit")
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


@needs_no_system_conda
@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_yes_prints_the_licence_before_the_first_download(platform, tmp_path, no_cc_path):
    """With --yes and no conda, the first thing fetched is the Miniforge: the licence is already on screen."""
    repo, script, env, calls = _sandbox(tmp_path, platform, no_cc_path)
    _rc, out = _run(script, "--tool protenix --yes --skip-preflight", env, repo)
    assert doc_block() in out, "the licence block was never printed"
    block_end = out.find(doc_block()) + len(doc_block())
    assert calls.exists() and "Miniforge" in out[block_end:], (
        "no download line appeared after the licence: the run never reached its first download"
    )
    assert "Miniforge" not in out[: out.find(doc_block())], "a download line came before the licence text"


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
    repo, script, env, calls = _sandbox(tmp_path, platform, no_cc_path, cc=False, cxx=True)
    env["CC"] = "/nonexistent/compiler"
    rc, out = _run(script, "--tool protenix --yes --skip-preflight", env, repo)
    assert rc != 0, out
    _nothing_was_created(repo, tmp_path, calls)


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_protenix_is_in_the_toolchain_preflight_table(platform):
    src = INSTALLERS[platform].read_text()
    block = re.search(r"TOOLCHAIN_TOOLS=\((.*?)\n\)", src, re.S)
    assert block and re.search(r'"DO_PROTENIX\|Protenix\|[^"]+"', block.group(1)), "Protenix is not in TOOLCHAIN_TOOLS"


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_a_conda_forge_style_compiler_name_is_accepted(platform, tmp_path, no_cc_path):
    """check_build_toolchain accepts <arch>-conda-linux-gnu-gcc, so the early check must too."""
    repo, script, env, calls = _sandbox(tmp_path, platform, no_cc_path, cc=False)
    arch = "aarch64" if platform == "aarch64" else os.uname().machine
    cdir = tmp_path / "condacc"
    cdir.mkdir()
    for name in ("gcc", "g++"):
        (cdir / f"{arch}-conda-linux-gnu-{name}").write_text("#!/bin/sh\nexit 0\n")
        (cdir / f"{arch}-conda-linux-gnu-{name}").chmod(0o755)
    env["PATH"] = f"{cdir}:{env['PATH']}"
    rc, out = _run(script, "--tool protenix", env, repo)  # no terminal, no --yes: stops at the licence
    assert "No C compiler found" not in out and "No C++ compiler found" not in out, out
    assert doc_block() in out, "the gate after the compiler check was never reached"
    assert rc != 0
    _nothing_was_created(repo, tmp_path, calls)


def _on_path(tmp_path: Path, env: dict[str, str], *names: str) -> None:
    d = tmp_path / "extra-bin"
    d.mkdir(exist_ok=True)
    for name in names:
        (d / name).write_text("#!/bin/sh\nexit 0\n")
        (d / name).chmod(0o755)
    env["PATH"] = f"{d}:{env['PATH']}"


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_gcc_without_a_cxx_compiler_is_refused_up_front_before_the_licence(platform, tmp_path, no_cc_path):
    """A gcc-only box passed the old gate, accepted the licence, then died building scikit-learn-extra."""
    repo, script, env, calls = _sandbox(tmp_path, platform, no_cc_path, cc=False)
    _on_path(tmp_path, env, "gcc")
    rc, out = _run(script, "--tool protenix --yes --skip-preflight", env, repo)
    assert rc != 0, out
    assert "No C++ compiler found" in out and "g++" in out and "export CXX=/path/to/g++" in out, out
    assert "scikit-learn-extra" in out and "No C compiler found" not in out, out
    assert doc_block() not in out, "the licence was shown to a run that cannot build"
    _nothing_was_created(repo, tmp_path, calls)


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_a_conda_forge_style_cxx_name_is_accepted(platform, tmp_path, no_cc_path):
    repo, script, env, calls = _sandbox(tmp_path, platform, no_cc_path, cc=True, cxx=False)
    arch = "aarch64" if platform == "aarch64" else os.uname().machine
    _on_path(tmp_path, env, f"{arch}-conda-linux-gnu-g++")
    rc, out = _run(script, "--tool protenix", env, repo)
    assert "No C++ compiler found" not in out and doc_block() in out and rc != 0, out
    _nothing_was_created(repo, tmp_path, calls)


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_cxx_environment_variable_is_accepted_and_a_bad_one_is_not(platform, tmp_path, no_cc_path):
    repo, script, env, calls = _sandbox(tmp_path, platform, no_cc_path, cc=False)
    _on_path(tmp_path, env, "gcc")
    env["CXX"] = "/bin/true"
    rc, out = _run(script, "--tool protenix", env, repo)
    assert "No C++ compiler found" not in out and doc_block() in out and rc != 0, out

    env["CXX"] = "/nonexistent/g++"
    rc, out = _run(script, "--tool protenix", env, repo)
    assert "No C++ compiler found" in out and doc_block() not in out and rc != 0, out
    _nothing_was_created(repo, tmp_path, calls)


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_both_compilers_present_reaches_the_licence_gate(platform, tmp_path, no_cc_path):
    repo, script, env, calls = _sandbox(tmp_path, platform, no_cc_path, cc=False)
    _on_path(tmp_path, env, "gcc", "g++")
    rc, out = _run(script, "--tool protenix", env, repo)
    assert "compiler found" not in out and doc_block() in out and rc != 0, out
    _nothing_was_created(repo, tmp_path, calls)


# ─── a wrong-architecture run is refused before any licence is shown ───────────────────────────


def test_a_wrong_architecture_is_refused_before_a_licence_is_shown_aarch64_script(tmp_path, no_cc_path):
    if os.uname().machine == "aarch64":
        pytest.skip("this host really is aarch64")
    repo, script, env, calls = _sandbox(tmp_path, "aarch64", no_cc_path, arch="native")
    rc, out = _run(script, "--tool protenix", env, repo)
    assert rc != 0 and "Expected aarch64" in out, out
    assert doc_block() not in out, "a licence was shown to a run that was about to be refused for its architecture"
    _nothing_was_created(repo, tmp_path, calls)


def test_a_wrong_architecture_is_refused_before_a_licence_is_shown_x86_script(tmp_path, no_cc_path):
    repo, script, env, calls = _sandbox(tmp_path, "x86", no_cc_path, arch="aarch64")
    # install.sh looks for conda before it refuses an aarch64 host (existing order); give it one
    env["BINDERSCOUT_CONDA"] = str(fake_base(tmp_path / "base"))
    # direct subprocess: run_bash would add the override that lets install.sh run on aarch64
    r = subprocess.run(
        ["bash", str(script), "--tool", "protenix"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(repo),
        timeout=120,
    )
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "x86_64 installer" in out, out
    assert doc_block() not in out, "a licence was shown to a run that was about to be refused for its architecture"
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
    echo "env CC=$CC CXX=$CXX" >> "$FAKE_LOG"
    ;;
esac
exit 0
"""

FAKE_PY = r"""#!/bin/sh
echo "python $*" >> "$FAKE_LOG"
if [ -n "$PROTENIX_ROOT_DIR" ]; then
  mkdir -p "$PROTENIX_ROOT_DIR/checkpoint" "$PROTENIX_ROOT_DIR/common"
  ckpt="$PROTENIX_ROOT_DIR/checkpoint/$PROTENIX_MODEL.pt"
  if [ -n "$FAKE_FETCH_FAIL" ]; then   # a dropped connection: only a .part exists, and the step fails
    head -c 100 /dev/zero > "$ckpt.part"
    exit 1
  fi
  if [ -n "$FAKE_BAD_HASH" ]; then     # the right size, the wrong bytes
    head -c "${FAKE_CKPT_BYTES:-4096}" /dev/zero | tr '\0' x > "$ckpt"
  else
    head -c "${FAKE_CKPT_BYTES:-4096}" /dev/zero > "$ckpt"
  fi
  for f in components.cif components.cif.rdkit_mol.pkl clusters-by-entity-40.txt obsolete_release_date.csv; do
    echo x > "$PROTENIX_ROOT_DIR/common/$f"
  done
fi
[ -n "$FAKE_IMPORT_FAIL" ] && case "$*" in *"import protenix"*|*"import importlib.metadata"*) exit 1 ;; esac
exit 0
"""


def _flow(tmp_path: Path, platform: str, no_cc_path: str, **extra: str):
    repo, script, env, calls = _sandbox(tmp_path, platform, no_cc_path)
    # describe a tiny fake checkpoint to the installer text under test (see FLOW_BYTES)
    text = script.read_text()
    assert text.count(f"PROTENIX_CKPT_BYTES={CKPT_BYTES}\n") == 1 and text.count(CKPT_SHA256) == 1
    script.write_text(text.replace(str(CKPT_BYTES), str(FLOW_BYTES), 1).replace(CKPT_SHA256, FLOW_SHA256))
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
    # the compilers the gate accepted reach the build: the pip steps inherit $CC / $CXX
    assert "env CC=/bin/true CXX=/bin/true" in calls_log
    fetch = calls_log.find("download_from_url")
    assert fetch > at[-1], "the weights were fetched before the env was complete"
    # the weights landed where Task 18 will point --model-dir, with the (flow-sized) checkpoint
    ckpt = repo / "weights" / "protenix" / "checkpoint" / "protenix_base_default_v1.0.0.pt"
    assert ckpt.stat().st_size == FLOW_BYTES
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
    rc, out = _run_tty(script, "--second-engine protenix --skip-preflight", env, repo, "y\n")
    assert rc == 0, out
    assert (repo / ".install_state" / "protenix").is_file()
    assert doc_block() in out and "Accept and download? [y/N]" in out
    assert f"conda create -n {ENV}" in log.read_text()


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_a_wrong_checkpoint_size_refuses_and_writes_no_marker(platform, tmp_path, no_cc_path):
    repo, script, env, _calls, _log, _base = _flow(tmp_path, platform, no_cc_path, FAKE_CKPT_BYTES="1234")
    rc, out = _run(script, "--tool protenix --yes --skip-preflight", env, repo)
    assert rc != 0, out
    assert str(FLOW_BYTES) in out and "1234" in out, out
    assert not (repo / ".install_state" / "protenix").exists()


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_a_wrong_checkpoint_hash_refuses_names_both_hashes_and_removes_the_file(platform, tmp_path, no_cc_path):
    repo, script, env, _calls, _log, _base = _flow(tmp_path, platform, no_cc_path, FAKE_BAD_HASH="1")
    rc, out = _run(script, "--tool protenix --yes --skip-preflight", env, repo)
    observed = hashlib.sha256(b"x" * FLOW_BYTES).hexdigest()
    assert rc != 0, out
    assert FLOW_SHA256 in out and observed in out, "the refusal must name the expected and the observed hash"
    assert not (repo / "weights" / "protenix" / "checkpoint" / "protenix_base_default_v1.0.0.pt").exists()
    assert not (repo / ".install_state" / "protenix").exists()


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_a_download_that_dies_leaves_no_checkpoint_and_no_marker(platform, tmp_path, no_cc_path):
    repo, script, env, _calls, _log, _base = _flow(tmp_path, platform, no_cc_path, FAKE_FETCH_FAIL="1")
    rc, out = _run(script, "--tool protenix --yes --skip-preflight", env, repo)
    ckdir = repo / "weights" / "protenix" / "checkpoint"
    assert rc != 0, out
    assert not (ckdir / "protenix_base_default_v1.0.0.pt").exists(), "a half-downloaded file looks finished"
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
    assert re.search(r"✗\s+Protenix", out) and str(FLOW_BYTES) in out, out


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
def test_a_repeat_install_still_succeeds_and_keeps_its_marker(platform, tmp_path, no_cc_path):
    """Resume behaviour itself (skip finished files, .part then rename) is executed below, against the
    real embedded download code; here only the flow around it."""
    repo, script, env, _calls, _log, _base = _flow(tmp_path, platform, no_cc_path)
    assert _run(script, "--tool protenix --yes --skip-preflight", env, repo)[0] == 0
    rc, out = _run(script, "--tool protenix --yes --skip-preflight", env, repo)
    assert rc == 0, out
    assert doc_block() in (repo / ".install_state" / "protenix").read_text()


# ─── the embedded download code, executed ──────────────────────────────────────────────────

# The key names the installer indexes in Protenix's own URL table (protenix 1.1.0
# web_service/dependency_url.py) and the layout it writes under PROTENIX_ROOT_DIR.
URL_KEYS = {
    "protenix_base_default_v1.0.0": "checkpoint/protenix_base_default_v1.0.0.pt",
    "ccd_components_file": "common/components.cif",
    "ccd_components_rdkit_mol_file": "common/components.cif.rdkit_mol.pkl",
    "pdb_cluster_file": "common/clusters-by-entity-40.txt",
    "obsolete_release_data_csv": "common/obsolete_release_date.csv",
}

STUB_INFERENCE = """
import os, urllib.request

def download_from_url(tos_url, checkpoint_path, check_weight=True):
    assert check_weight is False, "install must not unpickle a download"
    fail = os.environ.get("STUB_FAIL_SUFFIX")
    if fail and tos_url.endswith(fail):
        with open(checkpoint_path, "wb") as f:
            f.write(b"partial")
        raise RuntimeError("connection dropped")
    urllib.request.urlretrieve(tos_url, checkpoint_path)
"""


def _embedded_download_code(platform: str) -> str:
    fn = extract_functions(INSTALLERS[platform], "_protenix_fetch_weights")
    m = re.search(r"<<'PY'\n(.*?)\nPY\n", fn, re.S)
    assert m, "the embedded download program was not found in _protenix_fetch_weights"
    return m.group(1)


def _stubbed_download(tmp_path: Path, platform: str, **env_extra: str):
    """Run the installer's own download program against a stub Protenix whose URL table is file://."""
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    urls = {}
    for key in URL_KEYS:
        f = src / key
        f.write_bytes(f"content of {key}\n".encode())
        urls[key] = f.as_uri()
    stub = tmp_path / "stub"
    for pkg in ("protenix", "protenix/web_service", "runner"):
        (stub / pkg).mkdir(parents=True, exist_ok=True)
        (stub / pkg / "__init__.py").write_text("")
    (stub / "protenix/web_service/dependency_url.py").write_text(f"URL = {urls!r}\n")
    (stub / "runner/inference.py").write_text(STUB_INFERENCE)
    root = tmp_path / "root"
    model = "protenix_base_default_v1.0.0"
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": str(stub),
        "PROTENIX_ROOT_DIR": str(root),
        "PROTENIX_MODEL": model,
        "PROTENIX_CKPT_BYTES": str(len(f"content of {model}\n")),
        **env_extra,
    }
    r = subprocess.run(
        [sys.executable, "-c", _embedded_download_code(platform)], env=env, capture_output=True, text=True, cwd=tmp_path
    )
    return r, root, src


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_the_embedded_download_indexes_the_right_keys_and_writes_the_right_layout(platform, tmp_path):
    r, root, src = _stubbed_download(tmp_path, platform)
    assert r.returncode == 0, r.stdout + r.stderr
    for key, rel in URL_KEYS.items():
        assert (root / rel).read_bytes() == (src / key).read_bytes(), key
    assert not list(root.rglob("*.part")), "a .part file was left behind"


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_an_interrupted_download_leaves_only_a_part_file_and_a_rerun_resumes(platform, tmp_path):
    ckpt_rel = URL_KEYS["protenix_base_default_v1.0.0"]
    r, root, _src = _stubbed_download(tmp_path, platform, STUB_FAIL_SUFFIX="protenix_base_default_v1.0.0")
    assert r.returncode != 0
    assert not (root / ckpt_rel).exists(), "a half-downloaded checkpoint looks finished"
    assert (root / (ckpt_rel + ".part")).exists()

    # a file an earlier run finished must not be fetched again; the stale .part must go
    done = root / URL_KEYS["ccd_components_file"]
    done.parent.mkdir(parents=True, exist_ok=True)
    done.write_bytes(b"SENTINEL: finished earlier")
    r, root, src = _stubbed_download(tmp_path, platform)
    assert r.returncode == 0, r.stdout + r.stderr
    assert done.read_bytes() == b"SENTINEL: finished earlier", "a finished file was downloaded again"
    assert (root / ckpt_rel).read_bytes() == (src / "protenix_base_default_v1.0.0").read_bytes()
    assert not list(root.rglob("*.part"))


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_a_checkpoint_of_the_wrong_size_is_replaced_not_kept(platform, tmp_path):
    ckpt = tmp_path / "root" / URL_KEYS["protenix_base_default_v1.0.0"]
    ckpt.parent.mkdir(parents=True)
    ckpt.write_bytes(b"truncated")
    r, _root, src = _stubbed_download(tmp_path, platform)
    assert r.returncode == 0, r.stdout + r.stderr
    assert ckpt.read_bytes() == (src / "protenix_base_default_v1.0.0").read_bytes()


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_the_installers_pin_the_checkpoint_size_and_hash(platform):
    src = INSTALLERS[platform].read_text()
    assert re.search(rf"^PROTENIX_CKPT_BYTES={CKPT_BYTES}$", src, re.M)
    assert re.search(rf'^PROTENIX_CKPT_SHA256="{CKPT_SHA256}"$', src, re.M)
    assert CKPT_SHA256 in DOC.read_text(), "the licence record does not state the pinned hash"


# ─── the aarch64-only warning ───────────────────────────────────────────────────────────────

AARCH64_WARNING = "UNVALIDATED ON aarch64 HARDWARE"


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_only_the_aarch64_installer_warns_that_its_cu128_torch_is_unvalidated(platform, tmp_path, no_cc_path):
    repo, script, env, _calls, _log, _base = _flow(tmp_path, platform, no_cc_path)
    rc, out = _run(script, "--tool protenix --yes --skip-preflight", env, repo)
    assert rc == 0, "the warning must not block the install:\n" + out
    if platform == "aarch64":
        assert AARCH64_WARNING in out and "cu128" in out and "cu130" in out, out
        assert "torch.cuda.is_available() == True" in out and "torch.ones(8, device='cuda')" in out, out
        # after the licence was accepted, before any install work
        assert out.index(doc_block()) < out.index(AARCH64_WARNING)
        assert (repo / ".install_state" / "protenix").is_file()
    else:
        assert AARCH64_WARNING not in out, "the x86 installer must not carry the aarch64 warning"
