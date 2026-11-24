"""Autonomous orchestrators phase 3d (PyAutoBrain#568): the shift digest.

One test group per clause of the prompt's `Witness:`: the digest is appended
to the shift record in the `PyAutoMind/batches/AGENTS.md` format (brief work vs
backlog picks, each pick with its reason, one proof packet per task, every
counter); `batch brief --check` accepts it and refuses one missing a counter
or a pick reason; and it is posted exactly once — a second run posts nothing.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import _shift_fixtures as sf
from _shift_fixtures import BATCH, BRAIN, LEDGER_MERGE, NOW, git  # noqa: F401 — re-exported
import _brief  # noqa: E402
import _digest  # noqa: E402
import _orchestrator as orch  # noqa: E402

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
    - draft/feature/pyautoheart/named.md
    - draft/feature/pyautoheart/never.md
  - backlog: scoped
  - scoped:
    - epics: e1
  - review-minutes: 45
  - lanes: any local-dev
  - merge-cap: 1
  - token-budget: 1000
  - max-workers: 3
"""

# The fixture prompts target an organ other than Brain, Mind or Hands: a shift
# never dips those (PyAutoBrain#637, item 7), and these shifts dip `picked`.
PROMPT = """\
# {name}

Type: feature
Target: PyAutoHeart
Repos:
- PyAutoHeart
Difficulty: small
Autonomy: supervised
Priority: normal
Status: formalised
{epic}Consequence: glance
Witness: a unit test
Review-minutes: 3
Unattended: ready
Lane: any

Body.
"""

# A non-empty queue.md: an empty or absent one stops an unattended shift's
# backlog dip (M2.3), and these shifts dip for `picked`. Its one entry ranks
# nothing the brief admits, so every pick still reads "not in queue.md".
QUEUE = "# Queue\n\n## 1. Elsewhere\n- kind: prompt\n- ref: draft/feature/pyautoheart/outside.md\n"

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

    def spawn_closeout(self, task, pr_url, prompt_path, lease_dir, **_kw):
        # Phase 4b: a green glance PR gets a close-out; this one never reports.
        return {"pid": 0, "agent_id": "c0ffee00"}


class _Working:
    def state(self, agent_id):
        return "working"

    def session_of(self, agent_id):
        return None


def _mind(root: Path) -> Path:
    folder = root / "draft" / "feature" / "pyautoheart"
    folder.mkdir(parents=True)
    (folder / "named.md").write_text(PROMPT.format(name="named", epic=""))
    (folder / "picked.md").write_text(PROMPT.format(name="picked", epic="Epic: e1\n"))
    (folder / "outside.md").write_text(PROMPT.format(name="outside", epic=""))
    (root / "queue.md").write_text(QUEUE)
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
    assert counters["picks"]["picked"]["why"].startswith("scoped epic e1 · not in queue.md")
    assert "outside" not in counters["picks"]

    d = _digest.build(_brief.parse(brief.read_text())["brief"], slot, counters,
                      health=_health, issue=ISSUE)
    work = d.split("### Brief work")[1].split("### Backlog picks")[0]
    picks = d.split("### Backlog picks")[1].split("### Proof packets")[0]
    # Each task: the outcome in plain words and the title, linked to its PR
    # (never to a Mind path, which moves and 404s, #634); the detail below.
    # This fixture's worker wrote `merged` with no merge slot taken: the
    # digest says so from the slot file (R3, #661 review).
    assert ("- **Merged with NO merge slot — needs you** — [named](https://github.com/o/r/pull/1)\n"
            "  <sub>`named` · glance · small · pyautoheart · merged in-turn with NO merge slot"
            " — R3 revert-condition evidence</sub>") in work
    # The fixture writes no prompt for `never`: it says so (M3.6b, R5).
    assert ("- **Not started** — never\n  <sub>`never` · not started — skipped: no draft "
            "prompt for it (already issued to active/, retired or never pushed)</sub>") in work
    assert "blob/main" not in d
    # Green and glance: since phase 4b its close-out is running at review time.
    assert ("- **Still running — close-out checking it** — [picked](https://github.com/o/r/pull/2)\n"
            "  <sub>`picked` · glance · small · pyautoheart · close-out running"
            " · why: scoped epic e1 · not in queue.md") in picks
    assert "`named`" not in picks


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


