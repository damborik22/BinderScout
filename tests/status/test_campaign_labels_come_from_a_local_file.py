"""Campaign labels and deadlines are operator facts, so they live outside the repo.

The probe cannot know that four `tfr1_*` run directories are one campaign, nor
when it is due. Those are facts about the campaign, not about any box, and they
name real projects — so they come from a machine-local JSON file named by
$BINDERSCOUT_CAMPAIGNS, never from anything tracked here.

The terminal and the pushed page then read the same two maps from the same place,
which is the whole point: a grouping that exists only in the page would make the
two views disagree about what a campaign is.
"""

import json

from status.cli import build_document, load_campaign_map


def test_a_missing_file_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("BINDERSCOUT_CAMPAIGNS", str(tmp_path / "nope.json"))
    assert load_campaign_map() == {}


def test_no_variable_set_is_not_an_error(monkeypatch):
    monkeypatch.delenv("BINDERSCOUT_CAMPAIGNS", raising=False)
    assert load_campaign_map() == {}


def test_malformed_json_is_ignored_rather_than_crashing_the_view(tmp_path, monkeypatch):
    bad = tmp_path / "map.json"
    bad.write_text("{not json")
    monkeypatch.setenv("BINDERSCOUT_CAMPAIGNS", str(bad))
    assert load_campaign_map() == {}


def test_both_maps_reach_the_document(tmp_path, monkeypatch):
    path = tmp_path / "map.json"
    path.write_text(
        json.dumps(
            {
                "campaigns": {"tfr1_apical": "TfR1", "tfr1_rfd4": "TfR1"},
                "deadlines": {"TfR1": "2026-11-02T11:59:00Z"},
            }
        )
    )
    monkeypatch.setenv("BINDERSCOUT_CAMPAIGNS", str(path))
    monkeypatch.setattr("status.cli.collect_local", lambda host="local": {"reachable": True, "runs": {}})

    doc = build_document([], timeout_s=5)
    assert doc["campaigns"]["tfr1_rfd4"] == "TfR1"
    assert doc["deadlines"]["TfR1"] == "2026-11-02T11:59:00Z"


def test_unknown_keys_in_the_file_are_dropped(tmp_path, monkeypatch):
    path = tmp_path / "map.json"
    path.write_text(json.dumps({"campaigns": {"a": "A"}, "secrets": {"k": "v"}}))
    monkeypatch.setenv("BINDERSCOUT_CAMPAIGNS", str(path))
    monkeypatch.setattr("status.cli.collect_local", lambda host="local": {"reachable": True, "runs": {}})

    doc = build_document([], timeout_s=5)
    assert "secrets" not in doc
    assert doc["campaigns"] == {"a": "A"}
