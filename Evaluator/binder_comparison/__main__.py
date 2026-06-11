"""Enable `python -m binder_comparison`.

The ``run`` subcommand (and others) launch nested steps via
``python -m binder_comparison ...``; without this module that invocation fails
with "No module named binder_comparison.__main__".
"""

from binder_comparison.main import main

if __name__ == "__main__":
    main()
