"""A pinned checkpoint needs a pinned loader, or the pin is only half a contract.

**The 2026-09-27 version of this file asserted the wrong half, and is retracted here.**
It concluded that ESMFold2 support "exists only from transformers 5.x" because PyPI
4.57.6 ships no ``transformers.models.esmfold2`` module, and therefore required the
installers to pin ``transformers>=5.16`` and the checkpoint to be ``69869f737bef``.

That reasoning confused a version STRING with a distribution. The loader this engine
actually runs on is the **biohub fork**, ``github.com/Biohub/transformers`` at commit
``3a8956fb``, which *reports* version 4.57.6 and is the only build whose class is named
``ESMFold2Model`` and carries ``load_esmc`` -- the method the fold calls. Measured
2026-10-05:

* BM2's working env, untouched since it produced the CALCA and CBG pools and the
  563-design benchmark: ``transformers 4.57.6`` whose ``direct_url.json`` records
  ``github.com/Biohub/transformers @ 3a8956fb``, with ``ESMFold2Model.load_esmc``
  present.
* PyPI ``transformers`` 5.16.1, 5.17.0 and 5.18.0: all three expose ``EsmFold2Model``
  with ``__init__(self, config)`` and **no** ``load_esmc``. So
  ``from_pretrained(..., load_esmc=False)`` raises
  ``TypeError: unexpected keyword argument 'load_esmc'`` on every released 5.x.
* Consequence of the retracted pin: installing ``transformers>=5.16`` replaced a working
  loader with one that cannot fold, while the env still verified clean. ESMFold2 is the
  DEFAULT refold engine, so this took it out everywhere the pin was applied.
* With the fork plus ``8fc3ff471022``, the control design ``quick-boar-ruby`` refolds to
  ``iptm 0.8875`` against a stored ``0.8925`` -- i.e. it reproduces the benchmark.

So ``8fc3ff471022`` is not "unloadable": it is the revision every validated result in
this project was produced with, and the one the fork loads. The ``num_distogram_bins``
measurement in the retracted docstring was real but applies only to PyPI 5.x, which this
engine does not run on.

The fork's git URL currently 404s, so a fresh env cannot fetch it and must mirror the
package from a machine that has it. ``refold_esmfold2`` refuses at load time when the
resolved class lacks ``load_esmc``, which is what turns that from a silent half-install
into a named failure.

These checks are static -- they read the pin, the revision and the guard -- because the
alternative needs ~10 GB of weights and a datacentre-class card.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "Evaluator" / "scripts" / "refold_esmfold2.py"
INSTALLERS = (REPO / "install" / "install.sh", REPO / "install" / "install_aarch.sh")

#: The revision the biohub fork loads, and the one behind every validated result here.
_VALIDATED_REVISION = "8fc3ff471022fdce52c77030685eb775de0c00a3"

#: Authored against a transformers pre-release (5.16.0.dev0) whose API no released
#: transformers reproduces. Pinning it is what broke the default engine.
_DEV_ONLY_REVISION = "69869f737beffec5294845ede23db5fc0b4f509e"


def _pinned_revision() -> str:
    text = SCRIPT.read_text()
    match = re.search(
        r'"biohub/ESMFold2":\s*os\.environ\.get\("ESMFOLD2_REVISION"\)\s*or\s*"([0-9a-f]{40})"',
        text,
    )
    assert match, "refold_esmfold2 no longer pins a revision for biohub/ESMFold2"
    return match.group(1)


def test_the_validated_revision_is_the_default():
    assert _pinned_revision() == _VALIDATED_REVISION, (
        "the default ESMFold2 revision must be the one the biohub fork loads and that "
        "produced the benchmark. See this module's docstring for the measurement."
    )


def test_the_dev_only_revision_is_not_pinned():
    assert _pinned_revision() != _DEV_ONLY_REVISION, (
        "69869f737bef was authored against transformers 5.16.0.dev0, whose load_esmc "
        "API no released transformers provides — pinning it disables the default engine."
    )


@pytest.mark.parametrize("installer", INSTALLERS, ids=lambda p: p.name)
def test_no_installer_forces_a_transformers_5x_into_the_esmfold2_env(installer):
    """A 5.x pin installs a class that cannot fold, over a fork that can."""
    for spec in re.findall(r"'transformers([><=!,.0-9]*)'", installer.read_text()):
        for major, _minor in re.findall(r"(\d+)\.(\d+)", spec):
            assert int(major) < 5, (
                f"{installer.name} pins transformers{spec}; PyPI 5.x ships EsmFold2Model "
                "without load_esmc and cannot fold. The loader is the biohub fork."
            )


@pytest.mark.parametrize("installer", INSTALLERS, ids=lambda p: p.name)
def test_installers_do_not_replace_a_present_fork(installer):
    text = installer.read_text()
    assert "load_esmc" in text, (
        f"{installer.name} must detect an existing biohub fork (by ESMFold2Model.load_esmc) "
        "and skip installing transformers over it"
    )


def test_both_installers_agree_on_the_pin():
    """Two implementations pinning different loaders is the same defect wearing a hat."""
    specs = {tuple(re.findall(r"'transformers([><=!,.0-9]*)'", i.read_text())) for i in INSTALLERS}
    assert len(specs) == 1, f"the installers pin different transformers versions: {specs}"


def test_the_loader_accepts_both_class_names():
    """The fork calls it ESMFold2Model, PyPI 5.x calls it EsmFold2Model. Asserting either
    one alone re-breaks the other direction, so the loader tries both."""
    text = SCRIPT.read_text()
    assert "EsmFold2Model" in text and "ESMFold2Model" in text, (
        "refold_esmfold2 must try both transformers class spellings"
    )


def test_the_loader_refuses_a_class_without_load_esmc():
    """A class under the right name is not the right class. Without this guard the
    failure is a bare TypeError hundreds of lines into a run, naming nothing."""
    text = SCRIPT.read_text()
    assert 'hasattr(ESMFold2Model, "load_esmc")' in text, (
        "refold_esmfold2 must refuse when the resolved class has no load_esmc"
    )
