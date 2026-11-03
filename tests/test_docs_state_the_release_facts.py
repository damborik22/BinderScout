"""The documents a new user or agent reads first must state what is true now.

Each assertion here pins a statement that was wrong in a shipped document:

* the README banner told readers the line was "unreleased, not tagged" and that
  ``master`` was "frozen at 1.0.3" while v2.0.0-v2.0.2 were already tagged on the
  public remote and ``master`` stood at 1.2.x;
* the README gave ``git clone -b aarch64`` for a branch that does not exist;
* ``binderscout status`` had no user-facing documentation at all;
* CLAUDE.md said the two lines "share no ancestry" (they share one commit),
  that v2.0.x was "not published" (its tags are on the public remote) and that
  three master fixes were absent from this line (two have since been ported);
* THIRD_PARTY_NOTICES.md's GPLv3 written offer cited commit SHAs that stopped
  existing in the 2026-10-27 history rewrite, so the offer pointed at nothing.

These are deliberately about facts and not about prose: each one is a phrase or
a derived value, so rewording a paragraph does not break them but restating a
falsehood does.
"""

import hashlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True)


# --- README ------------------------------------------------------------------


def test_readme_banner_is_not_the_stale_do_not_use_notice():
    readme = _text("README.md")
    for stale in ("DO NOT USE", "not tagged", "frozen at", "validated seven-tool"):
        assert stale not in readme, f"README.md still says {stale!r}"


def test_readme_states_the_branch_and_tag_layout():
    top = _text("README.md")[:4000]
    for needle in ("v2.0.0", "v2.0.2", "v2.0.3", "master", "v1.2", "archive/v1.1.x"):
        assert needle in top, f"the README banner does not mention {needle!r}"


def test_readme_does_not_send_aarch64_users_to_a_branch_that_does_not_exist():
    readme = _text("README.md")
    assert "clone -b aarch64" not in readme
    assert "install_aarch.sh" in readme
    # One tree, two installers: the section must say so rather than imply branches.
    section = readme[readme.index("## Platform") :]
    assert "no `aarch64` branch" in section


def test_readme_documents_every_status_flag_the_parser_accepts():
    sys.path.insert(0, str(REPO))
    from status import cli

    flags = sorted(set(re.findall(r"--[a-z]+", cli.USAGE)))
    assert {"--hosts", "--local", "--json", "--html", "--watch"} <= set(flags)
    readme = _text("README.md")
    assert "### `binderscout status`" in readme
    block = readme[readme.index("### `binderscout status`") :]
    block = block[: block.find("\n### ", 10)]
    missing = [f for f in flags if f"| `{f}" not in block]
    assert not missing, f"README.md's status section does not document {missing}"
    for var in ("BINDERSCOUT_FLEET", "BINDERSCOUT_CAMPAIGNS"):
        assert var in block


def test_readme_counts_nine_design_tools_where_it_counts_them():
    readme = _text("README.md")
    assert "the eight tools' outputs" not in readme
    assert "Five of eight tools" not in readme


# --- CLAUDE.md ---------------------------------------------------------------


def test_claude_md_ancestry_publication_and_port_status():
    claude = _text("CLAUDE.md")
    assert "no common ancestry" not in claude
    assert "Shipped to the fleet" not in claude
    assert "602345a" in claude, "the one commit the two lines share should be named"
    assert "Three master fixes are still absent" not in claude
    assert "filter-tmprot" in claude


def test_claude_md_does_not_list_the_aliases_it_forbids():
    claude = _text("CLAUDE.md")
    rule = claude[claude.index("This repo is PUBLIC") :][:1500]
    assert "alias" in rule
    assert "architecture" in rule
    assert not re.search(r"\bbm[0-9]\b", rule, re.I)


def test_claude_md_documents_the_pae_iptm_facts():
    claude = _text("CLAUDE.md")
    for needle in (
        "point-PAE",
        "unordered tier",
        "_pinned",
        "--d0-binder-length",
        "re-blocks",
    ):
        assert needle in claude, f"CLAUDE.md does not state {needle!r}"
    assert "transposes internally" not in claude


