"""The index must survive extract -> sidecar -> report, or it is invisible."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pandas")

import pandas as pd
from binder_comparison.cli.extract import _write_native_metrics_sidecar
from binder_comparison.core.schema import ExtractedBinder

SEQ_A = "MKTAYIAKQRQISFVK"
SEQ_B = "GGSGGSWELVKQRQIS"


def test_sidecar_carries_generation_index(tmp_path: Path) -> None:
    binders = [
        ExtractedBinder("m_1", SEQ_A, "mosaic", generation_index=12, generation_index_source="explicit"),
        ExtractedBinder("p_1", SEQ_B, "pxdesign"),
    ]
    fasta = tmp_path / "seqs.fasta"
    fasta.write_text(f">m_1\n{SEQ_A}\n>p_1\n{SEQ_B}\n")

    _write_native_metrics_sidecar(binders, fasta)

    df = pd.read_csv(tmp_path / "seqs_native_metrics.csv")
    assert "generation_index" in df.columns, "extract drops it -> the report can never see it"
    assert "generation_index_source" in df.columns
    row_a = df[df["sequence"] == SEQ_A].iloc[0]
    assert int(row_a["generation_index"]) == 12
    assert row_a["generation_index_source"] == "explicit"
    row_b = df[df["sequence"] == SEQ_B].iloc[0]
    assert pd.isna(row_b["generation_index"])
    assert row_b["generation_index_source"] == "unavailable"


def test_report_attach_keeps_generation_index(tmp_path: Path) -> None:
    """The sidecar attach keeps only native_-prefixed columns, so an unprefixed
    generation_index would be silently dropped on the way into metrics.csv."""
    from binder_comparison.cli.report import _attach_native_metrics_sidecar

    fasta = tmp_path / "seqs.fasta"
    fasta.write_text(f">m_1\n{SEQ_A}\n>p_1\n{SEQ_B}\n")
    sidecar = tmp_path / "seqs_native_metrics.csv"
    sidecar.write_text(
        "sequence,source_tool,binder_id,generation_index,generation_index_source,native_mosaic_ranking_loss\n"
        f"{SEQ_A},mosaic,m_1,12,explicit,0.25\n"
        f"{SEQ_B},pxdesign,p_1,,unavailable,\n"
    )

    df = pd.DataFrame({"sequence": [SEQ_A, SEQ_B], "binder_id": ["m_1", "p_1"]})
    out = _attach_native_metrics_sidecar(df, str(fasta))

    assert "generation_index" in out.columns, "dropped by the native_-only filter"
    assert "generation_index_source" in out.columns
    assert int(out.loc[out["sequence"] == SEQ_A, "generation_index"].iloc[0]) == 12
    assert out.loc[out["sequence"] == SEQ_B, "generation_index_source"].iloc[0] == "unavailable"
    assert len(out) == 2, "the attach must not multiply rows"
