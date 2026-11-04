"""Autonomous orchestrators phase 4a (PyAutoBrain#570): shadow shifts + the pilot ledger.

The pilot's baseline is two shadow shifts: the orchestrator proposes and
digests, the human works as today. A shadow tick plans inside the brief and
records what it would have dispatched — no lease, no worker — and the shift's
`finish_shift` appends one row to `batches/pilot/pilot.md`.
"""

from __future__ import annotations

import datetime as _dt
import shutil
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "tests"))
import test_orchestrator_digest as t  # noqa: E402 — the 3d fixtures
from test_orchestrator_digest import _brief, _digest, orch  # noqa: E402

SHADOW = "  - shadow: yes\n"


class NoSpawn:
    def spawn(self, *a, **kw):
        raise AssertionError("a shadow shift must never spawn")


def _shadow(tmp_path: Path, extra=SHADOW, mind_root=None):
    mind = mind_root or t._mind(tmp_path / "mind")
    brief = (mind / "batches" / "2026-11-04-shadow.md") if mind_root else tmp_path / "shift.md"
    brief.parent.mkdir(parents=True, exist_ok=True)
    brief.write_text(t.BRIEF.format(issue=t.ISSUE, packet="") + extra)
    return mind, brief, tmp_path / "home"


def test_a_shadow_tick_proposes_with_reasons_and_spawns_nothing(tmp_path):
    mind, brief, home = _shadow(tmp_path)
    r = orch.tick(brief, mind, home=home, now=t.NOW, spawner=NoSpawn())
    assert r["action"] == "shadow" and r["spawned"] == []
    assert sorted(r["proposed"]) == ["named", "picked"]
    slot = orch.slot_dir(brief, home)
    assert orch.leases(slot) == {}
    picks = orch.read_counters(slot)["picks"]
    assert picks["named"] == {"prompt": "draft/feature/pyautobrain/named.md",
                              "why": "named task", "tier": "glance", "proposed": True,
                              "title": "named", "size": "small", "repos": ["pyautobrain"]}
    assert picks["picked"]["why"].startswith("scoped epic e1 · not in queue.md")
    assert orch.read_counters(slot)["sessions"] == 0


def test_a_second_shadow_tick_proposes_nothing_new(tmp_path):
    mind, brief, home = _shadow(tmp_path)
    orch.tick(brief, mind, home=home, now=t.NOW, spawner=NoSpawn())
    r = orch.tick(brief, mind, home=home, now=t.NOW + _dt.timedelta(minutes=1),
                  spawner=NoSpawn())
    assert r["proposed"] == []


def test_proposals_stop_at_max_sessions(tmp_path):
    mind, brief, home = _shadow(tmp_path, extra=SHADOW + "  - max-sessions: 1\n")
    r = orch.tick(brief, mind, home=home, now=t.NOW, spawner=NoSpawn())
    assert r["proposed"] == ["named"]


def test_the_shadow_digest_lists_proposals_and_validates(tmp_path):
    mind, brief, home = _shadow(tmp_path)
    orch.tick(brief, mind, home=home, now=t.NOW, spawner=NoSpawn())
    slot = orch.slot_dir(brief, home)
    d = _digest.build(_brief.parse(brief.read_text())["brief"], slot,
                      orch.read_counters(slot), health=t._health)
    assert "- **named** (`named`; small · pyautobrain) — proposed (shadow) — glance" in d
    assert "- **picked** (`picked`; small · pyautobrain) — proposed (shadow) — glance — why: scoped epic e1 · not in queue.md" in d
    assert "- never — not started" in d
    assert _digest.NO_PACKETS_SHADOW in d
    # Every counter is 0 in a shadow shift: one line, not nine.
    assert _digest.SHADOW_COUNTERS + " · review-minutes-planned: 45" in d
    assert "- merges: " not in d
    rec = tmp_path / "with_digest.md"
    rec.write_text(brief.read_text() + "\n" + d)
    res = _brief.check(rec, mind)
    assert res["ok"], res["errors"]


@pytest.mark.parametrize("value,ok", [("yes", True), ("no", True), ("maybe", False)])
def test_brief_check_validates_shadow(tmp_path, value, ok):
    mind, brief, _ = _shadow(tmp_path, extra=f"  - shadow: {value}\n")
    res = _brief.check(brief, mind)
    assert res["ok"] is ok
    if not ok:
        assert "brief.shadow: maybe — yes or no" in res["errors"]


def test_pilot_row_has_one_cell_per_column_and_leaves_the_humans_blank(tmp_path):
    mind, brief, home = _shadow(tmp_path)
    orch.tick(brief, mind, home=home, now=t.NOW, spawner=NoSpawn())
    slot = orch.slot_dir(brief, home)
    row = _digest.pilot_row(slot.name, _brief.parse(brief.read_text())["brief"],
                            orch.read_counters(slot))
    cells = [c.strip() for c in row.strip().strip("|").split("|")]
    assert len(cells) == len(_digest.PILOT_COLUMNS)
    got = dict(zip(_digest.PILOT_COLUMNS, cells))
    assert got["mode"] == "shadow" and got["slot"] == "shift"
    assert got["review-minutes-actual"] == "?" and got["overrules"] == "?"
    # Shadow merges are the human's own in the window — the baseline.
    assert got["merges"] == "?"
    assert got["review-minutes-planned"] == "45" and got["tokens"] == "0"


