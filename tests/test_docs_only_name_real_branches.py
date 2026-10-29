"""No tracked document may send a reader to a branch that does not exist.

`aarch64` has never been a branch on this remote — aarch64 support is
`install/install_aarch.sh`, on `master`, next to the x86_64 installer. The docs said
otherwise in several places at once:

* README advertised `git clone -b aarch64 …`, which fails outright.
* CONTRIBUTING.md's "Branch structure" table listed `aarch64` as a platform branch
  "periodically rebased from master", and called `master` x86_64-only.
* CLAUDE.md had it twice: a "Machines and platforms" table whose first column was
  headed *Branch*, and a "Git and branching" section naming a "Platform branch".

Three of those four survived the pass that fixed the first, which is the argument for a
test rather than another careful read. A contributor who follows any of them gets
`error: pathspec 'aarch64' did not match any file(s) known to git` and cannot tell
whether the branch was deleted or they mistyped it.

Deliberately narrow, in two ways, because the obvious broad version does not work:

* It reads git COMMANDS, not prose about branches. "The `else` branch" of an
  `if` statement, "the `all` branch" of a case — these are branches in the other sense,
  and a pattern matching ``` `x` branch ``` flags them all. The second test below is the
  one exception: it hunts the specific claim that recurred, and only that one.
* A line naming another project's repository is skipped. Upstream branches are real and
  not ours to validate: Proteina-Complexa's `dev`, foundry's `production`.

The branch list is hardcoded. `git branch -r` is no use here — CI checks out a single
branch, so the other remote-tracking refs are absent and every name would read as
unknown. Update BRANCHES when a line is added or retired; that edit is the moment to
check the docs too.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The real branches on origin, as of 1.0.8.
BRANCHES = {"master", "v2.0.x"}

# Placeholders and generic git examples, not claims about this repo.
EXAMPLES = {"-b", "my-feature", "feature", "branch-name", "your-branch", "HEAD", "."}

# Unambiguous: each of these tells the reader to put a working tree on that ref.
CHECKOUT = (
    re.compile(r"git\s+clone[^\n`]*?-b\s+(?P<name>[A-Za-z0-9._/-]+)"),
    re.compile(r"git\s+checkout\s+(?:-{1,2}\S+\s+)*(?P<name>[A-Za-z0-9._/-]+)"),
    re.compile(r"git\s+switch\s+(?:-{1,2}\S+\s+)*(?P<name>[A-Za-z0-9._/-]+)"),
)

# The claim that recurred. Prose, so it needs the negation guard below.
AARCH_BRANCH = re.compile(r"(?:`aarch64`|\baarch64\b)\s+branch\b|\bbranch\s+`?aarch64`?")

# A sentence saying the branch does NOT exist is the correction, not the error. The
# negation can sit on either side: "There is no `aarch64` branch" puts it before,
# "`git clone -b aarch64 …`, which fails: no such branch exists" puts it after.
NEGATION = re.compile(r"\b(no|not|never|nonexistent|non-existent|neither|fails|does not exist)\b", re.I)

# Another project's repository on the same line: its branches are real and not ours.
FOREIGN = re.compile(r"github\.com/(?!damborik22/)", re.I)


def _negated(text: str, start: int, end: int) -> bool:
    return bool(NEGATION.search(text[max(0, start - 90) : start]) or NEGATION.search(text[end : end + 90]))


def _line_of(text: str, pos: int) -> str:
    return text[text.rfind("\n", 0, pos) + 1 : (text.find("\n", pos) + 1 or len(text)) - 1]


def _docs() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split()
    return [
        REPO / p
        for p in out
        # docs/data: archived captures. INVESTIGATION_*: provenance records that state
        # which branch the code was on at the time, which is history, not an instruction.
        if not p.startswith("docs/data/") and "INVESTIGATION_" not in p
    ]


def test_no_document_tells_you_to_check_out_a_branch_that_does_not_exist():
    offenders = []
    for path in _docs():
        text = path.read_text(encoding="utf-8")
        for pattern in CHECKOUT:
            for match in pattern.finditer(text):
                name = match.group("name")
                if name in BRANCHES or name in EXAMPLES or "<" in name or "{" in name:
                    continue
                if FOREIGN.search(_line_of(text, match.start())) or _negated(text, match.start(), match.end()):
                    continue
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.relative_to(REPO)}:{line}: checkout of {name!r} — real: {sorted(BRANCHES)}")
    assert not offenders, "documents tell the reader to check out branches that do not exist:\n  " + "\n  ".join(
        offenders
    )


def test_no_document_claims_this_repo_has_an_aarch64_branch():
    offenders = []
    for path in _docs():
        text = path.read_text(encoding="utf-8")
        for match in AARCH_BRANCH.finditer(text):
            if FOREIGN.search(_line_of(text, match.start())) or _negated(text, match.start(), match.end()):
                continue
            line = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(REPO)}:{line}: {_line_of(text, match.start()).strip()[:110]}")
    assert not offenders, (
        "documents describe an `aarch64` branch; there is none — aarch64 support is "
        "install/install_aarch.sh on master:\n  " + "\n  ".join(offenders)
    )


def test_the_negation_guard_does_not_swallow_a_real_claim():
    """The guard skips negated sentences; it must not skip an actual instruction.

    Without this, a stray "not" near a real claim would silence the finding and both
    tests above would go quietly vacuous.
    """
    denial = "There is no separate `aarch64` branch — support lives on master."
    claim = "Platform work happens on the `aarch64` branch, rebased from master."

    m = AARCH_BRANCH.search(denial)
    assert m and _negated(denial, m.start(), m.end()), "a sentence denying the branch should be skipped"

    m = AARCH_BRANCH.search(claim)
    assert m and not _negated(claim, m.start(), m.end()), "a sentence asserting the branch must be caught"
