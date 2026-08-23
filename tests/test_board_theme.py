"""Contract tests for `board/_theme.py` — the shared look of the one-tap
board family.

The theme is presentation-only, so these do not assert pixels: they pin the
things a renderer relies on and a careless edit silently breaks. Chiefly that
the family stays a *family* (every organ styled, every board wearing its own
accent) and that colour keeps meaning something (the exception is tinted, the
default is not).
"""

import re
import sys
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN_HOME / "board"))

import _theme  # noqa: E402

# The board family declared in config/policy.yaml — the theme must dress all
# of it, not just the two boards that adopted it first.
POLICY_BOARDS = re.findall(
    r"^    (\w+): \S+$",
    re.search(r"^  boards:\n((?:    \w+: \S+\n)+)",
              (BRAIN_HOME / "config" / "policy.yaml").read_text(),
              re.M).group(1), re.M)


def test_every_declared_board_has_a_complete_palette_entry():
    for key in POLICY_BOARDS:
        assert key in _theme.ORGANS, key
        o = _theme.ORGANS[key]
        for field in ("organ", "glyph", "tagline",
                      "ink_light", "ink_dark", "glow", "hero"):
            assert o.get(field), f"{key}.{field}"
        assert len(o["hero"]) == 2


def _luminance(hex_colour):
    parts = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
           for c in parts]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_every_accent_is_readable_on_its_own_background():
    # These pages are read outdoors on phones. An accent that fails here is
    # a link nobody can see, not a matter of taste.
    for key, o in _theme.ORGANS.items():
        assert _contrast(o["ink_light"], "#ffffff") >= 4.5, f"{key} light"
        assert _contrast(o["ink_dark"], "#0d1117") >= 4.5, f"{key} dark"


def test_css_substitutes_every_placeholder():
    sheet = _theme.css("mind")
    # A stray %(...)s means a renderer would ship a broken stylesheet.
    assert not re.search(r"%\([a-z_]+\)s", sheet)
    assert _theme.ORGANS["mind"]["ink_light"] in sheet
    assert _theme.ORGANS["mind"]["ink_dark"] in sheet
    assert "prefers-color-scheme:dark" in sheet


def test_each_board_wears_its_own_accent():
    mind, brain = _theme.css("mind"), _theme.css("brain")
    assert _theme.ORGANS["brain"]["glow"] not in mind
    assert _theme.ORGANS["mind"]["glow"] not in brain


def test_an_unknown_organ_still_renders():
    # An adopting fork with a board we have no palette for gets the umbrella's
    # look, never a KeyError mid-render.
    assert _theme.css("no-such-organ")
    assert "<header" in _theme.hero("no-such-organ", "Board")


def test_the_hero_reproduces_the_logo_wordmark():
    page = _theme.hero("mind", "Dashboard", "lede text")
    assert f'{_theme.WORD}<b>{_theme.ORGANS["mind"]["organ"]}</b>' in page
    assert _theme.ORGANS["mind"]["tagline"] in page
    assert "Dashboard" in page and "lede text" in page


def test_pills_tone_the_exception_and_leave_the_default_neutral():
    row = _theme.pills("autoarray", "small", "supervised", "normal")
    # `supervised` and `normal` are what almost every prompt says — tinting
    # them would colour the whole backlog and tell a reader nothing.
    assert row.count('class="pill n"') == 3
    assert '<span class="pill">autoarray</span>' in row  # target = identity
    flagged = _theme.pills("autoarray", "too-large", "human-required", "high")
    assert flagged.count('class="pill r"') == 3
    assert 'class="pill g"' in _theme.pills("-", "small", "safe", "low")


def test_the_work_type_leads_and_carries_a_glyph_not_a_colour():
    row = _theme.pills("autoarray", "small", work_type="bug")
    assert row.index('class="pill w"') < row.index("autoarray")
    assert _theme.WORK_TYPE_GLYPHS["bug"] in row
    # Colour stays reserved for judgement — the category is not one.
    assert '"pill w y"' not in row


def test_triage_is_the_one_work_type_that_asks_for_attention():
    # `triage` means nobody has classified this yet, which is a real call to
    # action rather than a category.
    assert 'class="pill w y"' in _theme.pills("autoarray", work_type="triage")


def test_every_work_type_in_the_taxonomy_has_a_glyph():
    sizing = BRAIN_HOME / "agents" / "faculties" / "sizing"
    sys.path.insert(0, str(sizing))
    import _sizing  # noqa: E402
    assert set(_sizing.WORK_TYPES) == set(_theme.WORK_TYPE_GLYPHS)


def test_pills_escape_their_values_and_vanish_when_empty():
    assert _theme.pills("-", "-", "-", "-") == ""
    assert "&lt;b&gt;" in _theme.pills("<b>")


def test_boards_footer_skips_self_and_tags_each_sibling():
    links = {k: f"https://example.invalid/{k}/" for k in _theme.ORGANS}
    footer = _theme.boards_footer(links, "mind")
    assert 'data-organ="mind"' not in footer
    for key in _theme.ORGANS:
        if key != "mind":
            assert f'data-organ="{key}"' in footer
            # …and the chip is tinted by that organ's own accent.
            assert f'.boards a[data-organ="{key}"]' in _theme.css("mind")


def test_stats_render_pairs_and_vanish_when_empty():
    assert _theme.stats() == ""
    assert "<b>3</b><span>In flight</span>" in _theme.stats((3, "In flight"))
