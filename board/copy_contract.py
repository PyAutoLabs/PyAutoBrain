"""Shared regression assertion for rendered dashboard copy buttons.

Use from a renderer's HTML tests, after rendering a representative page. This
checks the actual clipboard attributes, independently of skill-name registries
or prompt conversion helpers. It performs no network or filesystem access.
"""

import re
from html.parser import HTMLParser


class _CopyButtons(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.count = 0
        self.violations = []

    def handle_starttag(self, tag, attrs):
        if tag != "button":
            return
        attrs = dict(attrs)
        terminal = "term" in (attrs.get("class") or "").split() or (attrs.get("aria-label") or "").lower().startswith("copy command:")
        for key in ("data-cmd", "data-copy"):
            if key not in attrs:
                continue
            self.count += 1
            payload = attrs[key] or ""
            # Absolute executable paths (/usr/bin/tool) are not slash skills.
            # A bare /tool is ambiguous and must be marked as a terminal chip.
            if not terminal and re.match(r"^\s*/[a-zA-Z][\w-]*(?=\s|$)", payload):
                self.violations.append(f"{key}: {payload.strip()[:160]}")


def assert_portable_copy_payloads(page):
    """Fail on slash-skill clipboard payloads, or a vacuous page with no buttons.

    Both data-cmd (board family) and data-copy (Eyes) are checked. HTML entities
    are decoded by the parser; shell commands and explicit terminal chips are
    preserved. This is an assertion only: never rewrite the renderer's output.
    """
    parser = _CopyButtons()
    parser.feed(page)
    parser.close()
    assert parser.count, "No copy payloads found; render an actionable dashboard fixture"
    assert not parser.violations, "Assistant-specific copy payloads:\n" + "\n".join(
        parser.violations)
