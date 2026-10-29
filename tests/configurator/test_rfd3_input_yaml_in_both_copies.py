"""Both copies of the RFD3 run script must hand rfd3 `infer_ori_strategy: hotspots`.

Two files write the YAML that `rfd3 design` reads, and nothing keeps them in step: the
configurator's `write_run_rfd3`, and `bindmaster_examples/run_rfd3.sh.template`, which
CLAUDE.md names as the pattern to copy and which the writer only "mirrors" ("Two copies, no
mechanism keeping them in step -- so check both when changing either").

The key between them is load-bearing, and its absence fails SILENTLY. Without
`infer_ori_strategy: hotspots` rfd3 centres the coordinate frame on the whole fixed motif's
centre of mass and seeds every diffused binder atom there, so the binder nucleates inside the
target and grows as an extended coil. No error, no warning, `n_chainbreaks` stays 0, every
downstream guard passes. Measured on CBG/2VDY, with the key vs without: |fixed_com| 23.05 A
vs 0.008 A, binder Rg 10.9 A vs 23.1 A, DSSP helix 0.85 vs 0.27, binder pLDDT after refold
0.84-0.89 vs 0.38-0.44. That cost 304 backbones, and the ApoE4 (6NCO) campaign, whose RFD3 run
omitted the key too, has already shipped a gene order.

It got in through the template alone (8597b28: "The configurator already emitted the key
correctly; only the template lacked it, so a hand-written script copied from the template
inherited the omission"). That is also where the tests are blind.
`TestRfd3RefusesWithoutHotspots` pins the writer; its one template test,
`test_template_does_not_promise_a_com_fallback`, asserts that two phrases are ABSENT, which a
template with the key deleted satisfies. Delete the line from the template and the suite
stays green.

So these tests run the code instead of reading it. The YAML heredoc is lifted out of each
copy (the writer's real output; the template filled in as its header says to), executed in
bash the way the script executes it, and the file it writes is parsed with PyYAML: that file
is what rfd3 reads. Searching the text would not do. The template's own header comment spells
out `infer_ori_strategy: hotspots` in prose, so a substring test still passes with the real
key gone; the last test here pins that trap shut.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))
import configurator as conf

TEMPLATE = Path(__file__).resolve().parents[2] / "bindmaster_examples" / "run_rfd3.sh.template"

# The two writers of the YAML. Named in test ids and in every failure message, so a red
# test says which copy drifted.
COPIES = ("writer", "template")

# What the user configures, and what rfd3 must then be told: the chain-prefixed residues
# the strategy aims the binder at.
CONFIGURED_HOTSPOTS = "10,20,30"
RFD3_HOTSPOTS = "A10,A20,A30"

SEE = 'CLAUDE.md, "RFD3 / foundry runtime gotchas"'

# `cat > "$INPUTS_YAML" <<EOF`, whatever the variable and the tag are called.
SPEC_HEREDOC = re.compile(r'^cat > "\$\{?(?P<var>\w*YAML\w*)\}?" <<(?P<tag>\w+)$')


@pytest.fixture
def target_pdb(tmp_path):
    """A 40-residue, 1-based, CA-only chain A: long enough to hold the hotspots."""
    pdb = tmp_path / "target.pdb"
    pdb.write_text(
        "".join(
            f"ATOM  {i:5d}  CA  ALA A{i:4d}    {3.8 * i:8.3f}   0.000   0.000  1.00  0.00           C\n"
            for i in range(1, 41)
        )
    )
    return pdb


@pytest.fixture
def cfg(tmp_path, target_pdb):
    run_dir = tmp_path / "runs" / "test"
    run_dir.mkdir(parents=True)
    return {
        "name": "test_target",
        "run_dir": run_dir,
        "target_pdb": target_pdb,
        "target_pdb_src": str(target_pdb),
        "target_sequence": "A" * 40,
        "chains": "A",
        "hotspots": CONFIGURED_HOTSPOTS,
        "min_length": 65,
        "max_length": 150,
        "n_designs": 10,
    }


def _fill_template(text):
    """Fill the placeholders the way the template's header tells a person to.

    A placeholder added later that this does not know about gets a neutral "1": these tests
    care about two facts in the YAML, not about every knob.
    """
    fills = {
        "TARGET_PDB": "/data/target.pdb",
        "TARGET_SEQ": "A" * 40,
        "TARGET_CONTIG": "A1-40",
        "BINDER_LO": "60",
        "BINDER_HI": "140",
        "N_BATCHES": "88",
        "DIFF_BATCH_SIZE": "8",
        "MPNN_SAMPLES": "5",
        "MPNN_TEMPERATURE": "0.1",
        "SELECT_HOTSPOTS_LINE": f'  select_hotspots: "{RFD3_HOTSPOTS}"',
    }
    return re.sub(r"\{\{(\w+)\}\}", lambda m: fills.get(m.group(1), "1"), text)


def _script_text(which_copy, cfg, tmp_path):
    """One copy of the run script, as a user would end up holding it."""
    if which_copy == "writer":
        script = tmp_path / "run_rfd3.sh"
        conf.write_run_rfd3(script, cfg)
        return script.read_text()
    if not TEMPLATE.is_file():
        # Not a skip: a skip is how a deleted template would go unnoticed. CLAUDE.md still
        # tells people to copy this file, so either it comes back or those pointers go too.
        pytest.fail(f"{TEMPLATE} is missing, but CLAUDE.md names it as the pattern to copy for RFD3 run scripts.")
    return _fill_template(TEMPLATE.read_text())


def _spec_rfd3_would_read(script_text, label, workdir, target_pdb):
    """Run the script's own YAML heredoc in bash, and parse the file it writes."""
    lines = script_text.splitlines()
    opens = [i for i, line in enumerate(lines) if SPEC_HEREDOC.match(line)]
    assert len(opens) == 1, (
        f'{label}: expected exactly one `cat > "$INPUTS_YAML" <<TAG` heredoc writing the input YAML '
        f"that rfd3 reads, found {len(opens)}. If the script now writes that YAML another way, teach "
        "this helper the new way rather than dropping the check: `infer_ori_strategy` lives in that file."
    )
    start = opens[0]
    opener = SPEC_HEREDOC.match(lines[start])
    end = next((j for j in range(start + 1, len(lines)) if lines[j] == opener["tag"]), None)
    assert end is not None, f"{label}: the YAML heredoc opened with <<{opener['tag']} is never closed"

    spec_path = workdir / f"{label}_binder_spec.yaml"
    runner = workdir / f"{label}_spec_block.sh"
    # Under the same `set -euo pipefail` the real script runs with, so an unset variable in
    # the heredoc fails here as it would there.
    runner.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f'TARGET_PDB="{target_pdb}"',
                f'{opener["var"]}="{spec_path}"',
                *lines[start : end + 1],
            ]
        )
        + "\n"
    )
    proc = subprocess.run(
        ["bash", str(runner)], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "HOME": str(workdir)}
    )
    assert proc.returncode == 0, f"{label}: the YAML heredoc failed under `set -euo pipefail`:\n{proc.stderr}"
    text = spec_path.read_text()
    # Imported here, not at the top: CI pins pyyaml==6.0.3, but the configurator imports only the
    # stdlib and install/locks/binder-eval.txt pins no PyYAML, so in such an environment a
    # module-level import would abort collection of the whole suite. Failing, not skipping: a
    # skip is how CI would go blind if the pin went.
    try:
        import yaml
    except ImportError:
        pytest.fail("PyYAML is required to read the YAML rfd3 reads (CI installs pyyaml==6.0.3); install it.")
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        pytest.fail(f"{label}: the input YAML rfd3 would read does not parse ({exc}):\n{text}")


