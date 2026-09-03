"""tests/test_batch_collect.py — the Batch Agent's collection rules.

`batches/AGENTS.md` states the rule every test here defends: **a green session
is not a delivered task**. A member counts as delivered only with a PR that has
a non-empty diff and checks that actually ran, and a member that ends green
with no PR is reported not delivered, loudly. So most of these are refusals
too — refusals to call something delivered on evidence that does not say so,
and refusals to invent evidence that is simply not here.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
_spec = importlib.util.spec_from_file_location(
    "_batch_collect_under_test",
    BRAIN / "agents" / "conductors" / "batch" / "_batch.py")
_batch = importlib.util.module_from_spec(_spec)
sys.modules["_batch_collect_under_test"] = _batch
_spec.loader.exec_module(_batch)

STAMP = "2026-09-03T08:00Z"

PROMPT = """# Add a resampling info section

Type: bug
Target: autofit
Witness: the new section appears in search.summary and a unit test pins it

The bottom of `search.summary` says nothing about resampling, so a run that
resampled heavily looks identical to one that did not.
"""

ACTIVE = """# Active Tasks

## resampling-info-summary-section
- issue: https://github.com/ExampleOrg/ExampleFit/issues/1551
- prompt: active/resampling.md
- status: library-shipped, awaiting-merge
- library-pr: https://github.com/ExampleOrg/ExampleFit/pull/1554

## something-else
- prompt: active/other.md
- status: pr-open
- prs:
  - https://github.com/ExampleOrg/ExampleArray/pull/9
"""

MEMBER = ("  - resampling: draft/bug/autofit/resampling.md — glance — 3 — "
          "session ended green (exit 0, cloud session, --auto)")


def record(*members, keys="", notes=True) -> str:
    body = ["# Batch 2026-09-03 pm", "",
            "- dispatched: 2026-09-03T17:40Z",
            "- review-at: 2026-09-04T08:00Z",
            "- lane: any",
            "- review-minutes-planned: 3",
            "- members:"]
    body += list(members)
    if keys:
        body.append(keys)
    if notes:
        body += ["- notes: |",
                 "    What actually happened.",
                 "    - delivered: this line is prose, not a key",
                 "    Nothing stalled."]
    return "\n".join(body) + "\n"


def mini_mind(tmp_path, *members, active=ACTIVE, notes=True, keys="",
              review=None) -> Path:
    mind = tmp_path / "mind"
    (mind / "batches" / "packets").mkdir(parents=True)
    (mind / "batches" / "reviews").mkdir(parents=True)
    (mind / "draft" / "bug" / "autofit").mkdir(parents=True)
    (mind / "active").mkdir(parents=True)
    (mind / "batches" / "2026-09-03-pm.md").write_text(
        record(*(members or (MEMBER,)), keys=keys, notes=notes),
        encoding="utf-8")
    (mind / "batches" / "2026-09-03-am.md").write_text(
        record("  - other: draft/bug/autofit/resampling.md — glance — 1 — "
               "REJECTED by the human at review"), encoding="utf-8")
    (mind / "draft" / "bug" / "autofit" / "resampling.md").write_text(
        PROMPT, encoding="utf-8")
    (mind / "active" / "resampling.md").write_text(PROMPT, encoding="utf-8")
    (mind / "active.md").write_text(active, encoding="utf-8")
    if review is not None:
        (mind / "batches" / "reviews" / "2026-09-03-pm.md").write_text(
            review, encoding="utf-8")
    return mind


def pr(**over) -> dict:
    row = {"repo": "ExampleOrg/ExampleFit", "number": 1554,
           "url": "https://github.com/ExampleOrg/ExampleFit/pull/1554",
           "state": "OPEN", "additions": 86, "deletions": 12,
           "changed_files": 3, "mergeable": "MERGEABLE", "merged": False,
           "head_ref": "feature/autofit-resampling-info",
           "head_sha": "2629933c", "head_repo": "ExampleOrg/ExampleFit",
           "checks": [{"name": "tests", "status": "completed",
                       "conclusion": "success"}]}
    row.update(over)
    return row


def evidence(**over) -> dict:
    row = {"prs": [pr()],
           "witness": {"holds": True, "evidence": "the new test is green"},
           "adversary": {"ran": True, "model": "gpt-5.1",
                         "author_model": "claude-opus-4", "verdict": "CLEAN"}}
    row.update(over)
    return {"resampling": row}


def one(d, slug="resampling"):
    return next(s for s in d["members"] if s["slug"] == slug)


# ------------------------------------------------------ reading the record --
def test_a_member_outcome_may_contain_the_separator(tmp_path):
    """Every one of the nine dev outcomes in the 2026-08-31-pm record contains
    spaces and several contain the separator itself. Splitting with maxsplit=3
    keeps the outcome whole; the Cortex conductor's `(?P<state>\\S+)$` does
    not, which is why this module does not reuse it."""
    line = ("  - resampling: draft/bug/autofit/resampling.md — glance — 3 — "
            "DELIVERED (ExampleFit#1554 — 4/4 checks green, mergeable clean)")
    row = _batch.parse_member(line)
    assert row["slug"] == "resampling"
    assert row["path"] == "draft/bug/autofit/resampling.md"
    assert row["tier"] == "glance" and row["minutes"] == "3"
    assert row["outcome"].endswith("mergeable clean)")
    assert "—" in row["outcome"]


def test_an_unparsable_member_line_is_a_note_not_a_crash(tmp_path):
    """The two science members of the 2026-08-31-pm record have a sentence
    where the path goes. Reporting them is right; refusing to collect the slot
    because of them is not."""
    science = ("  - subhalo-wave: PyAutoCortex phases/subhalo_validation/ "
               "(four phases, one per lens) — judge — 15 — REFRESHED, carried")
    mind = mini_mind(tmp_path, MEMBER, science)
    d = _batch.collect(mind, "2026-09-03-pm")
    assert [s["slug"] for s in d["members"]] == ["resampling"]
    assert any("does not read as a member line" in n for n in d["notes"])
    assert any("subhalo-wave" in n for n in d["notes"])


def test_the_em_dash_may_be_typed_as_two_hyphens(tmp_path):
    row = _batch.parse_member(
        "  - resampling: draft/bug/autofit/resampling.md -- glance -- 3 -- "
        "DELIVERED (ExampleFit#1554)")
    assert row and row["tier"] == "glance" and row["minutes"] == "3"


def test_a_notes_block_is_never_read_as_members(tmp_path):
    """`- notes: |` carries prose that looks exactly like the ledger — the
    fixture's block contains a `- delivered:` line on purpose."""
    mind = mini_mind(tmp_path)
    rec = _batch.read_record(
        (mind / "batches" / "2026-09-03-pm.md").read_text(encoding="utf-8"))
    assert [m["slug"] for m in rec["members"]] == ["resampling"]
    assert "notes" in rec["keys"]
    assert "delivered" not in rec["keys"]


