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

The design in one line: *the page wears its organ's logo*. Each organ has an
accent taken from its logo's glyph colour, and every board opens with a dark
hero reproducing that logo's wordmark — white `PyAuto`, accent-coloured organ
name, letterspaced tagline underneath, inside the logo's ring. Below the hero
the page returns to a plain readable document, because these are lists people
scan on a phone before breakfast, not dashboards to admire.

Colour carries meaning, never decoration:

* the **accent** is organ identity — one hue per board, used for links,
  section rules, stats and the hero;
* **pills** are the task facets (target, difficulty, autonomy, priority), so
  a backlog can be scanned by colour instead of read word by word;
* **ok / warn / bad** stay reserved for the verdict semantics they already
  carry on the Heart-style boards.

`ORGANS` is the palette table, keyed by the same board names as
`config/policy.yaml` `board: boards:` — that mapping is the declared config
surface an adopting fork replaces, so no repo is named here. Five of the six
palettes are sampled from the actual logo files: the glyph colour and the
wordmark's own tagline, straight off `logo.png` in each organ's repo. The
umbrella board has no logo, so its accent and tagline are designed to sit in
the family instead. Every accent is checked for >= 4.5:1 contrast against
its own background (light on `#fff`, dark on `#0d1117`).
"""

# ---------------------------------------------------------------- palette ---
# ink_light / ink_dark: the accent as *text*, per colour scheme.
# glow:  the logo's own glyph colour — used only on the dark hero, where it
#        needs to sing rather than pass a contrast check against white.
# hero:  (lift, base) — the hero's radial gradient, echoing each logo's
#        vignette: a tinted lift behind the wordmark falling to near-black.
ORGANS = {
    "mind": {
        "organ": "Mind",
        "glyph": "\U0001f4cb", "tagline": "Intent. Priority. Flow.",
        "ink_light": "#0a7d72", "ink_dark": "#2ee6cf", "glow": "#00d1ba",
        "hero": ("#0a3f39", "#000000"),
    },
    "brain": {
        "organ": "Brain",
        "glyph": "\U0001f9e0", "tagline": "Reason. Plan. Decide.",
        "ink_light": "#2159c9", "ink_dark": "#6f9dff", "glow": "#4d8bff",
        "hero": ("#1b2a6b", "#000312"),
    },
    "heart": {
        "organ": "Heart",
        "glyph": "❤️", "tagline": "Check. Validate. Protect.",
        "ink_light": "#b50f1a", "ink_dark": "#ff6b73", "glow": "#ff1c28",
        "hero": ("#4a0a10", "#000000"),
    },
    "hands": {
        "organ": "Hands",
        "glyph": "\U0001f6e0️", "tagline": "Build. Execute. Deliver.",
        "ink_light": "#9a5400", "ink_dark": "#ffa733", "glow": "#ff9201",
        "hero": ("#4a2c00", "#000000"),
    },
    "memory": {
        "organ": "Memory",
        "glyph": "\U0001f4da", "tagline": "Remember. Learn. Evolve.",
        "ink_light": "#6b34d6", "ink_dark": "#b37eff", "glow": "#b37eff",
        "hero": ("#2e1a5c", "#000000"),
    },
    # The umbrella is the one board with no logo to sample: the accent and
    # the tagline are designed to sit in the family rather than read off a
    # file. Replace both from the logo if that repo ever grows one.
    "organism": {
        "organ": "Scientist",
        "glyph": "\U0001f9ec", "tagline": "Describe. Build. Release.",
        "ink_light": "#0b6fa4", "ink_dark": "#5ec7f5", "glow": "#38bdf8",
        "hero": ("#0c3f5c", "#00070d"),
    },
}

import html as _html

WORD = "PyAuto"  # the half of every wordmark that stays white


def _esc(value):
    return _html.escape(str(value), quote=True)


def organ(key):
    """The palette entry for a board, or the umbrella's when `key` is
    unknown — an adopting fork gets a styled page rather than a crash."""
    return ORGANS.get(key, ORGANS["organism"])


# -------------------------------------------------------------------- css ---
# One stylesheet, two colour schemes, one substituted accent. Kept in the
# same dense hand-wrapped style as the renderers that inline it: this ships
# inside every page, and these pages are opened on phones over mobile data.
_CSS = """\
:root{color-scheme:light dark;--bg:#fff;--fg:#1f2328;--muted:#59636e;
 --line:#d8dee4;--btn:#f6f8fa;--ok:#1a7f37;--warn:#9a6700;--bad:#d1242f;
 --accent:%(ink_light)s;--tint:%(ink_light)s14;--edge:%(ink_light)s3d;
 --hero-lift:%(hero_lift)s;--hero-base:%(hero_base)s;--glow:%(glow)s}
