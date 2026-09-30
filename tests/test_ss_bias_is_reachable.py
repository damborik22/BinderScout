"""The geometry bias must actually reach a generated run.

`ss_bias` was a DEAD KNOB from whenever it was added until 2026-09-30: the parameter
existed on `design()`, it gated `sp.HelixLoss()` and `sp.DistogramRadiusOfGyration()`, and
the sole call site never passed it — so both terms were unreachable in every script the
configurator produced, while the template advertised helix/compact shaping.

That is this repo's recurring defect (built-but-unconnected), so these tests check the
whole chain rather than the template in isolation: the call site passes it, the
configurator injects it, and the two terms compose instead of excluding each other.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "binderscout_examples" / "hallucinate_binderscout.py"
CONFIGURATOR = REPO / "configurator" / "configurator.py"


def _load_configurator(name="bs_cfg_ssbias"):
    spec = importlib.util.spec_from_file_location(name, CONFIGURATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_call_site_passes_ss_bias():
    """The exact bug. `design()` has one call site; it must hand the knob over."""
    tree = ast.parse(TEMPLATE.read_text())
    calls = [
        n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "design"
    ]
    assert calls, "no call to design() found — the template has been restructured"
    for c in calls:
        passed = {kw.arg for kw in c.keywords}
        assert "ss_bias" in passed, (
            "design() is called without ss_bias, so it takes the default 'none' and both "
            "HelixLoss and DistogramRadiusOfGyration are unreachable in every generated run"
        )


def test_the_template_defines_the_constant_the_call_site_reads():
    tree = ast.parse(TEMPLATE.read_text())
    names = {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    assert "SS_BIAS" in names, "the call site reads SS_BIAS but the template never defines it"


@pytest.mark.parametrize(
    ("bias", "helix", "compact"),
    [("none", False, False), ("helix", True, False), ("compact", False, True), ("helix+compact", True, True)],
)
def test_the_two_terms_compose_rather_than_exclude(bias, helix, compact, tmp_path):
    """`if/elif` silently made 'helix+compact' mean 'helix'.

    Executed, not read: the branch logic is lifted out of the template's source and run,
    so a refactor back to elif fails here rather than shipping.
    """
    src = TEMPLATE.read_text()
    start = src.index("    _bias = {b.strip()")
    end = src.index("sp.DistogramRadiusOfGyration()", start) + len("sp.DistogramRadiusOfGyration()")
    block = src[start:end]

    added = []

    class _Loss:
        def __add__(self, other):
            return self

    class _SP:
        def HelixLoss(self):
            added.append("helix")
            return 0

        def DistogramRadiusOfGyration(self):
            added.append("compact")
            return 0

    ns = {"ss_bias": bias, "sp_loss": _Loss(), "sp": _SP()}
    exec(compile(ast.parse(block.replace("    ", "", 1).replace("\n    ", "\n")), "<block>", "exec"), ns)

    assert ("helix" in added) is helix, f"{bias}: helix term {'missing' if helix else 'unexpected'}"
    assert ("compact" in added) is compact, f"{bias}: compact term {'missing' if compact else 'unexpected'}"


def test_an_unknown_bias_is_refused_not_silently_ignored():
    """A typo used to cost a whole campaign running with no bias at all."""
    src = TEMPLATE.read_text()
    start = src.index("    _bias = {b.strip()")
    end = src.index("sp.DistogramRadiusOfGyration()", start) + len("sp.DistogramRadiusOfGyration()")
    block = src[start:end].replace("    ", "", 1).replace("\n    ", "\n")

    class _Loss:
        def __add__(self, other):
            return self

    class _SP:
        def HelixLoss(self):
            return 0

        def DistogramRadiusOfGyration(self):
            return 0

    with pytest.raises(ValueError, match="unknown term"):
        exec(compile(ast.parse(block), "<block>", "exec"), {"ss_bias": "compct", "sp_loss": _Loss(), "sp": _SP()})


@pytest.mark.parametrize("bias", ["none", "helix", "compact", "helix+compact"])
def test_the_configurator_injects_it_into_the_generated_script(bias, tmp_path):
    """Wired in the template is not wired in the pipeline."""
    mod = _load_configurator()
    out = tmp_path / "hallucinate.py"
    mod.write_mosaic_hallucinate(
        out,
        {
            "run_dir": tmp_path,
            "target_sequence": "EDEARLLLAALVQDYVQMKASELEQEQEREGS",
            "n_designs": 4,
            "min_length": 28,
            "max_length": 28,
            "mosaic_ss_bias": bias,
            "hotspots": "",
        },
    )
    lines = [ln for ln in out.read_text().splitlines() if ln.startswith("SS_BIAS")]
    assert len(lines) == 1, f"expected exactly one SS_BIAS line, got {lines}"
    assert repr(bias) in lines[0], f"configurator did not inject {bias!r}: {lines[0]}"


def test_the_configurator_refuses_an_invalid_bias(tmp_path):
    mod = _load_configurator("bs_cfg_ssbias_bad")
    with pytest.raises(SystemExit):
        mod.write_mosaic_hallucinate(
            tmp_path / "h.py",
            {
                "run_dir": tmp_path,
                "target_sequence": "EDEARLLLAALVQDYVQMKASELEQEQEREGS",
                "n_designs": 4,
                "min_length": 28,
                "max_length": 28,
                "mosaic_ss_bias": "globular",
                "hotspots": "",
            },
        )