# --------------------------------------------------------------- the legs --
def test_no_pr_is_not_delivered_however_green_the_session(tmp_path):
    """The record's own first rule. A session's green status means it exited
    without an infrastructure error, nothing more."""
    mind = mini_mind(tmp_path)
    d = _batch.collect(mind, "2026-09-03-pm", evidence=evidence(prs=[]))
    assert one(d)["health"] == "NOT-DELIVERED"
    assert d["not_delivered"] == ["resampling"]
    assert _batch.main(["collect", "--mind", str(mind), "--slot",
                        "2026-09-03-pm"]) == 1


def test_an_empty_diff_is_not_delivered(tmp_path):
    mind = mini_mind(tmp_path)
    d = _batch.collect(mind, "2026-09-03-pm", evidence=evidence(
        prs=[pr(additions=0, deletions=0, changed_files=0)]))
    assert one(d)["health"] == "NOT-DELIVERED"
    assert one(d)["legs"]["diff"][0] == _batch.FAIL


def test_checks_that_never_ran_are_not_delivered_but_a_red_check_failed(tmp_path):
    """Two different findings that a single "checks bad" verdict would blur:
    nothing ran (the work never reached CI) versus something ran and went
    red (the work is wrong)."""
    mind = mini_mind(tmp_path)
    never = _batch.collect(mind, "2026-09-03-pm",
                           evidence=evidence(prs=[pr(checks=[])]))
    assert one(never)["health"] == "NOT-DELIVERED"
    assert "never ran" in one(never)["legs"]["checks"][1]
    red = _batch.collect(mind, "2026-09-03-pm", evidence=evidence(prs=[pr(
        checks=[{"name": "tests", "status": "completed",
                 "conclusion": "failure"}])]))
    assert one(red)["health"] == "FAILED"
    assert "tests" in one(red)["legs"]["green"][1]


def test_a_self_run_adversary_is_an_absent_leg(tmp_path):
    """AUTONOMY.md leg 5, verbatim: a self-run adversary leg is an absent leg,
    not a weak one, and recording it as run is a false ledger row."""
    mind = mini_mind(tmp_path)
    d = _batch.collect(mind, "2026-09-03-pm", evidence=evidence(
        adversary={"ran": True, "model": "claude-opus-4",
                   "author_model": "claude-opus-4", "verdict": "CLEAN"}))
    verdict, why = one(d)["legs"]["adversary"]
    assert verdict == _batch.FAIL
    assert "absent leg, not a weak one" in why


def test_a_missing_witness_is_unobservable_and_makes_the_member_suspect(tmp_path):
    (tmp_path / "mind").mkdir(parents=True, exist_ok=True)
    mind = mini_mind(tmp_path)
    (mind / "draft" / "bug" / "autofit" / "resampling.md").write_text(
        PROMPT.replace("Witness: the new section appears in search.summary "
                       "and a unit test pins it\n", ""), encoding="utf-8")
    (mind / "active" / "resampling.md").unlink()
    d = _batch.collect(mind, "2026-09-03-pm", evidence=evidence())
    assert one(d)["legs"]["witness"][0] == _batch.UNOBSERVABLE
    assert one(d)["health"] == "SUSPECT"


