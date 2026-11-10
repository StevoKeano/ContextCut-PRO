"""Small whitelist HTML sanitizer for scan display markup.

The dashboard builds scan highlighting client-side and persists the resulting
HTML. That HTML is later re-rendered with ``innerHTML``, so it must never be
trusted. This sanitizer allows only the small tag/attribute set the scan UI
actually produces.
"""

from __future__ import annotations

import html
from html.parser import HTMLParser

_ALLOWED_TAGS = {"a", "span", "br", "div", "p"}
_ALLOWED_ATTRS = {
    "a": {"href", "title", "target", "rel"},
    "span": {"class", "title", "style"},
    "div": {"class", "style"},
    "p": {"class", "style"},
    "br": set(),
}
_SAFE_STYLES = {
    "font-size",
    "text-decoration",
    "color",
    "font-style",
    "margin-top",
    "padding",
    "border-top",
    "display",
    "width",
}


def _safe_href(value: str) -> str:
    value = (value or "").strip()
    lower = value.lower()
    if lower.startswith("http://") or lower.startswith("https://"):
        return html.escape(value, quote=True)
    if value.startswith("/knowledge/"):
        return html.escape(value, quote=True)
    return ""


def _safe_style(value: str) -> str:
    if not value:
        return ""
    parts = []
    for decl in value.split(";"):
        if ":" not in decl:
            continue
        prop, _, val = decl.partition(":")
        prop = prop.strip().lower()
        val = val.strip()
        if prop not in _SAFE_STYLES:
            continue
        if any(ch in val.lower() for ch in ("javascript:", "expression", "url(")):
            continue
        parts.append(f"{prop}: {val}")
    return "; ".join(parts)


def _safe_attrs(tag: str, attrs) -> str:
    allowed = _ALLOWED_ATTRS.get(tag, set())
    out = []
    for name, value in attrs:
        name = (name or "").lower()
        if name not in allowed:
            continue
        if name == "href":
            value = _safe_href(value or "")
            if not value:
                continue
        elif name == "style":
            value = _safe_style(value or "")
            if not value:
                continue
        elif name in ("class", "title", "target", "rel"):
            value = html.escape(value or "", quote=True)
        out.append(f'{name}="{value}"')
    if tag == "a" and any(a.startswith('href="') for a in out):
        if not any(a.startswith('rel="') for a in out):
            out.append('rel="noopener noreferrer"')
    return (" " + " ".join(out)) if out else ""


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag not in _ALLOWED_TAGS:
            return
        if tag == "br":
            self.out.append("<br>")
            return
        self.out.append(f"<{tag}{_safe_attrs(tag, attrs)}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _ALLOWED_TAGS and tag != "br":
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        self.out.append(html.escape(data, quote=False))

    def handle_entityref(self, name):
        self.out.append(html.escape(f"&{name};", quote=False))

    def handle_charref(self, name):
        self.out.append(html.escape(f"&#{name};", quote=False))


def sanitize_scan_html(value: str) -> str:
    """Return a safe subset of *value*, or an escaped string on failure."""
    if not value:
        return ""
    parser = _Sanitizer()
    try:
        parser.feed(str(value))
        parser.close()
        return "".join(parser.out)
    except Exception:
        return html.escape(str(value), quote=False)


__all__ = ["sanitize_scan_html"]
