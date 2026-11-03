"""``binderscout.__version__`` must equal the newest numbered heading in CHANGELOG.md.

The version string and the changelog are edited by different hands at different
times, and nothing tied them together: the release is tagged from whichever one
someone remembered to update.

``[Unreleased]`` is not a version and is skipped. Between releases the newest numbered heading is the
last release, and the release commit bumps ``__version__`` and adds the new heading together; if one is
edited without the other this test fails, on every branch.
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_HEADING = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.M)


def _newest_changelog_version() -> str:
    match = _HEADING.search((REPO / "CHANGELOG.md").read_text(encoding="utf-8"))
    assert match, "CHANGELOG.md has no numbered release heading"
    return match.group(1)


def _cli_version() -> str:
    sys.path.insert(0, str(REPO))
    import binderscout

    return binderscout.__version__


def test_the_parser_finds_the_newest_numbered_heading_not_unreleased():
    assert re.fullmatch(r"\d+\.\d+\.\d+", _newest_changelog_version())


def test_version_matches_the_newest_changelog_heading():
    assert _cli_version() == _newest_changelog_version()
