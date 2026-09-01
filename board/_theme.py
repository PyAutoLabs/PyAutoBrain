"""board/_theme.py — the shared look of the one-tap board family.

Every organ publishes the same kind of page: a phone-first, self-contained
list of rows, each carrying a 📋 copy-for-Claude payload. Until now each
renderer carried its own copy of the same GitHub-grey stylesheet, so the
family looked like six unrelated pages that happened to share a layout — and
none of them looked like the organ whose logo sits at the top of its README.

This module is the one place that answers "what does a board look like". It
is **presentation only**: no state, no collection, no policy. Renderers
import it and ask for the stylesheet, the hero and the small components; they
keep owning what goes in the rows.

The design in one line: *the page wears its organ's logo*. Every board opens
with a dark hero that redraws the logo it sits under: the organ's own mark in
line art, the wordmark (white `PyAuto`, the organ name in its accent), the
hairline-and-dot rule, and the letterspaced tagline. Below the hero the organ
keeps speaking: the accent runs on through the page's *type* rather than
stopping at the masthead. Body copy stays plain, because these are lists
people scan on a phone before breakfast, not dashboards to admire.

The mark is **drawn, not borrowed**. An emoji stood in for it at first, which
read as a cartoon beside the real logo — 🧠 is not the Brain's circuit brain.
`MARKS` holds each logo's glyph as inline SVG line art traced off the file:
it inherits the accent, stays sharp at any size, and costs ~1KB in the one
page that uses it, where the 80-150KB `logo.png` would be most of the page.

The accent is the page's **type colour**, not merely its link colour: the
things that give a page its shape — section headings, disclosure summaries,
code spans, the emphasised head of a row — are all set in the organ's hue, so
a board reads as its organ from top to bottom instead of as grey GitHub
chrome under a coloured masthead. Only the running prose stays near-black.

Colour is doing two jobs at once now, and the decorative one never overwrites
the semantic one:

* the **accent** is organ identity — links, headings, summaries, code, the
  section rules, the stats and the hero;
* **pills** are the task facets (target, difficulty, autonomy, priority), so
  a backlog can be scanned by colour instead of read word by word;
* **ok / warn / bad** stay reserved for the verdict semantics they already
  carry on the Heart-style boards.

That reservation is literal in the stylesheet: the accent rule is
`b:not([class])`, so an element carrying a semantic class — `ok`, `warn`,
`bad`, `muted`, a pill tone — keeps the colour that class means, and only
unclassed emphasis takes the organ's hue.

`ORGANS` is the palette table, keyed by the same board names as
`config/policy.yaml` `board: boards:` — that mapping is the declared config
surface an adopting fork replaces, so no repo is named here. Five of the six
palettes are sampled from the actual logo files: the mark, the glyph colour
and the wordmark's own tagline, straight off `logo.png` in each organ's repo.
The
umbrella board has no logo, so its accent and tagline are designed to sit in
the family instead. Every accent is checked for >= 4.5:1 contrast against
its own background (light on `#fff`, dark on `#0d1117`).
"""

# ---------------------------------------------------------------- palette ---
# ink_light / ink_dark: the accent as *text*, per colour scheme.
# glow:  the logo's own glyph colour — used only on the dark hero, where it
#        needs to sing rather than pass a contrast check against white.
# glow2: the far end of the wordmark's gradient, for the two logos that set
#        their organ name in one (Brain runs blue → violet, Memory violet →
#        purple). Omitted where the logo's wordmark is a flat colour.
# hero:  (lift, base) — the hero's radial gradient, echoing each logo's
#        vignette: a tinted lift behind the wordmark falling to near-black.
ORGANS = {
    "brain": {
        "organ": "Brain",
        "tagline": "Reason. Plan. Decide.",
        "ink_light": "#2159c9", "ink_dark": "#6f9dff", "glow": "#4d8bff",
        "glow2": "#a855f7",
        "hero": ("#16234f", "#000312"),
    },
    "mind": {
        "organ": "Mind",
        "tagline": "Intent. Priority. Flow.",
        "ink_light": "#0a7d72", "ink_dark": "#2ee6cf", "glow": "#00d1ba",
        "hero": ("#07302b", "#000000"),
    },
    "memory": {
        "organ": "Memory",
        "tagline": "Remember. Learn. Evolve.",
        "ink_light": "#6b34d6", "ink_dark": "#b37eff", "glow": "#b37eff",
        "glow2": "#8b5cf6",
        "hero": ("#221345", "#000000"),
    },
    "heart": {
        "organ": "Heart",
        "tagline": "Check. Validate. Protect.",
        "ink_light": "#b50f1a", "ink_dark": "#ff6b73", "glow": "#ff1c28",
        "hero": ("#37080d", "#000000"),
    },
    "hands": {
        "organ": "Hands",
        "tagline": "Build. Execute. Deliver.",
        "ink_light": "#9a5400", "ink_dark": "#ffa733", "glow": "#ff9201",
        "hero": ("#372100", "#000000"),
    },
    # The umbrella is the one board with no logo to sample: the accent and
    # the tagline are designed to sit in the family rather than read off a
    # file. Replace both from the logo if that repo ever grows one.
    "organism": {
        "organ": "Scientist",
        "tagline": "Describe. Build. Release.",
        "ink_light": "#0b6fa4", "ink_dark": "#5ec7f5", "glow": "#38bdf8",
        "hero": ("#092e43", "#00070d"),
    },
}