def test_a_flagged_decision_keeps_a_green_member_out_of_healthy(tmp_path):
    """decide-and-flag: the run made a call it was not licensed to make. Green
    checks do not settle that — a human does."""
    mind = mini_mind(tmp_path)
    clean = _batch.collect(mind, "2026-09-03-pm", evidence=evidence())
    assert one(clean)["health"] == "HEALTHY"
    d = _batch.collect(mind, "2026-09-03-pm", evidence=evidence(
        flagged=["decide-and-flag: PR opened rather than parked"]))
    assert one(d)["health"] == "SUSPECT"
    assert "decide-and-flag" in "\n".join(
        b for _l, b in one(d)["blocks"])


def test_members_sort_failures_first_and_pending_last(tmp_path):
    mind = mini_mind(
        tmp_path,
        "  - clean: draft/bug/autofit/resampling.md — glance — 3 — session ended green",
        "  - broken: draft/bug/autofit/resampling.md — judge — 20 — session ended green",
        "  - waiting: draft/bug/autofit/resampling.md — judge — 9 — CARRIED, "
        "still running")
    ev = {"clean": evidence()["resampling"],
          "broken": dict(evidence()["resampling"],
                         prs=[pr(checks=[{"name": "tests",
                                          "status": "completed",
                                          "conclusion": "failure"}])]),
          "waiting": evidence()["resampling"]}
    d = _batch.collect(mind, "2026-09-03-pm", evidence=ev)
    assert [s["slug"] for s in d["members"]] == ["broken", "clean", "waiting"]
    assert one(d, "waiting")["health"] == "PENDING"


def test_no_evidence_at_all_is_unobservable_not_delivered(tmp_path):
    """The third verdict. Calling these legs PASS would invent evidence;
    calling them FAIL would condemn every member of every offline collect."""
    mind = mini_mind(tmp_path)
    d = _batch.collect(mind, "2026-09-03-pm")
    assert one(d)["health"] == "SUSPECT"
    assert all(one(d)["legs"][k][0] == _batch.UNOBSERVABLE
               for k in ("pr", "diff", "checks", "green"))
    assert d["delivered"] == (0, 1)


def test_active_md_is_matched_by_prompt_basename_when_the_slug_differs(tmp_path):
    """The record's slug is a dispatch label, the registry's is the task's
    name: `autofit-resampling-info` is registered as
    `resampling-info-summary-section`."""
    mind = mini_mind(tmp_path)
    active = _batch.read_active(mind)
    entry, how = _batch.active_for(
        {"slug": "autofit-resampling-info", "path": "draft/x/resampling.md"},
        active)
    assert entry["slug"] == "resampling-info-summary-section"
    assert how == "prompt basename"
    assert entry["prs"] == ["https://github.com/ExampleOrg/ExampleFit/pull/1554"]
    assert entry["issue"].endswith("/issues/1551")


# ------------------------------------------------------------ the packet ---
def packet_of(mind) -> str:
    return (mind / "batches" / "packets" / "2026-09-03-pm.html").read_text(
        encoding="utf-8")


def apply_once(mind, ev=None, stamp=STAMP):
    d = _batch.collect(mind, "2026-09-03-pm", evidence=ev or evidence())
    d["stamp"] = stamp
    notes = _batch.apply_collect(mind, d, stamp)
    return d, notes


def test_apply_writes_a_complete_document_and_the_record_keys(tmp_path):
    mind = mini_mind(tmp_path)
    apply_once(mind)
    page = packet_of(mind)
    assert page.startswith("<!DOCTYPE html>")
    assert page.rstrip().endswith("</html>")
    assert page.count("<script>") == 1 and page.count("</script>") == 1
    assert "[hidden] { display: none !important; }" in page
    assert "<html lang=\"en\">" in page and "charset" in page
    record = (mind / "batches" / "2026-09-03-pm.md").read_text(encoding="utf-8")
    assert f"- collected: {STAMP}" in record
    assert f"- refreshed: {STAMP} — collect (1 member(s))" in record
    assert "- delivered: 1/1" in record
    assert "- packet: batches/packets/2026-09-03-pm.html" in record


def sections(page: str) -> dict:
    out = {}
    for start, end, mid in _batch._member_spans(page):
        out[mid] = page[start:end]
    return out


def test_a_refresh_regenerates_one_section_and_leaves_the_others_alone(tmp_path):
    """TEMPLATE.md: the morning refresh regenerates that section in place, at
    the same path, and never touches another member's markup — the human is
    reading the page while it happens, and their notes live in it."""
    mind = mini_mind(
        tmp_path,
        "  - clean: draft/bug/autofit/resampling.md — glance — 3 — session ended green",
        "  - second: draft/bug/autofit/resampling.md — glance — 3 — session ended green")
    ev = {"clean": evidence()["resampling"], "second": evidence()["resampling"]}
    apply_once(mind, ev)
    before = packet_of(mind)
    ev["second"] = dict(ev["second"], prs=[pr(checks=[
        {"name": "tests", "status": "completed", "conclusion": "failure"}])])
    apply_once(mind, ev)
    after = packet_of(mind)
    assert sections(before)["m-clean"] == sections(after)["m-clean"]
    assert sections(before)["m-second"] != sections(after)["m-second"]
    assert set(sections(before)) == set(sections(after))
    assert (mind / "batches" / "packets" / "2026-09-03-pm.html").is_file()


