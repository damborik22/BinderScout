"""The four sequence-joined attaches in cli/report.py must not multiply rows.

Every ``binder_id``-joined attach in report.py carries ``validate="m:1"``
(report.py:828, :863, :1012, :1052, :1083, :1130), and
``comparison/merger.py:139`` carries it too. The four ``sequence``-joined
attaches did not, so a right-hand table holding the same sequence twice
silently multiplied the metrics rows — and because ``rank_designs()`` runs
downstream, one design then occupied two ranks and every design below it
shifted down by one. No exception, no warning.

Duplicate sequences are not hypothetical: two tools can emit the same binder,
``extract --keep-duplicates`` emits one sequence under several binder_ids, and
CLAUDE.md records that ``refold_boltz2.py`` appends to its CSV and can carry
duplicate rows after a partial failure.

``comparison/merger.py:129-139`` is the guarded idiom these follow.
"""

import pandas as pd
import pytest
from binder_comparison.cli.report import (
    _attach_native_metrics,
    _attach_native_metrics_sidecar,
    _attach_soluprot_results,
    _attach_tmprot_results,
)

DUPED = "AAAA"


def _pool() -> pd.DataFrame:
    """Three distinct designs, descending consensus so rank is 1, 2, 3."""
    return pd.DataFrame(
        {
            "binder_id": ["a", "b", "c"],
            "sequence": [DUPED, "BBBB", "CCCC"],
            "consensus_iptm_mean": [0.90, 0.80, 0.70],
            "consensus_iptm_n": [3, 3, 3],
            "consensus_iptm": [0.90, 0.80, 0.70],
            "plddt_binder_mean": [0.9, 0.8, 0.7],
        }
    )


def _write_soluprot(tmp_path):
    p = tmp_path / "soluprot.csv"
    pd.DataFrame(
        {
            "sequence": [DUPED, DUPED, "BBBB"],
            "soluprot_score": [0.51, 0.62, 0.73],
            "soluprot_passes": [True, True, False],
        }
    ).to_csv(p, index=False)
    return str(p)


def _write_tmprot(tmp_path):
    p = tmp_path / "tmprot.csv"
    pd.DataFrame({"sequence": [DUPED, DUPED, "BBBB"], "predicted_tm": [55.0, 61.0, 48.0]}).to_csv(p, index=False)
    return str(p)


def _write_native(tmp_path):
    p = tmp_path / "native.csv"
    pd.DataFrame(
        {
            "Sequence": [DUPED, DUPED, "BBBB"],
            "Average_ShapeComplementarity": [0.61, 0.68, 0.55],
        }
    ).to_csv(p, index=False)
    return str(p)


def _write_sidecar(tmp_path):
    """The sidecar attach is keyed off the FASTA path, not a CSV path."""
    fasta = tmp_path / "seqs.fasta"
    fasta.write_text(f">a\n{DUPED}\n>b\nBBBB\n>c\nCCCC\n")
    pd.DataFrame(
        {
            "sequence": [DUPED, DUPED, "BBBB"],
            "native_mosaic_loss": [1.1, 2.2, 3.3],
        }
    ).to_csv(tmp_path / "seqs_native_metrics.csv", index=False)
    return str(fasta)


ATTACHES = [
    pytest.param(_attach_soluprot_results, _write_soluprot, id="soluprot"),
    pytest.param(_attach_tmprot_results, _write_tmprot, id="tmprot"),
    pytest.param(_attach_native_metrics, _write_native, id="native_metrics"),
    pytest.param(_attach_native_metrics_sidecar, _write_sidecar, id="native_sidecar"),
]


@pytest.mark.parametrize(("attach", "write_input"), ATTACHES)
def test_duplicate_sequence_does_not_multiply_rows(attach, write_input, tmp_path):
    df = _pool()
    out = attach(df, write_input(tmp_path))

    assert len(out) == len(df), (
        f"{attach.__name__} multiplied {len(df)} designs into {len(out)} rows on a "
        "right-hand table holding one duplicated sequence"
    )
    assert out["binder_id"].is_unique


@pytest.mark.parametrize(("attach", "write_input"), ATTACHES)
def test_duplicate_sequence_keeps_first_and_warns(attach, write_input, tmp_path):
    """Keep the first row per sequence, and say so — silence is what made this
    defect survive. Matches merger.py:129-139."""
    with pytest.warns(UserWarning, match="duplicate sequence"):
        out = attach(_pool(), write_input(tmp_path))
    assert len(out) == 3


def test_rank_is_not_corrupted_by_a_duplicated_sequence(tmp_path):
    """The reason this matters: rank_designs() runs downstream of the attaches."""
    from binder_comparison.comparison.scoring import rank_designs

    with pytest.warns(UserWarning):
        merged = _attach_soluprot_results(_pool(), _write_soluprot(tmp_path))
    ranked = rank_designs(merged)

    assert ranked["binder_id"].is_unique, "one design occupied more than one rank"
    assert ranked.sort_values("rank")["binder_id"].tolist() == ["a", "b", "c"]
    assert ranked.loc[ranked.binder_id == "c", "rank"].item() == 3
