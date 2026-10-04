"""Canonical refolding exceptions.

``PartialRefoldFailure`` carries the one distinction the CLI's exit code has to make:
**3** means "some designs folded, their rows are on disk, re-run these indices", as
opposed to **1**, "this environment is broken". ``binder_comparison.main`` maps it.

The standalone ``Evaluator/scripts/refold_*.py`` scripts each define a class of the same
name, because they are required to run in envs where ``binder_comparison`` is not
importable. The runners therefore catch the script's class and re-raise this one, so the
CLI has a single class to catch whichever way the scripts were loaded.
"""

from __future__ import annotations


class PartialRefoldFailure(RuntimeError):
    """Some designs in the batch failed; the ones that folded are in the output CSV."""
