"""The editable dashboard (PyAutoMind#565): ★ per task row, Goals at the top,
all under a CSP that pins the one inline script and allows only the GitHub API.

Golden-HTML assertions on a fictional Mind. The browser half (taps, the fake
API, phone widths, zero CSP violations) is `tests/dashboard_edit_browser.cjs`;
the client's pure parsers are held to the Python readers by
`test_dashboard_edit_js.py`.
"""

import base64
import hashlib
import importlib.util
import re
import sys
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "_intake_dashboard_input_under_test",
    BRAIN_HOME / "agents" / "conductors" / "intake" / "_intake.py")
_intake = importlib.util.module_from_spec(_spec)
sys.modules["_intake_dashboard_input_under_test"] = _intake
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


def _stars(page: str, ref: str) -> list:
    return re.findall(r'<button type="button" class="star" data-ref="'
                      + re.escape(ref) + r'"[^>]*>★<span class="qpos">([^<]*)</span>',
                      page)


def test_every_prompt_row_has_a_star_showing_the_queue(tmp_path):
    page = _html(_mind(tmp_path))
    # Queued: pressed, with its position, in every section it appears in.
    rows = re.findall(r'<button type="button" class="star" data-ref='
                      r'"draft/feature/widgets/sprockets.md"[^>]*aria-pressed="(\w+)"', page)
    assert rows and set(rows) == {"true"}
    assert set(_stars(page, "draft/feature/widgets/sprockets.md")) == {"1"}
    # Matched by basename: the active/ row is queued under its draft/ ref.
    assert set(_stars(page, "active/axle.md")) == {"2"}
    # Not queued — and the Retired footer's ref is history, not the queue.
    assert set(_stars(page, "draft/feature/widgets/gears.md")) == {""}
    assert 'data-ref="draft/feature/widgets/levers.md" data-title="Levers" '\
           'aria-pressed="false"' in page
    # Read-only until the script finds a token.
    for button in re.findall(r'<button type="button" class="star"[^>]*>', page):
        assert button.endswith(" disabled>")


def test_the_goals_and_queue_box_sits_above_the_section_cards(tmp_path):
    page = _html(_mind(tmp_path))
    box = page[page.index('<aside class="steer" id="steer"'):page.index("</aside>")]
    assert 'data-repo="example-owner/PyAutoMind"' in box
    assert page.index('<aside class="steer"') < page.index('<nav class="board-nav"')
    assert ('<ol id="steer-goals"><li>Land the flywheel rework</li>'
            "<li>Keep &lt;b&gt;markup&lt;/b&gt; out &amp; escaped</li></ol>") in box
    assert "goals.md is public" in box
    assert box.count('<li class="task" data-ref=') == 2
    assert "&lt;img src=x onerror=alert(1)&gt; axle" in box
    assert "<img" not in page
    assert 'id="steer-token"' in box and 'type="password"' in box
    assert "actions=write" in box and "target_name=example-owner" in box
    assert 'id="steer-toast" role="status"' in page


def test_the_page_runs_under_a_csp_pinning_its_one_script(tmp_path):
    page = _html(_mind(tmp_path))
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    assert len(scripts) == 1 and "<script src" not in page
    digest = base64.b64encode(hashlib.sha256(scripts[0].encode()).digest()).decode()
    csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', page)
    assert csp, "the page must carry its CSP"
    policy = dict(d.strip().split(" ", 1) for d in csp.group(1).split(";"))
    assert policy["default-src"] == "'none'"
    assert policy["script-src"] == f"'sha256-{digest}'"
    assert policy["connect-src"] == "https://api.github.com"
    assert policy["base-uri"] == "'none'" and policy["form-action"] == "'none'"
    assert '<meta name="referrer" content="no-referrer">' in page
    # The CSP must come before anything it governs.
    assert page.index("Content-Security-Policy") < page.index("<style>")
    # No inline handlers (the CSP would block them) and no element the hostile
    # queue label could have smuggled in: attribute names, as a parser sees them.
    from html.parser import HTMLParser

    class Attrs(HTMLParser):
        names, tags = set(), set()

        def handle_starttag(self, tag, attrs):
            self.tags.add(tag)
            self.names.update(name for name, _v in attrs)

    seen = Attrs()
    seen.feed(page)
    assert not {n for n in seen.names if n.startswith("on")}
    assert not seen.tags & {"img", "iframe", "object", "embed", "link", "form"}
    # The client is the inlined script, and it talks to nothing but the API.
    assert "pyautomind.dashboard.token.v1" in scripts[0]
    hosts = set(re.findall(r"https://([a-z0-9.-]+)", _intake._edit_js()))
    assert hosts <= {"api.github.com", "github.com"}, hosts


def test_the_csp_hash_is_stable_so_check_stays_deterministic(tmp_path):
    mind = _mind(tmp_path)
    a, b = _html(mind), _html(mind)
    csp = re.compile(r"script-src '(sha256-[^']+)'")
    assert csp.search(a).group(1) == csp.search(b).group(1)


def test_absent_queue_and_goals_render_empty_not_a_crash(tmp_path):
    mind = _mind(tmp_path, queue=None, goals=None)
    page = _html(mind)
    assert '<ol id="steer-goals"></ol>' in page
    assert '<p class="muted" id="steer-goals-empty">(no goals yet)</p>' in page
    assert '<p class="muted" id="steer-queue-empty">(nothing queued)</p>' in page
    assert 'aria-pressed="true" aria-label' not in page
    md = _intake.render_dashboard(_intake.census(mind))
    assert "_(no goals — write them in [`goals.md`](goals.md))_" in md


def test_the_markdown_page_shows_goals_and_queue_read_only(tmp_path):
    md = _intake.render_dashboard(_intake.census(_mind(tmp_path)))
    goals = md[md.index("## Goals"):md.index("## Queue")]
    assert "1. Land the flywheel rework" in goals
    queue = md[md.index("## Queue"):md.index("## Start here")]
    assert "1. [Sprockets first](draft/feature/widgets/sprockets.md)" in queue
    assert "<img" not in queue