@pytest.mark.parametrize("old, new, error", [
    pytest.param("- reverts: 0\n", "", "digest: counter reverts missing", id="a-missing-counter"),
    pytest.param(" · why: scoped epic e1", "", "digest: backlog pick picked has no `why:`",
                 id="a-pick-without-a-reason"),
    pytest.param("#### picked", "#### someone-else", "digest: picked has no proof packet",
                 id="a-task-without-a-packet"),
])
def test_brief_check_refuses(tmp_path, old, new, error):
    mind, brief, home = _shift(tmp_path)
    rec = _with_digest(tmp_path, brief, home, lambda d: d.replace(old, new))
    res = _brief.check(rec, mind)
    assert not res["ok"]
    assert any(e == error or e.startswith(error + " ") for e in res["errors"]), res["errors"]


# --- posted exactly once ---------------------------------------------------------

def test_the_digest_is_posted_once_and_a_second_run_posts_nothing(tmp_path):
    mind, brief, home = _shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    poster = Poster()
    r = orch.tick(brief, mind, home=home, now=AFTER, poster=poster, health=_health,
                  agents=_Working())
    assert r["action"] == "digest" and r["post"]["posted"], r
    assert len(poster.calls) == 1 and poster.calls[0][0] == ISSUE
    assert poster.calls[0][1].startswith("## Digest")
    assert (slot / orch.DIGEST_MARKER).exists()

    # The glance PR's close-out is still out: the late sweep keeps reaping it
    # (#632, F1) — and posts nothing more.
    again = orch.tick(brief, mind, home=home, now=AFTER + _dt.timedelta(minutes=5),
                      poster=poster, health=_health, agents=_Working())
    assert again["action"] == "late" and again["late"] == [] and len(poster.calls) == 1
    direct = orch.finish_shift(brief, mind, slot, AFTER, poster=poster, health=_health)
    assert direct["post"] == {"posted": False, "error": "already posted this shift"}
    assert len(poster.calls) == 1


def test_a_failed_post_is_retried_next_tick_up_to_its_tries(tmp_path):
    """#610 item 6: a post `gh` said failed is retried — marker first, so a
    landed post is never repeated — and stops after POST_TRIES."""
    mind, brief, home = _shift(tmp_path)
    calls = []

    def failing(issue, body_file):
        calls.append(issue)
        return {"posted": False, "error": "HTTP 502"}

    for minutes in range(0, 30, 5):
        orch.tick(brief, mind, home=home, now=AFTER + _dt.timedelta(minutes=minutes),
                  poster=failing, health=_health)
    assert calls == [ISSUE] * orch.POST_TRIES

    mind, brief, home = _shift(tmp_path / "ok")
    flaky = iter([{"posted": False, "error": "HTTP 502"},
                  {"posted": True, "url": ISSUE + "#issuecomment-2"}])
    seen = []
    poster = lambda i, b: seen.append(i) or next(flaky)  # noqa: E731
    for minutes in (0, 5, 10, 15):
        orch.tick(brief, mind, home=home, now=AFTER + _dt.timedelta(minutes=minutes),
                  poster=poster, health=_health)
    assert seen == [ISSUE, ISSUE]                       # retried once, then never again
    marker = json.loads((orch.slot_dir(brief, home) / orch.DIGEST_MARKER).read_text())
    assert marker["state"] == "posted" and marker["tries"] == 2


def test_a_post_that_may_have_landed_is_never_retried(tmp_path):
    mind, brief, home = _shift(tmp_path)
    calls = []

    def timeout(argv, **kw):
        calls.append(argv)
        raise subprocess.TimeoutExpired(argv, 120)
    poster = lambda i, b: orch.gh_comment(i, b, run=timeout)  # noqa: E731
    for minutes in (0, 5, 10):
        orch.tick(brief, mind, home=home, now=AFTER + _dt.timedelta(minutes=minutes),
                  poster=poster, health=_health)
    assert len(calls) == 1   # a timeout may have posted: a second would be two comments


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

@sf.needs_ledger_merge
def test_the_digest_lands_in_the_record_on_mind_main(tmp_path, monkeypatch):
    bare, canon = sf.ledger_mind(tmp_path, monkeypatch)
    _mind(canon)
    (canon / "batches").mkdir()
    brief = canon / "batches" / "2026-11-04-am.md"
    brief.write_text(BRIEF.format(issue=ISSUE, packet=""))
    sf.push(canon)

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
                   "merged": ["https://x/pull/1"], "issues": []}