# ----------------------------------------------------------------- marks ---
# Each organ's logo glyph, traced off `logo.png` as line art on a 48x48 grid:
# a ring (closed, or left open where the logo opens it), the glyph inside it,
# and the small filled nodes the family's drawing style uses. Stroke colour
# is inherited, so one mark serves the hero, light mode and dark mode alike.
#
# Why drawn rather than embedded: the boards are self-contained single files
# read on phones over mobile data. The logos are 80-150KB of PNG each; these
# are ~1KB of path data, stay sharp on any screen, and take the accent.
# Keep them that way — a mark is a logo's glyph in line art, not a rendering.
MARKS = {
    # Brain — a circuit brain: two lobed hemispheres either side of a spine,
    # each branching into elbowed, node-tipped traces, inside a ring.
    "brain": (
        '<circle cx="24" cy="24" r="20.4"/>'
        '<path d="M24,12.6 C22.2,10.6 19.2,10.2 17.4,11.6 '
        'C16.2,12.5 15.6,13.9 15.7,15.3 '
        'C13.6,15.6 12.0,17.2 11.8,19.2 '
        'C11.6,20.6 12.1,21.9 13.0,22.9 '
        'C11.7,24.0 11.2,25.8 11.8,27.4 '
        'C12.4,29.0 13.9,30.0 15.5,30.1 '
        'C15.7,32.1 17.2,33.8 19.2,34.2 '
        'C20.9,34.6 22.7,34.0 24.0,32.8"/>'
        '<path d="M24,12.6 C25.8,10.6 28.8,10.2 30.6,11.6 '
        'C31.8,12.5 32.4,13.9 32.3,15.3 '
        'C34.4,15.6 36.0,17.2 36.2,19.2 '
        'C36.4,20.6 35.9,21.9 35.0,22.9 '
        'C36.3,24.0 36.8,25.8 36.2,27.4 '
        'C35.6,29.0 34.1,30.0 32.5,30.1 '
        'C32.3,32.1 30.8,33.8 28.8,34.2 '
        'C27.1,34.6 25.3,34.0 24.0,32.8"/>'
        '<path d="M24,12.6 L24,32.8"/>'
        '<path d="M24,16.6 L20.2,16.6 L20.2,13.4 '
        'M24,21.8 L16.6,21.8 L16.6,18.4 '
        'M24,26.4 L18.0,26.4 L18.0,29.6 '
        'M24,30.4 L21.2,30.4 L21.2,32.8 '
        'M24,16.6 L27.8,16.6 L27.8,13.4 '
        'M24,21.8 L31.4,21.8 L31.4,18.4 '
        'M24,26.4 L30.0,26.4 L30.0,29.6 '
        'M24,30.4 L26.8,30.4 L26.8,32.8"/>'
        '<g fill="currentColor" stroke="none">'
        '<circle cx="24" cy="11.6" r="1.4"/>'
        '<circle cx="20.2" cy="13.4" r="1.3"/>'
        '<circle cx="16.6" cy="18.4" r="1.3"/>'
        '<circle cx="18.0" cy="29.6" r="1.3"/>'
        '<circle cx="21.2" cy="32.8" r="1.2"/>'
        '<circle cx="27.8" cy="13.4" r="1.3"/>'
        '<circle cx="31.4" cy="18.4" r="1.3"/>'
        '<circle cx="30.0" cy="29.6" r="1.3"/>'
        '<circle cx="26.8" cy="32.8" r="1.2"/>'
        '<circle cx="24" cy="33.8" r="1.4"/></g>'
    ),
    # Mind — a left-facing head profile, a check inside the skull, three
    # node-tipped signal lines leaving the back of the head, inside a ring.
    "mind": (
        '<circle cx="24" cy="24" r="20.4"/>'
        '<path d="M20.2,37.6 L20.2,33.6 '
        'C20.2,32.4 19.4,31.6 18.4,30.8 '
        'C16.8,29.6 15.8,28.2 15.6,26.6 '
        'C15.5,25.6 14.9,25.2 13.9,24.9 '
        'C12.6,24.5 12.3,23.7 13.0,22.7 '
        'C13.8,21.6 14.5,20.6 14.6,19.4 '
        'C15.0,15.4 18.2,12.2 22.4,11.8 '
        'C27.2,11.3 31.6,14.6 32.3,19.2 '
        'C32.8,22.4 31.6,25.0 30.6,27.0 '
        'C29.9,28.4 29.6,29.6 29.6,31.2 '
        'L29.6,37.6"/>'
        '<circle cx="24.6" cy="19.6" r="4.4"/>'
        '<path d="M22.5,19.7 L24.0,21.3 L26.8,18.1"/>'
        '<path d="M34.2,16.5 L38.8,16.5 M35.2,21.0 L39.4,21.0 '
        'M33.6,25.5 L37.2,25.5"/>'
        '<g fill="currentColor" stroke="none">'
        '<circle cx="40.1" cy="16.5" r="1.4"/>'
        '<circle cx="40.7" cy="21.0" r="1.4"/>'
        '<circle cx="38.5" cy="25.5" r="1.4"/></g>'
    ),
    # Memory — an open book with a node-tree growing out of its spine and a
    # scatter of stars, under an arc open at the bottom.
    "memory": (
        '<path d="M10.6,37.6 A20.4,20.4 0 1 1 37.4,37.6"/>'
        '<path d="M24.0,28.2 C20.7,25.5 15.6,24.4 9.6,24.9 '
        'L9.6,37.8 C15.6,37.3 20.7,38.4 24.0,41.1 '
        'C27.3,38.4 32.4,37.3 38.4,37.8 '
        'L38.4,24.9 C32.4,24.4 27.3,25.5 24.0,28.2 Z"/>'
        '<path d="M24.0,28.2 L24.0,41.1"/>'
        '<path d="M13.0,28.6 C15.6,28.7 17.9,29.2 19.8,30.1 '
        'M13.0,30.7 C15.6,30.8 17.9,31.3 19.8,32.2 '
        'M13.0,32.8 C15.6,32.9 17.9,33.4 19.8,34.3 '
        'M35.0,28.6 C32.4,28.7 30.1,29.2 28.2,30.1 '
        'M35.0,30.7 C32.4,30.8 30.1,31.3 28.2,32.2 '
        'M35.0,32.8 C32.4,32.9 30.1,33.4 28.2,34.3"/>'
        '<path d="M24.0,28.0 L24.0,12.6 M24.0,19.0 L19.6,16.2 '
        'M24.0,23.6 L17.6,20.2 M24.0,19.0 L28.4,16.2 '
        'M24.0,23.6 L30.4,20.2"/>'
        '<g fill="currentColor" stroke="none">'
        '<circle cx="24" cy="11.4" r="1.5"/>'
        '<circle cx="19.2" cy="16.0" r="1.3"/>'
        '<circle cx="17.2" cy="20.0" r="1.3"/>'
        '<circle cx="28.8" cy="16.0" r="1.3"/>'
        '<circle cx="30.8" cy="20.0" r="1.3"/></g>'
        '<path d="M12.6,14.6 Q12.6,17.0 10.2,17.0 Q12.6,17.0 12.6,19.4 '
        'Q12.6,17.0 15.0,17.0 Q12.6,17.0 12.6,14.6 Z"/>'
        '<path d="M35.4,13.0 Q35.4,15.2 33.2,15.2 Q35.4,15.2 35.4,17.4 '
        'Q35.4,15.2 37.6,15.2 Q35.4,15.2 35.4,13.0 Z"/>'
        '<path d="M15.8,21.8 Q15.8,23.4 14.2,23.4 Q15.8,23.4 15.8,25.0 '
        'Q15.8,23.4 17.4,23.4 Q15.8,23.4 15.8,21.8 Z"/>'
    ),
    # Heart — a heart outline crossed by an ECG trace, with the check badge
    # sitting in the ring's lower-right gap.
    "heart": (
        '<path d="M30.4,43.4 A20.4,20.4 0 1 1 43.2,31.0"/>'
        '<path d="M24.0,34.5 L15.3,25.8 '
        'A5.8,5.8 0 0 1 15.3,17.7 '
        'A5.8,5.8 0 0 1 23.4,17.7 L24.0,18.3 L24.6,17.7 '
        'A5.8,5.8 0 0 1 32.7,17.7 '
        'A5.8,5.8 0 0 1 32.7,25.8 Z"/>'
        '<path d="M12.6,23.2 L16.6,23.2 L18.2,19.0 L20.8,27.6 '
        'L22.8,21.4 L24.4,24.6 L34.6,24.6"/>'
        '<circle cx="34.6" cy="34.4" r="6.6"/>'
        '<path d="M31.6,34.4 L33.9,36.8 L37.9,32.0"/>'
    ),
    # Hands — an open palm offering a gear, speed lines behind the cuff,
    # inside a ring left open at the lower-left where the lines enter.
    "hands": (
        '<path d="M12.2,38.8 A20.4,20.4 0 1 1 20.0,43.4"/>'
        '<path d="M27.0,12.8 L27.7,11.2 L29.4,11.7 L29.3,13.4 L30.1,14.1 '
        'L31.7,13.5 L32.6,15.0 L31.3,16.1 L31.4,17.2 L33.0,17.9 L32.5,19.6 '
        'L30.8,19.5 L30.1,20.3 L30.7,21.9 L29.2,22.8 L28.1,21.5 L27.0,21.6 '
        'L26.3,23.2 L24.6,22.7 L24.7,21.0 L23.9,20.3 L22.3,20.9 L21.4,19.4 '
        'L22.7,18.3 L22.6,17.2 L21.0,16.5 L21.5,14.8 L23.2,14.9 L23.9,14.1 '
        'L23.3,12.5 L24.8,11.6 L25.9,12.9 Z"/>'
        '<circle cx="27.0" cy="17.2" r="2.5"/>'
        '<path d="M16.2,30.4 C18.6,35.0 23.8,37.8 29.4,37.0 '
        'C33.2,36.4 36.6,34.4 38.8,31.4 '
        'C39.7,30.2 39.1,28.7 37.7,28.5 '
        'C36.7,28.4 35.9,28.9 35.2,29.5 L32.2,31.9 '
        'C29.2,34.0 25.0,34.0 21.6,32.0 Z"/>'
        '<path d="M16.2,30.4 L11.2,33.0 L14.2,38.4 L19.4,35.6"/>'
        '<circle cx="14.6" cy="34.6" r="1" fill="currentColor" stroke="none"/>'
        '<path d="M3.8,26.2 L11.6,26.2 M2.2,30.4 L8.6,30.4 '
        'M5.0,34.6 L9.4,34.6"/>'
    ),
    # Umbrella — no logo to sample, so the family language (ring, line-art,
    # node dots) applied to the double helix the board already carried.
    "organism": (
        '<circle cx="24" cy="24" r="20.4"/>'
        '<path d="M17.0,9.8 C17.0,15.9 31.0,18.3 31.0,24.0 '
        'C31.0,29.7 17.0,32.1 17.0,38.2"/>'
        '<path d="M31.0,9.8 C31.0,15.9 17.0,18.3 17.0,24.0 '
        'C17.0,29.7 31.0,32.1 31.0,38.2"/>'
        '<path d="M18.6,13.6 L29.4,13.6 M16.9,18.4 L31.1,18.4 '
        'M16.9,29.6 L31.1,29.6 M18.6,34.4 L29.4,34.4"/>'
        '<g fill="currentColor" stroke="none">'
        '<circle cx="17" cy="9.8" r="1.4"/><circle cx="31" cy="9.8" r="1.4"/>'
        '<circle cx="17" cy="38.2" r="1.4"/><circle cx="31" cy="38.2" r="1.4"/>'
        '</g>'
    ),
}

