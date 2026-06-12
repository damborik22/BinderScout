"""Put the bundled Evaluator package (Evaluator/binder_comparison) on sys.path.

The package is normally pip-installed into the binder-eval conda env; for repo-root
pytest we add its parent dir so `import binder_comparison...` resolves.
"""

import sys
from pathlib import Path

_EVALUATOR = Path(__file__).resolve().parents[2] / "Evaluator"
if str(_EVALUATOR) not in sys.path:
    sys.path.insert(0, str(_EVALUATOR))
