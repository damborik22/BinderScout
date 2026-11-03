"""Opt-in storage of the per-pair predicted-error DISTRIBUTION (``--save-pae-bins``).

The refold runners save only the EXPECTED PAE: ``E[e] = sum_b p_b * c_b`` over the
error bins. The engines compute their own ipTM from the whole distribution,
``E[1/(1+(e/d0)^2)]``, and because the kernel is convex in ``e`` the kernel of the
mean is not the mean of the kernel -- our point-PAE ipTM runs below the engine's own
and the gap cannot be recovered afterwards from the expected PAE alone. Keeping the
bin probabilities makes it recoverable (``scoring.compute_iptm_from_pae_bins``).

Default OFF. Nothing here runs, no file is written and no CSV column is added unless
the flag is passed. NOT used for ranking.

File layout (``<design>_pae_bins.npz``, ``numpy.savez_compressed``):
    probs        float16 [N, N, n_bins]  bin probabilities, same token ordering as the
                                         design's ``_pae.npy`` (Boltz-2 binder|target,
                                         ESMFold2 target|binder)
    bin_centres  float32 [n_bins]        error value (Angstrom) each bin stands for

Size, 300-token complex, 64 bins: 300*300*64 float16 values = 11.52 MB before
compression (``savez_compressed`` shrinks it; peaked distributions compress well, but
no real engine output has been measured yet -- GPU validation is pending).
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

PAE_BINS_COLUMN = "pae_bins_file"

# How far the expected value of the stored distribution may sit from the PAE the runner
# saved for the same design (mean absolute difference, Angstrom). The two come from one
# set of logits, so a healthy run differs only by float16 rounding and, for Boltz-2
# (which needs a second forward pass), GPU run-to-run noise. A wrong bin-centre
# convention, a transposed token order or a different diffusion sample misses by whole
# Angstroms. Loose enough for noise, tight enough for those.
PAE_BINS_CHECK_MEAN_ABS = 0.25


class PaeBinsMismatch(ValueError):
    """The distribution handed over does not reproduce the PAE saved for the same design."""


def softmax(logits: np.ndarray, axis: int = -1) -> np.ndarray:
    """Numerically stable softmax in float32."""
    x = np.asarray(logits, dtype=np.float32)
    x = x - x.max(axis=axis, keepdims=True)
    e = np.exp(x)
    return e / e.sum(axis=axis, keepdims=True)


def uniform_bin_centres(n_bins: int, max_error: float = 32.0) -> np.ndarray:
    """Centres of ``n_bins`` equal bins on ``[0, max_error]`` (Boltz-2 and ESMFold2 convention)."""
    width = max_error / n_bins
    return ((np.arange(n_bins) + 0.5) * width).astype(np.float32)


def expected_pae_from_bins(probs: np.ndarray, bin_centres: np.ndarray) -> np.ndarray:
    """E[e] per pair from bin probabilities, ``[N, N]`` in Angstrom."""
    return np.asarray(probs, dtype=np.float32) @ np.asarray(bin_centres, dtype=np.float32)


def bins_path_for(pae_path: str | Path) -> Path:
    """``foo_pae.npy`` -> ``foo_pae_bins.npz``, next to the PAE file."""
    p = Path(pae_path)
    return p.with_name(p.stem + "_bins.npz")


def save_pae_bins(
    path: str | Path,
    probs: np.ndarray,
    bin_centres: np.ndarray,
    *,
    expected_pae: np.ndarray | None = None,
    mean_abs_tol: float = PAE_BINS_CHECK_MEAN_ABS,
) -> Path:
    """Write the compressed ``.npz``; refuse if it does not agree with *expected_pae*.

    Raises:
        ValueError:       *probs* is not ``[N, N, n_bins]`` matching *bin_centres*.
        PaeBinsMismatch:  *expected_pae* is given and the mean absolute difference from
                          the distribution's own expectation exceeds *mean_abs_tol*.
                          A file that cannot be reconciled with the PAE it sits next to
                          is worse than no file: it would be trusted.
    """
    probs = np.asarray(probs)
    centres = np.asarray(bin_centres, dtype=np.float32)
    if probs.ndim != 3 or probs.shape[0] != probs.shape[1] or probs.shape[2] != centres.shape[0]:
        raise ValueError(f"probs must be [N, N, {centres.shape[0]}] to match bin_centres, got {probs.shape}")
    if expected_pae is not None:
        pae = np.asarray(expected_pae, dtype=np.float32)
        if pae.shape != probs.shape[:2]:
            raise PaeBinsMismatch(f"PAE is {pae.shape} but the bin probabilities are for {probs.shape[:2]} tokens")
        diff = float(np.abs(expected_pae_from_bins(probs, centres) - pae).mean())
        if not diff <= mean_abs_tol:  # also catches NaN
            raise PaeBinsMismatch(
                f"expected value of the bin distribution differs from the saved PAE by {diff:.3f} A "
                f"(mean abs; limit {mean_abs_tol}) -- bin centres, token order or sample do not match"
            )
    path = Path(path)
    np.savez_compressed(path, probs=probs.astype(np.float16), bin_centres=centres)
    return path


def load_pae_bins(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(probs float32 [N, N, n_bins], bin_centres float32 [n_bins])``."""
    with np.load(path) as z:
        return z["probs"].astype(np.float32), z["bin_centres"].astype(np.float32)


def assert_csv_can_take_pae_bins(csv_path: str | Path) -> None:
    """Refuse to append ``pae_bins_file`` rows under a header that does not have the column.

    The refold CSVs are append-mode (``--resume`` depends on it). Rows carrying one more
    field than the header would shift under the wrong column names.
    """
    p = Path(csv_path)
    if not p.exists() or p.stat().st_size == 0:
        return
    with p.open(newline="") as f:
        header = next(csv.reader(f), [])
    if PAE_BINS_COLUMN not in header:
        raise ValueError(
            f"--save-pae-bins: {p} already has rows without a '{PAE_BINS_COLUMN}' column, and appending "
            f"rows that carry one would misalign it. Write to a fresh output directory/CSV, or run "
            f"without --save-pae-bins."
        )
