"""Logs are not named after their tool, and the denominator is not always in cfg.

Both found by running the monitor against the live campaign on 2026-10-30 rather
than against fixtures:

- The Protein-Hunter arm had died three hours earlier with an OOM, and
  run_arm.sh had written its FAILED marker correctly -- but into
  `logs/bm4_ph_v2.log`, a campaign log named after the box and the attempt, not
  `<run>/logs/protein_hunter.log`. A probe that only looks for `<tool>.log`
  reports that arm as a silent `DEAD` with no reason, which is most of the
  information lost.

  Attribution is therefore by run_arm.sh's own marker (`END <tool> rc=`), which
  carries the tool name inside the file, rather than by filename.

- `n_designs` in the run config is the campaign-wide default. Each tool writes
  its own `settings.json` with the number it was actually given, which is the
  authoritative denominator.
"""

import json

import pytest

from status.probes import probe_tool

CFG = {"name": "camp", "n_designs": 50}


def _run(tmp_path, tool):
    (tmp_path / "config.json").write_text(json.dumps(CFG))
    d = tmp_path / tool
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_a_campaign_log_named_after_the_box_is_still_attributed(tmp_path, monkeypatch):
    _run(tmp_path, "protein_hunter") / "settings.json"
    (tmp_path / "protein_hunter" / "settings.json").write_text("{}")
    logs = tmp_path / "campaign_logs"
    logs.mkdir()
    (logs / "bm4_ph_v2.log").write_text(
        "KeyError: 'plddt'\n"
        "######## END protein_hunter rc=1 2026-10-30T11:23:34+01:00 ########\n"
        "######## protein_hunter FAILED -- do not read this arm as a zero-yield run ########\n"
    )
    monkeypatch.setenv("BINDERSCOUT_LOG_DIRS", str(logs))
    warnings = probe_tool("protein_hunter", tmp_path, CFG)["warnings"]
    assert any("rc=1" in w for w in warnings), warnings


def test_another_tools_log_is_not_attributed_to_this_arm(tmp_path, monkeypatch):
    (_run(tmp_path, "rfd3") / "settings.json").write_text("{}")
    logs = tmp_path / "campaign_logs"
    logs.mkdir()
    (logs / "bm4_ph_v2.log").write_text("######## END protein_hunter rc=1 ########\n")
    monkeypatch.setenv("BINDERSCOUT_LOG_DIRS", str(logs))
    assert probe_tool("rfd3", tmp_path, CFG)["warnings"] == []


def test_a_successful_log_raises_no_warning(tmp_path, monkeypatch):
    (_run(tmp_path, "rfd3") / "settings.json").write_text("{}")
    logs = tmp_path / "campaign_logs"
    logs.mkdir()
    (logs / "bm4_rfd3.log").write_text("######## END rfd3 rc=0 2026-10-30T01:00:00+01:00 ########\n")
    monkeypatch.setenv("BINDERSCOUT_LOG_DIRS", str(logs))
    assert probe_tool("rfd3", tmp_path, CFG)["warnings"] == []


def test_the_tools_own_settings_beats_the_campaign_default(tmp_path):
    d = _run(tmp_path, "protein_hunter")
    (d / "settings.json").write_text(json.dumps({"design_params": {"num_designs": 700}}))
    assert probe_tool("protein_hunter", tmp_path, CFG)["total"] == 700


def test_a_settings_file_without_a_count_falls_back_to_the_campaign_default(tmp_path):
    d = _run(tmp_path, "rfd3")
    (d / "settings.json").write_text(json.dumps({"design_params": {"num_cycles": 7}}))
    assert probe_tool("rfd3", tmp_path, CFG)["total"] == 50


@pytest.mark.parametrize("alias", ["pxdesign_local", "pxdesign"])
def test_a_config_alias_probes_the_real_tool_directory(tmp_path, alias):
    # tools_enabled carries `pxdesign_local`; the directory on disk is `pxdesign`.
    # Without the alias this renders a second, empty row with no denominator.
    d = tmp_path / "pxdesign"
    d.mkdir()
    (tmp_path / "config.json").write_text(json.dumps(CFG))
    (d / "d0.pdb").write_text("ATOM\n")
    r = probe_tool(alias, tmp_path, CFG)
    assert (r["done"], r["total"]) == (1, 50)
