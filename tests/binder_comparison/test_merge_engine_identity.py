"""Engine CSVs that folded the same binder against different targets must not merge in silence.

2026-10-28, PD-L1. The incident behind `test_merger_pool_universe.py` and `test_refold_resume.py`
was an engine CSV that carried rows from an earlier campaign. Those two fixes settle which
*binders* belong in the report. Nothing settles which *target* the surviving rows were folded
against, and `target_sequence` -- the only per-row record of it -- is thrown away at the join.

`merge_refold_results` joins the engine CSVs on the binder `sequence` alone. `target_sequence` is
one of `_PASSTHROUGH_COLS` ("identifiers shared across engines"), so it keeps its bare name in
every engine's frame. When the second engine is joined on, pandas renames the clash
`target_sequence_af3_dup` and the very next loop drops it (the comment beside it says "prefer the
first engine's values"). That is harmless while the copies agree. When they do not, the later
engine's target simply vanishes: no warning, no column, no trace.

A single `evaluate.sh` run hands one `--target-seq` to all three engines, so this needs CSVs from
two campaigns to meet. They can. Every refold engine opens its CSV in append mode (refold_boltz2.py,
refold_af3.py, refold_esmfold2.py), `--resume` keys on the binder sequence and never looks at the
target, and `binder-compare report` takes whichever three CSV paths it is handed. Driven through the
real `report` command with Boltz-2 on one target and AF3 + ESMFold2 on another, nothing in
`metrics.csv`, the console output or the warnings tells the run apart from an honest single-target
one: one target recorded, the other nowhere, `consensus_iptm_n` = 3, `rank` = 1. A design for which
no single target has more than two engines' evidence has cleared the 3-engine gate.

The merge is the one place that sees every engine's rows for the same binder side by side, so it is
the place to notice. These tests do not dictate HOW it is reported -- a UserWarning (the idiom
`_restrict_to_pool` and the duplicate-sequence guard already use) or a ValueError (what "No
non-empty refolding CSVs" raises) both satisfy them -- only that it is not silent.

`TestDisagreeingTargetsAreNotSilentlyMerged` was written RED against the 1.0.6 release: that is the
finding, not a mistake in the test. The second class holds controls that pass today and keep a fix
honest: agreeing engines stay quiet, spelling is not a different protein, and the merged frame keeps
exposing the target as `target_sequence`, because `visualization/report.py` reads it by that name to
tell the binder chain from the target chain in the 3D viewers. A fix that "solves" the disagreement
by removing `target_sequence` from `_PASSTHROUGH_COLS` makes that read silently find nothing.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd
import pytest
from binder_comparison.comparison.merger import merge_refold_results

# Two different proteins: valid amino-acid strings, short enough to read in a failure message.
_TARGET_A = "AFTVTVPKDLYVVEYGSNMTIECKFPVEKQ"  # the campaign being reported
_TARGET_B = "LEEKKVCQGTSNKLTQLGTFEDHFLSLQRM"  # some other campaign's target

# The pool. Only the last binder is ever folded against the wrong target, so a check that looks at
# one row (or one distinct value) instead of every row cannot pass by accident.
_POOL = ["MAEVKLSYVLQ", "SPEELLQKAIR", "GSHMTEYKLVV"]

_ENGINES = ("boltz", "af3", "esmfold2")  # the merger's own order: Boltz-2 anchors the join
_IPTM = {"boltz": 0.82, "af3": 0.78, "esmfold2": 0.74}


def _engine_csv(path: Path, engine: str, targets: list[str]) -> Path:
    """One row per pool binder, with the columns the real refold scripts write."""
    pd.DataFrame(
        [
            {
                "run_id": f"{engine}_{i:04d}",
                "idx": i,
                "sequence": seq,
                "target_sequence": target,
                "binder_length": len(seq),
                "iptm": _IPTM[engine],
            }
            for i, (seq, target) in enumerate(zip(_POOL, targets), 1)
        ]
    ).to_csv(path, index=False)
    return path


def _fasta(path: Path) -> Path:
    path.write_text("".join(f">b{i} source=mosaic length={len(s)}\n{s}\n" for i, s in enumerate(_POOL, 1)))
    return path


def _merge(tmp_path: Path, targets_by_engine: dict[str, list[str]]) -> tuple[pd.DataFrame | None, list[str]]:
    """Run the real merge; return (merged frame, or None if it refused; everything it said).

    A refusal counts as having said something: the tests only ask that a disagreement not pass in
    silence, not how it is reported.
    """
    csvs = {engine: _engine_csv(tmp_path / f"{engine}.csv", engine, t) for engine, t in targets_by_engine.items()}
    messages: list[str] = []
    merged = None
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            merged = merge_refold_results(
                csvs.get("boltz"),
                _fasta(tmp_path / "pool.fasta"),
                af3_csv=csvs.get("af3"),
                esmfold2_csv=csvs.get("esmfold2"),
            )
        except ValueError as exc:
            messages.append(str(exc))
    messages += [str(w.message) for w in caught]
    # A message that merely quotes pytest's temp path must not count as mentioning the target.
    return merged, [m.replace(str(tmp_path), "<tmp>") for m in messages]


def _mentions_the_target(messages: list[str]) -> bool:
    return any("target" in m.lower() for m in messages)


def _target_kept_for(merged: pd.DataFrame | None, sequence: str) -> str | None:
    if merged is None or "target_sequence" not in merged.columns:
        return None
    kept = merged.loc[merged["sequence"] == sequence, "target_sequence"].dropna()
    return kept.iloc[0] if len(kept) else None


class TestDisagreeingTargetsAreNotSilentlyMerged:
    """RED against 1.0.6: the merge keeps one engine's target and says nothing about the other."""

    @pytest.mark.parametrize(
        ("engines", "odd_one_out"),
        [
            pytest.param(_ENGINES, "boltz", id="boltz-is-the-odd-one-out"),
            pytest.param(_ENGINES, "af3", id="af3-is-the-odd-one-out"),
            pytest.param(_ENGINES, "esmfold2", id="esmfold2-is-the-odd-one-out"),
            pytest.param(("af3", "esmfold2"), "esmfold2", id="a-run-without-boltz-2"),
        ],
    )
    def test_a_binder_folded_against_two_targets_does_not_merge_in_silence(
        self, tmp_path: Path, engines: tuple[str, ...], odd_one_out: str
    ) -> None:
        """Whichever engine disagrees, and whether or not Boltz-2 is the anchor, it must be said."""
        agreeing = [_TARGET_A] * len(_POOL)
        disagreeing = [*agreeing[:-1], _TARGET_B]
        merged, messages = _merge(tmp_path, {e: disagreeing if e == odd_one_out else agreeing for e in engines})

        assert _mentions_the_target(messages), (
            f"{odd_one_out} folded {_POOL[-1]} against a different target than the other engine(s) did, and "
            f"merge_refold_results said nothing about it (messages: {messages!r}). It kept "
            f"target_sequence={_target_kept_for(merged, _POOL[-1])!r} for that binder and discarded the other, "
            "so the report names one target while the ipTMs on that row describe two different complexes."
        )


