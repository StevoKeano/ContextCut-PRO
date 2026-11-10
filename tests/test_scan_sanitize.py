"""Tests for the dashboard scan-HTML sanitizer."""

from scan_sanitize import sanitize_scan_html


def test_keeps_expected_markup():
    src = (
        '<div class="hit" style="border-top: 1px solid red">'
        '<span class="kw" title="match">Alice</span> lives in '
        '<a href="/knowledge/AliceInfo.md?line=3" title="source">Paris</a></div>'
    )
    out = sanitize_scan_html(src)
    assert '<div class="hit"' in out
    assert '<span class="kw"' in out
    assert 'href="/knowledge/AliceInfo.md?line=3"' in out
    assert 'rel="noopener noreferrer"' in out


def test_strips_script_and_event_handlers():
    out = sanitize_scan_html(
        '<img src=x onerror="alert(1)"><script>alert(2)</script>'
        '<div onclick="alert(3)">safe</div>'
    )
    assert "<img" not in out
    assert "<script" not in out
    assert "onerror" not in out
    assert "onclick" not in out
    assert "safe" in out


def test_rejects_javascript_href_and_dangerous_style():
    out = sanitize_scan_html(
        '<a href="javascript:alert(1)">x</a>'
        '<span style="background:url(javascript:alert(2));color:red">y</span>'
    )
    assert "javascript:" not in out
    assert "url(" not in out
    assert "color: red" in out


def test_escapes_plain_text():
    assert sanitize_scan_html("2 < 3 & 4 > 1") == "2 &lt; 3 &amp; 4 &gt; 1"


def test_empty_input():
    assert sanitize_scan_html("") == ""
