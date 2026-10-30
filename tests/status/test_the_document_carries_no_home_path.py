"""The status document is published to a page, so it must name no account.

`collect_local` reported the checkout as an absolute path. Captured across the
fleet that produced four real Unix account names in one 10 KB document -- every
box's, not just this one's -- and phase 2 publishes exactly this document to a
page. The repo path is still worth reporting (it tells you WHICH checkout a box
probed, and they are not uniform), so it is reported relative to the home
directory instead of dropped.
"""

import json

from status.collect import collect_local, home_relative


def test_a_home_path_becomes_tilde_relative():
    import pathlib

    home = pathlib.Path.home()
    assert home_relative(home / "dev" / "BindMaster") == "~/dev/BindMaster"
    assert home_relative(home) == "~"


def test_a_path_outside_home_is_kept_but_carries_no_account():
    assert home_relative("/opt/binderscout") == "/opt/binderscout"


def test_the_collected_document_names_no_account(tmp_path):
    (tmp_path / "runs").mkdir()
    doc = collect_local(repo_root=tmp_path, host="probe")
    blob = json.dumps(doc)
    assert "/home/" not in blob, blob[:400]


def test_the_real_local_document_names_no_account():
    # Belt and braces: the actual probe of this box, not a fixture.
    blob = json.dumps(collect_local(host="local"))
    assert "/home/" not in blob
