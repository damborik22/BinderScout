"""`pxdesign_local` and `pxdesign` are one arm, and must render as one row.

config.json's tools_enabled carries `pxdesign_local`; the directory on disk is
`pxdesign`. Enumerating both produced two identical rows on the live fleet.
"""

import json

from status.collect import _enabled_tools


def test_an_alias_and_its_real_name_collapse_to_one(tmp_path):
    (tmp_path / "pxdesign").mkdir()
    raw = {"tools_enabled": {"pxdesign_local": True, "pxdesign": True, "rfd3": True}}
    tools = _enabled_tools(tmp_path, raw)
    assert tools.count("pxdesign") == 1
    assert "pxdesign_local" not in tools
    assert "rfd3" in tools


def test_the_alias_alone_still_yields_the_real_tool(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({}))
    raw = {"tools_enabled": {"pxdesign_local": True}}
    assert _enabled_tools(tmp_path, raw) == ["pxdesign"]
