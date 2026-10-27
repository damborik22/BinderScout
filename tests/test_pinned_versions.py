"""The installer's version pins must stay internally consistent.

Three outages in this repo came from a floating dependency under pinned code —
BUG-14 (`pip install pyrosetta` -> 2026.29 changed set_interface), BUG-20
(`uv pip install atomworks` -> 3.0.0 deleted AtomSelectionStack), and the RUF071
CI failure (`pip install ruff` -> 0.17.x added a rule). The fix was to capture
every verified version into install/locks/ and feed those files to pip. These
tests guard the wiring, not the versions: a pin that drifts is a deliberate act,
a pin that silently stops being applied is a bug.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO / "install" / "install.sh"
LOCKS = REPO / "install" / "locks"

INSTALL_TEXT = INSTALL_SH.read_text()


def constraint_files() -> list[Path]:
    return sorted(LOCKS.glob("*.txt"))


def pins(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, _, version = line.partition("==")
        out[name.strip().lower()] = version.strip()
    return out


class TestEveryConstraintsCallHasAFile:
    def test_each_constraints_env_name_resolves_to_a_file(self):
        """A typo'd env name degrades to an unpinned install with only a warning."""
        names = re.findall(r'_constraints "([^"]+)"', INSTALL_TEXT)
        assert names, "no _constraints calls found — did the wiring get removed?"
        for name in names:
            assert (LOCKS / f"{name}.txt").is_file(), f"no install/locks/{name}.txt for {name}"

    def test_the_constraints_array_is_actually_used(self):
        """_constraints() without a single ${CONSTRAINTS[@]} splice pins nothing."""
        assert INSTALL_TEXT.count("${CONSTRAINTS[@]}") >= 8

    def test_mosaic_lock_is_vendored_and_referenced(self):
        """Mosaic/ is gitignored and recloned, so its lock can only live here."""
        assert (LOCKS / "mosaic.uv.lock").is_file()
        assert "LOCKS_DIR}/mosaic.uv.lock" in INSTALL_TEXT
        assert "--locked" in INSTALL_TEXT

    def test_mosaic_lock_pins_the_esm2quinox_alphabet_that_mosaic_reads(self):
        """BUG-24. Mosaic's losses/esm.py does `from esm2quinox._esm2 import _alphabet`
        and then indexes it with "b"/"e"/"m", one-hotting to a hardcoded width of 33.

        esm2quinox 0.1.0 is a 33-entry dict keyed exactly that way. 0.2.0 rewrote it
        as 32 entries keyed by symbol ("^", "$", "#"), so the ESM2 expressibility
        prior dies with KeyError: 'b' inside the jitted loss — on the first
        optimisation step, after the model and MSA have loaded. Mosaic declares only
        `esm2quinox>=0.1.0`, so a fresh install takes 0.2.0 and every Mosaic run
        fails. The first vendored lock pinned 0.2.0: it was captured from an install
        that had never been *run* (see EVIDENCE.md), which is exactly the gap that
        file exists to record.
        """
        lock = (LOCKS / "mosaic.uv.lock").read_text()
        block = re.search(r'name = "esm2quinox"\nversion = "([^"]+)"', lock)
        assert block, "esm2quinox is no longer in the Mosaic lock — did the loss change?"
        assert block.group(1).startswith("0.1."), (
            f"Mosaic lock pins esm2quinox {block.group(1)}; its esm.py needs the "
            "33-entry 0.1.x alphabet keyed 'b'/'e'/'m' (BUG-24)"
        )


