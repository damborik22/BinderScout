"""A pinned checkpoint needs a pinned loader, or the pin is only half a contract.

BinderScout 1.0.2 pinned the ESMFold2 model revision for reproducibility but left
`transformers` at `>=4.50` with no upper bound. The two halves then drifted apart via a
renamed config key, and by 2026-09-27 the pinned snapshot could not be loaded by any
installable transformers -- which broke the DEFAULT refold engine on every fresh install,
not just one machine.

Measured from the two checkpoint configs on that date:

    8fc3ff471022  transformers_version 4.57.6      structure_head.distogram_bins = 64
    69869f737bef  transformers_version 5.16.0.dev0 structure_head carries BOTH
                                                   num_distogram_bins = 64 and
                                                   distogram_bins = 64

transformers 5.x reads `num_distogram_bins`. The old config has only the old key, so the
head is built from the class default of 128 over 64-bin weights:
`distogram_head.weight: ckpt torch.Size([64, 256]) vs model torch.Size([128, 256])`.

And the old floor described nothing real: **4.57.6 has no `transformers.models.esmfold2`
module at all**, so `>=4.50` could never have been satisfied by a 4.x release.

These checks are static -- they read the pin and the revision -- because the alternative
needs ~10 GB of weights and a datacentre-class card.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "Evaluator" / "scripts" / "refold_esmfold2.py"
INSTALLERS = (REPO / "install" / "install.sh", REPO / "install" / "install_aarch.sh")

#: The snapshot whose config predates the key rename. It cannot be loaded by any
#: transformers that ships esmfold2, so it must never come back as the default.
_UNLOADABLE_REVISION = "8fc3ff471022fdce52c77030685eb775de0c00a3"

#: ESMFold2 support exists only from transformers 5.x, and the pinned snapshot's config
#: reports 5.16.0.dev0.
_MIN_TRANSFORMERS = (5, 16)


def test_the_unloadable_revision_is_not_pinned():
    text = SCRIPT.read_text()
    match = re.search(r'"biohub/ESMFold2":\s*os\.environ\.get\("ESMFOLD2_REVISION"\)\s*or\s*"([0-9a-f]{40})"', text)
    assert match, "refold_esmfold2 no longer pins a revision for biohub/ESMFold2"
    assert match.group(1) != _UNLOADABLE_REVISION, (
        "the pinned ESMFold2 revision is the one whose config predates the "
        "num_distogram_bins rename — it cannot be loaded by any transformers that "
        "ships esmfold2. See this test's docstring for the measurement."
    )


@pytest.mark.parametrize("installer", INSTALLERS, ids=lambda p: p.name)
def test_transformers_is_pinned_high_enough_to_have_esmfold2(installer):
    text = installer.read_text()
    found = re.findall(r"'transformers([><=!,.0-9]*)'", text)
    assert found, f"{installer.name} no longer installs transformers into the ESMFold2 env"
    for spec in found:
        floor = re.search(r">=\s*(\d+)\.(\d+)", spec)
        assert floor, f"{installer.name}: transformers spec {spec!r} has no >= floor"
        version = (int(floor.group(1)), int(floor.group(2)))
        assert version >= _MIN_TRANSFORMERS, (
            f"{installer.name} pins transformers{spec}, but ESMFold2 support starts at 5.x "
            f"(4.57.6 has no transformers.models.esmfold2 module at all) and the pinned "
            f"checkpoint's config reports {_MIN_TRANSFORMERS[0]}.{_MIN_TRANSFORMERS[1]}."
        )


@pytest.mark.parametrize("installer", INSTALLERS, ids=lambda p: p.name)
def test_both_installers_agree_on_the_pin(installer):
    """The two installers are separate implementations, and a loader pin that matches a
    checkpoint on one platform but not the other is the same defect wearing a hat."""
    specs = {re.findall(r"'transformers([><=!,.0-9]*)'", i.read_text())[0] for i in INSTALLERS}
    assert len(specs) == 1, f"the installers pin different transformers versions: {specs}"


def test_the_loader_accepts_both_class_names():
    """transformers renamed the class ESMFold2Model -> EsmFold2Model in 5.x. Asserting
    either one alone re-breaks the other direction."""
    text = SCRIPT.read_text()
    assert "EsmFold2Model" in text and "ESMFold2Model" in text, (
        "refold_esmfold2 must try both transformers class spellings"
    )
