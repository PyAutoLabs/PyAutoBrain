"""The read-only Mind dashboard (PyAutoBrain#640): a ★ and the planner's rank
`#n` on every queued prompt row, a 📋 copy button carrying the task's prompt
text, Goals, Queue and Questions in one collapsible block straight above
Start here, built from the page's own conventions (PyAutoBrain#650) — and no
network: a CSP that pins the one inline script and
allows no connections.

Golden-HTML assertions on a fictional Mind. The queue is edited in a `/queue`
chat (Brain `skills/queue`, Mind `scripts/queue_edit.py`), never from the page.
"""

import base64
import hashlib
import importlib.util
import re
import sys
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "_intake_dashboard_queue_under_test",
    BRAIN_HOME / "agents" / "conductors" / "intake" / "_intake.py")
_intake = importlib.util.module_from_spec(_spec)
sys.modules["_intake_dashboard_queue_under_test"] = _intake
_spec.loader.exec_module(_intake)

PROMPT = ("# {title}\n\nType: feature\nTarget: widgets\nDifficulty: small\n"
          "Autonomy: supervised\nPriority: high\nStatus: formalised\n\nBody.\n")
QUEUE = """# Queue

```markdown
## <n>. <label>
- kind: prompt
- ref: draft/<work-type>/<target>/<name>.md
```

## 1. Sprockets first
- kind: prompt
- ref: draft/feature/widgets/sprockets.md

## 2. <img src=x onerror=alert(1)> axle
- kind: prompt
- ref: draft/feature/widgets/axle.md

## Retired

### Old gears
- shipped-as: Gadgets#1
- ref: draft/feature/widgets/gears.md
"""
GOALS = """# Goals

## 1. Land the flywheel rework
- epics: flywheel-rework

## 2. Keep <b>markup</b> out & escaped
"""


def _mind(root: Path, queue=QUEUE, goals=GOALS) -> Path:
    for rel, title in (("draft/feature/widgets/sprockets.md", "Sprockets"),
                       ("draft/feature/widgets/gears.md", "Gears"),
                       ("draft/feature/widgets/levers.md", "Levers")):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(PROMPT.format(title=title), encoding="utf-8")
    (root / "active").mkdir()
    (root / "active" / "axle.md").write_text(PROMPT.format(title="Axle"), encoding="utf-8")
    (root / "active.md").write_text("## axle\n- status: issued\n- prompt: active/axle.md\n")
    (root / "repos.yaml").write_text(
        "repos:\n  PyAutoMind:\n    github: example-owner/PyAutoMind\n")
    if queue is not None:
        (root / "queue.md").write_text(queue, encoding="utf-8")
    if goals is not None:
        (root / "goals.md").write_text(goals, encoding="utf-8")
    return root


def _html(mind: Path) -> str:
    return _intake.render_dashboard_html(_intake.census(mind))


STAR_RE = re.compile(r'<span class="star" title="Queued: #(\d+) in queue.md" '
                     r'aria-label="Queued, rank (\d+)">★<span class="qpos">#(\d+)</span></span>')


def _rows(page: str, ref: str) -> list:
    """Every task row (section rows and the Queue rows) that links `ref`."""
    rows = re.findall(r'<div class="task">.*?</div>', page, re.S)
    return [r for r in rows if f'/{ref}"' in r or f'"{ref}"' in r]


def test_queued_rows_show_a_star_and_the_planners_rank_only(tmp_path):
    page = _html(_mind(tmp_path))
    sprockets = _rows(page, "draft/feature/widgets/sprockets.md")
    axle = _rows(page, "active/axle.md")
    assert sprockets and axle
    for row in sprockets:
        assert [m for m in STAR_RE.findall(row)] == [("1", "1", "1")], row
    # Matched by basename: the active/ row is queued under its draft/ ref.
    for row in axle:
        assert STAR_RE.findall(row) == [("2", "2", "2")], row
    # Not queued (and the Retired footer's ref is history, not the queue).
    for ref in ("draft/feature/widgets/gears.md", "draft/feature/widgets/levers.md"):
        rows = _rows(page, ref)
        assert rows and not any('class="star"' in r for r in rows), ref
    # Every star on the page is one of the two queued prompts.
    assert {m[0] for m in STAR_RE.findall(page)} == {"1", "2"}
    assert page.count('class="star"') == len(STAR_RE.findall(page))


def test_rank_is_the_planners_order_not_the_heading_number(tmp_path):
    """`#n` comes from the planner's `read_queue` (kind: prompt entries in file
    order), not from the `## <n>.` the human typed."""
    queue = QUEUE.replace("## 1. Sprockets first", "## 7. Sprockets first").replace(
        "## 2. <img", "## 3. <img")
    queue = queue.replace("## Retired", "## 4. A non-prompt entry\n- kind: retired\n"
                          "- ref: draft/feature/widgets/levers.md\n\n## Retired")
    mind = _mind(tmp_path, queue=queue)
    sys.path.insert(0, str(BRAIN_HOME / "agents" / "conductors" / "batch"))
    import _steer
    assert _steer.read_queue(mind) == ["draft/feature/widgets/sprockets.md",
                                       "draft/feature/widgets/axle.md"]
    page = _html(mind)
    assert {m[0] for m in STAR_RE.findall(page)} == {"1", "2"}
    assert not any('class="star"' in r for r in _rows(page, "draft/feature/widgets/levers.md"))


