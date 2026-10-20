"""CivitAI descriptions are HTML written by model makers. The Library shows them as plain text
(paragraphs, list bullets, and links as text the UI turns into anchors): no markup from the page is
ever put into ComfyUI's page."""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

MAX_CHARS = 20000
_BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "tr", "hr"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.href: list[str | None] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag == "li":
            self.out.append("\n• ")
        elif tag in _BLOCK:
            self.out.append("\n")
        if tag == "a":
            href = dict(attrs).get("href") or ""
            self.href.append(href if re.match(r"https?://", href) else None)
            self.out.append("\0")  # where the link text starts

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag == "a" and self.href:
            href = self.href.pop()
            text_start = len(self.out) - 1 - self.out[::-1].index("\0") if "\0" in self.out else len(self.out)
            text = "".join(self.out[text_start + 1:]).strip()
            del self.out[text_start:]
            if href and text and href.rstrip("/") not in text:
                self.out.append(f"{text} ({href})")
            else:
                self.out.append(href or text)
        elif tag in _BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def to_text(raw: str | None) -> str:
    if not raw:
        return ""
    p = _Text()
    try:
        p.feed(str(raw))
        p.close()
        text = "".join(x for x in p.out if x != "\0")
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html.unescape(str(raw)))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\n+• ", "\n• ", text).strip()  # list items one per line
    return text[:MAX_CHARS] + ("…" if len(text) > MAX_CHARS else "")
