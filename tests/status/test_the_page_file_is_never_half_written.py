"""A browser polls the file on a timer, so it can read it mid-write.

The generator runs every few minutes; a phone left on the page re-reads every
60 s. Those two clocks are unrelated, so sooner or later a read lands inside a
write. Writing in place would hand that reader a truncated document -- half a
campaign, no closing tags -- which renders as a blank or broken page and looks
exactly like a dead fleet.

Writing beside the file and renaming makes the swap atomic: a reader sees the
old page or the new one.
"""

from status.cli import write_html

_DOC = {
    "generated_at": "2026-10-31T07:10:56Z",
    "campaigns": {},
    "hosts": {"host-a": {"reachable": True, "runs": {}}},
}


def test_the_page_is_complete_and_no_temporary_file_is_left_behind(tmp_path):
    page = tmp_path / "site" / "index.html"
    write_html(page, _DOC)

    assert page.read_text().rstrip().endswith("</html>")
    # The rename is what makes the swap atomic; a leftover .tmp means the
    # renderer wrote in place and only copied afterwards.
    assert [p.name for p in (tmp_path / "site").iterdir()] == ["index.html"]


def test_rewriting_replaces_the_page_rather_than_appending(tmp_path):
    page = tmp_path / "index.html"
    write_html(page, _DOC)
    first = page.read_text()
    write_html(page, {**_DOC, "generated_at": "2026-10-31T07:20:00Z"})
    second = page.read_text()

    assert "2026-10-31T07:10:56Z" not in second
    assert "2026-10-31T07:20:00Z" in second
    assert len(second) < 2 * len(first), "the page grew: it was appended to, not replaced"
