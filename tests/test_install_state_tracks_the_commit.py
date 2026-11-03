"""A tool installed against another commit must be REPORTED, and must not be rebuilt silently.

`mark_tool_installed` has always stamped `<iso8601>\\t<short-sha>` into
`.install_state/<tool>`, but nothing ever read the sha back: `is_tool_marked`
tests file existence, so a tool built against an older tree audited as a plain
`installed`. `--verify` now reports it as STALE instead.

Two things are pinned here, because both have already been got wrong:

1. **The behaviour**, not just the helpers. An earlier version of this change was
   guarded only by a byte-identity check between the two installers, so deleting
   the stale branch from BOTH would have left four identical, unreachable helper
   bodies and a green suite.

2. **That `--repair` does NOT act on staleness by itself.** Staleness is commit
   INEQUALITY, not "older than", and the marker records HEAD at install time —
   so one `git pull`, even a docs-only commit, marks every tool stale at once.
   Merging that into the repair list turned `--repair` into a whole-fleet
   reinstall (AF2 weights included), against its own documented purpose. It takes
   an explicit `--stale`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
INSTALLERS = {"x86": REPO / "install" / "install.sh", "aarch64": REPO / "install" / "install_aarch.sh"}
_HELPERS = ("current_repo_sha", "marker_recorded_sha", "tool_marker_is_stale")


def _extract(script: Path, names: tuple[str, ...]) -> str:
    """Pull the named shell functions out of *script* so they can be sourced alone."""
    text = script.read_text().splitlines()
    out: list[str] = []
    for name in names:
        start = next((i for i, l in enumerate(text) if l.startswith(f"{name}(")), None)
        assert start is not None, f"{name} missing from {script.name}"
        depth = 0
        for i in range(start, len(text)):
            out.append(text[i])
            depth += text[i].count("{") - text[i].count("}")
            if depth == 0 and i > start:
                break
    return "\n".join(out)


def _run(script: Path, marker_body: str | None, head: str) -> bool:
    """True when tool_marker_is_stale says the marker is stale."""
    helpers = _extract(script, _HELPERS)
    prog = [
        "set -u",
        helpers,
        # stub the two things the helpers read from the environment
        f'current_repo_sha() {{ printf "%s" "{head}"; }}',
        'INSTALL_STATE_DIR="$PWD/.install_state"',
        'mkdir -p "$INSTALL_STATE_DIR"',
    ]
    if marker_body is not None:
        prog.append(f"printf '{marker_body}' > \"$INSTALL_STATE_DIR/demo\"")
    prog.append("if tool_marker_is_stale demo; then echo STALE; else echo FRESH; fi")
    r = subprocess.run(["bash", "-c", "\n".join(prog)], capture_output=True, text=True, cwd="/tmp")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().endswith("STALE")


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
@pytest.mark.parametrize(
    ("marker", "head", "expect_stale", "why"),
    [
        ("2026-10-29T00:00:00+01:00\\t1b1500c\\n", "1b1500c", False, "same commit"),
        ("2026-10-01T00:00:00+01:00\\tdeadbee\\n", "1b1500c", True, "different commit"),
        ("2026-10-01T00:00:00+01:00\\n", "1b1500c", False, "pre-sha one-field marker"),
        ("2026-10-01T00:00:00+01:00\\tunknown\\n", "1b1500c", False, "sha recorded as unknown"),
        (None, "1b1500c", False, "no marker at all"),
        ("2026-10-29T00:00:00+01:00\\t1b1500c\\n", "", False, "not a git checkout"),
    ],
)
def test_staleness_is_commit_inequality_with_both_shas_known(platform, marker, head, expect_stale, why):
    assert _run(INSTALLERS[platform], marker, head) is expect_stale, why


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_verify_actually_calls_the_staleness_check(platform):
    """Pins the CALL SITE. The helpers being present and identical is not enough."""
    text = INSTALLERS[platform].read_text()
    body = text[text.index("verify_selected_tools()") :]
    body = body[: body.index("\nreport_stale_tools") if "\nreport_stale_tools" in body else 4000]
    assert "tool_marker_is_stale" in body, (
        f"{INSTALLERS[platform].name}: verify_selected_tools no longer consults "
        "tool_marker_is_stale, so a tool built against another commit audits as plain 'installed'."
    )


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_repair_does_not_rebuild_stale_tools_without_the_flag(platform):
    """A docs-only commit must not turn --repair into a whole-fleet reinstall."""
    text = INSTALLERS[platform].read_text()
    assert "REPAIR_STALE" in text, f"{INSTALLERS[platform].name}: no --stale opt-in"
    merge = 'for _s in "${VERIFY_STALE[@]+"${VERIFY_STALE[@]}"}"; do _broken+=("${_s}"); done'
    assert merge in text, "the stale->repair merge line vanished entirely"
    guarded = text[: text.index(merge)].rstrip().endswith('if [[ "${REPAIR_STALE:-false}" == true ]]; then')
    assert guarded, (
        f"{INSTALLERS[platform].name}: the VERIFY_STALE -> _broken merge is not behind "
        "REPAIR_STALE, so --repair would rebuild every tool after any commit."
    )
