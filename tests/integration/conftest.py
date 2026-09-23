"""Put the bundled Evaluator package on sys.path (same as tests/binder_comparison)."""

import sys
from pathlib import Path

_EVALUATOR = Path(__file__).resolve().parents[2] / "Evaluator"
if str(_EVALUATOR) not in sys.path:
    sys.path.insert(0, str(_EVALUATOR))

# ...and this directory, so the tests can import their sibling pool builder.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