def test_every_task_row_copies_its_prompt_text(tmp_path):
    page = _html(_mind(tmp_path))
    for ref in ("draft/feature/widgets/sprockets.md", "active/axle.md",
                "draft/feature/widgets/levers.md"):
        rows = _rows(page, ref)
        assert rows
        for row in rows:
            assert (f'<button class="copy" data-cmd="Use the start-dev skill. {ref}" '
                    'aria-label="Copy the AI command">📋</button>') in row, row
    # The Queue rows carry the same copy text, under their queue.md ref.
    box = _queue(page)
    assert box.count('<div class="task">') == 2
    assert ('data-cmd="Use the start-dev skill. draft/feature/widgets/axle.md"') in box
    # The copy handler is the shared one: async clipboard, textarea fallback.
    script = re.findall(r"<script>(.*?)</script>", page, re.S)[0]
    assert "navigator.clipboard.writeText" in script
    assert 'document.createElement("textarea")' in script


#: The shared collapsible block every section is folded into by
#: `board/_theme.section_layout` — closed by default (no `open`).
BLOCK = '<details class="board-section"><summary><h2>{title}'
STEER = "Autopilot"


def _block(page: str, title: str) -> str:
    """One whole section block, from its `<details>` to its `</details>`."""
    start = page.index(BLOCK.format(title=title))
    return page[start:page.index("</div></details>", start) + len("</div></details>")]


def _queue(page: str) -> str:
    """The Queue sub-part of the Autopilot block."""
    block = _block(page, STEER)
    return block[block.index('<h3 id="queue">'):block.index('<h3 id="inbox">')]


def test_one_autopilot_block_straight_above_start_here(tmp_path):
    """PyAutoBrain#650: Goals, Queue, Questions and Shift share ONE block — the
    same `details.board-section` as Start here and its siblings — directly
    above Start here, with one badge and four sub-parts in Start here's form,
    and a nav card of its own made by the same helper as the others."""
    mind = _mind(tmp_path)
    page = _html(mind)
    steer, start = (page.index(BLOCK.format(title=t)) for t in (STEER, "Start here"))
    assert page.index('<nav class="board-nav"') < steer < start
    block = _block(page, STEER)
    assert steer + len(block) == start                  # adjacent
    # Identical shell to every other section, closed, with one badge.
    assert block.startswith(f'<details class="board-section"><summary><h2>{STEER}</h2>'
                            '<span class="section-badge">2 queued · 0 questions</span>'
                            '</summary><div class="board-section-body"><a id="autopilot"></a>')
    assert block.count('class="section-badge"') == 1
    assert "<details open" not in page and 'class="board-section" open' not in page
    # Four sub-parts, Start here's `<h3>` + quiet `facets` note form.
    heads = re.findall(r'<h3 id="([a-z]+)">', block)
    assert heads == ["goals", "queue", "inbox", "shift"]
    assert '<p class="muted">(no shift yet)</p>' in block
    # The nav card: first, the shared helper's markup, the badge's number,
    # linking the block's anchor (the theme's section script opens it).
    nav = re.search(r'<nav class="board-nav".*?</nav>', page, re.S).group()
    cards = re.findall(r'<a class="board-nav-card" href="#([a-z-]+)">', nav)
    assert cards[:2] == ["autopilot", "start-here"]
    assert ('<a class="board-nav-card" href="#autopilot"><span class="board-nav-count">2'
            '</span><span class="board-nav-label">Autopilot</span>') in nav
    assert page.count('id="autopilot"') == 1
    md = _intake.render_dashboard(_intake.census(mind))
    assert "| [Autopilot](#autopilot) | 2 |" in md
    assert re.search(r'<h3 id="queue">Queue <span class="facets">\(read-only', block)
    # Queue rows are the page's ordinary `.task` rows: ★ rank, 📋, link.
    assert len(STAR_RE.findall(_queue(page))) == 2
    # Moved, not duplicated: no standalone boxes, no classes of their own.
    for gone in ('<aside', 'class="steer', 'class="inbox', "steer-queue",
                 "steer-goals", 'class="qid"', "Goals and queue", "<h2>Batch",
                 'class="verdict'):
        assert gone not in page, gone
    for gone in (".steer", ".inbox", "ol.steer-queue"):
        assert gone not in page[page.index("<style>"):page.index("</style>")], gone
    assert not re.search(r"<h2>(Goals|Queue|Questions)[ <]", page)