def test_a_pending_member_becomes_a_full_block_on_refresh_with_the_same_id(tmp_path):
    mind = mini_mind(
        tmp_path,
        "  - resampling: draft/bug/autofit/resampling.md — glance — 3 — "
        "DELIVERED (ExampleFit#1554)")
    ev = evidence()
    ev["resampling"] = dict(ev["resampling"], pending=True)
    apply_once(mind, ev)
    before = sections(packet_of(mind))["m-resampling"]
    assert "chip-pending" in before and "PENDING" in before
    assert "Health evidence" not in before
    apply_once(mind, evidence())
    after = sections(packet_of(mind))["m-resampling"]
    assert "Health evidence" in after and "chip-pending" not in after
    assert 'id="m-resampling"' in after


def test_the_submit_markdown_schema_is_parse_stable(tmp_path):
    """The orchestrator parses the review on these exact forms; a cosmetic
    edit here silently breaks close-out."""
    mind = mini_mind(
        tmp_path,
        "  - clean: draft/bug/autofit/resampling.md — glance — 3 — session ended green",
        "  - second: draft/bug/autofit/resampling.md — judge — 9 — session ended green")
    d, _ = apply_once(mind, {"clean": evidence()["resampling"],
                             "second": evidence()["resampling"]})
    page = packet_of(mind)
    assert '"# Batch review " + SLOT' in page
    assert '"- decision: "' in page and '"- ruled: "' in page
    assert '"## Follow-ups accepted"' in page
    members = json.loads(re.search(r"var MEMBERS = (\[.*?\]);", page,
                                   re.S).group(1))
    assert [m["slug"] for m in members] == [s["slug"] for s in d["members"]]
    assert [m["id"] for m in members] == [s["id"] for s in d["members"]]
    assert all(m["health"] for m in members)


def test_stored_review_state_is_versioned_and_every_access_is_guarded(tmp_path):
    """The page is opened from Pages, from a file:// path and from inside an
    artifact viewer; two of those can throw on the accessor itself."""
    mind = mini_mind(tmp_path)
    apply_once(mind)
    page = packet_of(mind)
    assert 'var KEY = "slot-review-2026-09-03-pm-v1";' in page
    touches = [ln for ln in page.split("\n")
               if "window.localStorage" in ln]
    assert touches
    assert all("try {" in ln for ln in touches)


# ------------------------------------------------------------ the record ---
def test_a_ruling_word_outcome_is_never_rewritten(tmp_path):
    """The am record's REJECTED/ACCEPTED members are a review that happened.
    A machine reading must not overwrite a human's sentence."""
    mind = mini_mind(
        tmp_path,
        "  - ruled: draft/bug/autofit/resampling.md — glance — 3 — REJECTED "
        "by the human at review",
        "  - fresh: draft/bug/autofit/resampling.md — glance — 3 — session ended green "
        "into the wave")
    apply_once(mind, {"ruled": evidence()["resampling"],
                      "fresh": evidence()["resampling"]})
    record = (mind / "batches" / "2026-09-03-pm.md").read_text(encoding="utf-8")
    assert "REJECTED by the human at review" in record
    assert "session ended green" not in record
    assert "  - fresh: draft/bug/autofit/resampling.md — glance — 3 — HEALTHY" \
        in record


def test_the_notes_block_survives_a_record_rewrite_byte_for_byte(tmp_path):
    mind = mini_mind(tmp_path)
    path = mind / "batches" / "2026-09-03-pm.md"
    before = path.read_text(encoding="utf-8")
    block = before[before.index("- notes: |"):]
    apply_once(mind)
    after = path.read_text(encoding="utf-8")
    assert after[after.index("- notes: |"):] == block


def test_a_second_apply_adds_one_refreshed_line_and_nothing_else(tmp_path):
    mind = mini_mind(tmp_path)
    path = mind / "batches" / "2026-09-03-pm.md"
    apply_once(mind)
    first = path.read_text(encoding="utf-8").split("\n")
    apply_once(mind, stamp="2026-09-03T09:30Z")
    second = path.read_text(encoding="utf-8").split("\n")
    added = [ln for ln in second if ln not in first]
    assert added == ["- refreshed: 2026-09-03T09:30Z — collect (1 member(s))"]
    assert len(second) == len(first) + 1
    assert first.count(f"- collected: {STAMP}") == 1
    assert second.count(f"- collected: {STAMP}") == 1


REVIEW = """# Batch review 2026-09-03-pm

- packet: PyAutoMind/batches/packets/2026-09-03-pm.html
- reviewed-at: 2026-09-04T08:30Z
- review-minutes-actual: 55

## resampling — HEALTHY
- decision: merge
- ruled: yes

Ship it, the summary block reads well.

## Follow-ups accepted
"""


def test_a_submitted_review_closes_the_record_and_never_rewrites_the_packet(tmp_path):
    """`batches/packets/AGENTS.md`: the archived page and the review file are
    the audit pair — what was shown, what was ruled. A correction gets a new
    dated page, not an edit."""
    mind = mini_mind(tmp_path, review=REVIEW)
    d, notes = apply_once(mind)
    assert not (mind / "batches" / "packets" / "2026-09-03-pm.html").exists()
    assert any("never rewritten after a review" in n for n in notes)
    record = (mind / "batches" / "2026-09-03-pm.md").read_text(encoding="utf-8")
    assert "- reviewed-at: 2026-09-04T08:30Z" in record
    assert "- review-minutes-actual: 55" in record
    assert "- review: batches/reviews/2026-09-03-pm.md" in record
    assert d["review"]["members"]["resampling"]["decision"] == "merge"
    assert d["review"]["members"]["resampling"]["ruled"] == "yes"
    # Reported, never enacted.
    assert "merge" in _batch.collect_report(d)


