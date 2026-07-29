"""Every `binder-compare` flag a skill prescribes must exist on that subcommand.

The skills under `.claude/skills/` are agent INSTRUCTIONS — they get executed, not
read. After Part U removed `--rank-by` and `--screen-metric` (4fc3690), two skill
files still told an agent to run
`binder-compare report … --rank-by two_stage`, which argparse now rejects with
exit 2. Nothing caught it, because prose is not tested.

This walks every fenced/inline `binder-compare <cmd> …` line in the skills and
checks each long flag against the real parser, so documentation cannot outlive
the flag it describes.
"""

import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "Evaluator"))

_SKILLS = _ROOT / ".claude" / "skills"

# `--<tool>` and friends are placeholders, not flags.
_PLACEHOLDER = re.compile(r"[<>{}$]")
_CMD = re.compile(r"binder-compare\s+([a-z0-9-]+)((?:\s+\S+)*)")
_FLAG = re.compile(r"(?<![\w-])--[a-z0-9][a-z0-9-]*")


def _subparsers() -> dict[str, set[str]]:
    """Map subcommand name → its accepted long option strings."""
    import argparse

    from binder_comparison import main as bc_main

    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="command")
    for name in dir(bc_main):
        mod = getattr(bc_main, name)
        if hasattr(mod, "add_parser") and getattr(mod, "__name__", "").startswith("binder_comparison.cli"):
            mod.add_parser(subs)
    return {
        cmd: {opt for action in sub._actions for opt in action.option_strings if opt.startswith("--")}
        for cmd, sub in subs.choices.items()
    }


def _prescribed_flags():
    """Yield (file, subcommand, flag) for every binder-compare invocation in the skills."""
    for md in sorted(_SKILLS.rglob("*.md")):
        for line in md.read_text().splitlines():
            for cmd, rest in _CMD.findall(line):
                for flag in _FLAG.findall(rest):
                    if not _PLACEHOLDER.search(flag):
                        yield md.relative_to(_ROOT), cmd, flag


@pytest.mark.skipif(not _SKILLS.exists(), reason="no .claude/skills in this checkout")
def test_every_flag_a_skill_prescribes_exists():
    known = _subparsers()
    bad = []
    for md, cmd, flag in _prescribed_flags():
        if cmd not in known:
            continue  # a subcommand this checkout does not ship — covered below
        if flag not in known[cmd]:
            bad.append(f"{md}: `binder-compare {cmd} {flag}` — not a flag of `{cmd}`")
    assert not bad, "skills prescribe flags that argparse rejects:\n  " + "\n  ".join(bad)


@pytest.mark.skipif(not _SKILLS.exists(), reason="no .claude/skills in this checkout")
def test_every_subcommand_a_skill_prescribes_exists():
    known = _subparsers()
    bad = {
        f"{md}: `binder-compare {cmd}`" for md, cmd, _flag in _prescribed_flags() if cmd not in known and "-" not in cmd
    }
    assert not bad, "skills prescribe subcommands that do not exist:\n  " + "\n  ".join(sorted(bad))
