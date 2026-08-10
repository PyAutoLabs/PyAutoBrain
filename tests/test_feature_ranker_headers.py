"""tests/test_feature_ranker_headers.py — the ranker honours declared headers.

PyAutoMind/REFERENCE.md promises that the `Difficulty:` Intake persists is "the
value the Feature Agent later acts on", and defines `Status:` / `Priority:` /
`Blocked-by:` alongside it. The ranker previously read none of them, so a prompt
declaring `Status: blocked`, `Priority: low` AND an explicit `Blocked-by:` gate
came back as the recommended next pick.

Hermetic: every test fabricates a temp Mind, so nothing depends on the live
backlog — including the regression case, which pins the offending prompt's
HEADER SHAPE rather than the file itself. Fixtures use invented repo names so
the file carries no instance facts.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
FEATURE = BRAIN_HOME / "agents" / "conductors" / "feature" / "_feature.py"
sys.path.insert(0, str(BRAIN_HOME / "agents" / "faculties" / "sizing"))

from _sizing import declared_blocked, declared_header, parse_prompt  # noqa: E402


def _write(mind: Path, rel: str, body: str) -> Path:
    p = mind / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


def _prompt(title, *, difficulty=None, priority=None, status=None,
            blocked_by=None, extra=""):
    head = [f"# {title}", "", "Type: feature", "Target: widgets"]
    if difficulty:
        head.append(f"Difficulty: {difficulty}")
    if priority:
        head.append(f"Priority: {priority}")
    if status:
        head.append(f"Status: {status}")
    if blocked_by:
        head.append(f"Blocked-by: {blocked_by}")
    return "\n".join(head) + "\n\n" + (extra or "Some body text.") + "\n"


def _select(mind: Path, *args):
    r = subprocess.run(
        [sys.executable, str(FEATURE), "--mind", str(mind), "--json",
         "select", "--limit", "20", *args],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _order(shortlist):
    return [row["path"] for row in shortlist]


# --- the regression case ------------------------------------------------------

# The header shape of draft/feature/autonomy/10_scheduled_runs.md, which the
# ranker recommended as the next task to start. Pinned as a fixture, not read
# from the live file, so fixing the backlog cannot silently retire this test.
BLOCKED_SHAPE = _prompt(
    "Scheduled runs",
    difficulty="medium", priority="low", status="blocked",
    blocked_by="7_queue_runner.md (and transitively 1-5)",
    extra="Do not start before the queue runner has run cleanly.",
)


def test_blocked_prompt_is_never_the_recommended_pick(tmp_path):
    _write(tmp_path, "draft/feature/autonomy/scheduled_runs.md", BLOCKED_SHAPE)
    _write(tmp_path, "draft/feature/widgets/ordinary.md", _prompt("Ordinary"))
    d = _select(tmp_path)
    assert d["selected_task"].endswith("ordinary.md")
    # still listed, so a human can see and override it — just never recommended
    assert _order(d["shortlist"])[-1].endswith("scheduled_runs.md")
    assert d["shortlist"][-1]["blocked"]


def test_blocked_by_alone_is_enough_to_sink_a_prompt(tmp_path):
    _write(tmp_path, "draft/feature/widgets/gated.md",
           _prompt("Gated", blocked_by="Widget#12, Gadget#7"))
    _write(tmp_path, "draft/feature/widgets/ordinary.md", _prompt("Ordinary"))
    d = _select(tmp_path)
    assert d["selected_task"].endswith("ordinary.md")
    assert _order(d["shortlist"])[-1].endswith("gated.md")


def test_next_action_refuses_to_start_a_blocked_pick(tmp_path):
    _write(tmp_path, "draft/feature/widgets/only_one.md", BLOCKED_SHAPE)
    d = _select(tmp_path)
    assert "Do NOT start" in d["next_action"]


# --- declared difficulty wins -------------------------------------------------

# A short prompt derives `small`; declaring `too-large` must override it.
def test_declared_difficulty_overrides_the_derived_level(tmp_path):
    p = _write(tmp_path, "draft/feature/widgets/declared.md",
               _prompt("Declared", difficulty="too-large"))
    d = _select(tmp_path)
    row = d["shortlist"][0]
    assert row["difficulty"] == "too-large"
    assert row["difficulty_declared"] == "too-large"
    assert row["difficulty_derived"] != "too-large"
    assert d["difficulty_disagreement"] is True
    assert parse_prompt(p, tmp_path)["declared_difficulty"] == "too-large"


def test_derived_difficulty_still_used_when_none_declared(tmp_path):
    _write(tmp_path, "draft/feature/widgets/plain.md", _prompt("Plain"))
    d = _select(tmp_path)
    row = d["shortlist"][0]
    assert row["difficulty_declared"] is None
    assert row["difficulty"] == row["difficulty_derived"]
    assert d["difficulty_disagreement"] is False


# --- priority orders the shortlist --------------------------------------------

def test_priority_orders_two_otherwise_equal_prompts(tmp_path):
    body = "Some body text."
    _write(tmp_path, "draft/feature/widgets/a_low.md",
           _prompt("A", priority="low", extra=body))
    _write(tmp_path, "draft/feature/widgets/b_high.md",
           _prompt("B", priority="high", extra=body))
    order = _order(_select(tmp_path)["shortlist"])
    assert order[0].endswith("b_high.md")
    assert order[1].endswith("a_low.md")


def test_priority_is_honoured_under_the_impact_constraint_too(tmp_path):
    body = "Some body text."
    _write(tmp_path, "draft/feature/widgets/a_low.md",
           _prompt("A", priority="low", extra=body))
    _write(tmp_path, "draft/feature/widgets/b_high.md",
           _prompt("B", priority="high", extra=body))
    order = _order(_select(tmp_path, "--impact")["shortlist"])
    assert order[0].endswith("b_high.md")


# --- fenced blocks are documentation, not declarations ------------------------

def test_keys_inside_a_fence_are_not_read_as_declarations():
    """REFERENCE.md's own rule, and the reason it exists: a prompt that QUOTES
    another prompt's header (the bug prompt for this fix does) must not inherit
    it. Without this, the bug report would declare itself blocked."""
    text = (
        "# Explaining the keys\n\nType: bug\nPriority: high\n\n"
        "```\nDifficulty: too-large\nStatus: blocked\nPriority: low\n"
        "Blocked-by: Widget#1\n```\n\nreal body\n"
    )
    h = declared_header(text)
    assert h["priority"] == "high"          # the real declaration, outside the fence
    assert h["declared_difficulty"] is None  # the quoted ones are documentation
    assert h["status"] is None
    assert h["blocked_by"] == []
    assert declared_blocked(h) is None


def test_trailing_comment_is_stripped_but_a_ref_hash_survives():
    h = declared_header(
        "Difficulty: medium        # small | medium | large\n"
        "Blocked-by: Widget#1334, Gadget#1331   # WP1 gate (MERGED)\n"
    )
    assert h["declared_difficulty"] == "medium"
    assert h["blocked_by"] == ["Widget#1334, Gadget#1331"]


def test_unknown_difficulty_value_is_ignored_rather_than_trusted():
    assert declared_header("Difficulty: enormous\n")["declared_difficulty"] is None