def test_parse_done_keeps_issue_urls_out_of_prs():
    """#610 item 6: an issue a worker parked on is never a PR."""
    out = _digest.parse_done("https://github.com/o/r/issues/7\nhttps://github.com/o/r/pull/3\n")
    assert out["prs"] == ["https://github.com/o/r/pull/3"]
    assert out["issues"] == ["https://github.com/o/r/issues/7"]
    state, _ = _digest.task_state("t", {"outcomes": {"t": _digest.parse_done(
        "https://github.com/o/r/issues/7\n")}}, lambda u: 1 / 0)   # health never asked
    assert state == "https://github.com/o/r/issues/7 — PARKED-ON-ISSUE"


def _checks(*buckets):
    return json.dumps([{"name": f"c{i}", "bucket": b, "state": b.upper()}
                       for i, b in enumerate(buckets)])


@pytest.mark.parametrize("rc,out,err,want", [
    (0, _checks("pass", "pass"), "", "HEALTHY"),
    (0, _checks("pass", "skipping"), "", "HEALTHY"),
    (8, _checks("pass", "pending"), "", "RUNNING"),
    (1, _checks("pass", "fail"), "", "FAILED"),
    # gh's exit code counts a cancelled check as skipped: judged per check.
    (0, _checks("pass", "cancel"), "", "FAILED"),
    (1, "", "no checks reported on the 'x' branch", "NO-CHECKS"),
    # Only skipped checks: nothing completed, so nothing to call green.
    (0, _checks("skipping"), "", "NO-CHECKS"),
    (0, "[]", "", "NO-CHECKS"),
    (1, "", "HTTP 401: Bad credentials", "UNKNOWN"),
    (0, _checks("pass", "mystery"), "", "UNKNOWN"),
])
def test_pr_health_judges_every_check(rc, out, err, want):
    def run(argv, **kw):
        assert argv[:3] == ["gh", "pr", "checks"] and "--json" in argv
        return subprocess.CompletedProcess(argv, rc, out, err)
    assert _digest.pr_health("https://github.com/o/r/pull/1", run=run) == want
    assert _digest.pr_health("https://github.com/o/r/issues/3", run=run) == "PARKED-ON-ISSUE"