class TestAgreementIsUnremarkable:
    """Controls. A guard that fires on every merge, or that renames what the report reads, is worse than none."""

    def test_engines_that_agree_on_the_target_merge_without_a_word_about_it(self, tmp_path: Path) -> None:
        merged, messages = _merge(tmp_path, {engine: [_TARGET_A] * len(_POOL) for engine in _ENGINES})

        assert merged is not None
        assert len(merged) == len(_POOL)
        assert not _mentions_the_target(messages), messages

    def test_targets_that_differ_only_in_case_or_padding_are_the_same_target(self, tmp_path: Path) -> None:
        """`scripts/refold_boltz2.py` run directly upper-cases and strips its target before writing it, while
        the `binder-compare refold-*` commands write whatever `--target-seq` held. The report reads the
        column just as forgivingly (`.str.upper().str.strip()`), so spelling is not a disagreement."""
        spellings = {"boltz": _TARGET_A, "af3": _TARGET_A.lower(), "esmfold2": f"  {_TARGET_A}  "}
        merged, messages = _merge(tmp_path, {engine: [spelling] * len(_POOL) for engine, spelling in spellings.items()})

        assert merged is not None
        assert len(merged) == len(_POOL)
        assert not _mentions_the_target(messages), messages

    def test_the_agreed_target_is_still_exposed_as_target_sequence(self, tmp_path: Path) -> None:
        """`generate_report` reads `df["target_sequence"]` to pick the binder chain and the target chain
        for the 3D viewers, and falls back to a blind "chain A is the binder" when it is absent. Moving
        the column out of `_PASSTHROUGH_COLS` leaves it as `boltz_target_sequence`, `af3_target_sequence`,
        ..., and that read quietly finds nothing. If the column is renamed on purpose, change
        `generate_report` in the same commit and this test with it."""
        merged, _ = _merge(tmp_path, {engine: [_TARGET_A] * len(_POOL) for engine in _ENGINES})

        assert merged is not None
        assert "target_sequence" in merged.columns, (
            f"the merged frame no longer has a `target_sequence` column (columns: {sorted(merged.columns)}); "
            "visualization/report.py reads it by that name"
        )
        assert set(merged["target_sequence"].dropna()) == {_TARGET_A}
