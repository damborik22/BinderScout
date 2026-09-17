"""Binder Design Comparison Tool.

Compare binder sequences from BindCraft, BoltzGen, Mosaic, PXDesign,
Proteina-Complexa, and Protein Hunter using Boltz-2 standardised refolding
(plus AF3 and ESMFold2).
"""

# Read from the installed package metadata rather than repeated as a literal:
# this file, `main.py`'s `--version` and `pyproject.toml` previously carried
# three independent copies of the number, which is three chances to drift.
# `pyproject.toml` is now the only place it is written.
try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("binder-comparison")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"
