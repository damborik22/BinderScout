"""The two installers must not drift where they are meant to agree.

`install/install.sh` (x86_64) and `install/install_aarch.sh` (aarch64) are
separate files on purpose — different CUDA stacks, different wheel availability,
different conda channels. But a handful of things in them are *not* architecture
dependent, and every one of those that drifted has cost a run:

* BUG-14 was fixed on x86_64 in July and left unfixed on aarch64 until
  2026-10-28. `_patch_bindcraft_pyrosetta()` migrates the one BindCraft call site
  that PyRosetta 2026.29 broke. It is pure text manipulation of a cloned Python
  file, so it is identical on both arches — but it existed in only one of them,
  and a DGX Spark install produced zero designs after ~8 min of GPU per
  trajectory.
* `PXDESIGN_COMMIT` was pinned on x86_64 and left as the literal `"HEAD"` on
  aarch64, so two Spark installs a week apart got different PXDesign code while
  every other tool was pinned.

These tests assert the shared pieces stay shared. They do not assert that the
two files are similar overall — they are not, and should not be.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
X86 = REPO / "install" / "install.sh"
AARCH = REPO / "install" / "install_aarch.sh"

X86_TEXT = X86.read_text()
AARCH_TEXT = AARCH.read_text()

TEXTS = {"install.sh": X86_TEXT, "install_aarch.sh": AARCH_TEXT}

# Parametrise on the name only — the file bodies are too large to serve as test ids.
INSTALLERS = pytest.mark.parametrize("name", sorted(TEXTS))

# Helpers that must exist, and be byte-identical, in BOTH installers. Each reads only
# paths and conda env names that the two files define identically, so a difference means
# one architecture has been fixed and the other has not. Three fixes landed in
# install.sh alone before this list existed:
#   * run_logged — the streaming rewrite. aarch64 kept the version that buffered into a
#     mktemp file and had no non-TTY branch at all, so on a Spark `tail -f` showed
#     nothing for the whole 45-90 min BindCraft step and a redirected run printed
#     nothing ever. install_aarch.sh is what `bindmaster install` dispatches to there,
#     so the fix was in the one file that platform never runs.
#   * _pin_rfd3_atomworks — rc-foundry floats atomworks on both platforms.
#   * _patch_bindcraft_pyrosetta — the original entry, ported by 764854f.
SHARED_FUNCTIONS = pytest.mark.parametrize("func", ["_patch_bindcraft_pyrosetta", "run_logged", "_pin_rfd3_atomworks"])


def shell_function(text: str, name: str) -> str | None:
    """Return the body of shell function *name*, or None if it is not defined.

    Relies on the repo's own formatting: a function opens at column zero as
    `name() {` and closes with a `}` at column zero.
    """
    match = re.search(rf"^{re.escape(name)}\(\) \{{\n(.*?)^\}}$", text, re.S | re.M)
    return match.group(1) if match else None


def assignment(text: str, var: str) -> str | None:
    match = re.search(rf'^{re.escape(var)}="([^"]*)"', text, re.M)
    return match.group(1) if match else None


class TestPyrosettaCallSitePatch:
    """BUG-14's call-site migration must exist, and be the same, on both arches."""

    @INSTALLERS
    def test_installer_defines_the_patch(self, name):
        text = TEXTS[name]
        assert shell_function(text, "_patch_bindcraft_pyrosetta") is not None, (
            f"{name} does not define _patch_bindcraft_pyrosetta(). BindCraft is pinned "
            f'at a commit that calls iam.set_interface("A_B"), which PyRosetta 2026.29 '
            f"rejects; without the patch every trajectory dies in score_interface() "
            f"and the run yields zero designs (BUG-14)."
        )

    @SHARED_FUNCTIONS
    def test_the_two_copies_are_identical(self, func):
        x86 = shell_function(X86_TEXT, func)
        aarch = shell_function(AARCH_TEXT, func)
        # Not just equality: None == None would pass for a symbol missing from both.
        assert x86 is not None, f"install.sh does not define {func}()"
        assert aarch is not None, f"install_aarch.sh does not define {func}()"
        assert x86 == aarch, (
            f"{func}() differs between install.sh and install_aarch.sh. These helpers "
            f"have no architecture-dependent behaviour, so a difference means one arch "
            f"has been fixed and the other has not — the exact shape of BUG-14."
        )

    @INSTALLERS
    def test_installer_calls_the_patch(self, name):
        text = TEXTS[name]
        body = shell_function(text, "install_bindcraft")
        assert body is not None, f"{name} has no install_bindcraft()"
        assert "_patch_bindcraft_pyrosetta" in body, (
            f"{name} defines _patch_bindcraft_pyrosetta() but install_bindcraft() "
            f"never calls it. A patch that is never applied is not a fix."
        )

    @INSTALLERS
    def test_the_patch_keeps_the_pre_2026_29_fallback(self, name):
        text = TEXTS[name]
        body = shell_function(text, "_patch_bindcraft_pyrosetta")
        assert body is not None, f"{name} does not define _patch_bindcraft_pyrosetta()"
        assert "except ImportError" in body, (
            f"{name}'s patch dropped the ImportError fallback. The emitted code must "
            f"work against both sides of the 2026.29 boundary: aarch64 takes PyRosetta "
            f"unpinned from the graylab conda channel, so the version is not known in "
            f"advance."
        )

    @INSTALLERS
    def test_the_patch_verifies_its_own_result(self, name):
        text = TEXTS[name]
        body = shell_function(text, "_patch_bindcraft_pyrosetta")
        assert body is not None, f"{name} does not define _patch_bindcraft_pyrosetta()"
        after_heredoc = body.split("PYEOF")[-1]
        assert "DockingPartners" in after_heredoc and "print_fail" in after_heredoc, (
            f"{name}'s patch does not re-check the file after editing it. The heredoc's "
            f"exit status does not prove the replacement matched, and a silent miss "
            f"costs GPU-hours before it shows up."
        )


