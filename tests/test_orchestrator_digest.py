"""Autonomous orchestrators phase 3d (PyAutoBrain#568): the shift digest.

One test group per clause of the prompt's `Witness:`: the digest is appended
to the shift record in the `PyAutoMind/batches/AGENTS.md` format (brief work vs
backlog picks, each pick with its reason, one proof packet per task, every
counter); `batch brief --check` accepts it and refuses one missing a counter
or a pick reason; and it is posted exactly once — a second run posts nothing.
"""

from __future__ import annotations

import datetime as _dt
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
BATCH = BRAIN / "agents" / "conductors" / "batch"
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
sys.path.insert(0, str(BATCH))
import _brief  # noqa: E402
import _digest  # noqa: E402
import _orchestrator as orch  # noqa: E402

NOW = _dt.datetime(2026, 11, 4, 9, 0, tzinfo=_dt.timezone.utc)
AFTER = NOW + _dt.timedelta(hours=3)
ISSUE = "https://github.com/example-org/example-mind/issues/9999"

BRIEF = """\
# Batch 2026-11-04 am
- dispatched: 2026-11-04T08:30Z
- review-at: 2026-11-04T11:30Z
- issue: {issue}
{packet}- brief:
  - goals:
    - 1. dry shift
  - tasks:
    - draft/feature/pyautobrain/named.md
    - draft/feature/pyautobrain/never.md
  - backlog: scoped
  - scoped:
    - epics: e1
  - review-minutes: 45
  - lanes: any local-dev
  - merge-cap: 1
  - token-budget: 1000
  - max-workers: 3
"""

PROMPT = """\
# {name}

Type: feature
Target: PyAutoBrain
Repos:
- PyAutoBrain
Difficulty: small
Autonomy: supervised
Priority: normal
Status: formalised
{epic}Consequence: glance
Witness: a unit test
Review-minutes: 3
Unattended: ready

Body.
"""

PROOF = """\
#### named — https://github.com/o/r/pull/1
- claim: the thing is true
- witness: `pytest -q`
    3 passed
- not checked: nothing else
- revert: `git revert abc`
"""


class FilesSpawner:
    """A worker that has already finished: `.done` (and, for some, a proof)."""

    def __init__(self, done: dict[str, str], proofs: dict[str, str]):
        self.done, self.proofs = done, proofs

    def spawn(self, task, prompt_path, lease_dir):
        Path(lease_dir).mkdir(parents=True, exist_ok=True)
        if task in self.proofs:
            (Path(lease_dir) / f"{task}.proof.md").write_text(self.proofs[task])
        (Path(lease_dir) / f"{task}.done").write_text(self.done.get(task, ""))
        return {"pid": 0, "session_id": None, "worktree": None}

    def spawn_closeout(self, task, pr_url, prompt_path, lease_dir):
        # Phase 4b: a green glance PR gets a close-out; this one never reports.
        return {"pid": 0, "agent_id": "c0ffee00"}


class _Working:
    def state(self, agent_id):
        return "working"

    def session_of(self, agent_id):
        return None


def _mind(root: Path) -> Path:
    folder = root / "draft" / "feature" / "pyautobrain"
    folder.mkdir(parents=True)
    (folder / "named.md").write_text(PROMPT.format(name="named", epic=""))
    (folder / "picked.md").write_text(PROMPT.format(name="picked", epic="Epic: e1\n"))
    (folder / "outside.md").write_text(PROMPT.format(name="outside", epic=""))
    return root


def _run_shift(tmp_path: Path, brief: Path, mind: Path, home: Path):
    """Dispatch at NOW, reap one tick later — both workers finished."""
    sp = FilesSpawner(
        done={"named": "merged https://github.com/o/r/pull/1\n",
              "picked": "https://github.com/o/r/pull/2\n"},
        proofs={"named": PROOF})
    r = orch.tick(brief, mind, home=home, now=NOW, spawner=sp, health=_health,
                  agents=_Working())
    assert sorted(s["task"] for s in r["spawned"]) == ["named", "picked"], r
    orch.tick(brief, mind, home=home, now=NOW + _dt.timedelta(minutes=1), spawner=sp,
              health=_health, agents=_Working())