import html as _html

WORD = "PyAuto"  # the half of every wordmark that stays white


def _esc(value):
    return _html.escape(str(value), quote=True)


def organ(key):
    """The palette entry for a board, or the umbrella's when `key` is
    unknown — an adopting fork gets a styled page rather than a crash."""
    return ORGANS.get(key, ORGANS["organism"])


def mark(key):
    """The organ's logo glyph as an inline SVG, drawn in the current colour.

    Unknown keys fall back with `organ()`, so an adopting fork's board wears
    the umbrella's mark rather than rendering an empty ring.
    """
    art = MARKS.get(key) or MARKS["organism"]
    return ('<svg class="mark" viewBox="0 0 48 48" fill="none" '
            'stroke="currentColor" stroke-width="1.3" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{art}</svg>')


# -------------------------------------------------------------------- css ---
# One stylesheet, two colour schemes, one substituted accent. Kept in the
# same dense hand-wrapped style as the renderers that inline it: this ships
# inside every page, and these pages are opened on phones over mobile data.
_CSS = """\
:root{color-scheme:light dark;--bg:#fff;--fg:#1f2328;--muted:#59636e;
 --line:#d8dee4;--btn:#f6f8fa;--ok:#1a7f37;--warn:#9a6700;--bad:#d1242f;
 --accent:%(ink_light)s;--tint:%(ink_light)s14;--edge:%(ink_light)s3d;
 --hero-lift:%(hero_lift)s;--hero-base:%(hero_base)s;--glow:%(glow)s;
 --glow2:%(glow2)s}
@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#f0f6fc;
 --muted:#9198a1;--line:#2c333c;--btn:#151b23;--ok:#3fb950;--warn:#d29922;
 --bad:#f85149;--accent:%(ink_dark)s;--tint:%(ink_dark)s1f;
 --edge:%(ink_dark)s47}}
*{box-sizing:border-box}
/* Wrapping is the page DEFAULT, not a per-component opt-in. These boards are
   read on phones, and every one of them prints run URLs, dotted test ids and
   long file paths — a single unbreakable token in any element a renderer adds
   itself (a reasons list, a footer, a details block) spills past the right
   edge and gives the WHOLE page a horizontal scroll. `overflow-wrap` is
   inherited, so setting it here covers markup this module has never seen.
   The three max-width/overflow rules do the same job for the things that
   cannot be wrapped: an image, a table, a code block. */
body{margin:0 auto;max-width:44rem;padding:0 1rem 4rem;background:var(--bg);
 color:var(--fg);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",
 Helvetica,Arial,sans-serif;-webkit-text-size-adjust:100%%;
 overflow-wrap:anywhere}
/* 44rem is a PHONE reading measure, and these boards are read on laptops too.
   Above the cap the column stops being a measure and starts being a waste:
   the data boards (Heart's check table, Mind's task lists) run ~40 short
   lines down a 704px strip with the rest of the screen empty. One step up on
   laptop-class viewports, and only there — every narrower screen keeps the
   phone shape byte for byte. */
@media(min-width:64rem){body{max-width:60rem}}
img,svg,table{max-width:100%%}
pre{overflow-x:auto}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
/* The accent is the page's *type* colour, not just its link colour: the
   things that give a page its shape — headings, disclosure summaries, code
   spans, the emphasised head of a row — are all set in the organ's hue, so
   the page reads as its organ instead of as grey GitHub chrome. Semantics
   are untouched: anything carrying a class (ok/warn/bad, the pills, muted)
   keeps the colour that class means. */
b:not([class]),strong:not([class]){color:var(--accent)}
.muted{color:var(--muted)}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}
/* A bare list is page text, not a quotation. The UA's 40px indent steps it in
   from every other block on the page — measured on the Heart board, the
   evidence-gap bullets started at x=56 against a 16px body margin, which
   reads as a stray inset column on a phone. The lists that are layout rather
   than prose (.stats, .boards, ul.det) set their own padding and win on
   specificity. */
ul,ol{padding-left:1.15rem}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.92em;
 color:var(--accent);background:var(--tint);border:1px solid var(--edge);
 padding:.05em .35em;border-radius:5px}
/* --- hero: the logo, rendered as type ---------------------------------- */
.hero{margin:0 -1rem 1.4rem;padding:2.1rem 1.4rem 1.7rem;position:relative;
 overflow:hidden;text-align:center;color:#fff;background:var(--hero-base);
 background-image:radial-gradient(78%% 104%% at 50%% 14%%,
  var(--hero-lift) 0%%,var(--hero-base) 72%%)}
@media(min-width:46rem){.hero{margin:1rem 0 1.6rem;border-radius:16px}}
.hero::after{content:"";position:absolute;left:12%%;right:12%%;bottom:0;
 height:2px;background:linear-gradient(90deg,transparent,var(--glow),
 transparent);opacity:.75}
/* The mark carries its own ring, so the frame is light and glow only —
   the logos set their glyph on black with a halo, not in a chip. */
.orb{display:block;width:5.6rem;height:5.6rem;margin:0 auto .75rem;
 color:var(--glow);filter:drop-shadow(0 0 9px %(glow)s7a)}
.orb svg{display:block;width:100%%;height:100%%}
.hero h1{margin:0;font-size:1.85rem;line-height:1.1;font-weight:700;
 letter-spacing:-.022em;color:#fff}
/* Two wordmarks run their organ name as a gradient; for the rest --glow2
   repeats --glow, so the same rule paints a flat colour. */
.hero h1 b{font-weight:700;color:var(--glow);
 background:linear-gradient(96deg,var(--glow),var(--glow2));
 -webkit-background-clip:text;background-clip:text}
@supports(-webkit-background-clip:text){
 .hero h1 b{-webkit-text-fill-color:transparent}}
.hero .kind{display:block;margin-top:.5rem;font-size:.66rem;font-weight:600;
 letter-spacing:.26em;text-transform:uppercase;color:#ffffffa6}
/* The hairline with a lit dot at its centre: every logo separates wordmark
   from tagline with one, and it is the detail that reads as "same mark". */
.hero .rule{position:relative;width:11.5rem;height:1px;margin:1rem auto .75rem;
 background:linear-gradient(90deg,transparent,var(--glow),transparent);
 opacity:.7}
.hero .rule::after{content:"";position:absolute;left:50%%;top:50%%;
 width:.4rem;height:.4rem;margin:-.2rem 0 0 -.2rem;border-radius:50%%;
 background:var(--glow);box-shadow:0 0 7px 1px var(--glow)}
.hero .tag{margin:0;font-size:.63rem;font-weight:600;
 letter-spacing:.3em;text-transform:uppercase;color:var(--glow);opacity:.9}
.lede{margin:0 0 .9rem}
/* --- sections ---------------------------------------------------------- */
h2{font-size:1.1rem;margin:2.1rem 0 .3rem;padding:0 0 .35rem;font-weight:650;
 position:relative;color:var(--accent);border-bottom:2px solid var(--edge)}
/* The hero's lit rule, quieted and reused: the hairline under a section
   starts at full accent and fades into the edge tone. Purely the ::after,
   so a browser that skips it still gets the plain hairline. */
h2::after{content:"";position:absolute;left:0;bottom:-2px;width:44%%;height:2px;
 background:linear-gradient(90deg,var(--accent),var(--accent) 15%%,transparent)}
h2 a{color:inherit}
/* The heading is the accent; its parenthetical stays a quiet aside rather
   than competing at the same weight. */
h2 .muted{font-weight:400}
h3{font-size:.98rem;margin:1.3rem 0 .2rem;font-weight:650;color:var(--accent)}
/* --- rows -------------------------------------------------------------- */
.task{display:flex;gap:.6rem;align-items:flex-start;padding:.45rem .35rem;
 margin:0 -.35rem;border-bottom:1px solid var(--line);border-radius:7px}
.task:hover{background:var(--tint);box-shadow:inset 2px 0 0 var(--accent)}
.task p{margin:.25rem 0 0;flex:1}
button.copy{flex:0 0 auto;width:2.6rem;height:2.6rem;font-size:1.1rem;
 border:1px solid var(--edge);border-radius:9px;background:var(--tint);
 cursor:pointer;color:var(--accent);transition:border-color .12s,color .12s}
button.copy:hover{border-color:var(--accent);color:var(--accent)}
button.copy.ok{color:var(--ok);border-color:var(--ok);background:transparent}
button.copy.term{font-size:.95rem}
/* A copy button with a WORDED face is a chip, not an icon. The rule above is
   a fixed 2.6rem square — right for a bare clipboard glyph, a trap for a
   label: the text wraps inside 42px into a one-word-per-line column and
   spills out of its own box (observed on the health board's "clear them all"
   line). Size to the label instead, and hold it on one line the way `.pill`
   does — a chip that will not fit is elided, never allowed to push the page
   sideways. `vertical-align:bottom` because `overflow:hidden` moves an
   inline-block's baseline to its bottom edge. */
button.copy.text{width:auto;height:auto;max-width:100%%;padding:.34rem .62rem;
 font-size:.85rem;font-weight:600;white-space:nowrap;overflow:hidden;
 text-overflow:ellipsis;vertical-align:bottom}
button.more{display:block;width:100%%;margin:.7rem 0;padding:.55rem;
 border:1px dashed var(--edge);border-radius:9px;background:transparent;
 color:var(--muted);cursor:pointer;font:inherit;font-size:.9em}
button.more:hover{color:var(--accent);border-style:solid}
details{margin:.5rem 0}
summary{cursor:pointer;font-weight:600;padding:.4rem 0;color:var(--accent)}
summary::marker{color:var(--accent)}
/* --- facet pills: the backlog, scannable by colour --------------------- */
.facets{color:var(--muted);font-size:.85em}
.tags{display:block;margin-top:.32rem;line-height:1.9}
/* A pill is a LABEL, and a label that will not fit is elided, never allowed
   to push the page sideways. `nowrap` is what makes a chip read as a chip, so
   it is also the one thing the page-wide wrap guard above cannot reach: an
   over-long value (a board handing a whole log sentence to a facet) used to
   run a chip a thousand pixels wide. The row's prose carries the meaning; the
   chip carries the word. `vertical-align:bottom` because `overflow:hidden`
   moves an inline-block's baseline to its bottom edge. */
.pill{display:inline-block;max-width:100%%;padding:.06em .5em;border-radius:999px;
 font-size:.74em;font-weight:650;letter-spacing:.015em;white-space:nowrap;
 overflow:hidden;text-overflow:ellipsis;
 vertical-align:bottom;border:1px solid var(--edge);background:var(--tint);
 color:var(--accent)}
.pill+.pill{margin-left:.28rem}
.pill.n{border-color:var(--line);background:var(--btn);color:var(--muted)}
.pill.w{border-color:transparent;background:var(--btn);color:var(--muted);
 font-size:.7em;letter-spacing:.09em;text-transform:uppercase}
.pill.w.y{color:var(--warn);border-color:var(--warn);background:transparent}
.pill.g{border-color:var(--ok);background:transparent;color:var(--ok)}
.pill.y{border-color:var(--warn);background:transparent;color:var(--warn)}
.pill.r{border-color:var(--bad);background:transparent;color:var(--bad)}
/* --- stat strip -------------------------------------------------------- */
.stats{display:flex;flex-wrap:wrap;gap:.4rem;margin:0 0 1rem;padding:0;
 list-style:none}
.stats li{flex:1 1 auto;min-width:5.2rem;padding:.5rem .6rem;text-align:center;
 border:1px solid var(--line);border-radius:10px;background:var(--btn)}
.stats b{display:block;font-size:1.15rem;line-height:1.2;color:var(--accent);
 font-variant-numeric:tabular-nums}
.stats span{font-size:.68rem;letter-spacing:.1em;text-transform:uppercase;
 color:var(--accent);opacity:.75}
/* --- verdict banner ---------------------------------------------------- */
.verdict{margin:0 0 1rem;padding:.7rem .85rem;border-radius:10px;
 border:1px solid var(--line);border-left:4px solid var(--muted);
 background:var(--btn)}
.verdict.ok{border-left-color:var(--ok)}
.verdict.warn{border-left-color:var(--warn)}
.verdict.bad{border-left-color:var(--bad)}
.verdict b{display:block;font-size:1.02rem}
.verdict.ok b{color:var(--ok)}
.verdict.warn b{color:var(--warn)}
.verdict.bad b{color:var(--bad)}
/* --- tables ------------------------------------------------------------ */
table.recent{width:100%%;border-collapse:collapse;font-size:.95em}
table.recent td{border-bottom:1px solid var(--line);
 padding:.45rem .4rem .45rem 0;vertical-align:top}
table.recent tr:hover td{background:var(--tint)}
table.recent td.when{white-space:nowrap;color:var(--muted);
 font-variant-numeric:tabular-nums}
table.recent td.what{white-space:nowrap;color:var(--accent);font-size:.85em;
 padding-top:.58rem;opacity:.8}
table.recent td.pick{width:2.6rem;padding-right:0}
table.recent button.copy{width:2.2rem;height:2.2rem;font-size:.95rem}
/* On a phone a four-column row is not a row, it is a ribbon. Measured at a
   375px viewport: the meta columns took 156px and the text was left 187 — half
   the screen — so every entry wrapped into a tall thin column down the right
   while the meta cells sat beside it as empty height. Below 34rem the row
   stacks: the meta reads as one small header line with the button at its end,
   and the text takes the full width underneath. */
@media(max-width:34rem){
 /* `:not([hidden])` is load-bearing: `display:flex` here outranks the UA
    sheet's `[hidden]{display:none}`, which would reveal the whole paged
    Recent feed at once. */
 table.recent tr:not([hidden]){display:flex;flex-wrap:wrap;align-items:baseline;gap:0 .5rem;
  padding:.5rem 0;border-bottom:1px solid var(--line)}
 table.recent td{display:block;width:auto;border-bottom:0;padding:0}
 table.recent td.what{padding-top:0}
 table.recent td.pick{width:auto;margin-left:auto}
 table.recent td:not([class]){flex:1 0 100%%;margin-top:.15rem}
}
/* --- the family footer: one chip per sibling board, in its own colour --- */
.boards{display:flex;flex-wrap:wrap;gap:.4rem;margin:2.4rem 0 0;padding:0;
 list-style:none;border-top:1px solid var(--line);padding-top:1rem}
.boards a{display:inline-block;padding:.3rem .7rem;border-radius:999px;
 font-size:.82em;font-weight:600;border:1px solid currentColor;opacity:.85}
.boards a:hover{opacity:1;text-decoration:none}
.mdsrc{font-size:.85em}
"""