class TestSharedPins:
    """Tool revisions that are not architecture dependent must agree."""

    @pytest.mark.parametrize("var", ["PXDESIGN_COMMIT", "BOLTZGEN_COMMIT", "MOSAIC_COMMIT"])
    @INSTALLERS
    def test_no_installer_floats_a_tool_on_head(self, var, name):
        text = TEXTS[name]
        value = assignment(text, var)
        assert value is not None, f"{name} does not set {var}"
        assert value.upper() != "HEAD", (
            f'{name} sets {var}="HEAD", so two installs on different days get '
            f"different code while every other tool here is pinned."
        )

    def test_pxdesign_commit_matches_across_installers(self):
        x86 = assignment(X86_TEXT, "PXDESIGN_COMMIT")
        aarch = assignment(AARCH_TEXT, "PXDESIGN_COMMIT")
        assert x86 == aarch, (
            f"PXDESIGN_COMMIT differs: install.sh={x86!r}, install_aarch.sh={aarch!r}. "
            f"PXDesign's Python is architecture-independent — only its torch build "
            f"differs per arch — so the two installers should track one revision."
        )

    def test_bindcraft_commit_agrees_as_far_as_it_is_written(self):
        """aarch64 abbreviates the SHA; the short form must prefix the long one."""
        x86 = assignment(X86_TEXT, "BINDCRAFT_COMMIT")
        aarch = assignment(AARCH_TEXT, "BINDCRAFT_COMMIT")
        shorter, longer = sorted([x86, aarch], key=len)
        assert longer.startswith(shorter), (
            f"BINDCRAFT_COMMIT disagrees: install.sh={x86!r}, "
            f"install_aarch.sh={aarch!r}. The pyrosetta call-site patch is written "
            f"against the call site as it exists at this commit."
        )


