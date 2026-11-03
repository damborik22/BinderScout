"""The checkout marker must not be repointed at a clone that has no runs, and the scan follows a home link.

`runs/` is gitignored, so every git worktree and scratch clone lacks it. The marker used to be
rewritten by EVERY CLI invocation from whatever checkout ran it and was accepted without `runs/`, so
one run of the CLI from a scratch clone repointed the box's marker and the ssh probe then reported
zero runs. It is also common for a checkout to be reached through a symlink in $HOME (it lives on
other storage); the bounded scan skipped symlinked directories and never found it.
"""

import pytest

from status import collect
from status.collect import checkout_marker_path, record_checkout, resolve_repo


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("BINDERSCOUT_DIR", raising=False)
    return h


def _checkout(path, runs=True):
    path.mkdir(parents=True)
    (path / "binderscout.py").write_text("# stand-in\n")
    if runs:
        (path / "runs").mkdir()
    return path


def test_a_marker_naming_a_clone_without_runs_falls_through_to_the_scan(home, tmp_path):
    real = _checkout(home / "work" / "real")
    scratch = _checkout(tmp_path / "scratch", runs=False)
    marker = checkout_marker_path()
    marker.parent.mkdir(parents=True)
    marker.write_text(str(scratch) + "\n")

    assert resolve_repo() == real


def test_running_the_cli_from_a_clone_without_runs_does_not_repoint_a_working_marker(home, tmp_path):
    real = _checkout(tmp_path / "storage" / "real")
    scratch = _checkout(tmp_path / "scratch", runs=False)
    record_checkout(real)

    record_checkout(scratch)

    assert checkout_marker_path().read_text().strip() == str(real.resolve())
    assert resolve_repo() == real.resolve()


def test_a_clone_without_runs_is_still_recorded_when_nothing_better_is_recorded(home, tmp_path):
    scratch = _checkout(tmp_path / "scratch", runs=False)
    record_checkout(scratch)
    assert checkout_marker_path().read_text().strip() == str(scratch.resolve())


def test_a_checkout_with_runs_replaces_a_stale_marker(home, tmp_path):
    old = _checkout(tmp_path / "old")
    new = _checkout(tmp_path / "new")
    record_checkout(old)
    (old / "binderscout.py").unlink()

    record_checkout(new)

    assert resolve_repo() == new.resolve()


def test_the_scan_follows_a_symlink_directly_under_home(home, tmp_path):
    real = _checkout(tmp_path / "other_storage" / "repo")
    (home / "BinderScout").symlink_to(real, target_is_directory=True)

    assert resolve_repo() == home / "BinderScout"


def test_a_link_back_to_home_is_not_walked_again_and_does_not_eat_the_scan_budget(home, tmp_path, monkeypatch):
    """`self -> $HOME` is already visited (by realpath): walking it would revisit every sibling and,
    with the directory cap, push the real checkout out of reach."""
    real = _checkout(home / "zz" / "repo")
    (home / "self").symlink_to(home, target_is_directory=True)
    monkeypatch.setattr(collect, "_SCAN_MAX_DIRS", 3)

    assert resolve_repo() == real


def test_two_links_to_one_checkout_still_find_it(home, tmp_path):
    real = _checkout(tmp_path / "storage" / "repo")
    (home / "a").symlink_to(real, target_is_directory=True)
    (home / "b").symlink_to(real, target_is_directory=True)

    assert resolve_repo() == home / "a"


def test_symlinks_below_depth_one_are_still_not_followed(home, tmp_path):
    real = _checkout(tmp_path / "storage" / "repo")
    (home / "dir").mkdir()
    (home / "dir" / "link").symlink_to(real, target_is_directory=True)

    assert resolve_repo() is None