@pytest.mark.skipif(not t.LEDGER_MERGE.is_file() or shutil.which("git") is None,
                    reason="needs git and PyAutoMind's scripts/ledger_merge.py")
def test_a_shadow_shift_lands_exactly_one_pilot_row_on_mind_main(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    bare = tmp_path / "remote.git"
    t.git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    canon = tmp_path / "canon"
    t.git(tmp_path, "clone", "-q", str(bare), str(canon))
    t.git(canon, "config", "user.name", "Test")
    t.git(canon, "config", "user.email", "test@example.invalid")
    t._mind(canon)
    (canon / "scripts").mkdir()
    shutil.copy(t.LEDGER_MERGE, canon / "scripts" / "ledger_merge.py")
    (canon / "batches" / "pilot").mkdir(parents=True)
    (canon / "batches" / "pilot" / "pilot.md").write_text("# Pilot\n\n" + _digest.PILOT_HEADER)
    mind, brief, home = _shadow(tmp_path, mind_root=canon)
    t.git(canon, "add", "-A")
    t.git(canon, "commit", "-q", "-m", "seed")
    t.git(canon, "push", "-q", "origin", "HEAD:main")

    orch.tick(brief, canon, home=home, now=t.NOW, spawner=NoSpawn())
    r = orch.tick(brief, canon, home=home, now=t.AFTER, poster=t.Poster(), health=t._health)
    assert r["ledger"]["committed"], r
    pilot = t.git(bare, "show", "main:batches/pilot/pilot.md").stdout
    rows = [ln for ln in pilot.splitlines() if ln.startswith("| 2026-11-04-shadow ")]
    assert len(rows) == 1 and "| shadow |" in rows[0]
    assert pilot.count("| slot |") == 1  # the header was not appended twice
    landed = t.git(bare, "show", "main:batches/2026-11-04-shadow.md").stdout
    assert "proposed (shadow)" in landed and _digest.validate(landed) == []

    # A finished shift writes nothing more.
    slot = orch.slot_dir(brief, home)
    again = orch.finish_shift(brief, canon, slot, t.AFTER, poster=t.Poster(), health=t._health)
    assert again["ledger"] is None
    assert _digest.validate(t.git(bare, "show", "main:batches/2026-11-04-shadow.md").stdout) == []
    assert t.git(bare, "show", "main:batches/pilot/pilot.md").stdout == pilot


# --- readable picks (PyAutoBrain#579) ------------------------------------------

def test_titled_picks_validate_and_a_missing_why_names_the_slug(tmp_path):
    mind, brief, home = _shadow(tmp_path)
    orch.tick(brief, mind, home=home, now=t.NOW, spawner=NoSpawn())
    slot = orch.slot_dir(brief, home)
    d = _digest.build(_brief.parse(brief.read_text())["brief"], slot,
                      orch.read_counters(slot), health=t._health, issue=t.ISSUE)
    assert _digest.validate(d) == []
    import re
    bad = re.sub(r" — why: scoped epic e1[^\n]*", " — why: NOT RECORDED", d)
    assert any("backlog pick picked has no `why:`" in e for e in _digest.validate(bad))
    # The one-line shadow counters are accepted only as that line: a live
    # digest without its counters is still refused.
    live = d.replace(_digest.SHADOW_COUNTERS, "- something else")
    assert any("counter merges missing" in e for e in _digest.validate(live))


def test_an_old_untitled_digest_still_validates():
    """Shift 1 (2026-11-04) was digested before picks had titles."""
    old = ("## Digest\n\n### Brief work\n- none\n\n### Backlog picks\n"
           "- batch_slice — proposed (shadow) — notify — why: scoped tier notify\n\n"
           "### Proof packets\n- none — shadow shift: nothing was dispatched\n\n### Counters\n"
           + "".join(f"- {k}: 0\n" for k in _digest.COUNTERS))
    assert _digest.validate(old) == []
    assert _digest.label("batch_slice", {"prompt": "draft/x.md"}) == "batch_slice"


def test_a_live_pilot_row_counts_the_orchestrators_merges(tmp_path):
    brief = {"review-minutes": {"value": "30"}, "token-budget": {"value": "100"}}
    counters = orch.read_counters(tmp_path)
    counters["outcomes"] = {"a": {"prs": ["u"], "merged": ["u"]}}
    cells = dict(zip(_digest.PILOT_COLUMNS,
                     [c.strip() for c in _digest.pilot_row("s", brief, counters).strip().strip("|").split("|")]))
    assert cells["mode"] == "live" and cells["merges"] == "1"


def test_batch_watch_shows_titles(tmp_path):
    import _watch
    mind, brief, home = _shadow(tmp_path)
    orch.tick(brief, mind, home=home, now=t.NOW, spawner=NoSpawn())
    text = _watch.render(_watch.snapshot(brief, orch.slot_dir(brief, home), t.NOW, health=t._health))
    assert "- **named** (`named`; small · pyautobrain) — proposed (shadow)" in text
