"""Nothing enforced the public-repo identifier rule across the tree. Now something does.

CLAUDE.md states the rule -- no machine IPs, DNS hostnames, Unix usernames,
absolute /home paths, cluster accounts or SSH host-key fingerprints in tracked
files -- and then says plainly: "Nothing enforces it across the tree, which is
why the claim above could be false for three days without anyone noticing."

That gap is not theoretical. On 2026-10-30 a test fixture written for the status
monitor pasted a real cluster login-node address into a tracked file to exercise
an error sanitiser. It was caught by a manual grep before being pushed; nothing
in the suite would have caught it.

The checks here DERIVE what to look for rather than listing it, which matters
twice over: the test itself would otherwise have to contain the very identifiers
it bans, and a derived check adapts to whichever box it runs on.

  own account name   -> from the home directory
  own hostname       -> from the kernel
  private IPv4       -> the RFC 1918 ranges, by shape
  key fingerprints   -> by shape

Documentation ranges (RFC 5737) and loopback are deliberately allowed: fixtures
need addresses, and those are the addresses fixtures are supposed to use.

A companion check for absolute /home paths lives in
tests/test_no_user_home_paths_in_tree.py, which this does not duplicate.
"""

import re
import socket
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# A binary with a build-time path baked in by whatever compiled it; recorded in
# CLAUDE.md rather than patched, because removing it needs an aarch64 rebuild.
KNOWN_EXEMPT = {"tools/aarch64/dssp"}

# RFC 1918, by shape. The real address that slipped through was in 10/8.
_PRIVATE_IPV4 = re.compile(
    r"(?<![0-9.])(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3})(?![0-9.])"
)

# ssh-keygen / known_hosts fingerprints.
_FINGERPRINT = re.compile(r"SHA256:[A-Za-z0-9+/]{43}")


def _tracked_text_files():
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, text=True, check=True
    ).stdout
    for rel in filter(None, out.split("\0")):
        if rel in KNOWN_EXEMPT:
            continue
        path = REPO / rel
        try:
            yield rel, path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # binary or unreadable; the home-path test covers binaries


def _hits(pattern):
    found = []
    for rel, text in _tracked_text_files():
        for line_no, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                found.append(f"{rel}:{line_no}")
    return found


def test_no_private_ipv4_address_is_tracked():
    hits = _hits(_PRIVATE_IPV4)
    assert not hits, (
        "private IPv4 address in tracked file(s): "
        + ", ".join(hits[:10])
        + "  -- use an RFC 5737 documentation range (192.0.2.x / 198.51.100.x / 203.0.113.x)"
    )


def test_no_ssh_host_key_fingerprint_is_tracked():
    hits = _hits(_FINGERPRINT)
    assert not hits, "SSH host-key fingerprint in tracked file(s): " + ", ".join(hits[:10])


def test_this_accounts_name_does_not_appear_in_the_tree():
    account = Path.home().name
    if not account or len(account) < 4:
        return  # too short to match meaningfully without false positives
    hits = _hits(re.compile(r"\b" + re.escape(account) + r"\b"))
    assert not hits, (
        f"this box's account name appears in tracked file(s): {', '.join(hits[:10])}"
        "  -- use $HOME or a repo-relative path"
    )


def test_this_machines_hostname_does_not_appear_in_the_tree():
    labels = {socket.gethostname(), socket.gethostname().split(".")[0]}
    for label in labels:
        if not label or len(label) < 5:
            continue
        hits = _hits(re.compile(r"\b" + re.escape(label) + r"\b", re.IGNORECASE))
        assert not hits, (
            f"this box's hostname {label!r} appears in tracked file(s): {', '.join(hits[:10])}"
            "  -- use the ~/.ssh/config alias"
        )