def _design_entries(spec, label):
    """rfd3 reads `{design_name: {option: value, ...}}`; return that mapping.

    The strategy is an option of each design, so every entry is held to it. A key that slips
    to column 0 parses as a top-level scalar, not as an option of the design, and is refused
    here rather than waved through.
    """
    ok = isinstance(spec, dict) and spec and all(isinstance(entry, dict) for entry in spec.values())
    assert ok, f"{label}: expected design entries mapping option names to values, got {spec!r}"
    return spec


def _entries_rfd3_would_read(which_copy, cfg, target_pdb, tmp_path):
    spec = _spec_rfd3_would_read(_script_text(which_copy, cfg, tmp_path), which_copy, tmp_path, target_pdb)
    return _design_entries(spec, which_copy)


class TestRfd3InputYamlInBothCopies:
    """Each test holds the configurator's writer and the hand-copied template to the same
    expectation, so neither copy can drift alone."""

    @pytest.mark.parametrize("which_copy", COPIES)
    def test_each_copy_writes_a_yaml_that_centres_the_binder_on_the_hotspots(
        self, which_copy, cfg, target_pdb, tmp_path
    ):
        """The shipped bug: a copy whose YAML has no `infer_ori_strategy`, or has `com`."""
        for name, entry in _entries_rfd3_would_read(which_copy, cfg, target_pdb, tmp_path).items():
            assert entry.get("infer_ori_strategy") == "hotspots", (
                f"{which_copy}: design {name!r} in the YAML rfd3 would read sets infer_ori_strategy to "
                f"{entry.get('infer_ori_strategy')!r} (entry: {entry}). Without `infer_ori_strategy: hotspots` "
                "rfd3 centres the binder on the whole target's centre of mass and silently grows extended "
                f"coils that pass every downstream guard. See {SEE}: infer_ori_strategy is LOAD-BEARING."
            )

    @pytest.mark.parametrize("which_copy", COPIES)
    def test_each_copy_writes_a_yaml_that_names_the_hotspots_to_aim_at(self, which_copy, cfg, target_pdb, tmp_path):
        """`hotspots` is only as good as the residues beside it: none aborts rfd3's dataloader
        (BUG-27), and the wrong ones aim the binder at the wrong epitope with nothing to say so."""
        for name, entry in _entries_rfd3_would_read(which_copy, cfg, target_pdb, tmp_path).items():
            assert entry.get("select_hotspots") == RFD3_HOTSPOTS, (
                f"{which_copy}: design {name!r} in the YAML rfd3 would read has select_hotspots "
                f"{entry.get('select_hotspots')!r}, expected {RFD3_HOTSPOTS!r} (entry: {entry}). "
                f"`infer_ori_strategy: hotspots` aims the binder at exactly these residues. See {SEE}."
            )

    def test_a_comment_that_spells_out_the_key_is_not_mistaken_for_the_key(self, target_pdb, tmp_path):
        """The control for the two tests above, and the reason they run the heredoc.

        The template's header comment says `infer_ori_strategy: hotspots` in prose, so a text
        search passes with the real key deleted. The YAML that rfd3 reads has no such key, and
        these helpers must say so.
        """
        script = "\n".join(
            [
                "# infer_ori_strategy: hotspots needs hotspots to aim at",
                'INPUTS_YAML="$RUN_DIR/binder_spec.yaml"',
                'cat > "$INPUTS_YAML" <<EOF',
                "helix_binder:",
                "  input: ${TARGET_PDB}",
                "  # infer_ori_strategy: hotspots",
                f'  select_hotspots: "{RFD3_HOTSPOTS}"',
                "EOF",
            ]
        )
        assert "infer_ori_strategy: hotspots" in script, "the control must contain the text a search would find"
        entries = _design_entries(_spec_rfd3_would_read(script, "control", tmp_path, target_pdb), "control")
        assert all("infer_ori_strategy" not in entry for entry in entries.values()), (
            f"a comment was read as the key: {entries}"
        )