def test_the_autopilot_block_is_read_only(tmp_path):
    page = _html(_mind(tmp_path))
    block = _block(page, STEER)
    assert ("<ol><li>Land the flywheel rework</li>"
            "<li>Keep &lt;b&gt;markup&lt;/b&gt; out &amp; escaped</li></ol>") in block
    assert "&lt;img src=x onerror=alert(1)&gt; axle" in block
    assert "<img" not in page
    assert "<code>/queue</code>" in block
    for gone in ("<textarea", "<input", "<form", "<select", "contenteditable",
                 "<button type=\"button\"", "fetch("):
        assert gone not in block, gone
    for gone in ('type="password"', "steer-token", "steer-edit", "steer-toast",
                 "🔑", "Connect this device"):
        assert gone not in page, gone


def test_the_page_makes_no_api_call_and_its_csp_allows_none(tmp_path):
    page = _html(_mind(tmp_path))
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    assert len(scripts) == 1 and "<script src" not in page
    assert "fetch(" not in page and "XMLHttpRequest" not in page
    assert "api.github.com" not in page
    assert "localStorage" not in scripts[0]
    digest = base64.b64encode(hashlib.sha256(scripts[0].encode()).digest()).decode()
    csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', page)
    assert csp, "the page must carry its CSP"
    policy = dict(d.strip().split(" ", 1) for d in csp.group(1).split(";"))
    assert policy["default-src"] == "'none'"
    assert "connect-src" not in policy, "default-src 'none' already forbids connections"
    assert policy["script-src"] == f"'sha256-{digest}'"
    assert policy["base-uri"] == "'none'" and policy["form-action"] == "'none'"
    assert '<meta name="referrer" content="no-referrer">' in page
    assert page.index("Content-Security-Policy") < page.index("<style>")
    from html.parser import HTMLParser

    class Attrs(HTMLParser):
        names, tags = set(), set()

        def handle_starttag(self, tag, attrs):
            self.tags.add(tag)
            self.names.update(name for name, _v in attrs)

    seen = Attrs()
    seen.feed(page)
    assert not {n for n in seen.names if n.startswith("on")}
    assert not seen.tags & {"img", "iframe", "object", "embed", "link", "form", "input"}


def test_without_js_the_stars_and_rows_are_still_in_the_markup(tmp_path):
    """Everything but the copy action is server-rendered: strip the script and
    the stars, ranks, links and Queue block are all still there."""
    page = re.sub(r"<script>.*?</script>", "", _html(_mind(tmp_path)), flags=re.S)
    assert len(STAR_RE.findall(page)) >= 4
    assert _queue(page).count('<div class="task"><span class="star"') == 2
    assert 'href="https://github.com/example-owner/PyAutoMind/blob/main/draft/feature/widgets/sprockets.md"' in page \
        or 'href="draft/feature/widgets/sprockets.md"' in page


def test_the_csp_hash_is_stable_so_check_stays_deterministic(tmp_path):
    mind = _mind(tmp_path)
    a, b = _html(mind), _html(mind)
    csp = re.compile(r"script-src '(sha256-[^']+)'")
    assert csp.search(a).group(1) == csp.search(b).group(1)


def test_absent_queue_and_goals_render_empty_not_a_crash(tmp_path):
    mind = _mind(tmp_path, queue=None, goals=None)
    page = _html(mind)
    block = _block(page, STEER)
    # The page's empty-state form: one muted, parenthesised line per part.
    assert '<h3 id="goals">Goals</h3>\n<p class="muted">(no goals yet — edit in chat)</p>' in block
    assert ('<p class="muted">(queue is empty — add with <code>/queue</code>)</p>\n'
            '<h3 id="inbox">') in block
    assert '<p class="muted">(no open questions)</p>\n<h3 id="shift">' in block
    assert '<span class="section-badge">0 queued · 0 questions</span>' in block
    assert "<ol" not in block and 'class="task"' not in block
    assert 'class="star"' not in page
    md = _intake.render_dashboard(_intake.census(mind))
    assert "_(no goals yet — edit in chat)_" in md
    assert "_(queue is empty — add with `/queue`)_" in md
    assert "_(no open questions)_" in md


def test_the_markdown_page_shows_goals_and_queue_read_only(tmp_path):
    md = _intake.render_dashboard(_intake.census(_mind(tmp_path)))
    # Same shape as the HTML twin: one section, four sub-parts, then Start here.
    assert md.index("## Autopilot") < md.index("**Goals**") < md.index("**Queue**") \
        < md.index("**Questions**") < md.index("**Shift**") < md.index("## Start here")
    assert "\n## Goals\n" not in md and "\n## Queue\n" not in md and "\n## Questions" not in md
    goals = md[md.index("**Goals**"):md.index("**Queue**")]
    assert "1. Land the flywheel rework" in goals
    queue = md[md.index("**Queue**"):md.index("**Questions**")]
    assert "1. [Sprockets first](draft/feature/widgets/sprockets.md)" in queue
    assert "2. [" in queue and "](draft/feature/widgets/axle.md)" in queue
    assert "<img" not in queue
