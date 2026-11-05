"""CLI for the AF3-replacement benchmark: join a merged refold CSV to labels and compare panels.

The registry verifies a checksum against the committed manifest, so a synthetic store cannot satisfy it;
``benchmarks.load_labels`` is stubbed here. Everything below is synthetic data.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from binder_comparison import benchmarks
from binder_comparison.comparison import panel_benchmark as pb

SCRIPT = Path(__file__).resolve().parents[2] / "Evaluator" / "scripts" / "panel_benchmark.py"
BASE = "x,y,z"

# t1 separates perfectly (AUC 1.0). t2 binders 0.9, 0.4 vs non-binders 0.5, 0.1: 3 of 4 pairs -> AUC 0.75.
# Macro over the two targets is therefore 0.875. `w` is a perfect t2 ranking (a better candidate).
_MEAN = {
    "t1": ([0.9, 0.8, 0.7], [0.3, 0.2, 0.1]),
    "t2": ([0.9, 0.4], [0.5, 0.1]),
}
_W_T2 = ([0.9, 0.8], [0.2, 0.1])


def _load_cli():
    spec = importlib.util.spec_from_file_location("panel_benchmark_cli_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows():
    out = []
    for t, (pos, neg) in _MEAN.items():
        wpos, wneg = _W_T2 if t == "t2" else (pos, neg)
        for i, (m, w, b) in enumerate(
            [(m, w, True) for m, w in zip(pos, wpos, strict=True)]
            + [(m, w, False) for m, w in zip(neg, wneg, strict=True)]
        ):
            out.append({"id": f"{t}_{i}", "target": t, "binds": b, "m": m, "w": w})
    return out


def _merged(extra=None) -> pd.DataFrame:
    rows = [
        {"id": r["id"], "x": r["m"] + 0.1, "y": r["m"], "z": r["m"] - 0.1, "w": r["w"], "v": r["m"]} for r in _rows()
    ]
    rows += extra or []
    return pd.DataFrame(rows)


def _pool(extra=None) -> pd.DataFrame:
    rows = [
        {
            "id": r["id"],
            "target": r["target"],
            "binds": int(r["binds"]),
            "outcome": "bound" if r["binds"] else "not_bound",
        }
        for r in _rows()
    ]
    rows += [
        # A design that was never tested: a huge score would flip t1's AUC if it were read as a negative.
        {"id": "t1_untested", "target": "t1", "binds": 0, "outcome": "not_tested"},
        {"id": "t1_excl", "target": "t1", "binds": 0, "outcome": "excluded:aggregator"},
    ]
    return pd.DataFrame(rows + (extra or []))


@pytest.fixture
def run(tmp_path, monkeypatch):
    cli = _load_cli()

    def _run(merged=None, pool=None, *panels, extra_args=(), labels_csv=None):
        merged_path = tmp_path / "merged.csv"
        (merged if merged is not None else _merged()).to_csv(merged_path, index=False)
        monkeypatch.setattr(
            benchmarks,
            "load_labels",
            (lambda name: pool if pool is not None else _pool())
            if labels_csv is None
            else (lambda name: (_ for _ in ()).throw(AssertionError("registry must not be read"))),
        )
        out = tmp_path / "out.json"
        argv = ["--merged", str(merged_path), "--out", str(out)]
        for p in panels or (BASE,):
            argv += ["--panel", p]
        argv += list(extra_args)
        if labels_csv is not None:
            argv += ["--labels-csv", str(labels_csv)]
        rc = cli.main(argv)
        return rc, (json.loads(out.read_text(), parse_constant=_no_nan) if out.exists() else None)

    return _run


def _no_nan(token):
    raise AssertionError(f"JSON holds {token}, which is not valid JSON")


def test_baseline_macro_and_median_auc_and_unmeasured_rows_are_absent(run, capsys):
    merged = _merged(
        extra=[
            # Scored far above every binder; read as a negative it would drag t1's AUC below 1.0.
            {"id": "t1_untested", "x": 9.0, "y": 9.0, "z": 9.0, "w": 9.0, "v": 9.0},
            {"id": "t1_excl", "x": 9.0, "y": 9.0, "z": 9.0, "w": 9.0, "v": 9.0},
        ]
    )
    rc, res = run(merged)
    assert rc == 0
    panel = res["panels"][BASE]
    assert panel["per_target_auc"] == {"t1": pytest.approx(1.0), "t2": pytest.approx(0.75)}
    assert panel["macro_auc"] == pytest.approx(0.875)
    assert panel["median_auc"] == pytest.approx(0.875)
    assert panel["n_per_target"] == {"t1": 6, "t2": 4}
    assert res["n_dropped_unmeasured"] == 2
    assert "t1" in capsys.readouterr().out  # the joined n per target is printed


def test_candidate_is_scored_against_the_baseline_with_the_candidate_first(run):
    rc, res = run(None, None, BASE, "w,w")
    assert rc == 0
    cand = res["panels"]["w,w"]
    assert "paired_bootstrap_diff" not in res["panels"][BASE]
    d = cand["paired_bootstrap_diff"]
    # candidate minus baseline: t2 goes 0.75 -> 1.0, t1 stays 1.0
    assert d["per_target_diff"]["t2"] == pytest.approx(0.25)
    assert d["macro_diff"] == pytest.approx(0.125)
    assert d["coverage"]["t1"] == {"n_total": 6, "n_scored": 6, "n_dropped_unscored": 0}
    assert cand["passes"]["ok"] is True
    assert cand["passes"]["failed_clauses"] == []
    # and the same sign convention when the candidate is the worse one
    rc, res = run(None, None, "w,w", BASE)
    assert res["panels"][BASE]["paired_bootstrap_diff"]["macro_diff"] == pytest.approx(-0.125)


def test_a_candidate_with_blank_values_flows_to_clause_d_not_to_a_refusal(run):
    merged = _merged()
    merged.loc[merged["id"] == "t2_1", "v"] = np.nan
    rc, res = run(merged, None, BASE, "v,v")
    assert rc == 0
    verdict = res["panels"]["v,v"]["passes"]
    assert verdict["ok"] is False
    assert pb.CLAUSE_D in verdict["failed_clauses"]
    assert res["panels"]["v,v"]["paired_bootstrap_diff"]["coverage"]["t2"]["n_dropped_unscored"] == 1


def test_blank_in_the_baseline_panel_is_refused_naming_the_count(run, tmp_path, capsys):
    merged = _merged()
    merged.loc[merged["id"].isin(["t1_0", "t2_1"]), "y"] = np.nan
    rc, res = run(merged)
    assert rc == 2
    assert res is None
    err = capsys.readouterr().err
    assert "2" in err and "y" in err


def test_a_merged_id_with_no_label_row_is_refused_naming_the_count(run, capsys):
    merged = _merged(
        extra=[{"id": "ghost_1", "x": 0.5, "y": 0.5, "z": 0.5}, {"id": "ghost_2", "x": 0.5, "y": 0.5, "z": 0.5}]
    )
    rc, res = run(merged)
    assert rc == 2
    assert res is None
    assert "2 merged id" in capsys.readouterr().err


def test_a_panel_column_absent_from_the_merged_csv_is_refused(run, capsys):
    rc, res = run(None, None, BASE, "nope,w")
    assert rc == 2
    assert res is None
    assert "nope" in capsys.readouterr().err


def test_labels_csv_replaces_the_registry_and_null_labels_are_dropped_and_counted(run, tmp_path, capsys):
    labels = pd.DataFrame([{"id": r["id"], "target": r["target"], "hit": int(r["binds"])} for r in _rows()])
    labels["hit"] = labels["hit"].astype(float)
    labels.loc[labels["id"] == "t1_0", "hit"] = np.nan  # an unlabelled design: dropped, never a negative
    path = tmp_path / "labels.csv"
    labels.to_csv(path, index=False)
    rc, res = run(None, None, extra_args=["--label-column", "hit"], labels_csv=path)
    assert rc == 0
    assert res["n_dropped_null_label"] == 1
    assert res["panels"][BASE]["n_per_target"] == {"t1": 5, "t2": 4}
    # t1 without its top binder: 2 binders over 3 non-binders, still separated
    assert res["panels"][BASE]["per_target_auc"]["t1"] == pytest.approx(1.0)
    assert "1 design" in capsys.readouterr().out


def test_labels_csv_with_values_that_are_not_binary_is_refused(run, tmp_path):
    labels = pd.DataFrame([{"id": r["id"], "target": r["target"], "binds": 2} for r in _rows()])
    path = tmp_path / "labels.csv"
    labels.to_csv(path, index=False)
    rc, _ = run(labels_csv=path)
    assert rc == 2


def test_a_merged_target_column_joins_on_id_and_target_so_a_design_screened_twice_is_not_doubled(run):
    # One design id appears under both targets in the labels; only the merged target says which row is meant.
    pool = _pool(extra=[{"id": "t1_0", "target": "t2", "binds": 0, "outcome": "not_bound"}])
    merged = _merged()
    merged["target"] = merged["id"].str[:2]
    rc, res = run(merged, pool)
    assert rc == 0
    assert res["panels"][BASE]["n_per_target"] == {"t1": 6, "t2": 4}
    assert res["panels"][BASE]["macro_auc"] == pytest.approx(0.875)
    # without the merged target the same id is ambiguous and the join is refused rather than doubled
    rc, _ = run(_merged(), pool)
    assert rc == 2


def test_a_one_class_target_has_no_auc_and_the_output_is_still_valid_json(run):
    # t3 has binders only: no AUC exists there. It must come out as null (run() rejects a bare NaN),
    # and the macro average must be taken over the targets that do have one.
    ids = ["t3_0", "t3_1"]
    pool = _pool(extra=[{"id": i, "target": "t3", "binds": 1, "outcome": "bound"} for i in ids])
    merged = _merged(extra=[{"id": i, "x": 0.5, "y": 0.5, "z": 0.5, "w": 0.5, "v": 0.5} for i in ids])
    rc, res = run(merged, pool, BASE, "w,w")
    assert rc == 0
    assert res["panels"][BASE]["per_target_auc"]["t3"] is None
    assert res["panels"][BASE]["macro_auc"] == pytest.approx(0.875)
    assert res["panels"]["w,w"]["paired_bootstrap_diff"]["per_target_diff"]["t3"] is None