def test_a_closed_batch_keeps_every_member_line_and_every_value_it_has(tmp_path):
    """Found on the live pm record: `PR OPENED AT REVIEW (…)` opens with no
    ruling word, and the record's `reviewed-at:` carried a clause about where
    the review sat. Once the review has landed the record is history — no
    member line changes, and the close leg fills only what is blank."""
    mind = mini_mind(
        tmp_path,
        "  - resampling: draft/bug/autofit/resampling.md — glance — 3 — PR "
        "OPENED AT REVIEW (ExampleFit#1554 from the parked branch)",
        keys="- reviewed-at: 2026-09-04T08:30 (transcribed; the review sat "
             "outside the packet)\n- review-minutes-actual: (not given)\n"
             "- delivered: 6/9 cloud members (5 PR sets green + 1 verdict)",
        review=REVIEW)
    apply_once(mind)
    record = (mind / "batches" / "2026-09-03-pm.md").read_text(encoding="utf-8")
    assert "- delivered: 6/9 cloud members (5 PR sets green + 1 verdict)" in record
    assert "- delivered: 0/1" not in record
    assert "PR OPENED AT REVIEW (ExampleFit#1554 from the parked branch)" in record
    assert "— HEALTHY" not in record
    assert ("- reviewed-at: 2026-09-04T08:30 (transcribed; the review sat "
            "outside the packet)") in record
    assert "- reviewed-at: 2026-09-04T08:30Z" not in record
    assert "- review-minutes-actual: 55" in record
    assert "(not given)" not in record


def test_review_minutes_not_given_is_not_written_back(tmp_path):
    mind = mini_mind(tmp_path, review=REVIEW.replace("55", "(not given)"))
    apply_once(mind)
    record = (mind / "batches" / "2026-09-03-pm.md").read_text(encoding="utf-8")
    assert "review-minutes-actual" not in record


# --------------------------------------------------------------- the cli ---
def test_exit_codes(tmp_path, capsys):
    mind = mini_mind(tmp_path)
    ev_file = tmp_path / "ev.json"
    ev_file.write_text(json.dumps({"schema": 1, "members": evidence()}),
                       encoding="utf-8")
    assert _batch.main(["collect", "--mind", str(mind), "--slot",
                        "2026-09-03-pm", "--evidence", str(ev_file)]) == 0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"members": evidence(prs=[])}), encoding="utf-8")
    assert _batch.main(["collect", "--mind", str(mind), "--slot",
                        "2026-09-03-pm", "--evidence", str(bad)]) == 1
    assert _batch.main(["collect", "--mind", str(mind),
                        "--slot", "nope"]) == 2
    assert _batch.main(["collect", "--mind", str(tmp_path / "nowhere")]) == 4


def test_malformed_evidence_is_a_usage_error(tmp_path):
    mind = mini_mind(tmp_path)
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert _batch.main(["collect", "--mind", str(mind), "--slot",
                        "2026-09-03-pm", "--evidence", str(broken)]) == 2


def test_collect_only_flags_are_refused_on_plan(tmp_path):
    mind = mini_mind(tmp_path)
    assert _batch.main(["plan", "--mind", str(mind), "--apply"]) == 2


def test_the_newest_slot_is_the_default_and_the_sort_is_lexical(tmp_path):
    mind = mini_mind(tmp_path)
    assert _batch.newest_slot(mind) == "2026-09-03-pm"
    (mind / "batches" / "2026-09-03-night.md").write_text(record(MEMBER),
                                                          encoding="utf-8")
    assert _batch.newest_slot(mind) == "2026-09-03-pm"


