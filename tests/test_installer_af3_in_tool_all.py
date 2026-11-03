"""`--tool all` installs every refold engine the default 3-engine gate needs, AF3 included.

The report's cross-engine gate defaults to three engines. `--tool all` used to hold AF3 back
"because its weights are gated", which gave a default install two engines, so every design
failed the gate and was ranked last. Holding it back bought nothing: install_af3 only builds
the env (a public clone, a source build, the public CCD data) and then PRINTS where to request
the weights -- it neither downloads nor needs them to succeed. evaluate.sh now resolves the
weights up front and drops AF3 by name when they are absent, so a default install degrades to
a clearly reported two-engine run until the operator places them.

The safety precondition for having AF3 in `all` is that the installer still never fetches the
gated weights; that is pinned here beside the membership itself.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLERS = [ROOT / "install" / "install.sh", ROOT / "install" / "install_aarch.sh"]


def _all_arm(src: str) -> str:
    """The `--tool all` arm of the argument parser, up to the next tool's arm."""
    m = re.search(r"^ {16}all\)\n(.*?)^ {16}bindcraft\)", src, re.S | re.M)
    assert m, "the `all)` arm of the --tool parser was not found"
    return m.group(1)


def _function(src: str, name: str) -> str:
    m = re.search(rf"^{re.escape(name)}\(\) \{{\n(.*?)^\}}", src, re.S | re.M)
    assert m, f"{name}() not found"
    return m.group(1)


@pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
def test_tool_all_includes_af3(path):
    arm = _all_arm(path.read_text())
    code = "\n".join(line.split("#", 1)[0] for line in arm.splitlines())
    assert re.search(r"\bDO_AF3=true\b", code), (
        f"{path.name}: `--tool all` leaves AF3 out, so a default install has two refold engines "
        "against the report's default three-engine gate and ranks every design last"
    )


@pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
def test_af3_is_on_in_the_interactive_menu(path):
    block = re.search(r"TOOL_REGISTRY=\((.*?)\n\)", path.read_text(), re.S)
    assert block
    row = next(line for line in block.group(1).splitlines() if '"DO_AF3|' in line)
    assert row.strip().strip('"').split("|")[3] == "true", f"{path.name}: the menu leaves AF3 unticked by default"


@pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
def test_install_af3_never_fetches_the_gated_weights(path):
    """The precondition that makes AF3-in-`all` safe: build the env, print how to get weights."""
    body = _function(path.read_text(), "install_af3")
    code = "\n".join(line.split("#", 1)[0] for line in body.splitlines())
    for verb in (r"\bcurl\b", r"\bwget\b", r"huggingface", r"\bgsutil\b", r"\bgdown\b", r"hf_hub_download"):
        assert not re.search(verb, code), f"{path.name}: install_af3 fetches something ({verb}); weights are gated"
    # it tells the operator where the weights go, and that they are not bundled
    assert "NOT bundled" in body
    assert "AF3_MODEL_DIR" in body
    assert "~/.alphafold3/models" in body


@pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
def test_a_missing_toolchain_is_reported_for_af3_in_all(path):
    """AF3 is a jax + C++ source build, so with it in `all` the preflight must cover it."""
    src = path.read_text()
    block = re.search(r"TOOLCHAIN_TOOLS=\((.*?)\n\)", src, re.S)
    assert block and "DO_AF3|" in block.group(1)


@pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
def test_the_header_does_not_still_call_af3_opt_in(path):
    head = re.sub(r"\s*#?\s+", " ", "\n".join(path.read_text().splitlines()[:12]))
    assert not re.search(r"AF3[^.]*\bopt-in", head), head
    assert not re.search(r"ESMFold2[^.]*\bopt-in", head), head
