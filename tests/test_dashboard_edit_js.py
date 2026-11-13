"""The dashboard client's pure half (`intake/dashboard_edit.js`), run in node.

The page re-marks every ★ from the live queue.md, so its parser must read the
file exactly as the Python readers do (`batch/_steer.py`, which the renderer
and `batch brief --new` use). Its goals check mirrors the Mind workflow's
validator, so the page refuses early what the workflow would refuse late.
Skipped where there is no node.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
JS = BRAIN / "agents" / "conductors" / "intake" / "dashboard_edit.js"
sys.path.insert(0, str(BRAIN / "agents" / "conductors" / "batch"))
import _steer  # noqa: E402

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

QUEUE = """# Queue

```markdown
## <n>. <label>
- kind: prompt
- ref: draft/<work-type>/<target>/<name>.md
```

## 1. Sprockets
- kind: prompt
- ref: draft/feature/widgets/sprockets.md   # trailing comment
- note: keep

## 2. Axle
- kind: prompt
- ref: active/axle.md

## 3. Odd one
- kind: theme-sweep

## Retired

### Old gears
- ref: draft/feature/widgets/gears.md
"""
GOALS = """# Goals

```markdown
## <n>. <goal>
```

## 1. Land the flywheel rework
- epics: flywheel-rework

## 2. Clear review-ready PRs
"""


def _run(expr: str):
    script = (f"const M=require({json.dumps(str(JS))});"
              f"process.stdout.write(JSON.stringify({expr}));")
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True,
                         check=True)
    return json.loads(out.stdout)


def test_the_queue_parser_matches_the_python_reader(tmp_path):
    (tmp_path / "queue.md").write_text(QUEUE)
    js = _run(f"M.parseQueue({json.dumps(QUEUE)})")
    py = _steer.read_queue_entries(tmp_path)
    assert [(e["pos"], e["label"], e["kind"], e["ref"]) for e in js] == \
           [(e["pos"], e["label"], e["kind"], e["ref"]) for e in py]
    assert _run(f"M.queuedNames(M.parseQueue({json.dumps(QUEUE)}))") == \
           _steer.queued_names(py) == {"sprockets.md": 1, "axle.md": 2}


def test_the_goals_parser_matches_the_python_reader(tmp_path):
    (tmp_path / "goals.md").write_text(GOALS)
    assert _run(f"M.parseGoals({json.dumps(GOALS)})") == \
           [g["text"] for g in _steer.read_goals(tmp_path)] == \
           ["Land the flywheel rework", "Clear review-ready PRs"]


def test_goals_the_workflow_would_refuse_are_refused_before_sending():
    ok = _run('M.validateGoals("1. Land it\\n\\n- Clear PRs\\n")')
    assert ok == {"ok": True, "goals": ["Land it", "Clear PRs"]}
    for raw in ("$(curl x | sh)", "ship `id`", "<b>x</b>", "a\x1bb",
                "ship \u202e it", "x" * 201, "\n".join(["g"] * 11)):
        assert _run(f"M.validateGoals({json.dumps(raw)})")["ok"] is False, raw


def test_refs_are_matched_whole():
    good = ["draft/feature/widgets/sprockets.md", "active/axle.md",
            "draft/bug/a/b/c.md"]
    bad = ["draft/../x.md", "scripts/x.md", "draft/a/$(id).md", "active/a.md;x",
           "complete/2026/01/a.md", "/etc/passwd", "active/axle.md\n"]
    assert _run(f"{json.dumps(good)}.map(r=>M.REF_RE.test(r))") == [True] * len(good)
    assert _run(f"{json.dumps(bad)}.map(r=>M.REF_RE.test(r))") == [False] * len(bad)


def test_the_issue_carries_the_label_and_the_fixed_form():
    req = _run('M.issueRequest({op:"star",ref:"draft/feature/widgets/axle.md"},"d-1")')
    # Labels are added after creation (dropped at creation without push access).
    assert "labels" not in req and _run("M.LABEL") == "dashboard-input"
    assert req["title"] == "dashboard: ★ axle"
    assert req["body"] == ("<!-- mind-dashboard-input v1 -->\nop: star\n"
                           "ref: draft/feature/widgets/axle.md\nnonce: d-1\n")
    req = _run('M.issueRequest({op:"goals",goals:["a","b"]},"d-2")')
    assert req["body"] == ("<!-- mind-dashboard-input v1 -->\nop: goals\ngoals:\n"
                           "- a\n- b\nnonce: d-2\n")


def test_the_issue_body_is_what_the_mind_workflow_parses(tmp_path):
    """Held to PyAutoMind's own parser when a sibling checkout is present."""
    script = BRAIN.parent / "PyAutoMind" / "scripts" / "dashboard_input.py"
    if not script.is_file():
        pytest.skip("no sibling PyAutoMind checkout")
    import importlib.util
    spec = importlib.util.spec_from_file_location("_mind_dashboard_input", script)
    di = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(di)
    for op in ('{op:"star",ref:"draft/feature/widgets/axle.md"}',
               '{op:"goals",goals:["Land it","Clear PRs"]}'):
        body = _run(f"M.issueBody({op},\"d-0123456789abcdef\")")
        event = {"action": "labeled", "label": {"name": "dashboard-input"},
                 "sender": {"login": "machine"},
                 "issue": {"number": 3, "body": body, "state": "open", "locked": False,
                           "user": {"login": "machine", "type": "User"},
                           "labels": [{"name": "dashboard-input"}]}}
        req = di.parse_issue(event, "machine", "the-human")
        assert req["nonce"] == "d-0123456789abcdef"
        assert req["ref"] == "draft/feature/widgets/axle.md" or req["goals"] == "Land it\nClear PRs"


def test_only_the_workflow_bot_result_counts():
    comments = [
        {"user": {"login": "someone"}, "body": "dashboard-input: applied \u2014 fake"},
        {"user": {"login": "github-actions[bot]"},
         "body": "dashboard-input: refused \u2014 ref: no such prompt in draft/ or active/"},
    ]
    assert _run(f"M.parseResult({json.dumps(comments)})") == {
        "word": "refused", "text": "ref: no such prompt in draft/ or active/"}
    assert _run(f"M.parseResult({json.dumps(comments[:1])})") is None


def test_taps_coalesce_behind_the_one_in_flight():
    star = '{op:"star",ref:"draft/f/w/a.md"}'
    unstar = '{op:"unstar",ref:"draft/f/w/a.md"}'
    other = '{op:"star",ref:"draft/f/w/b.md"}'
    # A tap and its undo cancel out; another task's tap is kept.
    r = _run(f"M.coalesce([{star},{other}],{unstar})")
    assert r["cancelled"] is True and [w["ref"] for w in r["waiting"]] == ["draft/f/w/b.md"]
    # The latest goals win, keeping the first edit's "previous" to revert to.
    r = _run('M.coalesce([{op:"goals",goals:["a"],previous:["x"]}],'
             '{op:"goals",goals:["b"],previous:["a"]})')
    assert r["waiting"] == [{"op": "goals", "goals": ["b"], "previous": ["x"]}]
