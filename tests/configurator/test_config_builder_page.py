"""The static config-builder page must not become a second source of truth.

`configurator.py` is ~4,600 lines driving a linear wizard, and a headless
`--config config.json` replay already exists — so a form that only emits that
JSON is a genuinely useful second door into the pipeline, for anyone who does
not want to answer eighty prompts.

The risk is the one this repo keeps paying for: a second surface listing tools
and flags drifts from the first. So the page is GENERATED from
`REQUIRED_CFG_KEYS` and the shipped example, never hand-written, and these tests
fail if the committed page stops matching what the generator produces. That
makes drift a red CI run rather than a config that enables nothing.

The traps the audit found are pinned individually, because each is silent:
`tools_enabled` uses `pxdesign_local` (a config saying `pxdesign` enables
nothing and exits 1); `use_boltz` / `use_af3` / `primary_engine` read from `cfg`
despite looking like `tools_enabled` keys; and `run_dir` must be relative.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GENERATOR = REPO / "tools" / "make_config_builder.py"
PAGE = REPO / "docs" / "config-builder.html"


def _generate() -> str:
    out = subprocess.run([sys.executable, str(GENERATOR), "--stdout"], capture_output=True, text=True, cwd=REPO)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_the_committed_page_matches_the_generator():
    """THE drift guard. If configurator.py gains a tool or a key and nobody
    regenerates, this fails instead of the page quietly going stale."""
    assert PAGE.exists(), f"{PAGE} is missing — run tools/make_config_builder.py"
    assert PAGE.read_text() == _generate(), (
        "docs/config-builder.html is out of date with configurator.py. "
        "Regenerate it: python tools/make_config_builder.py"
    )


def test_every_tool_the_configurator_knows_appears():
    sys.path.insert(0, str(REPO / "configurator"))
    import configurator as conf

    page = PAGE.read_text()
    for tool in conf.REQUIRED_CFG_KEYS:
        assert f'"{tool}"' in page, f"{tool} is missing from the builder page"


def test_it_uses_pxdesign_local_not_pxdesign():
    """A config with `pxdesign` enables nothing and the run exits 1."""
    page = PAGE.read_text()
    assert '"pxdesign_local"' in page
    assert '"pxdesign"' not in page.replace('"pxdesign_local"', "")


def test_engine_selection_is_documented_as_a_cfg_key():
    """use_boltz / use_af3 / primary_engine LOOK like tools_enabled entries in
    every wizard-written config, and are read from cfg."""
    page = PAGE.read_text()
    for key in ("use_boltz", "use_af3", "use_esmfold2", "primary_engine"):
        assert key in page


def test_the_page_is_self_contained():
    """No server, no CDN: it has to work from a file:// URL on a machine with no
    network, which is the situation it exists for."""
    page = PAGE.read_text()
    assert "<script" in page
    for remote in ("http://", "https://cdn", 'src="//'):
        assert remote not in page, f"the page references {remote} — it must be self-contained"


def test_the_shipped_example_still_validates_against_the_configurator():
    """The reference output. If the schema moves, this fails here rather than in
    someone's run."""
    sys.path.insert(0, str(REPO / "configurator"))
    import configurator as conf

    cfg = json.loads((REPO / "examples" / "CALCA" / "smoke.json").read_text())
    missing = conf._missing_cfg_keys(cfg["cfg"], cfg["tools_enabled"])
    assert not missing, f"examples/CALCA/smoke.json is missing required keys: {missing}"


def test_generated_default_config_satisfies_required_keys():
    """Round trip: the page's own defaults must produce a config the configurator
    accepts. A form that emits an invalid config is worse than no form."""
    sys.path.insert(0, str(REPO / "configurator"))
    import configurator as conf

    out = subprocess.run(
        [sys.executable, str(GENERATOR), "--emit-default-config"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert out.returncode == 0, out.stderr
    cfg = json.loads(out.stdout)

    missing = conf._missing_cfg_keys(cfg["cfg"], cfg["tools_enabled"])
    assert not missing, f"the page's default config would be rejected: {missing}"
    assert not Path(cfg["cfg"]["run_dir"]).is_absolute(), "run_dir must be relative"


@pytest.mark.parametrize("tool", ["bindcraft", "boltzgen", "mosaic", "rfd3"])
def test_required_keys_for_each_tool_are_present_in_the_default(tool):
    sys.path.insert(0, str(REPO / "configurator"))
    import configurator as conf

    out = subprocess.run(
        [sys.executable, str(GENERATOR), "--emit-default-config"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    cfg = json.loads(out.stdout)["cfg"]
    for key in conf.REQUIRED_CFG_KEYS[tool]:
        # target_pdb is DERIVED by generate() from target_pdb_src, so the
        # configurator counts it present whenever the source structure is given.
        # Mirroring that rule rather than re-stating it is the point.
        if key == "target_pdb" and cfg.get("target_pdb_src"):
            continue
        assert key in cfg, f"{tool} needs {key}, which the default config omits"