@pytest.mark.parametrize("backlog,record,want", [
    ("fill-idle", {"path": "x/a.md"}, "backlog: fill-idle"),
    ("fill-idle", {"path": "x/a.md", "queue_rank": 2, "queued": True}, "backlog: fill-idle · queue.md #3"),
    ("scoped", {"path": "x/a.md", "consequence": "notify", "queue_rank": 4, "queued": False,
                "review_minutes": 3, "priority": "high", "epic": "e1", "phase": 2.0},
     "scoped tier notify · not in queue.md · priority high · ~3 review-min · epic e1 phase 2"),
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


# --- M3.6j (PyAutoBrain#683): the digest's merge order -------------------------------

def test_683_the_digest_lists_each_librarys_merge_order_and_marks_the_next_prm(tmp_path):
    """A library's shift PRs merge in PR order: the digest names, per library,
    the PRs in order, ▶ on the one that needs the human's /prm now, and says
    of each later PR what it waits behind — and still validates."""
    mind, brief, home = _shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    c = orch.read_counters(slot)
    g7, g8, g9 = (f"https://github.com/example-org/autogalaxy/pull/{n}" for n in (7, 8, 9))
    c["outcomes"] = {"named": {"prs": [g7], "merged": [], "issues": []},
                     "picked": {"prs": [g9, g8], "merged": [], "issues": []}}
    c["closeouts"] = {g7: {"task": "named", "state": "refused",
                           "why": "decision-taken label → human /prm"}}
    c["merge_waits"] = {g8: {"task": "picked", "behind": [g7]},
                        g9: {"task": "picked", "behind": [g7, g8]}}
    d = _digest.build(_brief.parse(brief.read_text())["brief"], slot, c, health=_health,
                      issue=ISSUE)
    block = d.split("### Merge order")[1].split("### Proof packets")[0]
    lines = [ln.strip() for ln in block.strip().splitlines()]
    assert lines[0] == "- **autogalaxy**, merged in this order:"
    assert lines[1] == (f"- ▶ {g7} — needs your /prm: decision-taken label → human /prm")
    assert lines[2] == (f"- {g8} — waits behind autogalaxy#7 (needs your /prm: "
                        "decision-taken label → human /prm) — merge autogalaxy#7 first")
    assert lines[3].startswith(f"- {g9} — waits behind autogalaxy#7") \
        and "autogalaxy#8 (itself waiting)" in lines[3]
    assert "Waiting — merges after an earlier PR (your /prm first)" in d
    assert _digest.validate(d) == []
    # Nothing waits: no block.
    c["merge_waits"] = {}
    assert "### Merge order" not in _digest.build(
        _brief.parse(brief.read_text())["brief"], slot, c, health=_health, issue=ISSUE)


# --- PyAutoBrain#718: the review table at the top of the digest ----------------------

G = "https://github.com/example-org/autogalaxy/pull/"


def _row(task, counters, health=_health, tier="judge"):
    state, _ = _digest.task_state(task, counters, health)
    return _digest.review_row(task, counters, state, tier)


@pytest.mark.parametrize("counters, health, group", [
    pytest.param({"outcomes": {"t": {"prs": [G + "1"], "merged": [], "issues": []}},
                  "closeouts": {G + "1": {"state": "refused", "why": "tier judge — your /prm"}}},
                 _health, _digest.G_MERGE, id="awaiting-prm"),
    pytest.param({"outcomes": {"t": {"prs": [G + "1"], "merged": [], "issues": []}}},
                 _health, _digest.G_MERGE, id="ci-green"),
    pytest.param({"outcomes": {"t": {"prs": [G + "1"], "merged": [], "issues": []}}},
                 lambda u: "NO-CHECKS", _digest.G_MERGE, id="no-checks"),
    pytest.param({"outcomes": {"t": {"prs": [G + "1"], "merged": [G + "1"], "issues": []}}},
                 _health, _digest.G_MERGE, id="merged-with-no-slot-needs-you"),
    pytest.param({"outcomes": {"t": {"prs": [], "merged": [], "issues": [G[:-5] + "issues/3"]}}},
                 _health, _digest.G_ANSWER, id="parked-on-issue"),
    pytest.param({"parked": ["t"]}, _health, _digest.G_ANSWER, id="blocked-on-a-person"),
    pytest.param({"outcomes": {"t": {"prs": [G + "1"], "merged": [], "issues": []}}},
                 lambda u: "FAILED", _digest.G_FIX, id="ci-failed"),
    pytest.param({"abandoned": ["t"]}, _health, _digest.G_FIX, id="abandoned"),
    pytest.param({"pending_redispatch": ["t"]}, _health, _digest.G_FIX, id="not-redispatched"),
    pytest.param({}, _health, _digest.G_BLOCKED, id="not-started"),
    pytest.param({"dropped": {"t": {}}}, _health, _digest.G_BLOCKED, id="dropped"),
    pytest.param({"outcomes": {"t": {"prs": [], "merged": [], "issues": [], "obsolete": "done"}}},
                 _health, _digest.G_BLOCKED, id="obsolete"),
    pytest.param({"outcomes": {"t": {"prs": [G + "1"], "merged": [], "issues": []}}},
                 lambda u: "RUNNING", _digest.G_MERGE, id="ci-running-is-your-prm"),
    pytest.param({"outcomes": {"t": {"prs": [G + "1"], "merged": [], "issues": []}},
                  "closeouts": {G + "1": {"state": "running"}}},
                 _health, _digest.G_RUNNING, id="closeout-running"),
    pytest.param({"outcomes": {"t": {"prs": [G + "1"], "merged": [G + "1"], "issues": []}},
                  "closeouts": {G + "1": {"state": "merged", "model": "m"}}},
                 _health, _digest.G_DONE, id="merged-unattended"),
    pytest.param({"outcomes": {"t": {"prs": [], "merged": [], "issues": [G[:-5] + "issues/3"],
                                     "verdicts": [G[:-5] + "issues/3"]}}},
                 _health, _digest.G_DONE, id="verdict-posted"),
    pytest.param({"picks": {"t": {"proposed": True}}}, _health, _digest.G_PROPOSED,
                 id="proposed-shadow"),
])
def test_718_each_state_sits_in_its_action_group(counters, health, group):
    assert _row("t", counters, health)["group"] == group


def test_718_a_task_goes_to_its_most_urgent_group():
    """One PR merged, one awaiting /prm: the task is a Merge row, not Done."""
    c = {"outcomes": {"t": {"prs": [G + "1", G + "2"], "merged": [G + "1"], "issues": []}},
         "closeouts": {G + "1": {"state": "merged", "model": "m"},
                       G + "2": {"state": "refused", "why": "decision-taken — the human's /prm"}}}
    row = _row("t", c)
    assert row["group"] == _digest.G_MERGE
    assert row["open_prs"] == 1                       # the merged one is not counted
    assert row["cells"][3] == "Merged; decision-taken"   # in PR order


def test_718_groups_in_order_numbered_straight_through_and_empty_ones_left_out():
    rows = [{"group": g, "cells": [name, "judge", "—", "—"], "open_prs": 1}
            for g, name in [(_digest.G_DONE, "d"), (_digest.G_MERGE, "m1"),
                            (_digest.G_BLOCKED, "b"), (_digest.G_MERGE, "m2")]]
    lines = _digest.review_table_lines(rows)
    assert lines[0] == "### Review table"
    assert lines[1] == "2 to /prm (2 PRs) · 1 blocked or not started · 1 done"
    one = [{**rows[1], "open_prs": 1}]
    assert _digest.review_table_lines(one)[1] == "1 to /prm (1 PR)"
    body = [ln for ln in lines if ln.startswith("| ") and not ln.startswith("| # ")]
    assert body == ["| | **Merge: your /prm** | | | |", "| 1 | m1 | judge | — | — |",
                    "| 2 | m2 | judge | — | — |", "| | **Blocked or not started** | | | |",
                    "| 3 | b | judge | — | — |", "| | **Done** | | | |",
                    "| 4 | d | judge | — | — |"]
    assert not any("Answer" in ln or "Still running" in ln for ln in lines)
    assert _digest.review_table_lines([])[1].startswith("Nothing to review")


def test_718_a_multi_pr_task_lists_its_prs_in_merge_order_with_after():
    g7, g8, g9 = G + "7", G + "8", G + "9"
    lens = "https://github.com/example-org/autolens/pull/5"
    c = {"outcomes": {"t": {"prs": [g9, lens, g8], "merged": [], "issues": []}},
         "closeouts": {g7: {"state": "refused", "why": "tier judge — your /prm"}},
         "merge_waits": {g8: {"behind": [g7]}, g9: {"behind": [g7, g8]}}}
    row = _row("t", c)
    assert row["group"] == _digest.G_MERGE
    assert row["cells"][2] == (f"[autogalaxy#8]({g8}) after autogalaxy#7<br>"
                               f"[autogalaxy#9]({g9}) after autogalaxy#7, autogalaxy#8<br>"
                               f"[autolens#5]({lens})")


def test_718_pipes_and_newlines_never_break_the_table():
    c = {"picks": {"t": {"title": "a | b\nc"}},
         "backlog_gates": {"named": {"draft/x/t.md": "repo a|b held by\nsomeone"}}}
    row = _row("t", c)
    assert row["cells"][0] == r"a \| b c"
    assert row["cells"][3] == r"repo a\|b held by someone"
    line = _digest.review_table_lines([row])[-2]
    assert line.count("|") - line.count(r"\|") == 6     # 5 cells, never more


def test_718_the_digest_opens_with_the_table_and_brief_work_is_unchanged(tmp_path):
    """Built from a real shift: the table sits after the notices and before
    `### Brief work`, covers each named task and backlog pick once, leaves a
    settled carry-over out, and the record still validates."""
    mind, brief, home = _shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    c = orch.read_counters(slot)
    done = "https://github.com/o/r/pull/66"
    c["picks"]["carried"] = {"title": "Carried", "tier": "glance"}
    c["outcomes"]["carried"] = {"prs": [done], "merged": [], "issues": [],
                                "carried_from": "2026-11-03-am"}
    c["closeouts"] = {**(c.get("closeouts") or {}),
                      done: {"state": "refused", "settled": "merged", "why": "already merged"}}
    b = _brief.parse(brief.read_text())["brief"]
    d = _digest.build(b, slot, c, health=_health, issue=ISSUE)
    head, rest = d.split("### Brief work", 1)
    table = head.split("### Review table", 1)[1]
    assert head.index("## Digest") < head.index("### Review table")
    # `named` merged in-turn with no slot: it needs you, but no PR is left open.
    assert table.splitlines()[1] == "1 to /prm · 1 blocked or not started · 1 still running"
    rows = [ln for ln in table.splitlines() if ln[:2] == "| " and ln[2:3].isdigit()]
    assert [r.split(" | ")[1] for r in rows] == ["named", "never", "picked"]
    assert "Carried" not in table                         # settled: left out
    assert "| " not in rest.split("### Proof packets")[0]   # no table rows below
    # The entries below are exactly what they were (the earlier tests pin them).
    assert ("- **Merged with NO merge slot — needs you** — [named](https://github.com/o/r/pull/1)"
            in rest)
    assert _digest.validate(d) == []
    rec = tmp_path / "record.md"
    rec.write_text(brief.read_text() + "\n" + d)
    res = _brief.check(rec, mind)
    assert res["ok"], res["errors"]


_ONE = {"prs": [G + "1"], "merged": [], "issues": []}


def _co(state, **kw):
    return {"outcomes": {"t": dict(_ONE)}, "closeouts": {G + "1": {"state": state, **kw}}}


@pytest.mark.parametrize("counters, health, group, note", [
    pytest.param(_co("updated", after=[G + "0"]), lambda u: "FAILED", _digest.G_FIX,
                 "branch updated, CI FAILED", id="updated-ci-failed"),
    pytest.param(_co("updated", after=[G + "0"]), _health, _digest.G_MERGE,
                 "branch updated, CI HEALTHY", id="updated-ci-green"),
    pytest.param(_co("updated", after=[G + "0"]), lambda u: "RUNNING", _digest.G_MERGE,
                 "branch updated, CI RUNNING", id="updated-ci-running"),
    pytest.param(_co("current"), lambda u: "FAILED", _digest.G_FIX,
                 "branch up to date, CI FAILED", id="current-ci-failed"),
    pytest.param(_co("current"), _health, _digest.G_MERGE,
                 "branch up to date, CI HEALTHY", id="current-ci-green"),
    pytest.param(_co("current"), lambda u: "RUNNING", _digest.G_MERGE,
                 "branch up to date, CI RUNNING", id="current-ci-running"),
    pytest.param({"outcomes": {"t": dict(_ONE)}}, lambda u: "RUNNING", _digest.G_MERGE,
                 "CI still running", id="ci-running"),
    pytest.param({"outcomes": {"t": dict(_ONE)},
                  "sweep_waits": {G + "1": {"why": "workspace sweep unknown since 08:00Z"}}},
                 _health, _digest.G_MERGE, "workspace sweep unknown", id="sweep-wait"),
    pytest.param({"outcomes": {"t": {"prs": [], "merged": [], "issues": []}}}, _health,
                 _digest.G_BLOCKED, "finished, no PR or issue named", id="finished-no-pr"),
    pytest.param({"outcomes": {"t": {**_ONE, "merged": [G + "1"]}}}, _health, _digest.G_MERGE,
                 "merged with NO merge slot", id="in-turn-no-slot"),
    pytest.param({"outcomes": {"t": {**_ONE, "merged": [G + "1"]}},
                  "slot_holders": {_digest._merge_slots.pr_key(G + "1"): {"task": "t"}}},
                 _health, _digest.G_DONE, "Merged", id="in-turn-merged-with-slot"),
    pytest.param(_co("refused", settled="merged",
                     why="already merged since 2026-11-23-am3 (by someone)"),
                 _health, _digest.G_DONE, "Already merged — nothing to do", id="settled"),
    pytest.param({"outcomes": {"t": {**_ONE, "merged": [G + "1"]}}, "dropped": {"t": {}}},
                 _health, _digest.G_MERGE, "dropped by /drop; merged with NO merge slot",
                 id="dropped-but-merged-with-no-slot"),
    pytest.param({"outcomes": {"t": {"prs": [], "merged": [],
                                     "issues": [G[:-5] + "issues/3"]}}, "dropped": {"t": {}}},
                 _health, _digest.G_BLOCKED, "dropped by /drop; question on autogalaxy#3",
                 id="dropped-parked-stays-blocked"),
    pytest.param({"outcomes": {"t": dict(_ONE)}, "dropped": {"t": {}}},
                 lambda u: "FAILED", _digest.G_FIX, "dropped by /drop; CI failed — needs you",
                 id="dropped-but-ci-failed"),
])
def test_718_review_round_1_states(counters, health, group, note):
    row = _row("t", counters, health)
    assert (row["group"], row["cells"][3]) == (group, note)


def test_718_a_verdict_is_not_an_open_pr():
    c = {"outcomes": {"t": {"prs": [G + "1", G + "2"], "merged": [], "issues": [],
                            "verdicts": [G + "1"]}}}
    row = _row("t", c)
    assert row["group"] == _digest.G_MERGE and row["open_prs"] == 1
    assert _digest._count_line([row]) == "1 to /prm (1 PR)"


def test_718_cells_escape_html_and_never_double_escape_a_pipe():
    assert _digest._cell("<b>a</b> \\| b | c") == "&lt;b&gt;a&lt;/b&gt; \\| b \\| c"
