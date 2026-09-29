"""Refold structures must land on disk under their design's ``binder_id``.

Three engines in three conda environments plus the Foldseek join all derive that
filename, so the mapping lives in one module. These tests pin the two properties that
make it usable -- every design gets a *distinct* name, and a name is never taken from
the wrong design -- and then check each engine actually calls it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from binder_comparison.io.design_ids import safe_stem, structure_stems

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "Evaluator" / "scripts"


# ── the shared mapping ───────────────────────────────────────────────────────────


def test_the_binder_id_becomes_the_stem():
    assert structure_stems(["bindcraft_t_l28_s101"], ["refold1_abcd"]) == ["bindcraft_t_l28_s101"]


def test_the_engine_is_part_of_the_name():
    assert structure_stems(["bc_l28_s3"], ["refold1_abcd"], engine="boltz2") == ["bc_l28_s3_boltz2"]


def test_pooling_the_three_engines_cannot_collide():
    """The reason the engine is in the name at all.

    Each engine writes into its own directory, so nothing collides there. Copy all
    three into one folder -- the normal way to hand someone "all the PDBs" -- and
    without the engine suffix one design's three structures are three files of the
    same name, two of which vanish.
    """
    ids = ["rfd3_b7", "bc_l28_s3"]
    pooled = [
        f"{stem}.pdb"
        for engine, legacy in (
            ("boltz2", ["refold1_uu", "refold2_uu"]),
            ("af3", ["af3_0001", "af3_0002"]),
            ("esmfold2", ["esmfold2_0001", "esmfold2_0002"]),
        )
        for stem in structure_stems(ids, legacy, engine=engine)
    ]
    assert len(set(pooled)) == len(pooled) == 6, f"pooled names collide: {sorted(pooled)}"
    assert "rfd3_b7_af3.pdb" in pooled


def test_a_fallback_name_is_not_suffixed_twice():
    # The legacy names already say which engine wrote them.
    assert structure_stems([None], ["af3_0007"], engine="af3") == ["af3_0007"]


def test_path_separators_and_traversal_cannot_survive():
    stems = structure_stems(["../../etc/passwd", "a/b", ".."], ["f1", "f2", "f3"])
    for stem in stems:
        assert "/" not in stem and "\\" not in stem
        assert stem not in (".", "..")
        # A stem that sanitises to nothing but underscores must fall back, not be used.
        assert stem.strip("_"), f"{stem!r} is not a usable filename"
    assert stems[2] == "f3", "'..' has no usable characters and must fall back"


def test_a_missing_or_empty_id_keeps_the_engines_legacy_name():
    assert structure_stems([None, "", "   "], ["af3_0001", "af3_0002", "af3_0003"]) == [
        "af3_0001",
        "af3_0002",
        "af3_0003",
    ]


def test_two_designs_sharing_an_id_do_not_share_a_file():
    stems = structure_stems(["dup", "dup", "dup"], ["f1", "f2", "f3"])
    assert len(set(stems)) == 3, f"{stems} would clobber: one design's structure is lost"
    assert stems[0] == "dup"


def test_ids_that_differ_only_in_an_unsafe_character_stay_distinct():
    # 'a.b' and 'a/b' both sanitise to 'a_b'; collision handling must still separate them.
    stems = structure_stems(["a.b", "a/b"], ["f1", "f2"])
    assert len(set(stems)) == 2, f"{stems}: sanitisation collapsed two designs onto one file"


def test_a_length_mismatch_is_refused_not_silently_realigned():
    # The worst failure mode: every structure named after a different design, every
    # path resolving, nothing downstream able to notice.
    with pytest.raises(ValueError, match=r"off-by-one|refusing"):
        structure_stems(["a", "b"], ["f1", "f2", "f3"])


def test_no_ids_at_all_is_not_an_error():
    assert structure_stems(None, ["f1", "f2"]) == ["f1", "f2"]


def test_foldseek_uses_the_same_sanitiser_so_the_join_holds():
    # A second copy of this logic is how a structure becomes unfindable by its id.
    from binder_comparison.comparison import foldseek

    src = Path(foldseek.__file__).read_text()
    assert "safe_stem" in src, "foldseek must share the one sanitiser, not re-implement it"
    assert not re.search(r"isalnum\(\) or c in", src), "foldseek still has its own inline sanitiser"
    assert safe_stem("a.b") == "a_b"


# ── every engine must actually use it ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("script", "legacy", "engine"),
    [
        ("refold_boltz2.py", r"refold\{idx\}_\{run_id\}", "boltz2"),
        ("refold_af3.py", r"af3_\{idx:04d\}\.pdb", "af3"),
        ("refold_esmfold2.py", r"esmfold2_\{idx:04d\}\.pdb", "esmfold2"),
    ],
)
def test_each_engine_names_structures_from_the_shared_helper(script, legacy, engine):
    import ast

    src = (SCRIPTS / script).read_text()
    assert "binder_ids" in src, f"{script} has no way to receive the ids"
    assert not re.search(legacy, src), f"{script} still builds a structure path from the loop index"

    # ...and tells the helper which engine it is, or all three write the same names.
    declared = {
        kw.value.value
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "structure_stems"
        for kw in node.keywords
        if kw.arg == "engine" and isinstance(kw.value, ast.Constant)
    }
    assert declared == {engine}, f"{script} names structures without identifying itself: {declared or 'no engine'}"


@pytest.mark.parametrize("script", ["refold_boltz2.py", "refold_af3.py", "refold_esmfold2.py"])
def test_each_engine_reads_the_ids_from_the_fasta_header(script):
    """Run standalone, the scripts get ids only from the FASTA they are handed."""
    src = (SCRIPTS / script).read_text()
    assert "parse_fasta_pairs" in src, f"{script} discards the FASTA header, so it has no binder_id"


def test_the_shared_parser_takes_the_id_from_the_header():
    from binder_comparison.io.design_ids import parse_fasta_pairs

    pairs = parse_fasta_pairs(">bc_l28_s3  source=bindcraft  length=28\nAAAA\nCCCC\n>b2\nDDDD\n")
    assert pairs == [("bc_l28_s3", "AAAACCCC"), ("b2", "DDDD")], (
        "the id is the header's first token, and a wrapped sequence is one sequence"
    )


def test_a_headerless_list_is_not_concatenated_into_one_sequence():
    # Parsing a bare sequence list as FASTA would glue every line into one giant
    # "binder" and refold that instead of the pool.
    from binder_comparison.io.design_ids import parse_fasta_pairs

    assert parse_fasta_pairs("AAAA\nCCCC\n") == [(None, "AAAA"), (None, "CCCC")]


@pytest.mark.parametrize(
    ("module", "runner"),
    [
        ("refold_boltz2", "run_boltz2_refold"),
        ("refold_af3", "run_af3_refold"),
        ("refold_esmfold2", "run_esmfold2_refold"),
    ],
)
def test_the_cli_hands_the_runner_the_ids_it_parsed(module, runner, tmp_path, monkeypatch):
    """``read_fasta`` hands back (header, seq); dropping the header loses the id.

    Behavioural on purpose. Asserting that the string ``binder_ids`` appears in the
    file passes even when the parsed ids are computed and then never passed on.
    """
    import argparse
    import importlib

    cli = importlib.import_module(f"binder_comparison.cli.{module}")

    fasta = tmp_path / "seqs.fasta"
    fasta.write_text(">rfd3_b7  source=rfd3\nAAAACCCC\n>bc_l28_s3\nDDDDEEEE\n")

    captured: dict = {}
    monkeypatch.setattr(cli, runner, lambda **kw: captured.update(kw))

    args = argparse.Namespace(
        sequences=str(fasta),
        target_seq="MKTAYIAKQRQ",
        output=str(tmp_path / "out.csv"),
        output_dir=str(tmp_path / "structs"),
        num_seeds=1,
        num_samples=1,
        model_dir=None,
        scripts_path=None,
        resume=False,
        no_msa=True,
        allow_no_msa=True,
        msa_cache_dir=None,
        target_pdb=None,
        recycling_steps=1,
        model_name="full",
        model="full",
        num_loops=1,
        num_sampling_steps=1,
        num_diffusion_samples=1,
        seed=0,
    )
    cli.run(args)

    assert captured, f"cli/{module} never called {runner}"
    assert captured.get("binder_ids") == ["rfd3_b7", "bc_l28_s3"], (
        f"cli/{module} did not pass the binder ids through: {captured.get('binder_ids')!r}"
    )
    assert captured["sequences"] == ["AAAACCCC", "DDDDEEEE"]


@pytest.mark.parametrize("script", ["refold_boltz2.py", "refold_af3.py", "refold_esmfold2.py"])
def test_each_scripts_entry_point_parses_the_fasta_with_the_shared_parser(script):
    """Scoped to the standalone entry point, following one level of local helpers.

    A whole-file substring check is not enough: the guarded-import fallback also
    *defines* ``parse_fasta_pairs``, so the name is present in the file even after the
    entry point stops calling it and goes back to splitting lines itself.
    """
    import ast

    tree = ast.parse((SCRIPTS / script).read_text())
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    entry = funcs.get("main") or next(
        (n for n in tree.body if isinstance(n, ast.If) and ast.dump(n.test).find("__main__") >= 0),
        None,
    )
    assert entry is not None, f"{script} has no standalone entry point"

    def calls(node):
        return {c.func.id for c in ast.walk(node) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}

    reachable = calls(entry)
    for name in list(reachable):  # one level of local helpers, e.g. _parse_batch_input
        if name in funcs:
            reachable |= calls(funcs[name])

    assert "parse_fasta_pairs" in reachable, (
        f"{script}'s entry point does not reach the shared FASTA parser, so it cannot "
        "know any binder_id when run standalone"
    )


@pytest.mark.parametrize(
    "runner",
    ["run_boltz2_refold", "run_af3_refold", "run_esmfold2_refold"],
)
def test_each_runner_accepts_and_forwards_the_ids(runner):
    """The CLI -> runner -> refold_batch chain has no silent gap in the middle."""
    import ast
    import inspect

    from binder_comparison import refolding

    fn = getattr(refolding, runner)
    assert "binder_ids" in inspect.signature(fn).parameters, f"{runner} cannot receive the ids"

    # ...and passes them on rather than accepting and dropping them.
    tree = ast.parse(inspect.getsource(fn))
    forwarded = {
        kw.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "binder_ids" and isinstance(kw.value, ast.Name) and kw.value.id == "binder_ids"
    }
    assert forwarded, f"{runner} accepts binder_ids and never passes them to refold_batch"