@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#f0f6fc;
 --muted:#9198a1;--line:#2c333c;--btn:#151b23;--ok:#3fb950;--warn:#d29922;
 --bad:#f85149;--accent:%(ink_dark)s;--tint:%(ink_dark)s1f;
 --edge:%(ink_dark)s47}}
*{box-sizing:border-box}
body{margin:0 auto;max-width:44rem;padding:0 1rem 4rem;background:var(--bg);
 color:var(--fg);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",
 Helvetica,Arial,sans-serif;-webkit-text-size-adjust:100%%}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.muted{color:var(--muted)}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.92em;
 background:var(--btn);border:1px solid var(--line);padding:.05em .35em;
 border-radius:5px}
/* --- hero: the logo, rendered as type ---------------------------------- */
.hero{margin:0 -1rem 1.4rem;padding:2.1rem 1.4rem 1.7rem;position:relative;
 overflow:hidden;text-align:center;color:#fff;background:var(--hero-base);
 background-image:radial-gradient(105%% 130%% at 50%% -25%%,
  var(--hero-lift) 0%%,var(--hero-base) 68%%)}
@media(min-width:46rem){.hero{margin:1rem 0 1.6rem;border-radius:16px}}
.hero::after{content:"";position:absolute;left:12%%;right:12%%;bottom:0;
 height:2px;background:linear-gradient(90deg,transparent,var(--glow),
 transparent);opacity:.75}
