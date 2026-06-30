"""Tests for Phase 2: per-tool fairness classification (Items 3 + 5)."""

import pytest

pytest.importorskip("pandas")
import pandas as pd
from binder_comparison.comparison.tool_classification import (
    DEFAULT_EXTRACTOR_METADATA,
    TOOL_CLASSIFICATION,
    convergence_status,
    get_classification,
)
from binder_comparison.extractors.protein_hunter import ProteinHunterExtractor

# --- static classification lookup --------------------------------------------


def test_get_classification_case_insensitive():
    for name in ("bindcraft", "BindCraft", "BINDCRAFT"):
        cls = get_classification(name)
        assert cls is not None
        assert cls.display_name == "BindCraft"


def test_get_classification_unknown_returns_none():
    assert get_classification("not_a_tool") is None
    assert get_classification(None) is None


def test_boltzgen_nano_marked_as_vhh_cdr_redesign():
    """The reviewer flagged BoltzGen nano as VHH framework, not de-novo."""
    cls = get_classification("boltzgen_nano")
    assert cls is not None
    assert cls.modality == "vhh-cdr-redesign"
    assert "VHH" in cls.native_metric_interpretation


def test_protein_hunter_marked_pre_filtered_by_default():
    """Default Protein-Hunter extractor reads summary_high_iptm.csv → pre-filtered pool."""
    cls = get_classification("protein_hunter")
    assert cls is not None
    assert cls.pool_pre_filtered_default is True


def test_rfd3_native_metric_warns_about_self_consistency():
    """RFD3's native metric is MPNN sequence recovery; report should warn."""
    cls = get_classification("rfd3")
    assert cls is not None
    assert "self-consistency" in cls.native_metric_interpretation.lower()


def test_all_classifications_have_consistent_tool_name():
    """The dict key must match the tool_name field on the value."""
    for key, cls in TOOL_CLASSIFICATION.items():
        assert key == cls.tool_name, f"key {key!r} != tool_name {cls.tool_name!r}"


# --- convergence checks ------------------------------------------------------


def test_convergence_boltzgen_protein_flags_failed_run_below_threshold():
    failed, reason = convergence_status("boltzgen_protein", 0.05)
    assert failed is True
    assert reason is not None
    assert "0.050" in reason


def test_convergence_boltzgen_above_threshold_passes():
    failed, _reason = convergence_status("boltzgen_protein", 0.21)
    assert failed is False


def test_convergence_mosaic_never_fires():
    """Mosaic has no convergence check defined — should always return (False, None)."""
    failed, reason = convergence_status("mosaic", 0.0)
    assert (failed, reason) == (False, None)


def test_convergence_none_input_is_safe():
    failed, _reason = convergence_status("boltzgen_protein", None)
    assert failed is False


# --- extractor_metadata override (Item 3) ------------------------------------


def test_default_extractor_metadata_is_unfiltered():
    assert DEFAULT_EXTRACTOR_METADATA.pool_pre_filtered is False
    assert DEFAULT_EXTRACTOR_METADATA.source_csv is None


def test_protein_hunter_default_extractor_metadata_marks_pre_filtered():
    meta = ProteinHunterExtractor().extractor_metadata()
    assert meta.pool_pre_filtered is True
    assert meta.source_csv == "summary_high_iptm.csv"
    assert meta.notes and "filter" in meta.notes.lower()


def test_protein_hunter_all_runs_extractor_metadata_is_clean():
    meta = ProteinHunterExtractor(all_runs=True).extractor_metadata()
    assert meta.pool_pre_filtered is False
    assert meta.source_csv == "summary_all_runs.csv"


# --- banner HTML rendering ---------------------------------------------------


def _df_with(tools_and_means):
    """Build a tiny df with the given (tool, mean_ipsae_min) pairs."""
    rows = []
    for tool, mean in tools_and_means:
        rows.append({"source_tool": tool, "consensus_ipsae_min_mean": mean})
    return pd.DataFrame(rows)


def test_banner_flags_pre_filtered_pool():
    from binder_comparison.visualization.report import _tool_classification_banner_html

    df = _df_with([("protein_hunter", 0.85), ("mosaic", 0.80)])
    html = _tool_classification_banner_html(df)
    assert "PRE-FILTERED POOL" in html
    assert "Protein-Hunter" in html