# One organ chip colour per scheme, appended to the sheet so the family
# footer shows each sibling in its own hue rather than six identical links.
_CHIP = ("%(sel)s{color:%(light)s}"
         "@media(prefers-color-scheme:dark){%(sel)s{color:%(dark)s}}")


def css(key):
    """The complete stylesheet for one organ's board."""
    o = organ(key)
    lift, base = o["hero"]
    sheet = _CSS % {"ink_light": o["ink_light"], "ink_dark": o["ink_dark"],
                    "glow": o["glow"], "glow2": o.get("glow2", o["glow"]),
                    "hero_lift": lift, "hero_base": base}
    chips = "".join(_CHIP % {"sel": f'.boards a[data-organ="{k}"]',
                             "light": v["ink_light"], "dark": v["ink_dark"]}
                    for k, v in ORGANS.items())
    return sheet + chips + "\n"


# ------------------------------------------------------------- components ---
def hero(key, kind, lede_html=""):
    """The masthead: the organ's logo re-drawn — mark, wordmark, rule, tagline.

    `kind` is what this page *is* under the wordmark ("Dashboard", "Board"),
    so the mark stays the organ's and the page keeps its own name.
    """
    o = organ(key)
    lede = f'<p class="lede">{lede_html}</p>' if lede_html else ""
    return (f'<header class="hero"><span class="orb">{mark(key)}</span>'
            f'<h1>{WORD}<b>{o["organ"]}</b>'
            f'<span class="kind">{kind}</span></h1>'
            f'<div class="rule"></div>'
            f'<p class="tag">{o["tagline"]}</p></header>{lede}')