def _shift(tmp_path: Path, packet=""):
    mind = _mind(tmp_path / "mind")
    brief = tmp_path / "shift.md"
    brief.write_text(BRIEF.format(issue=ISSUE, packet=packet))
    home = tmp_path / "home"
    _run_shift(tmp_path, brief, mind, home)
    return mind, brief, home


class Poster:
    def __init__(self):
        self.calls = []

    def __call__(self, issue, body_file):
        self.calls.append((issue, Path(body_file).read_text()))
        return {"posted": True, "url": issue + "#issuecomment-1"}


def _health(url):
    return "HEALTHY"


# --- the digest's content -----------------------------------------------------------

def test_digest_separates_brief_work_from_backlog_picks_with_reasons(tmp_path):
    mind, brief, home = _shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    counters = orch.read_counters(slot)
    assert counters["picks"]["named"]["why"] == "named task"
    assert counters["picks"]["picked"]["why"] == "scoped epic e1"
    assert "outside" not in counters["picks"]

    d = _digest.build(_brief.parse(brief.read_text())["brief"], slot, counters,
                      health=_health)
    work = d.split("### Brief work")[1].split("### Backlog picks")[0]
    picks = d.split("### Backlog picks")[1].split("### Proof packets")[0]
    assert "- named — https://github.com/o/r/pull/1 — merged — glance" in work
    assert "- never — not started" in work
    # Green and glance: since phase 4b its close-out is running at review time.
    assert "- picked — https://github.com/o/r/pull/2 — close-out running — glance — why: scoped epic e1" in picks
    assert "named" not in picks


def test_one_proof_packet_per_task_and_an_honest_stub_when_missing(tmp_path):
    mind, brief, home = _shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    d = _digest.build(_brief.parse(brief.read_text())["brief"], slot,
                      orch.read_counters(slot), health=_health)
    packets = d.split("### Proof packets")[1].split("### Counters")[0]
    assert "- claim: the thing is true" in packets      # the worker's, verbatim
    assert "#### picked — https://github.com/o/r/pull/2" in packets
    assert "the worker wrote no proof packet" in packets
    assert "#### never" not in packets                  # never started, no packet


def test_every_counter_is_printed(tmp_path):
    mind, brief, home = _shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    d = _digest.build(_brief.parse(brief.read_text())["brief"], slot,
                      orch.read_counters(slot), health=_health)
    counters = d.split("### Counters")[1]
    for key in _digest.COUNTERS:
        assert f"- {key}: " in counters, key
    assert "- merges: 1" in counters
    assert "- tokens: 0 of 1000" in counters
    assert "- review-minutes-planned: 45" in counters
    assert "- glance-auto-merges: 0" in counters


# --- brief --check over the digest -----------------------------------------------

def _with_digest(tmp_path, brief, home, mutate=lambda d: d):
    slot = orch.slot_dir(brief, home)
    d = _digest.build(_brief.parse(brief.read_text())["brief"], slot,
                      orch.read_counters(slot), health=_health)
    rec = tmp_path / "record_with_digest.md"
    rec.write_text(brief.read_text() + "\n" + mutate(d))
    return rec


def test_brief_check_accepts_a_whole_digest(tmp_path):
    mind, brief, home = _shift(tmp_path)
    res = _brief.check(_with_digest(tmp_path, brief, home), mind)
    assert res["ok"], res["errors"]


def test_brief_check_refuses_a_missing_counter(tmp_path):
    mind, brief, home = _shift(tmp_path)
    rec = _with_digest(tmp_path, brief, home,
                       lambda d: d.replace("- reverts: 0\n", ""))
    res = _brief.check(rec, mind)
    assert not res["ok"] and "digest: counter reverts missing" in res["errors"]


def test_brief_check_refuses_a_pick_without_a_reason(tmp_path):
    mind, brief, home = _shift(tmp_path)
    rec = _with_digest(tmp_path, brief, home,
                       lambda d: d.replace(" — why: scoped epic e1", ""))
    res = _brief.check(rec, mind)
    assert not res["ok"]
    assert any("backlog pick picked has no `why:`" in e for e in res["errors"])