def test_banner_flags_vhh_framework():
    from binder_comparison.visualization.report import _tool_classification_banner_html

    df = _df_with([("boltzgen_nano", 0.50), ("mosaic", 0.80)])
    html = _tool_classification_banner_html(df)
    assert "VHH" in html.upper()


def test_banner_flags_failed_run_when_low_consensus_ipsae():
    from binder_comparison.visualization.report import _tool_classification_banner_html

    df = _df_with([("boltzgen_protein", 0.05), ("boltzgen_protein", 0.10)])
    html = _tool_classification_banner_html(df)
    assert "FAILED RUN" in html


def test_banner_handles_missing_source_tool_column():
    from binder_comparison.visualization.report import _tool_classification_banner_html

    assert _tool_classification_banner_html(pd.DataFrame({"x": [1]})) == ""


def test_banner_override_pool_pre_filtered_via_tool_overrides():
    """--tool-meta protein_hunter='pool_pre_filtered:false' should suppress the badge."""
    from binder_comparison.visualization.report import _tool_classification_banner_html

    df = _df_with([("protein_hunter", 0.85)])
    html_default = _tool_classification_banner_html(df)
    html_overridden = _tool_classification_banner_html(
        df, tool_overrides={"protein_hunter": {"pool_pre_filtered": False}}
    )
    # The override should drop the PRE-FILTERED tag (banner still renders without flags).
    assert "PRE-FILTERED POOL" in html_default
    assert "PRE-FILTERED POOL" not in html_overridden


# --- provenance footer (Item 6) ----------------------------------------------


def test_provenance_footer_renders_when_data_present():
    from binder_comparison.visualization.report import _provenance_footer_html

    html = _provenance_footer_html(
        {
            "git_sha": "abc12345",
            "evaluator_version": "0.1.0",
            "run_timestamp_utc": "2026-06-30T08:00:00Z",
            "cli_args": ["binder-compare", "report", "--rank-by", "two_stage"],
            "engine_versions": {"boltz": "2024.08", "af3": "v3.0.2"},
        }
    )
    assert "abc12345" in html
    assert "0.1.0" in html
    assert "2026-06-30" in html
    assert "binder-compare report --rank-by two_stage" in html
    assert "boltz" in html and "2024.08" in html


def test_provenance_footer_empty_for_no_data():
    from binder_comparison.visualization.report import _provenance_footer_html

    assert _provenance_footer_html(None) == ""
    assert _provenance_footer_html({}) == ""


# --- _parse_tool_meta CLI flag parser ----------------------------------------


def test_parse_tool_meta_parses_repeated_specs():
    from binder_comparison.cli.report import _parse_tool_meta

    out = _parse_tool_meta(
        [
            "protein_hunter=pool_pre_filtered:true;source_csv:summary_high_iptm.csv",
            "rfd3=notes:custom_note",
        ]
    )
    assert out["protein_hunter"]["pool_pre_filtered"] is True
    assert out["protein_hunter"]["source_csv"] == "summary_high_iptm.csv"
    assert out["rfd3"]["notes"] == "custom_note"


def test_parse_tool_meta_empty_input():
    from binder_comparison.cli.report import _parse_tool_meta

    assert _parse_tool_meta(None) == {}
    assert _parse_tool_meta([]) == {}


def test_parse_tool_meta_skips_malformed_pieces():
    from binder_comparison.cli.report import _parse_tool_meta

    out = _parse_tool_meta(["badspec_no_equals", "ok=key:val;malformed_no_colon"])
    # malformed spec without '=' is dropped; the well-formed one keeps key:val and drops malformed_no_colon
    assert "ok" in out
    assert out["ok"] == {"key": "val"}


# --- _collect_provenance auto-detection --------------------------------------


def test_collect_provenance_auto_populates_timestamp_and_cli_args():
    """git_sha presence depends on env (skipped if no git in PATH or no repo)."""
    import argparse

    from binder_comparison.cli.report import _collect_provenance

    prov = _collect_provenance(argparse.Namespace(engine_versions=None))
    assert "run_timestamp_utc" in prov
    assert "cli_args" in prov
    assert isinstance(prov["cli_args"], list)
    assert "evaluator_version" in prov  # at minimum "unknown"
