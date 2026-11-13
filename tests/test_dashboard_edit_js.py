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


def test_refs_and_the_dispatch_body():
    good = ["draft/feature/widgets/sprockets.md", "active/axle.md",
            "draft/bug/a/b/c.md"]
    bad = ["draft/../x.md", "scripts/x.md", "draft/a/$(id).md", "active/a.md;x",
           "complete/2026/01/a.md", "/etc/passwd"]
    assert _run(f"{json.dumps(good)}.map(r=>M.REF_RE.test(r))") == [True] * len(good)
    assert _run(f"{json.dumps(bad)}.map(r=>M.REF_RE.test(r))") == [False] * len(bad)
    body = _run('M.dispatchBody({op:"star",ref:"active/axle.md"},"d-1")')
    assert body == {"ref": "main", "return_run_details": True,
                    "inputs": {"op": "star", "nonce": "d-1", "ref": "active/axle.md"}}
    body = _run('M.dispatchBody({op:"goals",goals:["a","b"]},"d-2")')
    assert body["inputs"] == {"op": "goals", "nonce": "d-2", "goals": "a\nb"}