def test_fetch_without_gh_points_at_the_mcp_tools_and_still_scores(
        tmp_path, monkeypatch, capsys):
    """`gh` installs in a web session, authenticates, then 403s every
    repo-scoped call — so its absence is answered with a pointer, never a
    caught error."""
    monkeypatch.setattr(_batch.shutil, "which", lambda _name: None)
    mind = mini_mind(tmp_path)
    rc = _batch.main(["collect", "--mind", str(mind), "--slot",
                      "2026-09-03-pm", "--fetch"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "no gh here" in out and "--evidence <json>" in out
    assert out.count("no gh here") == 1
    assert "## resampling — SUSPECT" in out


def test_fetch_records_the_head_branch_of_every_pr(tmp_path, monkeypatch):
    """A record names members, never branches, and `active.md`'s PR field has
    four spellings — so the PR's own head is the only reliable member ->
    (repo, branch) map. It is asked for in the `--json` field list and carried
    through onto the row; a fork whose owner is gone reports an empty head
    repo rather than guessing `origin`."""
    calls = []
    head = {"headRefName": "feature/x", "headRefOid": "abc",
            "headRepository": {"name": "ExampleFit"},
            "headRepositoryOwner": {"login": "ExampleOrg"}}

    def fake(cmd, **_kw):
        calls.append(cmd)
        body = {"number": 1554, "url": "https://example.invalid/pull/1554",
                "state": "OPEN", "additions": 5, "deletions": 1,
                "changedFiles": 2, "mergeable": "MERGEABLE",
                "mergedAt": None, "statusCheckRollup": [], **head}
        return SimpleNamespace(returncode=0, stdout=json.dumps(body),
                               stderr="")

    monkeypatch.setattr(_batch.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(_batch.subprocess, "run", fake)
    mind = mini_mind(tmp_path)
    members = [{"slug": "resampling", "path": "draft/bug/autofit/resampling.md"}]
    active = _batch.read_active(mind)

    got, notes = _batch.fetch_evidence(members, active)

    assert notes == []
    assert "headRefName" in _batch.GH_FIELDS
    # The flag is what is pinned: a field dropped from the argv is a field the
    # evidence silently loses.
    assert any("headRefName" in str(arg) for arg in calls[0])
    row = got["resampling"]["prs"][0]
    assert row["head_ref"] == "feature/x"
    assert row["head_sha"] == "abc"
    assert row["head_repo"] == "ExampleOrg/ExampleFit"

    head["headRepositoryOwner"] = None
    got, _notes = _batch.fetch_evidence(members, active)
    assert got["resampling"]["prs"][0]["head_repo"] == ""
    assert got["resampling"]["prs"][0]["head_ref"] == "feature/x"


def test_fetch_asks_gh_for_mergedat_because_there_is_no_merged_field(
        tmp_path, monkeypatch):
    """`gh pr view --json` has no `merged` field. It does not drop an unknown
    name — it rejects the WHOLE request ("Unknown JSON field: merged", gh
    2.98), so one wrong word made every PR of every `--fetch` UNOBSERVABLE and
    the report blamed the PRs. `mergedAt` is the same fact, and the row's
    `merged` is derived from it."""
    assert "mergedAt" in _batch.GH_FIELDS
    assert "merged," not in _batch.GH_FIELDS

    rows = [{"number": 1554, "url": "u", "state": "MERGED", "additions": 5,
             "deletions": 1, "changedFiles": 2, "mergeable": "UNKNOWN",
             "mergedAt": "2026-09-01T19:34:55Z", "statusCheckRollup": [],
             "headRefName": "feature/x", "headRefOid": "abc",
             "headRepository": {"name": "ExampleFit"},
             "headRepositoryOwner": {"login": "ExampleOrg"}}]

    def fake(cmd, **_kw):
        return SimpleNamespace(returncode=0, stdout=json.dumps(rows[0]),
                               stderr="")

    monkeypatch.setattr(_batch.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(_batch.subprocess, "run", fake)
    mind = mini_mind(tmp_path)
    members = [{"slug": "resampling", "path": "draft/bug/autofit/resampling.md"}]
    got, notes = _batch.fetch_evidence(members, _batch.read_active(mind))
    assert notes == []
    assert got["resampling"]["prs"][0]["merged"] is True

    rows[0]["mergedAt"] = None
    got, _n = _batch.fetch_evidence(members, _batch.read_active(mind))
    assert got["resampling"]["prs"][0]["merged"] is False


def test_apply_writes_nothing_that_a_re_read_cannot_recover(tmp_path):
    """The rehearsal. A ledger half-written has no way back, so the rewrite is
    re-parsed on a throwaway copy before it is written for real."""
    mind = mini_mind(tmp_path)
    before = (mind / "batches" / "2026-09-03-pm.md").read_text(encoding="utf-8")
    d = _batch.collect(mind, "2026-09-03-pm", evidence=evidence())
    after = _batch.record_update(before, d, STAMP)
    assert _batch._rehearse_record(mind, before, after) == []
    broken = after.replace("  - resampling:", "  - resampling")
    assert _batch._rehearse_record(mind, before, broken)


# ------------------------------------------------------ the kinds registry --
def _fake_score(member, ctx):
    legs = {k: (_batch.PASS, "the fake kind says so") for k in _batch.LEGS}
    return {"slug": member["slug"], "kind": "fake", "id": f"m-{member['slug']}",
            "title": "A phase of a science project", "health": "HEALTHY",
            "eyebrow": "cortex · phase 3", "jobs": "342091",
            "chip": "witness landed", "est_minutes": 15, "tier": "judge",
            "pending": False, "merged": False, "flagged": [], "legs": legs,
            "links": [], "notes": [], "path": member["path"], "outcome": "",
            "prs": [], "summary": "", "ruling_line": "_(yours to write)_",
            "review_chips": [("accept", "Accept"), ("rerun", "Rerun")]}


def _fake_blocks(s):
    return [("Question", "Does the subhalo show up?"),
            ("Ruling", s["ruling_line"])]


def test_the_kinds_registry_is_the_extension_point(tmp_path):
    """Phase 5 registers a `cortex` kind here. Nothing about the report or the
    renderer may need to change for it, which is what this pins."""
    mind = mini_mind(
        tmp_path,
        "  - resampling: draft/bug/autofit/resampling.md — glance — 3 — "
        "session ended green",
        "  - subhalo: phases/subhalo_validation/pl_eff.md — judge — 15 — "
        "session ended green")
    kinds = dict(_batch.KINDS)
    kinds["fake"] = (_fake_score, _fake_blocks,
                     lambda m, ctx: m["path"].startswith("phases/"))
    d = _batch.collect(mind, "2026-09-03-pm", evidence=evidence(), kinds=kinds)
    d["stamp"] = STAMP
    assert {s["kind"] for s in d["members"]} == {"dev", "fake"}
    report = _batch.collect_report(d)
    assert "## subhalo — HEALTHY" in report
    assert "Does the subhalo show up?" in report
    page, notes = _batch.packet_html(d)
    assert notes == []
    assert 'id="m-subhalo"' in page
    assert "A phase of a science project" in page
    assert 'value="rerun"' in page


def test_every_interpolated_value_is_escaped(tmp_path):
    """A record, a prompt and a check name are all human-written text on a page
    served from Pages."""
    mind = mini_mind(
        tmp_path,
        "  - x<script>alert(1)</script>: draft/bug/autofit/resampling.md — "
        "glance — 3 — session ended green")
    d = _batch.collect(mind, "2026-09-03-pm")
    d["stamp"] = STAMP
    page, _notes = _batch.packet_html(d)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert page.count("<script>") == 1


# ------------------------------------------------------- ledger outcomes ----
COMPLETE = """## resampling-info-summary-section
- issue: https://github.com/ExampleOrg/ExampleFit/issues/1551 (closed, completed)
- completed: 2026-09-04
- library-pr: https://github.com/ExampleOrg/ExampleFit/pull/1554 (MERGED)
- batch: 2026-09-03-pm — member `resampling`, tier `glance`, 3 review-minutes
"""

UNREVIEWED_REVIEW = """# Batch review 2026-09-03-pm

- reviewed-at: 2026-09-04T08:30Z

## resampling — DELIVERED
- decision: UNREVIEWED
- ruled: no
"""

REJECTED_REVIEW = """# Batch review 2026-09-03-pm

- reviewed-at: 2026-09-04T08:30Z

## resampling — SUSPECT
- decision: reject — the diff answers a different question
- ruled: yes
"""


def _completed(mind: Path, body: str = COMPLETE, name: str = "shipped.md"):
    d = mind / "complete" / "2026" / "09"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body, encoding="utf-8")


def test_a_merged_member_is_read_from_the_completion_record(tmp_path):
    """All nine members of the 2026-08-31-pm slot merged and every one was
    recorded `decision: UNREVIEWED`. The completion records knew — they name
    the slot and the member — and nothing read them."""
    mind = mini_mind(tmp_path, review=UNREVIEWED_REVIEW)
    _completed(mind)
    d = _batch.collect(mind, "2026-09-03-pm")
    assert one(d)["outcome_ledger"] == "merged"
    assert d["outcomes"]["resampling"] == "merged"


def test_a_record_filed_under_the_members_own_name_still_counts(tmp_path):
    """The record's `- batch:` citation is the authoritative join; a record
    named after the member is the fallback, because a task is filed under its
    own name and a member carries a dispatch label."""
    mind = mini_mind(tmp_path)
    _completed(mind, body="## resampling\n- completed: 2026-09-04\n",
               name="resampling.md")
    assert one(_batch.collect(mind, "2026-09-03-pm"))["outcome_ledger"] == "merged"


def test_a_member_still_in_the_registry_is_carried(tmp_path):
    mind = mini_mind(tmp_path)
    assert one(_batch.collect(mind, "2026-09-03-pm"))["outcome_ledger"] == "carried"


def test_a_rejection_is_read_before_the_registry_row(tmp_path):
    """A rejected member is still in `active.md` — it is work that came back —
    so reading the registry first would report every rejection as carried."""
    mind = mini_mind(tmp_path, review=REJECTED_REVIEW)
    d = _batch.collect(mind, "2026-09-03-pm")
    assert one(d)["outcome_ledger"] == "rejected-at-review"


def test_a_member_the_ledger_says_nothing_about_is_unreviewed(tmp_path):
    mind = mini_mind(tmp_path, active="# Active Tasks\n")
    assert one(_batch.collect(mind,
                              "2026-09-03-pm"))["outcome_ledger"] == "unreviewed"


# ---------------------------------------------------------- the merge order --
LIB_PROMPT = """# A library change

Type: feature
Target: autofit
Repos:
- PyAutoFit
"""

WORKSPACE_PROMPT = """# A workspace change

Type: docs
Target: autofit_workspace
Repos:
- autofit_workspace
"""

SECOND_LIB_PROMPT = """# Another change to the same library

Type: bug
Target: autofit
Repos:
- PyAutoFit
"""


def _slot_of_three(tmp_path) -> Path:
    """One workspace member dispatched FIRST, then two library members on the
    same repo — the shape the merge order has to correct."""
    members = (
        "  - wsp: draft/docs/autofit_workspace/wsp.md — glance — 3 — DELIVERED",
        "  - lib-a: draft/feature/autofit/lib_a.md — judge — 20 — DELIVERED",
        "  - lib-b: draft/bug/autofit/lib_b.md — glance — 3 — DELIVERED",
    )
    mind = mini_mind(tmp_path, *members, active="# Active Tasks\n")
    d = mind / "draft" / "docs" / "autofit_workspace"
    d.mkdir(parents=True, exist_ok=True)
    (d / "wsp.md").write_text(WORKSPACE_PROMPT, encoding="utf-8")
    (mind / "draft" / "feature" / "autofit").mkdir(parents=True, exist_ok=True)
    (mind / "draft" / "feature" / "autofit" / "lib_a.md").write_text(
        LIB_PROMPT, encoding="utf-8")
    (mind / "draft" / "bug" / "autofit" / "lib_b.md").write_text(
        SECOND_LIB_PROMPT, encoding="utf-8")
    return mind


def test_the_merge_order_puts_the_library_before_its_dependants(tmp_path):
    """`collect` used to decline a merge order outright. `members` is sorted by
    health and cannot carry one — the record's dispatch order can, and the
    library-first gate reorders it."""
    d = _batch.collect(_slot_of_three(tmp_path), "2026-09-03-pm")
    assert [row["slug"] for row in d["merge_order"]] == ["lib-a", "lib-b", "wsp"]


def test_same_repo_members_are_serialised_and_say_why(tmp_path):
    """The first merge moves `main` and stales its siblings' evidence, so the
    order says which sibling is re-validated against what."""
    d = _batch.collect(_slot_of_three(tmp_path), "2026-09-03-pm")
    second = next(r for r in d["merge_order"] if r["slug"] == "lib-b")
    assert "after lib-a" in second["why"]
    assert "shares autofit" in second["why"]


def test_the_merge_order_reaches_the_report(tmp_path):
    d = _batch.collect(_slot_of_three(tmp_path), "2026-09-03-pm")
    body = _batch.collect_report(d)
    assert "## Merge order" in body
    assert "nothing here is enacted" in body
    assert body.index("1. **lib-a**") < body.index("3. **wsp**")


def test_nothing_is_filtered_out_of_the_merge_order(tmp_path):
    """A member with no PR is listed in its place with what it is waiting on:
    an order that silently omits a member is an order somebody merges out of."""
    d = _batch.collect(_slot_of_three(tmp_path), "2026-09-03-pm")
    assert len(d["merge_order"]) == len(d["members"]) == 3
    assert all("no PR recorded" in r["why"] for r in d["merge_order"])


# ------------------------------------------------ what the record gains ------
def test_the_record_gains_the_outcomes_and_merge_order_blocks(tmp_path):
    mind = _slot_of_three(tmp_path)
    d = _batch.collect(mind, "2026-09-03-pm")
    before = (mind / "batches" / "2026-09-03-pm.md").read_text(encoding="utf-8")
    after = _batch.record_update(before, d, STAMP)
    assert "- outcomes:" in after and "  - lib-a: unreviewed" in after
    assert "- merge-order:" in after and "  - 1. lib-a — library" in after
    # the blocks sit above `notes:`, never inside it
    assert after.index("- outcomes:") < after.index("- notes: |")
    assert _batch.read_outcomes(after)["wsp"] == "unreviewed"
    # and the record still reads as a record
    again = _batch.read_record(after)
    assert {m["slug"] for m in again["members"]} == {"wsp", "lib-a", "lib-b"}
    assert not again["unparsable"]


def test_a_second_apply_replaces_the_blocks_rather_than_repeating_them(tmp_path):
    mind = _slot_of_three(tmp_path)
    d = _batch.collect(mind, "2026-09-03-pm")
    once = _batch.record_update(
        (mind / "batches" / "2026-09-03-pm.md").read_text(encoding="utf-8"),
        d, STAMP)
    twice = _batch.record_update(once, d, STAMP)
    assert twice.count("- merge-order:") == 1
    assert twice.count("  - 1. lib-a — library") == 1


def test_a_closed_records_blocks_are_history(tmp_path):
    """`delivered:` and `packet:` are filled rather than set once a review has
    landed. The accounting is the same kind of fact."""
    mind = _slot_of_three(tmp_path)
    (mind / "batches" / "reviews" / "2026-09-03-pm.md").write_text(
        UNREVIEWED_REVIEW.replace("resampling", "lib-a"), encoding="utf-8")
    d = _batch.collect(mind, "2026-09-03-pm")
    before = (mind / "batches" / "2026-09-03-pm.md").read_text(
        encoding="utf-8").replace("- notes: |",
                                  "- outcomes:\n  - lib-a: merged\n- notes: |")
    after = _batch.record_update(before, d, STAMP)
    assert "  - lib-a: merged" in after
    assert "  - lib-a: unreviewed" not in after


def test_previous_carried_reads_the_newest_records_outcomes(tmp_path):
    mind = mini_mind(tmp_path)
    record = mind / "batches" / "2026-09-03-pm.md"
    record.write_text(record.read_text(encoding="utf-8").replace(
        "- notes: |",
        "- outcomes:\n  - resampling: carried\n  - other: merged\n- notes: |"),
        encoding="utf-8")
    assert _batch.previous_carried(mind) == ("2026-09-03-pm", ["resampling"])
