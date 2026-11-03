"""Installing the shortcut must never write to stdout.

`binderscout.py` (re)writes its `bin/` and `~/.local/bin` shortcuts on every
invocation, and on the first run in a fresh checkout it said so on **stdout**.
Anything that captures stdout then starts with that line: `status --json` failed
`json.load` at char 0 on a clean clone, while the same command passed on any
box where the shortcut already existed -- which is why it looked flaky.

The notice is for a human, so it belongs on stderr. This test builds the fresh
state itself instead of depending on whether the shortcut happens to exist.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_cli():
    spec = importlib.util.spec_from_file_location("binderscout_cli_under_test", REPO / "binderscout.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_first_run_announces_the_shortcut_on_stderr_only(tmp_path, monkeypatch, capsys):
    cli = _load_cli()
    fake_repo = tmp_path / "checkout"
    fake_repo.mkdir()
    monkeypatch.setattr(cli, "REPO", fake_repo)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()

    cli._install_binderscout_shortcut()

    out, err = capsys.readouterr()
    assert (fake_repo / "bin" / "binderscout").exists(), "the shortcut was not written, so this test proved nothing"
    assert out == "", f"the shortcut notice leaked onto stdout, which `status --json` consumers parse: {out!r}"
    assert "Shortcut installed" in err


def test_an_unwritable_checkout_reports_on_stderr_only(tmp_path, monkeypatch, capsys):
    cli = _load_cli()
    # A FILE where the bin/ directory should be makes mkdir fail with an OSError on any user,
    # including root, so the failure path runs without depending on file permissions.
    fake_repo = tmp_path / "checkout"
    fake_repo.mkdir()
    (fake_repo / "bin").write_text("not a directory")
    monkeypatch.setattr(cli, "REPO", fake_repo)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()

    cli._install_binderscout_shortcut()

    out, err = capsys.readouterr()
    assert out == "", f"the failure notice leaked onto stdout: {out!r}"
    assert "Could not write" in err


def test_the_shim_survives_a_checkout_path_with_shell_metacharacters(tmp_path, monkeypatch):
    """`exec python3 "<path>"` broke for a path containing $, a backtick or a double quote."""
    import subprocess

    cli = _load_cli()
    weird = tmp_path / 'a "quoted" $HOME `dir`'
    weird.mkdir()
    fake_script = weird / "binderscout.py"
    fake_script.write_text("import sys\nprint('ran', sys.argv[1:])\n")
    monkeypatch.setattr(cli, "REPO", weird)
    monkeypatch.setattr(cli, "__file__", str(fake_script))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()

    cli._install_binderscout_shortcut()

    shim = weird / "bin" / "binderscout"
    assert shim.exists(), "the shim was not written, so this proved nothing"
    out = subprocess.run(["bash", str(shim), "x"], capture_output=True, text=True)
    assert out.stdout.strip() == "ran ['x']", (out.stdout, out.stderr)


def _two_checkouts(cli, tmp_path, monkeypatch):
    """HOME's shortcut belongs to checkout A (a real script on disk); B is the invoker."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    a = tmp_path / "a"
    a.mkdir()
    (a / "binderscout.py").write_text("")
    b = tmp_path / "b"
    b.mkdir()
    (b / "binderscout.py").write_text("")
    monkeypatch.setattr(cli, "REPO", a)
    monkeypatch.setattr(cli, "__file__", str(a / "binderscout.py"))
    cli._install_binderscout_shortcut()
    shim = home / ".local" / "bin" / "binderscout"
    assert str(a / "binderscout.py") in shim.read_text(), "setup: A should own the command"
    monkeypatch.setattr(cli, "REPO", b)
    monkeypatch.setattr(cli, "__file__", str(b / "binderscout.py"))
    return shim, a, b


def test_a_query_from_another_checkout_does_not_take_over_the_account_command(tmp_path, monkeypatch):
    """`status --json` from a throwaway verification clone silently re-pointed the account's
    `binderscout` at that clone (found in the v2.0.3 end-to-end run on the aarch64 host)."""
    cli = _load_cli()
    shim, a, b = _two_checkouts(cli, tmp_path, monkeypatch)
    cli._install_binderscout_shortcut(repoint=False)
    assert str(a / "binderscout.py") in shim.read_text()
    assert str(b / "binderscout.py") not in shim.read_text()


def test_install_may_take_the_command_over(tmp_path, monkeypatch):
    cli = _load_cli()
    shim, _a, b = _two_checkouts(cli, tmp_path, monkeypatch)
    cli._install_binderscout_shortcut(repoint=True)
    assert str(b / "binderscout.py") in shim.read_text()


def test_a_shim_whose_checkout_is_gone_is_healed_even_by_a_query(tmp_path, monkeypatch):
    cli = _load_cli()
    shim, a, b = _two_checkouts(cli, tmp_path, monkeypatch)
    (a / "binderscout.py").unlink()
    cli._install_binderscout_shortcut(repoint=False)
    assert str(b / "binderscout.py") in shim.read_text()


def test_only_the_install_command_is_allowed_to_repoint_the_account_command(monkeypatch):
    """The call site, not just the function: main() must pass repoint=True for `install` alone."""
    cli = _load_cli()
    seen = []
    monkeypatch.setattr(cli, "_install_binderscout_shortcut", lambda repoint=True: seen.append(repoint))
    monkeypatch.setattr(cli, "_dispatch", lambda cmd, rest: None)
    for argv, expected in ((["status", "--json"], False), (["evaluate", "--help"], False), (["install"], True)):
        seen.clear()
        monkeypatch.setattr(cli.sys, "argv", ["binderscout.py", *argv])
        cli.main()
        assert seen == [expected], (argv, seen)
