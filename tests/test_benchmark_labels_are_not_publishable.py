"""Benchmark label rows must never become committable on this public repo.

2.0 Part Y adds `Evaluator/benchmarks/<pool>/`, where the public repo carries
only what is needed to AUDIT a result — a per-pool MANIFEST.json — while the
label rows live in a private store resolved by checksum.

Publishing them is irreversible, so this asserts the `.gitignore` rules rather
than trusting that they were written correctly. It fails closed: every data
format is checked, and the two metadata files are checked to be *trackable* so
a future over-broad rule cannot quietly ignore the manifest and break the
loader instead.
"""

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
POOL = "Evaluator/benchmarks/cao2022"

MUST_BE_IGNORED = [
    f"{POOL}/labels.csv",
    f"{POOL}/labels.tsv",
    f"{POOL}/labels.parquet",
    f"{POOL}/pae.npy",
    f"{POOL}/rows.npz",
    f"{POOL}/rows.pkl",
    f"{POOL}/anything.json",
]

MUST_BE_TRACKABLE = [
    f"{POOL}/MANIFEST.json",
    "Evaluator/benchmarks/SCHEMA.json",
]


def _is_ignored(path: str) -> bool:
    """git check-ignore exits 0 when the path IS ignored, 1 when it is not.

    --no-index so this answers the question for paths that do not exist yet,
    which is the whole point: the guard must precede the directory.
    """
    return (
        subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", path],
            cwd=REPO,
            capture_output=True,
        ).returncode
        == 0
    )


@pytest.mark.parametrize("path", MUST_BE_IGNORED)
def test_label_data_is_ignored(path):
    assert _is_ignored(path), (
        f"{path} is NOT gitignored — benchmark label rows would be committable "
        "on a public repo. See the 'Benchmark label registry' block in .gitignore."
    )


@pytest.mark.parametrize("path", MUST_BE_TRACKABLE)
def test_registry_metadata_stays_trackable(path):
    assert not _is_ignored(path), (
        f"{path} is gitignored, but the public repo must carry it — the loader "
        "resolves a pool by the checksum recorded there."
    )