.orb{display:inline-flex;align-items:center;justify-content:center;
 width:3.1rem;height:3.1rem;margin-bottom:.85rem;border-radius:50%%;
 font-size:1.45rem;line-height:1;border:1.5px solid var(--glow);
 background:radial-gradient(circle,#ffffff14 0%%,transparent 70%%);
 box-shadow:0 0 22px -4px var(--glow)}
.hero h1{margin:0;font-size:1.85rem;line-height:1.1;font-weight:700;
 letter-spacing:-.022em;color:#fff}
.hero h1 b{color:var(--glow);font-weight:700}
.hero .kind{display:block;margin-top:.5rem;font-size:.66rem;font-weight:600;
 letter-spacing:.26em;text-transform:uppercase;color:#ffffffa6}
.hero .tag{margin:.85rem 0 0;font-size:.63rem;font-weight:600;
 letter-spacing:.3em;text-transform:uppercase;color:var(--glow);opacity:.9}
.lede{margin:0 0 .9rem}
/* --- sections ---------------------------------------------------------- */
h2{font-size:1.1rem;margin:2.1rem 0 .3rem;padding:0 0 .35rem;font-weight:650;
 border-bottom:2px solid var(--edge)}
h3{font-size:.98rem;margin:1.3rem 0 .2rem;font-weight:650;color:var(--accent)}
/* --- rows -------------------------------------------------------------- */
.task{display:flex;gap:.6rem;align-items:flex-start;padding:.45rem .35rem;
 margin:0 -.35rem;border-bottom:1px solid var(--line);border-radius:7px}
.task:hover{background:var(--tint)}
.task p{margin:.25rem 0 0;flex:1;overflow-wrap:anywhere}
button.copy{flex:0 0 auto;width:2.6rem;height:2.6rem;font-size:1.1rem;
 border:1px solid var(--line);border-radius:9px;background:var(--btn);
 cursor:pointer;color:var(--fg);transition:border-color .12s,color .12s}
button.copy:hover{border-color:var(--accent);color:var(--accent)}
button.copy.ok{color:var(--ok);border-color:var(--ok);background:transparent}
button.copy.term{font-size:.95rem}
button.more{display:block;width:100%%;margin:.7rem 0;padding:.55rem;
 border:1px dashed var(--edge);border-radius:9px;background:transparent;
 color:var(--muted);cursor:pointer;font:inherit;font-size:.9em}
button.more:hover{color:var(--accent);border-style:solid}
details{margin:.5rem 0}
summary{cursor:pointer;font-weight:600;padding:.4rem 0}
summary::marker{color:var(--accent)}
/* --- facet pills: the backlog, scannable by colour --------------------- */
.facets{color:var(--muted);font-size:.85em}
.tags{display:block;margin-top:.32rem;line-height:1.9}
.pill{display:inline-block;padding:.06em .5em;border-radius:999px;
 font-size:.74em;font-weight:650;letter-spacing:.015em;white-space:nowrap;
 vertical-align:.09em;border:1px solid var(--edge);background:var(--tint);
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
 color:var(--muted)}
/* --- verdict banner ---------------------------------------------------- */
.verdict{margin:0 0 1rem;padding:.7rem .85rem;border-radius:10px;
 border:1px solid var(--line);border-left:4px solid var(--muted);
 background:var(--btn)}
.verdict.ok{border-left-color:var(--ok)}
.verdict.warn{border-left-color:var(--warn)}
.verdict.bad{border-left-color:var(--bad)}
.verdict b{display:block;font-size:1.02rem}
/* --- tables ------------------------------------------------------------ */
table.recent{width:100%%;border-collapse:collapse;font-size:.95em}
table.recent td{border-bottom:1px solid var(--line);
 padding:.45rem .4rem .45rem 0;vertical-align:top;overflow-wrap:anywhere}
table.recent tr:hover td{background:var(--tint)}
table.recent td.when{white-space:nowrap;color:var(--muted);
 font-variant-numeric:tabular-nums}
table.recent td.what{white-space:nowrap;color:var(--muted);font-size:.85em;
 padding-top:.58rem}
table.recent td.pick{width:2.6rem;padding-right:0}
table.recent button.copy{width:2.2rem;height:2.2rem;font-size:.95rem}
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
                    "glow": o["glow"], "hero_lift": lift, "hero_base": base}
    chips = "".join(_CHIP % {"sel": f'.boards a[data-organ="{k}"]',
                             "light": v["ink_light"], "dark": v["ink_dark"]}
                    for k, v in ORGANS.items())
    return sheet + chips + "\n"


# ------------------------------------------------------------- components ---
def hero(key, kind, lede_html=""):
    """The masthead: the organ's logo re-drawn as type.

    `kind` is what this page *is* under the wordmark ("Dashboard", "Board"),
    so the mark stays the organ's and the page keeps its own name.
    """
    o = organ(key)
    lede = f'<p class="lede">{lede_html}</p>' if lede_html else ""
    return (f'<header class="hero"><span class="orb">{o["glyph"]}</span>'
            f'<h1>{WORD}<b>{o["organ"]}</b>'
            f'<span class="kind">{kind}</span></h1>'
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
    "experiment": "⚗️", "triage": "❓",
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
    """
    out = []
    if work_type and work_type != "-":
        glyph = WORK_TYPE_GLYPHS.get(work_type, "")
        tone = " y" if work_type == "triage" else ""
        out.append(f'<span class="pill w{tone}">{glyph} {_esc(work_type)}'
                   f'</span>')
    first = True
    for v in values:
        if not v or v == "-":
            continue
        cls = "pill" if first else f'pill {_TONES.get(v, "n")}'
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
