"""ssh errors quote the address. This document gets pushed to a published page.

Every address below is from an IETF documentation range (RFC 5737) and every
hostname from .invalid (RFC 2606), so this fixture cannot name a real machine --
the first draft of it pasted a real login-node address into a public repo.

`Connection reset by 192.0.2.10 port 22` is exactly right in a terminal and
exactly wrong in anything that leaves the lab: phase 2 of this feature publishes
the same document to a page, and the repo's standing rule is that no machine
address, username or home path appears anywhere shareable.

So the host error is reduced to its CATEGORY at the point it is captured, which
is the only place that can be sure it happens before the value is stored.
"""

import pytest

from status.remote import sanitise_ssh_error


@pytest.mark.parametrize(
    "raw",
    [
        "Connection reset by 192.0.2.10 port 22",
        "ssh: connect to host node01.example.invalid port 22: Connection refused",
        "someuser@198.51.100.7: Permission denied (publickey).",
        "kex_exchange_identification: read: Connection reset by peer",
    ],
)
def test_no_address_or_account_survives(raw):
    out = sanitise_ssh_error(raw)
    assert "192.0.2" not in out
    assert "198.51.100" not in out
    assert "203.0.113" not in out
    assert "@" not in out
    assert ".invalid" not in out
    assert "someuser" not in out


def test_the_category_is_still_useful():
    assert "reset" in sanitise_ssh_error("Connection reset by 192.0.2.10 port 22")
    assert "refused" in sanitise_ssh_error("ssh: connect to host node.example.invalid port 22: Connection refused")
    assert "denied" in sanitise_ssh_error("someuser@203.0.113.4: Permission denied (publickey).")
    assert "timeout" in sanitise_ssh_error("timeout after 25s")


def test_an_unrecognised_error_is_not_leaked_verbatim():
    out = sanitise_ssh_error("some novel failure mentioning host 203.0.113.9 and user someuser")
    assert "203.0.113.9" not in out
    assert "someuser" not in out
    assert out, "but it must still say something"
