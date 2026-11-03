"""Documentation and tests must name machines by architecture, never by alias.

The repository is public. CLAUDE.md states the rule (no cluster names, no fleet
box aliases, no institution storage pointers), but its own text and several docs
and test fixtures broke it: they named the local cluster, listed the box aliases
in the very sentence that forbade them, and pointed at a storage path on the
institution's file share. The identifier test in
``test_no_infrastructure_identifiers_in_tree.py`` derives IPs, fingerprints and
*this* box's account from the machine running it; it cannot know the names of
the OTHER boxes, which is the gap this closes for prose and fixtures.

The patterns are assembled from fragments on purpose. A test that spelled the
names out would be a tracked file containing exactly what it bans.

Scope is documentation and tests. Installer, configurator and evaluator source
are checked by their own lanes; widening this to them is a one-line change to
``_roots`` once they are clean.
"""

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_CLUSTER = "cl" + "ara"
_PATTERNS = {
    "cluster name": re.compile(rf"\b{_CLUSTER}\b", re.I),
    "fleet box alias": re.compile(r"\bbm[0-9]\b", re.I),
    "box hostname": re.compile(r"(?<![/\w])bindmaster" + r"[0-9]\b", re.I),
    "institution share": re.compile(r"\b" + "MU" + "NI" + r"\b"),
    "institution storage path": re.compile(r"Project-01-" + "BIND" + "MASTER"),
    "cluster account / node": re.compile("dambo" + r"dav|\b(?:h200|l40s)-0[0-9]\b|ci" + "irc|cv" + "ut"),
}

# Planning records are being decided separately and are not edited here.
_PLANNING = ("PLAN_", "INVESTIGATION_", "REPORT_", "MORNING_DECISIONS", "NEXT_STAGES")


def _tracked_text_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout.splitlines()
    return [REPO / p for p in out]


def _in_scope(path: Path) -> bool:
    rel = path.relative_to(REPO).as_posix()
    if rel.startswith("docs/"):
        return not rel.split("/")[-1].startswith(_PLANNING) and rel.endswith((".md", ".html"))
    if rel.startswith(("tests/", "Evaluator/docs/")):
        return rel.endswith((".md", ".py", ".fasta", ".json", ".txt"))
    return rel in {
        "README.md",
        "CLAUDE.md",
        "CONTRIBUTING.md",
        "CHANGELOG.md",
        "STAGES.md",
        "THIRD_PARTY_NOTICES.md",
        "2.0/README.md",
        "Evaluator/README.md",
    }


def _hits() -> list[str]:
    found = []
    for path in _tracked_text_files():
        if not _in_scope(path) or path == Path(__file__).resolve() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for label, pat in _PATTERNS.items():
                if pat.search(line):
                    found.append(f"{path.relative_to(REPO)}:{n}: {label}")
    return found


def test_the_scan_sees_the_files_it_is_meant_to_guard():
    """A scope bug would make the real assertion below pass vacuously."""
    scanned = {p.relative_to(REPO).as_posix() for p in _tracked_text_files() if _in_scope(p)}
    for expected in ("README.md", "CLAUDE.md", "CHANGELOG.md", "tests/status/test_this_box_is_never_left_out.py"):
        assert expected in scanned


def test_the_patterns_catch_what_they_are_for():
    assert _PATTERNS["fleet box alias"].search("ssh bm" + "4 uptime")
    assert _PATTERNS["cluster name"].search("a job on " + _CLUSTER.title())
    assert not _PATTERNS["fleet box alias"].search("BM25 ranking")


def test_no_machine_alias_or_institution_pointer_in_docs_or_tests():
    hits = _hits()
    assert not hits, (
        "Name machines by architecture ('x86_64', 'aarch64') or generically ('a multi-user cluster'); "
        "machine-local facts belong in gitignored files or environment variables.\n  " + "\n  ".join(hits[:40])
    )
