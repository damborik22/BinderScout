"""Schema: the second slot's per-engine fields, AF3 unchanged and Protenix added alongside.

Everything is pinned as literals so a registry change cannot make these pass vacuously.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Evaluator"))
from binder_comparison.core.schema import LOWER_IS_BETTER, ZSCORE_METRICS, StandardisedMetrics

_AF3_FIELDS = [
    "af3_iptm",
    "af3_ptm",
    "af3_ranking_score",
    "af3_plddt_binder_mean",
    "af3_plddt_binder_min",
    "af3_plddt_target_mean",
    "af3_pae_bt",
    "af3_pae_tb",
    "af3_pae_bb",
    "af3_bt_ipsae",
    "af3_tb_ipsae",
    "af3_ipsae_min",
]
_PROTENIX_FIELDS = [f.replace("af3_", "protenix_", 1) for f in _AF3_FIELDS]


def test_af3_fields_are_kept_in_order():
    fields = list(StandardisedMetrics.__dataclass_fields__)
    start = fields.index("af3_iptm")
    assert fields[start : start + len(_AF3_FIELDS)] == _AF3_FIELDS


def test_protenix_fields_mirror_af3_and_follow_them():
    fields = list(StandardisedMetrics.__dataclass_fields__)
    start = fields.index("protenix_iptm")
    assert fields[start : start + len(_PROTENIX_FIELDS)] == _PROTENIX_FIELDS
    assert fields.index("af3_ipsae_min") < start


def test_zscore_metrics_gain_protenix_without_touching_af3():
    af3 = [m for m in ZSCORE_METRICS if m.startswith("af3_")]
    assert af3 == [
        "af3_iptm",
        "af3_ptm",
        "af3_ranking_score",
        "af3_plddt_binder_mean",
        "af3_bt_ipsae",
        "af3_tb_ipsae",
        "af3_ipsae_min",
        "af3_pae_iptm",
    ]
    assert [m for m in ZSCORE_METRICS if m.startswith("protenix_")] == [m.replace("af3_", "protenix_") for m in af3]


def test_lower_is_better_gains_protenix_pae_blocks():
    assert {m for m in LOWER_IS_BETTER if m.startswith("af3_")} == {"af3_pae_bt", "af3_pae_tb", "af3_pae_bb"}
    assert {m for m in LOWER_IS_BETTER if m.startswith("protenix_")} == {
        "protenix_pae_bt",
        "protenix_pae_tb",
        "protenix_pae_bb",
    }