# Facet vocabulary → pill tone. Anything unlisted falls back to the neutral
# tone, so a new `Difficulty:` value renders as a plain pill instead of
# silently taking someone else's colour.
# Colour marks the *exception*, never the default. `supervised` is 9 of every
# 10 prompts in the Mind — tinting it amber would paint the whole backlog and
# say nothing. So the majority value stays neutral and the tones are spent on
# what changes a decision: green go, amber caution, red handle-with-care.
_TONES = {
    "safe": "g",
    "large": "y",
    "high": "r", "too-large": "r", "human-required": "r",
}


# The PyAutoMind work-type taxonomy, one glyph each. The work type is what
# `draft/` is organised around and the one facet the boards never showed; a
# glyph carries it without spending colour, which is reserved for judgement.
WORK_TYPE_GLYPHS = {
    "feature": "✨", "bug": "\U0001f41b", "refactor": "♻️",
    "docs": "\U0001f4d6", "test": "\U0001f9ea", "release": "\U0001f680",
    "maintenance": "\U0001f9f9", "research": "\U0001f52c",
    "experiment": "⚗️", "human_review": "\U0001f440", "triage": "❓",
}


def pills(*values, work_type=None):
    """Facet values as a pill row.

    `work_type` leads when given — it is the category the whole taxonomy is
    built on, so it reads first, as a glyph plus a quiet uppercase tag rather
    than another coloured chip. `triage` is the exception: it means *nobody
    has classified this yet*, which is a real call to action.

    Of the positional values the first is the target repo/domain — it gets
    the organ accent, because it is identity, not judgement; the rest take
    their tone from `_TONES`, defaulting to neutral.

    `_TONES` is the *Mind's* facet vocabulary (a prompt's difficulty, autonomy
    and priority). A board whose rows carry different facets — a workflow
    conclusion, a Heart verdict, a version stamp — says its own tone by
    passing `(value, tone)` instead of a bare string, rather than growing that
    table with words it does not share. The tone is a class from the sheet:
    `g`/`y`/`r` for go/caution/handle-with-care, `n` for neutral, `""` for the
    organ accent.
    """
    out = []
    if work_type and work_type != "-":
        glyph = WORK_TYPE_GLYPHS.get(work_type, "")
        # Both of these are a call to action rather than a category: `triage`
        # means nobody has classified this, `human_review` means someone is
        # waiting on a person to read it.
        tone = " y" if work_type in ("triage", "human_review") else ""
        out.append(f'<span class="pill w{tone}">{glyph} {_esc(work_type)}'
                   f'</span>')
    first = True
    for v in values:
        tone = None
        if isinstance(v, tuple):
            v, tone = v
        if not v or v == "-":
            continue
        if tone is None:
            tone = "" if first else _TONES.get(v, "n")
        cls = f"pill {tone}".rstrip()
        out.append(f'<span class="{cls}">{_esc(v)}</span>')
        first = False
    return f'<span class="tags">{"".join(out)}</span>' if out else ""