class TestRfd3AtomworksPinIsOnBothArches:
    """rc-foundry installs atomworks UNPINNED, on both platforms.

    atomworks 3.0.0 moved `extra_fields` / `build_assembly` off parse_atom_array()
    into a PrepareConfig object and rejects leftover kwargs, while rfd3's pinned
    input_parsing.py still passes them. `import atomworks` and a version check both
    pass, so the failure arrives in the dataloader after a GPU is committed.
    """

    @INSTALLERS
    def test_the_pin_constant_is_set(self, name):
        version = assignment(TEXTS[name], "ATOMWORKS_VERSION")
        assert version, f"{name} does not pin ATOMWORKS_VERSION"
        assert int(version.split(".")[0]) < 3, f"{name} pins atomworks {version}; 3.x drops the two kwargs rfd3 passes"

    @INSTALLERS
    def test_install_rfd3_calls_the_pin(self, name):
        """The helper is not the fix; the call is.

        A test that exercises _pin_rfd3_atomworks directly stays green when the call
        is deleted from install_rfd3, which is the whole bug.
        """
        body = shell_function(TEXTS[name], "install_rfd3")
        assert body is not None, f"{name} has no install_rfd3()"
        assert "_pin_rfd3_atomworks" in body, (
            f"{name} defines _pin_rfd3_atomworks() but install_rfd3() never calls it, "
            f"so the env is built with whatever atomworks rc-foundry resolved."
        )

    @INSTALLERS
    def test_the_pin_asserts_the_signature_not_the_version(self, name):
        body = shell_function(TEXTS[name], "_pin_rfd3_atomworks")
        assert body is not None, f"{name} has no _pin_rfd3_atomworks()"
        assert "inspect.signature(parse_atom_array)" in body, (
            f"{name}'s pin does not inspect the signature; a version string alone "
            f"passes on any release that moves the kwargs again"
        )
        for kwarg in ("extra_fields", "build_assembly"):
            assert kwarg in body, f"{name} does not assert {kwarg} is still accepted"


class TestToolchainIsCheckedBeforeTheLongSteps:
    """BUG-08: `--tool all` reached the last step before reporting a one-second fact.

    SoluProt source-builds USEARCH v12 on both platforms (and scikit-learn 0.20.4 on
    aarch64, which has no wheel for it), so a box without a compiler cannot finish —
    but it found out ~57 min in. The check belongs in preflight.
    """

    @INSTALLERS
    def test_preflight_checks_for_a_compiler(self, name):
        body = shell_function(TEXTS[name], "preflight")
        assert body is not None, f"{name} has no preflight()"
        assert "DO_SOLUPROT" in body, (
            f"{name}'s preflight does not consider SoluProt, the tool that needs the toolchain"
        )
        for tool in ("git", "make", "g++"):
            assert tool in body, f"{name}'s preflight does not look for {tool}"

    def test_the_remedy_names_the_package_that_exists_for_the_platform(self):
        """conda-forge names its compiler metapackages per platform.

        gxx_linux-64 does not exist for linux-aarch64, so the copy-pasteable command
        in the aarch64 installer has to name gxx_linux-aarch64. A remedy that cannot
        resolve is worse than no remedy, and this is the no-root path.
        """
        x86 = shell_function(X86_TEXT, "preflight")
        aarch = shell_function(AARCH_TEXT, "preflight")
        assert "gxx_linux-64" in x86, "install.sh's remedy lost its conda-forge package"
        assert "gxx_linux-aarch64" in aarch, (
            "install_aarch.sh's toolchain remedy must name gxx_linux-aarch64; "
            "gxx_linux-64 has no linux-aarch64 build and the command would not resolve"
        )
        assert "gxx_linux-64 " not in aarch.replace("gxx_linux-aarch64", ""), (
            "install_aarch.sh still mentions the x86 package name"
        )