def test_brief_check_refuses_a_task_without_a_packet(tmp_path):
    mind, brief, home = _shift(tmp_path)
    rec = _with_digest(tmp_path, brief, home,
                       lambda d: d.replace("#### picked", "#### someone-else"))
    assert "digest: picked has no proof packet" in _brief.check(rec, mind)["errors"]


# --- posted exactly once ---------------------------------------------------------

def test_the_digest_is_posted_once_and_a_second_run_posts_nothing(tmp_path):
    mind, brief, home = _shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    poster = Poster()
    r = orch.tick(brief, mind, home=home, now=AFTER, poster=poster, health=_health)
    assert r["action"] == "digest" and r["post"]["posted"], r
    assert len(poster.calls) == 1 and poster.calls[0][0] == ISSUE
    assert poster.calls[0][1].startswith("## Digest")
    assert (slot / orch.DIGEST_MARKER).exists()

    again = orch.tick(brief, mind, home=home, now=AFTER + _dt.timedelta(minutes=5),
                      poster=poster, health=_health)
    assert again["action"] == "idle" and len(poster.calls) == 1
    direct = orch.finish_shift(brief, mind, slot, AFTER, poster=poster, health=_health)
    assert direct["post"] == {"posted": False, "error": "already posted this shift"}
    assert len(poster.calls) == 1


def test_a_failed_post_is_never_retried(tmp_path):
    mind, brief, home = _shift(tmp_path)
    calls = []

    def failing(issue, body_file):
        calls.append(issue)
        return {"posted": False, "error": "HTTP 502"}

    orch.tick(brief, mind, home=home, now=AFTER, poster=failing, health=_health)
    orch.tick(brief, mind, home=home, now=AFTER + _dt.timedelta(minutes=5),
              poster=failing, health=_health)
    assert calls == [ISSUE]  # a second comment would retire the watcher


def test_a_shift_that_never_ran_has_no_digest(tmp_path):
    mind = _mind(tmp_path / "mind")
    brief = tmp_path / "shift.md"
    brief.write_text(BRIEF.format(issue=ISSUE, packet=""))
    poster = Poster()
    r = orch.tick(brief, mind, home=tmp_path / "home", now=AFTER, poster=poster)
    assert r["action"] == "idle" and poster.calls == []


def test_stop_still_wins_after_review_at(tmp_path):
    mind, brief, home = _shift(tmp_path)
    (orch.slot_dir(brief, home) / orch.STOP_FILE).write_text("")
    poster = Poster()
    assert orch.tick(brief, mind, home=home, now=AFTER, poster=poster)["action"] == "stopped"
    assert poster.calls == []


def test_the_html_packet_is_opt_in(tmp_path):
    mind, brief, home = _shift(tmp_path)
    r = orch.tick(brief, mind, home=home, now=AFTER, poster=Poster(), health=_health)
    assert r["packet"] is None
    assert not (orch.slot_dir(brief, home) / "digest.html").exists()

    mind2, brief2, home2 = _shift(tmp_path / "b", packet="- packet: yes\n")
    r2 = orch.tick(brief2, mind2, home=home2, now=AFTER, poster=Poster(), health=_health)
    page = Path(r2["packet"]).read_text()
    assert "## Digest" in page and "<pre>" in page


# --- the record append, through the one Mind writer ------------------------------

LEDGER_MERGE = BRAIN.parent / "PyAutoMind" / "scripts" / "ledger_merge.py"
if not LEDGER_MERGE.is_file():
    LEDGER_MERGE = Path(os.environ.get("PYAUTO_MIND", "/nonexistent")) / "scripts" / "ledger_merge.py"


def git(cwd, *args):
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert res.returncode == 0, (args, res.stderr)
    return res


@pytest.mark.skipif(not LEDGER_MERGE.is_file() or shutil.which("git") is None,
                    reason="needs git and PyAutoMind's scripts/ledger_merge.py")