def stats(*pairs):
    """The count strip: `(number, label)` pairs as accent-numbered tiles."""
    items = "".join(f"<li><b>{n}</b><span>{label}</span></li>"
                    for n, label in pairs)
    return f'<ul class="stats">{items}</ul>' if items else ""


def boards_footer(links, current):
    """The family footer — one chip per sibling board, each in its own
    organ's colour, so the six pages read as one system. `links` is the
    `name -> url` mapping from `config/policy.yaml` `board: boards:`."""
    chips = "".join(
        f'<li><a data-organ="{_esc(k)}" href="{_esc(url)}">'
        f'{organ(k)["organ"]}</a></li>'
        for k, url in links.items() if k != current)
    return (f'<ul class="boards"><li class="muted" style="padding:.3rem 0">'
            f'Boards:</li>{chips}</ul>') if chips else ""


# Shared by every board: one tap on a payload button copies it and flashes ✓.
# The textarea path covers browsers without the async clipboard API.
JS = """\
async function copyCmd(b){
  const cmd=b.dataset.cmd;
  try{await navigator.clipboard.writeText(cmd);}
  catch(e){const t=document.createElement("textarea");t.value=cmd;
    document.body.appendChild(t);t.select();document.execCommand("copy");
    t.remove();}
  const old=b.textContent;
  b.textContent="\\u2713";b.classList.add("ok");
  setTimeout(()=>{b.textContent=old;b.classList.remove("ok");},1200);}
document.addEventListener("click",e=>{
  const b=e.target.closest("button.copy");if(b)copyCmd(b);});
"""