class TestConstraintsExcludeTheClassesThatBreakResolution:
    """Both exclusions were found by `pip install --dry-run`, not by reasoning."""

    @pytest.mark.parametrize("path", constraint_files(), ids=lambda p: p.stem)
    def test_no_nvidia_pins(self, path):
        """torch pins these itself, and to DIFFERENT versions per index: the
        cu121-index torch 2.5.1 wants nvidia-cuda-nvrtc-cu12==12.1.105, the PyPI
        torch 2.5.1 wants 12.4.127. Constraining them is ResolutionImpossible."""
        offenders = [k for k in pins(path) if k.startswith("nvidia")]
        assert not offenders, f"{path.name} re-introduced nvidia pins: {offenders}"

    @pytest.mark.parametrize("path", constraint_files(), ids=lambda p: p.stem)
    def test_no_packaging_infrastructure_pins(self, path):
        """--index-url REPLACES PyPI, and download.pytorch.org does not serve
        setuptools — so a constrained setuptools makes torch's own
        `depends on setuptools` unsatisfiable."""
        offenders = [k for k in pins(path) if k in {"setuptools", "wheel", "pip"}]
        assert not offenders, f"{path.name} re-introduced infra pins: {offenders}"

    @pytest.mark.parametrize("path", constraint_files(), ids=lambda p: p.stem)
    def test_only_pyrosetta_keeps_a_cuda_local_version(self, path):
        """`torch==2.5.1` matches the +cu121 wheel (PEP 440); `torch==2.5.1+cu121`
        is unfindable on PyPI. pyrosetta is the exception — there the local
        version is the build identity and find-links serves that exact string."""
        offenders = [k for k, v in pins(path).items() if "+" in v and k != "pyrosetta"]
        assert not offenders, f"{path.name} has local-version pins: {offenders}"


class TestLocksAgreeWithTheInlinePins:
    """Where install.sh names a version AND a constraints file covers that env,
    the two must not contradict each other — pip fails the install if they do."""

    def test_boltzgen_torch_matches_its_lock(self):
        assert "torch==2.14.1" in INSTALL_TEXT
        assert pins(LOCKS / "BoltzGen.txt")["torch"] == "2.14.1"

    def test_bindcraft_pyrosetta_matches_its_lock(self):
        pinned = re.search(r'PYROSETTA_VERSION="([^"]+)"', INSTALL_TEXT)
        assert pinned, "PYROSETTA_VERSION disappeared (BUG-14)"
        assert pins(LOCKS / "BindCraft.txt")["pyrosetta"] == pinned.group(1)

    def test_atomworks_pin_is_below_the_version_that_dropped_the_class(self):
        """atomworks 3.0.0 deleted AtomSelectionStack, which pdb_utils imports."""
        pinned = re.search(r'ATOMWORKS_VERSION="([^"]+)"', INSTALL_TEXT)
        assert pinned, "ATOMWORKS_VERSION disappeared (BUG-20)"
        major = int(pinned.group(1).split(".")[0])
        assert major < 3, f"atomworks {pinned.group(1)} has no AtomSelectionStack"


class TestNoCommitIsLeftAsHEAD:
    def test_every_pinned_commit_is_a_full_sha_or_tag(self):
        """PXDESIGN_COMMIT and PROTEINA_COMPLEXA_COMMIT were both the literal
        string "HEAD", so two installs a week apart got different code."""
        for name, value in re.findall(r'^(\w+_COMMIT)="([^"]*)"', INSTALL_TEXT, re.M):
            assert value != "HEAD", f"{name} is still HEAD"
            is_sha = re.fullmatch(r"[0-9a-f]{40}", value)
            is_tag = value.startswith("v")
            assert is_sha or is_tag, f"{name}={value!r} is neither a full SHA nor a tag"

    def test_the_rolling_download_urls_are_gone(self):
        """mmseqs.com/latest/ served a different binary on every install.

        Checked against code only — the comments above those lines quote the old
        URLs to explain why they went, and must not trip this.
        """
        code = "\n".join(ln for ln in INSTALL_TEXT.splitlines() if not ln.lstrip().startswith("#"))
        assert "mmseqs.com/latest/" not in code
        assert "mmseqs.com/foldseek/foldseek-linux" not in code
        assert "astral.sh/uv/install.sh" not in code