def test_the_digest_lands_in_the_record_on_mind_main(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    canon = tmp_path / "canon"
    git(tmp_path, "clone", "-q", str(bare), str(canon))
    git(canon, "config", "user.name", "Test")
    git(canon, "config", "user.email", "test@example.invalid")
    _mind(canon)
    (canon / "scripts").mkdir()
    shutil.copy(LEDGER_MERGE, canon / "scripts" / "ledger_merge.py")
    (canon / "batches").mkdir()
    brief = canon / "batches" / "2026-11-04-am.md"
    brief.write_text(BRIEF.format(issue=ISSUE, packet=""))
    git(canon, "add", "-A")
    git(canon, "commit", "-q", "-m", "seed")
    git(canon, "push", "-q", "origin", "HEAD:main")

    home = tmp_path / "home"
    _run_shift(tmp_path, brief, canon, home)
    status_before = git(canon, "status", "--porcelain").stdout
    r = orch.tick(brief, canon, home=home, now=AFTER, poster=Poster(), health=_health)
    assert r["ledger"]["committed"], r
    landed = git(bare, "show", "main:batches/2026-11-04-am.md").stdout
    assert "## Digest" in landed and "- reverts: 0" in landed
    assert git(canon, "status", "--porcelain").stdout == status_before

    # What landed is what `batch brief --check` accepts.
    fetched = tmp_path / "landed.md"
    fetched.write_text(landed)
    assert _digest.validate(landed) == []


# --- the small parts ---------------------------------------------------------------

def test_parse_done_reads_urls_and_merged_lines():
    out = _digest.parse_done("merged https://x/pull/1\nhttps://x/pull/2\n\nnoise\n")
    assert out == {"prs": ["https://x/pull/1", "https://x/pull/2"],
                   "merged": ["https://x/pull/1"]}


@pytest.mark.parametrize("rc,err,want", [(0, "", "HEALTHY"), (8, "", "RUNNING"),
                                         (1, "", "FAILED"),
                                         (1, "no checks reported", "NO-CHECKS")])
def test_pr_health_reads_the_gh_exit_code(rc, err, want):
    def run(argv, **kw):
        assert argv[:3] == ["gh", "pr", "checks"]
        return subprocess.CompletedProcess(argv, rc, "", err)
    assert _digest.pr_health("https://github.com/o/r/pull/1", run=run) == want
    assert _digest.pr_health("https://github.com/o/r/issues/3", run=run) == "PARKED-ON-ISSUE"


@pytest.mark.parametrize("backlog,record,want", [
    ("fill-idle", {"path": "x/a.md"}, "backlog: fill-idle (the planner's ranking)"),
    ("scoped", {"path": "x/a.md", "themes": ["jax"]}, "scoped tag jax"),
    ("scoped", {"path": "x/a.md", "consequence": "notify"}, "scoped tier notify"),
    ("scoped", {"path": "x/named.md"}, "named task"),
])
def test_pick_reason_names_the_rule(backlog, record, want):
    brief = {"backlog": {"value": backlog, "children": []},
             "scoped": {"value": "", "children": [
                 {"text": "tags: jax", "children": []},
                 {"text": "tiers: notify", "children": []}]},
             "tasks": {"value": "", "children": [{"text": "x/named.md", "children": []}]}}
    assert _brief.pick_reason(record, brief) == want


def test_batch_digest_verb_prints_and_writes_nothing(tmp_path):
    mind, brief, home = _shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    before = sorted(p.name for p in slot.rglob("*"))
    env = {**os.environ, "PATH": "/nonexistent"}  # no gh: health says UNKNOWN
    res = subprocess.run([sys.executable, str(BATCH / "_batch.py"), "digest",
                          "--record", str(brief), "--home", str(home),
                          "--mind", str(mind)],
                         capture_output=True, text=True, env=env)
    assert res.returncode == 0, res.stderr
    assert res.stdout.startswith("## Digest") and "- merges: 1" in res.stdout
    assert sorted(p.name for p in slot.rglob("*")) == before
    assert not (slot / orch.DIGEST_MARKER).exists()
