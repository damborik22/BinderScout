"""The host list comes from ``--hosts`` or ``$BINDERSCOUT_FLEET`` and nowhere else.

``fleet_hosts`` also honoured ``$FLEET_MACHINES``, the variable of one lab's own driver
script: a box that happened to export it for that script silently became a status
target here, and the name of the variable carried the lab's layout into a public CLI.
"""

from status.remote import fleet_hosts


def test_there_is_no_default_host(monkeypatch):
    monkeypatch.delenv("BINDERSCOUT_FLEET", raising=False)
    monkeypatch.delenv("FLEET_MACHINES", raising=False)
    assert fleet_hosts() == []


def test_the_documented_variable_is_honoured(monkeypatch):
    monkeypatch.setenv("BINDERSCOUT_FLEET", "host-a, host-b host-c")
    assert fleet_hosts() == ["host-a", "host-b", "host-c"]


def test_a_foreign_driver_variable_is_not_a_second_source(monkeypatch):
    monkeypatch.delenv("BINDERSCOUT_FLEET", raising=False)
    monkeypatch.setenv("FLEET_MACHINES", "host-a host-b")
    assert fleet_hosts() == []
