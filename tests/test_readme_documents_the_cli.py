"""The README's subcommand table must list exactly what `binder-compare` ships.

Fifteen of the twenty-two subcommands had no human-facing documentation at all:
`analyze-target`, `mature`, `monomer`, `affinity` and `wetlab` existed only inside
`.claude/skills/` — agent instructions, not a manual — and `prefilter`, `qc-annotate`,
`epitope`, `epitope-map`, `beta-check`, `diversity`, `hits` and `validate` were
documented nowhere. Someone driving the pipeline from a terminal could not discover
them without reading `main.py`.

A table fixes that once; this test keeps it fixed. Drift runs both ways and both are
wrong: a new subcommand nobody documents is invisible, and a documented subcommand
that no longer exists sends a reader to an argparse error.
"""

import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "Evaluator"))

_README = _ROOT / "README.md"
_HEADING = "#### All `binder-compare` subcommands"
# Table rows naming a subcommand: `| `extract` | … |`. Section-header rows
# (`| **Refolding** | |`) carry no code span and are skipped.
_ROW = re.compile(r"^\|\s*`([a-z0-9-]+)`\s*\|", re.M)


def _shipped_subcommands() -> set[str]:
    """Every subcommand `binder-compare --help` offers, from the real parser."""
    import argparse

    from binder_comparison import main as bc_main

    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="command")
    for name in dir(bc_main):
        mod = getattr(bc_main, name)
        if hasattr(mod, "add_parser") and getattr(mod, "__name__", "").startswith("binder_comparison.cli"):
            mod.add_parser(subs)
    return set(subs.choices)


def _documented_subcommands() -> set[str]:
    text = _README.read_text()
    start = text.index(_HEADING)
    rest = text[start + len(_HEADING) :]
    # The table ends at the next heading of the same or higher level.
    end = re.search(r"^#{1,4} ", rest, re.M)
    return set(_ROW.findall(rest[: end.start()] if end else rest))


def test_the_table_exists_and_is_not_empty():
    """Guard the parser so the real assertions below cannot pass vacuously."""
    assert _HEADING in _README.read_text(), "the subcommand table was removed"
    assert len(_documented_subcommands()) > 5


def test_every_shipped_subcommand_is_documented():
    missing = sorted(_shipped_subcommands() - _documented_subcommands())
    assert not missing, (
        f"binder-compare ships {missing} but README.md's subcommand table does not "
        f"list them — they are undiscoverable outside .claude/skills/ and main.py."
    )


def test_the_table_invents_nothing():
    extra = sorted(_documented_subcommands() - _shipped_subcommands())
    assert not extra, (
        f"README.md documents {extra}, which argparse does not accept — a reader "
        f"following the table gets 'invalid choice' and exit 2."
    )


# --- Evaluator/evaluate.sh ----------------------------------------------------

_EVALUATE_SH = _ROOT / "Evaluator" / "evaluate.sh"
_EVALUATE_HEADING = "#### `Evaluator/evaluate.sh` — the orchestrator's own flags"
# Self-documenting flags, excluded from the table on purpose.
_SELF_EVIDENT = {"-h", "--help", "-o"}


def _evaluate_sh_flags() -> set[str]:
    """Flags evaluate.sh's parse loop has a `case` arm for — the real acceptance list."""
    lines = _EVALUATE_SH.read_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("while [[ $# -gt 0 ]]"))
    end = next(i for i, ln in enumerate(lines[start:], start) if ln.strip() == "done")
    flags: set[str] = set()
    for line in lines[start + 1 : end]:
        if line.lstrip().startswith("#"):
            continue
        m = re.match(r"^\s*([^\s)(]+(?:\|[^\s)(]+)*)\)", line)
        if m:
            flags.update(tok for tok in m.group(1).split("|") if tok.startswith("-"))
    return flags - _SELF_EVIDENT


def _evaluate_sh_documented() -> set[str]:
    text = _README.read_text()
    start = text.index(_EVALUATE_HEADING)
    rest = text[start + len(_EVALUATE_HEADING) :]
    end = re.search(r"^#{1,4} ", rest, re.M)
    return set(re.findall(r"`(--[a-z0-9-]+)", rest[: end.start()] if end else rest))


def test_the_evaluate_sh_table_exists():
    assert _EVALUATE_HEADING in _README.read_text()
    assert len(_evaluate_sh_documented()) > 5


def test_every_evaluate_sh_flag_is_documented():
    """`run_evaluate.sh` wraps this script, so it is what operators actually run — and
    8 of its flags appeared nowhere in the README, including the cross-engine gate."""
    missing = sorted(_evaluate_sh_flags() - _evaluate_sh_documented())
    assert not missing, f"Evaluator/evaluate.sh accepts {missing} but README.md does not document them."


def test_the_evaluate_sh_table_invents_nothing():
    extra = sorted(_evaluate_sh_documented() - _evaluate_sh_flags())
    assert not extra, (
        f"README.md documents {extra} for evaluate.sh, which its parser rejects with 'Unknown argument' and exit 1."
    )