# --- Evaluator docs ----------------------------------------------------------


@pytest.mark.parametrize("doc", ["Evaluator/docs/evaluation/ranking.md", "Evaluator/docs/evaluation/metrics.md"])
def test_evaluator_docs_say_what_pae_iptm_is(doc):
    text = _text(doc)
    for needle in ("point-PAE", "_pinned", "--min-engines 2", "optimistic"):
        assert needle in text, f"{doc} does not state {needle!r}"


def test_evaluator_docs_count_nine_tools():
    assert "5 of 8 tools" not in _text("Evaluator/docs/evaluation/metrics.md")
    assert "8 design tools" not in _text("Evaluator/docs/evaluation/metrics.md")


# --- CONTRIBUTING ------------------------------------------------------------


def test_contributing_lists_rfd4_and_the_release_checklist():
    text = _text("CONTRIBUTING.md")
    assert "RFD4-Proteina/.venv" in text
    assert "\n## Releasing" in text
    section = text[text.index("\n## Releasing") :]
    for needle in ("ruff", "shellcheck", "__version__", "annotated tag", "dirty"):
        assert needle in section, f"the release checklist does not mention {needle!r}"
    assert re.search(r"gh release create \S+ --latest=false", section), "the release command must carry --latest=false"


# --- THIRD_PARTY_NOTICES -----------------------------------------------------


def _usearch_offer_commits() -> list[str]:
    return re.findall(r"commit `([0-9a-f]{7,40})`", _text("THIRD_PARTY_NOTICES.md"))


def _is_shallow() -> bool:
    return _git("rev-parse", "--is-shallow-repository").stdout.strip() == b"true"


def test_written_offer_cites_commits_that_exist():
    cited = _usearch_offer_commits()
    assert len(cited) >= 2, "the written offer must name the commit that added and the one that removed the binaries"
    if _git("rev-parse", "--git-dir").returncode != 0 or _is_shallow():
        pytest.skip("needs full history to resolve commits")
    gone = [c for c in cited if _git("cat-file", "-e", f"{c}^{{commit}}").returncode != 0]
    assert not gone, f"THIRD_PARTY_NOTICES.md cites commits that do not exist: {gone}"


def test_written_offer_checksums_match_the_binaries_at_the_cited_commit():
    if _git("rev-parse", "--git-dir").returncode != 0 or _is_shallow():
        pytest.skip("needs full history to resolve commits")
    text = _text("THIRD_PARTY_NOTICES.md")
    for name in ("usearch.x86_64", "usearch.aarch64"):
        path = f"Evaluator/tools/soluprot/{name}"
        documented = re.search(rf"`{re.escape(path)}`[^\n]*`([0-9a-f]{{64}})`", text)
        assert documented, f"no SHA-256 documented for {path}"
        digests = set()
        for commit in _usearch_offer_commits():
            blob = _git("show", f"{commit}:{path}")
            if blob.returncode == 0:
                digests.add(hashlib.sha256(blob.stdout).hexdigest())
        assert documented.group(1) in digests, f"{path}: no cited commit holds a blob with the documented SHA-256"


def test_third_party_table_covers_the_tools_added_since_it_was_written():
    text = _text("THIRD_PARTY_NOTICES.md")
    for needle in ("RFD4-Proteina", "nvidia/RFD4-Proteina", "TmProt", "GPL-3.0", "ESMFold2"):
        assert needle in text
    rfd4_row = next(line for line in text.splitlines() if line.startswith("| RFD4-Proteina"))
    assert "unverified" in rfd4_row.lower()


# --- CHANGELOG ---------------------------------------------------------------


def test_changelog_unreleased_section_is_written():
    text = _text("CHANGELOG.md")
    start = text.index("## [Unreleased]")
    end = text.index("\n## [", start + 5)
    body = text[start:end]
    assert len(body) > 2500, "the [Unreleased] section is empty or a stub"
    for needle in ("binderscout status", "--repair --stale", "stderr", "_pinned", "resume", "binderscout_paths"):
        assert needle in body, f"[Unreleased] does not mention {needle!r}"
