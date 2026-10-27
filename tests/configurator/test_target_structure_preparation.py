"""The target structure must be PREPARED, and the tag trim must be evidence-driven.

Two bugs, one subject, and they cannot be fixed apart (BUG-09 + BUG-16).

BUG-16: the target was copied into `runs/<name>/target/` verbatim, so on stock RCSB
5O45 every tool that reads the coordinates saw chain B — an 8-residue inhibitor peptide
bound in the exact epitope a binder has to reach — plus chain A's His6 tag. Nothing
warned.

BUG-09: the sequence trim. A regex over the sequence is the wrong mechanism, not merely
a mis-tuned one: `[GSAL]{0,3}H{5,10}$` stops at the 'E' of 5O45's AAALE linker and
trims 6 of 11 construct residues, and widening it to `[A-Z]{0,5}H{6,10}$` eats five
residues of NATIVE protein off a plain His6 tag. The depositor already named the
construct residues one by one (SEQADV / _struct_ref_seq_dif), so that is the primary
evidence and the pattern is only a fallback for files carrying no annotation.

Why one change: run_rfd3.sh recovers each binder as `best_full[len(target_sequence):]`.
Trimming the sequence while leaving the coordinates alone therefore glues the leftover
tag onto every delivered binder, with no error at any step.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))
import configurator as conf


def _atom(serial, name, res, chain, resnum, record="ATOM  "):
    """One fixed-format PDB atom record: altLoc blank at 17, resName 18-20, chain 22."""
    return (
        f"{record}{serial:5d}  {name:<3s}{res:>4s} {chain}{resnum:4d}    "
        f"{1.0:8.3f}{2.0:8.3f}{3.0:8.3f}{1.00:6.2f}{0.00:6.2f}          {name.strip()[0]:>2s}  "
    )


def _two_chain_pdb() -> str:
    """Chain A = GAH (H is the "tag"), chain B = a bound ligand peptide, plus a water,
    a heteroatom, SEQRES and a CONECT pointing at an atom that preparation removes."""
    lines = [
        "HEADER    TEST",
        "COMPND    2 CHAINS",
        "SEQRES   1 A    3  GLY ALA HIS",
        "SEQRES   1 B    1  TRP",
        "SSBOND   1 CYS A    1    CYS B    1",
        _atom(1, "N", "GLY", "A", 1),
        _atom(2, "CA", "GLY", "A", 1),
        _atom(3, "CA", "ALA", "A", 2),
        _atom(4, "CA", "HIS", "A", 3),
        _atom(5, "CA", "TRP", "B", 1),
        _atom(6, "O", "HOH", "A", 101, record="HETATM"),
        _atom(7, "C1", "9KK", "B", 201, record="HETATM"),
        "CONECT    7    5",
        "ANISOU    1  N   GLY A   1     1      1      1",
        "END",
    ]
    return "\n".join(lines) + "\n"


class TestTargetStructureIsPrepared:
    """A stock RCSB file is not a target."""

    def _prepared(self, tmp_path, chains="A", seq="GA"):
        src = tmp_path / "t_original.pdb"
        src.write_text(_two_chain_pdb())
        dest = tmp_path / "t.pdb"
        report = conf.prepare_target_pdb(src, dest, chains, seq)
        return report, dest, dest.read_text()

    def test_unselected_chains_are_dropped(self, tmp_path):
        report, dest, _ = self._prepared(tmp_path)
        assert report["dropped_chains"] == {"B": 1}
        assert conf.extract_sequence_from_pdb(str(dest), "B") is None

    def test_the_structure_matches_the_trimmed_sequence_exactly(self, tmp_path):
        """The one invariant that matters: a tool reading the coordinates and a tool
        reading cfg["target_sequence"] must see the same protein."""
        report, dest, _ = self._prepared(tmp_path, seq="GA")
        assert report["trimmed"] == 1
        assert conf.extract_sequence_from_pdb(str(dest), "A") == "GA"

    def test_waters_and_ligands_are_dropped(self, tmp_path):
        report, _dest, text = self._prepared(tmp_path)
        assert report["waters"] == 1
        assert report["ligands"] == {"9KK": 1}
        assert "HETATM" not in text

    def test_header_records_naming_removed_atoms_are_gone(self, tmp_path):
        """A SEQRES declaring more residues than survive killed BoltzGen with
        `IndexError: list index out of range` at pdb_parser.py:39 (entity.subchains[0]),
        and LINK/CONECT pointed at deleted atoms. SEQRES is dropped, not regenerated, so
        the sequence can only come from the ATOM records."""
        _report, _dest, text = self._prepared(tmp_path)
        records = {line[:6].strip() for line in text.splitlines()}
        for record in ("SEQRES", "CONECT", "SSBOND", "ANISOU", "COMPND"):
            assert record not in records, f"{record} survived preparation"
        assert text.startswith("HEADER")
        assert "REMARK 999 PREPARED BY BINDERSCOUT CONFIGURATOR" in text

    def test_it_is_a_well_formed_pdb(self, tmp_path):
        _report, _dest, text = self._prepared(tmp_path)
        lines = text.splitlines()
        assert lines[-1] == "END"
        assert lines[-2].startswith("TER   ")
        serials = [int(line[6:11]) for line in lines if line[:4] == "ATOM"]
        assert serials == list(range(1, len(serials) + 1)), "serials must be renumbered"

    def test_residue_numbering_is_preserved_so_hotspots_still_resolve(self, tmp_path):
        """Hotspots are the deposited residue numbers the user typed in Step 3."""
        _report, dest, _text = self._prepared(tmp_path)
        assert conf.pdb_chain_residue_numbers(str(dest), "A") == [1, 2]

    def test_a_sequence_that_is_not_in_the_structure_is_reported_not_guessed(self, tmp_path):
        report, dest, _text = self._prepared(tmp_path, seq="WWWWW")
        assert report["trim_failed"] == "A"
        assert conf.extract_sequence_from_pdb(str(dest), "A") == "GAH"

    def test_nothing_is_written_when_nothing_would_survive(self, tmp_path):
        """generate() then falls back to copying the source verbatim rather than
        handing the tools an empty structure."""
        src = tmp_path / "x_original.pdb"
        src.write_text("ATOM\n")
        dest = tmp_path / "x.pdb"
        assert conf.prepare_target_pdb(src, dest, "A", "") is None
        assert not dest.exists()

    def test_generate_keeps_the_untouched_source_alongside(self, tmp_path):
        run_dir = tmp_path / "runs" / "t"
        run_dir.mkdir(parents=True)
        src = tmp_path / "deposited.pdb"
        src.write_text(_two_chain_pdb())
        cfg = {
            "name": "t",
            "run_dir": run_dir,
            "target_pdb_src": str(src),
            "target_sequence": "GA",
            "chains": "A",
            "hotspots": None,
        }
        conf.generate(cfg, {})
        assert (run_dir / "target" / "t_original.pdb").read_text() == _two_chain_pdb()
        assert cfg["target_pdb"] == run_dir / "target" / "t.pdb"
        assert conf.extract_sequence_from_pdb(str(cfg["target_pdb"]), "A") == "GA"

    def test_a_cif_target_is_prepared_too(self, tmp_path):
        """BUG-19's column shift made this path silently fall through to a verbatim
        copy: prepare_target_pdb reads the CONVERTED pdb, which extract_sequence_from_pdb
        could not parse, so it found no residues and returned None."""
        run_dir = tmp_path / "runs" / "c"
        run_dir.mkdir(parents=True)
        src = tmp_path / "deposited.cif"
        src.write_text(_tagged_cif())
        cfg = {
            "name": "c",
            "run_dir": run_dir,
            "target_pdb_src": str(src),
            "target_sequence": _5O45_NATIVE,
            "chains": "A",
            "hotspots": None,
        }
        conf.generate(cfg, {})
        prepared = run_dir / "target" / "c.pdb"
        assert conf.extract_sequence_from_pdb(str(prepared), "A") == _5O45_NATIVE
        assert "PREPARED BY BINDERSCOUT CONFIGURATOR" in prepared.read_text()
        assert (run_dir / "target" / "c_original.pdb").is_file()
        assert (run_dir / "target" / "c.cif").read_text() == _tagged_cif()


# ─── Expression-tag detection ─────────────────────────────────────────────────

# 5O45 (PD-L1)'s real C-terminus, which is the whole of BUG-09's miss. The depositor
# flags ELEVEN residues (135-145 = AAALE + His6) as EXPRESSION TAG; a
# `[GSAL]{0,3}H{5,10}$` pattern stops at the 'E' of AAALE because E is not in [GSAL],
# so it trims 6 of 11 and five construct residues survive as designable surface and go
# into the shared target-MSA cache key.
_5O45_TAIL = "ITVKVNAPY" + "AAALE" + "HHHHHH"
_5O45_NATIVE = "ITVKVNAPY"
_5O45_FIRST = 126  # so the tag lands on 135-145, exactly as deposited

_ONE_TO_THREE: dict = {}
for _three, _one in conf.AA3TO1.items():
    _ONE_TO_THREE.setdefault(_one, _three)


def _seqadv(resname, chain, resnum, note="EXPRESSION TAG"):
    """One fixed-format SEQADV record: resName 13-15, chainID 17, seqNum 19-22,
    conflict 50-70 (1-based), matching the PDB format spec."""
    head = f"SEQADV TEST {resname:>3s} {chain} {resnum:4d} "
    return f"{head:<49s}{note:<21s}"


def _tagged_pdb(note="EXPRESSION TAG", tail=_5O45_TAIL, first=_5O45_FIRST, flag_from=135, flag_to=145):
    """5O45's shape: chain A's C-terminus plus its SEQADV records, and a chain B peptide."""
    head = ["HEADER    TEST"]
    atoms = []
    for i, one in enumerate(tail):
        num = first + i
        if flag_from <= num <= flag_to:
            head.append(_seqadv(_ONE_TO_THREE[one], "A", num, note))
        atoms.append(_atom(len(atoms) + 1, "CA", _ONE_TO_THREE[one], "A", num))
    atoms.append(_atom(len(atoms) + 1, "CA", "TRP", "B", 1))
    return "\n".join(head + atoms + ["END"]) + "\n"


def _tagged_cif(details="expression tag", strand="A", mon_override=None):
    """Minimal mmCIF with the same tag, annotated in _struct_ref_seq_dif."""
    lines = [
        "data_TEST",
        "loop_",
        "_atom_site.group_PDB",
        "_atom_site.id",
        "_atom_site.label_atom_id",
        "_atom_site.label_comp_id",
        "_atom_site.label_asym_id",
        "_atom_site.label_seq_id",
        "_atom_site.Cartn_x",
        "_atom_site.Cartn_y",
        "_atom_site.Cartn_z",
    ]
    for i, one in enumerate(_5O45_TAIL):
        lines.append(f"ATOM {i + 1} CA {_ONE_TO_THREE[one]} A {i + 1} 1.0 2.0 3.0")
    lines += [
        "#",
        "loop_",
        "_struct_ref_seq_dif.align_id",
        "_struct_ref_seq_dif.mon_id",
        "_struct_ref_seq_dif.pdbx_pdb_strand_id",
        "_struct_ref_seq_dif.seq_num",
        "_struct_ref_seq_dif.details",
        "_struct_ref_seq_dif.pdbx_auth_seq_num",
    ]
    for i, one in enumerate(_5O45_TAIL):
        if i + 1 <= len(_5O45_NATIVE):
            continue
        mon = mon_override or _ONE_TO_THREE[one]
        lines.append(f"1 {mon} {strand} {i + 1} '{details}' {_5O45_FIRST + i}")
    lines.append("#")
    return "\n".join(lines) + "\n"


@pytest.fixture
def always_yes(monkeypatch):
    monkeypatch.setattr(conf, "ask_yn", lambda *_a, **_k: True)


class TestExpressionTagTrimUsesTheDepositorsOwnAnnotation:
    """The construct residues are not guessable from the sequence, and they do not have
    to be guessed: the depositor named them, per residue, at deposition time (SEQADV in
    a PDB, _struct_ref_seq_dif in an mmCIF). Those records are in the lines the
    configurator already reads.
    """

    def test_the_whole_aaale_his6_tag_is_trimmed_not_just_the_his_run(self, tmp_path, always_yes):
        src = tmp_path / "5o45.pdb"
        src.write_text(_tagged_pdb())
        seq = conf.extract_sequence_from_pdb(str(src), "A")
        assert seq.endswith("ITVKVNAPYAAALE" + "HHHHHH")
        assert conf.warn_expression_tags(seq, str(src), "A") == _5O45_NATIVE

    def test_the_evidence_says_the_annotation_is_authoritative(self, tmp_path, always_yes, capsys):
        src = tmp_path / "5o45.pdb"
        src.write_text(_tagged_pdb())
        conf.warn_expression_tags(conf.extract_sequence_from_pdb(str(src), "A"), str(src), "A")
        out = capsys.readouterr().out
        assert "SEQADV" in out, "the user must be told this is the depositor's own record"
        assert "GUESS" not in out

    def test_the_mmcif_annotation_is_read_too(self, tmp_path, always_yes, capsys):
        src = tmp_path / "5o45.cif"
        src.write_text(_tagged_cif())
        seq = conf.extract_sequence_from_cif(str(src), "A")
        assert seq == _5O45_TAIL
        assert conf.warn_expression_tags(seq, str(src), "A") == _5O45_NATIVE
        assert "_struct_ref_seq_dif" in capsys.readouterr().out

    def test_declining_keeps_every_residue(self, tmp_path, monkeypatch):
        monkeypatch.setattr(conf, "ask_yn", lambda *_a, **_k: False)
        src = tmp_path / "5o45.pdb"
        src.write_text(_tagged_pdb())
        seq = conf.extract_sequence_from_pdb(str(src), "A")
        assert conf.warn_expression_tags(seq, str(src), "A") == seq

    @pytest.mark.parametrize("note", ["CLONING ARTIFACT", "LINKER"])
    def test_the_other_accepted_annotations(self, tmp_path, always_yes, note):
        src = tmp_path / "x.pdb"
        src.write_text(_tagged_pdb(note=note))
        seq = conf.extract_sequence_from_pdb(str(src), "A")
        assert conf.warn_expression_tags(seq, str(src), "A") == _5O45_NATIVE

    @pytest.mark.parametrize("note", ["CONFLICT", "ENGINEERED MUTATION", "VARIANT", "INSERTION", "DELETION"])
    def test_a_mutation_or_conflict_annotation_is_not_construct(self, tmp_path, always_yes, note):
        """Those residues are the protein that was crystallised, not added sequence.
        The pattern fallback may still offer the His run — but the annotation must not
        claim authority over AAALE."""
        src = tmp_path / "x.pdb"
        src.write_text(_tagged_pdb(note=note))
        lines = src.read_text().splitlines()
        assert conf._pdb_seqadv_construct(lines, "A") == {}

    def test_an_interior_annotation_is_never_excised(self):
        """An interior SEQADV is a point mutation, not a tag; removing it would splice
        two distant stretches of the chain together."""
        assert conf._terminal_construct_span({5}, 20) == (0, 20)
        assert conf._terminal_construct_span({0, 1, 5, 19}, 20) == (2, 19)

    def test_a_fully_flagged_chain_is_refused_rather_than_emptied(self):
        assert conf._terminal_construct_span({0, 1, 2}, 3) == (0, 3)

    def test_interior_flags_are_reported_as_kept(self, tmp_path, always_yes, capsys):
        src = tmp_path / "x.pdb"
        # Flag the terminal tag AND one interior residue (resnum 130, mid-chain).
        text = _tagged_pdb()
        # resnum 130 is index 4 of the chain, a VAL — the name must match or the
        # annotation is (correctly) refused as a chain mismatch.
        text = text.replace("HEADER    TEST\n", "HEADER    TEST\n" + _seqadv("VAL", "A", 130) + "\n")
        src.write_text(text)
        seq = conf.extract_sequence_from_pdb(str(src), "A")
        assert conf.warn_expression_tags(seq, str(src), "A") == _5O45_NATIVE
        out = capsys.readouterr().out
        assert "INTERIOR" in out and "KEPT" in out

    def test_a_chain_id_namespace_mismatch_is_refused_not_applied(self, tmp_path):
        """pdbx_pdb_strand_id is the AUTHOR chain id while the sequence extractor filters
        on label_asym_id. If the two denote different chains the annotated residue NAMES
        will not line up, and the annotation must be dropped, not applied blind."""
        src = tmp_path / "x.cif"
        src.write_text(_tagged_cif(mon_override="TRP"))
        seq = conf.extract_sequence_from_cif(str(src), "A")
        assert conf._annotated_construct_span(seq, str(src), "A") is None

    def test_an_annotation_for_another_chain_is_ignored(self, tmp_path):
        src = tmp_path / "x.cif"
        src.write_text(_tagged_cif(strand="B"))
        seq = conf.extract_sequence_from_cif(str(src), "A")
        assert conf._annotated_construct_span(seq, str(src), "A") is None


class TestTagPatternFallbackHandlesArbitraryLinkers:
    """For files with no per-residue annotation the pattern is all there is, so it must
    not assume the linker is made of G/S/A/L.
    """

    def _no_annotation(self, tmp_path, tail):
        src = tmp_path / "plain.pdb"
        src.write_text(_tagged_pdb(tail=tail, flag_from=10**6, flag_to=10**6))
        return str(src), conf.extract_sequence_from_pdb(str(src), "A")

    @pytest.mark.parametrize("linker", ["AAALE", "LE", "GSGS", "GGGGSGGGGS", "ENLYFQG", "LVPRGS", "GS", ""])
    def test_a_named_linker_in_front_of_the_his_run_goes_too(self, tmp_path, always_yes, linker):
        """AAALE is the one that mattered: [GSAL]{0,3} stopped at its 'E' on 5O45."""
        path, seq = self._no_annotation(tmp_path, _5O45_NATIVE + linker + "HHHHHH")
        assert conf.warn_expression_tags(seq, path, "A") == _5O45_NATIVE

    def test_an_unnamed_linker_costs_no_native_residues(self, tmp_path, always_yes):
        """The honest limit of a guess. "Up to 5 residues of anything" would catch RSVD
        here, but it also trims …ITVKVNAPY|HHHHHH down to …ITVK, because a pattern cannot
        tell a 0-residue linker from a 5-residue one. Over-trimming native protein is the
        worse failure, and the authoritative SEQADV path is what handles this properly."""
        path, seq = self._no_annotation(tmp_path, _5O45_NATIVE + "RSVD" + "HHHHHH")
        assert conf.warn_expression_tags(seq, path, "A") == _5O45_NATIVE + "RSVD"

    def test_a_plain_his_tag_never_eats_the_residues_in_front_of_it(self, tmp_path, always_yes):
        path, seq = self._no_annotation(tmp_path, _5O45_NATIVE + "HHHHHH")
        assert conf.warn_expression_tags(seq, path, "A") == _5O45_NATIVE

    def test_the_evidence_says_plainly_that_it_is_a_guess(self, tmp_path, always_yes, capsys):
        path, seq = self._no_annotation(tmp_path, _5O45_NATIVE + "AAALEHHHHHH")
        conf.warn_expression_tags(seq, path, "A")
        out = capsys.readouterr().out
        assert "GUESS" in out
        assert "SEQADV" not in out

    def test_a_native_sequence_with_no_his_run_is_left_alone(self, tmp_path, always_yes):
        path, seq = self._no_annotation(tmp_path, "ITVKVNAPYWKTVNDLGE")
        assert conf.warn_expression_tags(seq, path, "A") == seq

    def test_an_n_terminal_his_tag_is_still_found(self, always_yes):
        assert conf.warn_expression_tags("MGSSHHHHHHSSGLITVKVNAPY") == "ITVKVNAPY"


class TestPreparedStructureWarnsAboutConstructResiduesItKeeps:
    """prepare_target_pdb reads the SEQADV lines anyway. A cheap backstop for exactly
    the class of miss above: if a residue it is KEEPING is flagged as construct, the
    sequence trim did not happen or did not reach far enough.
    """

    def test_a_kept_tag_residue_is_named(self, tmp_path, capsys):
        src = tmp_path / "t_original.pdb"
        src.write_text(_tagged_pdb())
        dest = tmp_path / "t.pdb"
        report = conf.prepare_target_pdb(src, dest, "A", "")  # no trim: tag kept
        assert report["construct_kept"]["A"] == [str(n) for n in range(135, 146)]
        conf.report_target_preparation(report, dest)
        out = capsys.readouterr().out
        assert "flagged as construct" in out
        assert "135" in out

    def test_an_accepted_trim_leaves_nothing_to_warn_about(self, tmp_path):
        src = tmp_path / "t_original.pdb"
        src.write_text(_tagged_pdb())
        dest = tmp_path / "t.pdb"
        report = conf.prepare_target_pdb(src, dest, "A", _5O45_NATIVE)
        assert report["construct_kept"] == {}
        assert report["trimmed"] == 11
        assert conf.extract_sequence_from_pdb(str(dest), "A") == _5O45_NATIVE
        assert conf.pdb_chain_residue_numbers(str(dest), "A") == list(range(126, 135))
        assert conf.extract_sequence_from_pdb(str(dest), "B") is None


class TestSequenceAndCoordinatesAgreeAfterGeneration:
    """The coupling run_rfd3.sh depends on, asserted end to end.

    `best_full[len(target_sequence):]` is how every RFD3 binder is recovered, so a
    prepared structure one residue longer than cfg["target_sequence"] delivers a binder
    with the tag glued on and no error anywhere. That is why the trim and the
    preparation are one change.
    """

    @pytest.mark.parametrize("suffix", [".pdb", ".cif"])
    def test_the_prepared_structure_is_exactly_the_target_sequence(self, tmp_path, always_yes, suffix):
        src = tmp_path / f"5o45{suffix}"
        src.write_text(_tagged_cif() if suffix == ".cif" else _tagged_pdb())
        seq = conf.extract_sequence_from_structure(str(src), "A")
        trimmed = conf.warn_expression_tags(seq, str(src), "A")
        assert trimmed == _5O45_NATIVE

        run_dir = tmp_path / "runs" / "t"
        run_dir.mkdir(parents=True)
        cfg = {
            "name": "t",
            "run_dir": run_dir,
            "target_pdb_src": str(src),
            "target_sequence": trimmed,
            "chains": "A",
            "hotspots": None,
        }
        conf.generate(cfg, {})
        from_coords = conf.extract_sequence_from_pdb(str(cfg["target_pdb"]), "A")
        assert from_coords == cfg["target_sequence"]
        # And the bound peptide the PDB fixture carries in chain B is gone.
        assert conf.extract_sequence_from_pdb(str(cfg["target_pdb"]), "B") is None


RCSB_CIF = Path(__file__).resolve().parents[2] / "PXDesign" / "examples" / "5o45.cif"

# --- Three things the adversarial review of the BUG-16 fix found ------------


def test_an_unselected_chain_of_the_other_case_is_dropped_not_silently_kept(tmp_path):
    """PDB chain ids are case-sensitive, and folding them kept a chain for free.

    `available_chains()` lists "A" and "a" separately, so a user can select either.
    With the chain column `.upper()`ed on both sides, selecting "A" wrote chain `a`
    out verbatim as well, reported `dropped_chains == {}` and printed "kept chain(s)
    A" over it -- so a second chain sat in the target the designers read while the
    report said nothing was dropped. Lowercase ids are routine in deposits with
    more than 26 chains.
    """
    src = tmp_path / "two_cases.pdb"
    src.write_text(
        "ATOM      1  CA  GLY A   1      0.000   0.000   0.000  1.00  0.00           C\n"
        "ATOM      2  CA  ALA A   2      1.000   0.000   0.000  1.00  0.00           C\n"
        "ATOM      3  CA  TRP a   1      2.000   0.000   0.000  1.00  0.00           C\n"
        "ATOM      4  CA  TYR a   2      3.000   0.000   0.000  1.00  0.00           C\n"
        "END\n"
    )
    dest = tmp_path / "prepared.pdb"
    report = conf.prepare_target_pdb(src, dest, "A", "GA")

    assert report is not None
    body = [ln for ln in dest.read_text().splitlines() if ln[:4] == "ATOM"]
    assert {ln[21] for ln in body} == {"A"}, "chain 'a' was written into the prepared target"
    assert len(body) == 2
    assert report["dropped_chains"] == {"a": 2}, f"chain 'a' not reported as dropped: {report}"
    assert conf.extract_sequence_from_pdb(str(dest), "A") == "GA"


def test_a_modified_polymer_residue_is_reported_as_a_gap_not_just_a_ligand(tmp_path):
    """MSE is a polymer residue written as HETATM; dropping it holes the backbone.

    Selenomethionine is the standard SAD-phasing substitution and appears in a
    large share of crystal structures. Counting it among the ligands is accurate
    but not enough: the kept chain now has a gap at that residue, and
    `rfd3_target_contig` emits one more range per gap. The sequence agrees either
    way (extract_sequence_from_pdb is ATOM-only), which is exactly why nothing
    downstream raises -- so preparation has to say it.
    """
    src = tmp_path / "mse.pdb"
    src.write_text(
        "ATOM      1  CA  GLY A   1      0.000   0.000   0.000  1.00  0.00           C\n"
        "HETATM    2  CA  MSE A   2      1.000   0.000   0.000  1.00  0.00           C\n"
        "ATOM      3  CA  ALA A   3      2.000   0.000   0.000  1.00  0.00           C\n"
        "END\n"
    )
    report = conf.prepare_target_pdb(src, tmp_path / "prepared.pdb", "A", "GA")

    assert report is not None
    assert report["chain_gaps"] == {"A": ["MSE 2"]}, f"the gap was not reported: {report}"
    # A real ligand must NOT be reported as a gap: no CA, so it is not polymer.
    src2 = tmp_path / "ligand.pdb"
    src2.write_text(
        "ATOM      1  CA  GLY A   1      0.000   0.000   0.000  1.00  0.00           C\n"
        "HETATM    2  C1  9KK A 201      1.000   0.000   0.000  1.00  0.00           C\n"
        "END\n"
    )
    report2 = conf.prepare_target_pdb(src2, tmp_path / "prepared2.pdb", "A", "G")
    assert report2["ligands"] == {"9KK": 1}
    assert report2["chain_gaps"] == {}, "a ligand with no CA was reported as a backbone gap"


def test_the_construct_backstop_reads_the_cif_when_the_pdb_was_converted_from_one(tmp_path):
    """The backstop was inert on the default RCSB download format.

    `prepare_target_pdb` read SEQADV out of the PDB it was handed -- which, for a
    CIF target, is a file `cif_to_pdb_atoms` had just written from _atom_site
    records and therefore carries no SEQADV at all. So the one mechanism designed
    to catch "the sequence trim missed the tag" could never fire on exactly the
    input where the trim can be missed: a headless replay, a hand-written config,
    or a user who declines the Step 3 prompt with a CIF target.
    """
    if not RCSB_CIF.exists():
        pytest.skip("PXDesign/examples/5o45.cif not present (PXDesign is gitignored)")
    raw = tmp_path / "raw.pdb"
    assert conf.cif_to_pdb_atoms(str(RCSB_CIF), str(raw))
    untrimmed = conf.extract_sequence_from_pdb(str(raw), "A")

    without = conf.prepare_target_pdb(raw, tmp_path / "a.pdb", "A", untrimmed)
    assert without is not None
    with_cif = conf.prepare_target_pdb(raw, tmp_path / "b.pdb", "A", untrimmed, annotation_src=RCSB_CIF)
    assert with_cif is not None

    assert without["construct_kept"] == {}, "fixture precondition: the converted PDB has no SEQADV"
    kept = with_cif["construct_kept"].get("A", [])
    assert len(kept) == 11, f"expected the depositor's eleven construct residues, got {kept}"
    # Author numbering, because that is how the prepared file is numbered and what
    # the entry page shows: 5O45's tag is A135-A145.
    assert kept[0] == "135" and kept[-1] == "145", kept
