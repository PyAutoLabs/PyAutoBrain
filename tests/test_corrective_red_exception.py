"""Doc-contract tests for the human-authorized development paths through
Heart RED (PyAutoBrain#112 and the development-only override).

The exception is doctrine, not code, so its guardrails are pinned against the
canonical text of AUTONOMY.md — a weakening edit (dropping a forbidden action,
a record sink, or the human-only clause) fails loudly here rather than silently
widening either authorized path through a RED gate. The seam tests also pin
the "link, don't duplicate policy" contract: the ship skills point at
AUTONOMY.md and do not carry a second copy of the permitted/forbidden lists.
"""

from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
AUTONOMY = (BRAIN_HOME / "AUTONOMY.md").read_text()
SHIP_LIBRARY = (BRAIN_HOME / "skills" / "ship_library" / "ship_library.md").read_text()
SHIP_WORKSPACE = (BRAIN_HOME / "skills" / "ship_workspace" / "ship_workspace.md").read_text()
WORKFLOW = (BRAIN_HOME / "skills" / "WORKFLOW.md").read_text()
PRM = (BRAIN_HOME / "skills" / "prm" / "prm.md").read_text()

SECTION_HEADER = "## Corrective-PR exception for Heart RED (human-authorized)"
OVERRIDE_HEADER = "## Human override for Heart RED (development only)"


def _norm(text):
    """Lowercase, strip markdown emphasis, and collapse whitespace so assertions
    ignore ``**``/``` ` ``` and line wrapping."""
    return " ".join(text.replace("*", "").replace("`", "").lower().split())


def _section(header=SECTION_HEADER):
    """One policy section body, from its header to the next ``## ``."""
    start = AUTONOMY.index(header)
    rest = AUTONOMY[start + len(header):]
    end = rest.find("\n## ")
    return _norm(rest if end == -1 else rest[:end])


def test_section_exists():
    assert SECTION_HEADER in AUTONOMY


def test_development_override_requires_live_human_and_passing_branch_gates():
    sec = _section(OVERRIDE_HEADER)
    assert "non-corrective development branch" in sec
    assert "live human" in sec
    assert "every exact red reason string from heart's current verdict" in sec
    assert "passed all applicable tests, smoke, and review" in sec
    for stale_grant in ("standing", "stored", "batch", "ambient",
                        "earlier-session"):
        assert stale_grant in sec
    assert "specific task or issue" in sec
    assert "verbatim, or faithfully quoted, on the issue" in sec


def test_development_override_scope_records_and_release_boundary():
    sec = _section(OVERRIDE_HEADER)
    for permitted in ("commit", "push", "opening the task's pending-release pr"):
        assert permitted in sec
    for sink in ("github issue", "pr body", "pyautomind/active.md",
                 "- heart-red-override:", "pyautomind/autonomy_log.md",
                 "outcome red-override"):
        assert _norm(sink) in sec, sink
    assert "first table" in sec
    for forbidden in ("release rehearsal", "force merge",
                      "claim that the branch fixes heart",
                      "bypassing a failed test",
                      "required github check or branch protection"):
        assert forbidden in sec
    assert "heart remains red for release purposes" in sec


def test_development_override_merge_grant_expires_and_never_bypasses_ci():
    sec = _section(OVERRIDE_HEADER)
    assert "separate explicit human merge command" in sec
    assert "every required github check green" in sec
    assert "if the turn ends before the checks are green, the merge grant expires" in sec
    assert "human must invoke /prm again" in sec
    prm = _norm(PRM)
    assert "merge grant lasts only for the current turn" in prm
    assert "every required github check green" in prm
    assert "invoke /prm again" in prm


def test_development_override_is_never_autonomous_and_has_log_schema():
    sec = _section(OVERRIDE_HEADER)
    assert "never inferred or exercised by --auto" in sec
    assert "red parks the run first" in sec
    assert "red-override" in AUTONOMY


def test_both_ship_skills_link_the_development_override():
    marker = "Human override for Heart RED (development only)"
    assert marker in SHIP_LIBRARY
    assert marker in SHIP_WORKSPACE
    assert marker in WORKFLOW


def test_corrective_path_coexists_with_the_development_override():
    sec = _section()
    assert "narrow causal-fix path" in sec
    assert "alongside the development-only human override" in sec
    assert "one authorized way" not in sec


def test_permitted_set_is_commit_push_pr_open_only():
    sec = _section()
    for verb in ("commit", "push", "opening one"):
        assert verb in sec, verb
    # the permission is explicitly bounded
    assert "nothing else" in sec


def test_forbidden_set_named():
    sec = _section()
    for forbidden in ("merge", "issue close", "release", "release rehearsal",
                      "unrelated scope"):
        assert forbidden in sec, forbidden
    assert "every release stays blocked while heart is red" in sec


def test_four_record_sinks_named():
    sec = _section()
    for sink in ("github issue", "pr body", "pyautomind/active.md",
                 "autonomy_log.md", "- corrective-red:"):
        assert _norm(sink) in sec, sink


def test_park_without_shipping_cases_named():
    sec = _section()
    assert "park without shipping" in sec
    for case in ("mixed-scope diff", "stale or changed red reason",
                 "missing evidence", "not causal"):
        assert case in sec, case


def test_multiple_reasons_names_exactly_one():
    sec = _section()
    assert "multiple red reasons" in sec
    assert "names exactly one" in sec


def test_recovery_sequence_is_merge_then_fresh_validation_then_new_verdict():
    sec = _section()
    assert "recovery sequence" in sec
    assert "human merges" in sec
    assert "post-merge wheels" in sec
    assert "release-integration validation" in sec
    assert "new verdict" in sec
    assert "human-required" in sec  # release cap untouched


def test_agent_provides_the_quote():
    # The human quotes the exact RED reason, so the agent must surface it
    # verbatim from Heart's verdict — the human never reconstructs the wording.
    sec = _section()
    assert "the agent provides the quote" in sec
    assert "verbatim from heart's current verdict" in sec
    # and the ship gates instruct the agent to surface it at the RED step
    for doc in (SHIP_LIBRARY, SHIP_WORKSPACE, WORKFLOW):
        assert "verbatim from" in _norm(doc)


def test_exception_is_human_only_never_under_auto():
    sec = _section()
    assert "human act" in sec
    assert "never fires under --auto" in sec


def test_never_acknowledged_autonomously_invariant_survives_verbatim():
    # The exception must not weaken this hard invariant; it stays word-for-word.
    assert (
        "**Heart YELLOW/RED is never acknowledged autonomously.**" in AUTONOMY
    )


def test_hard_invariant_bullet_scopes_the_exception():
    inv = _norm(AUTONOMY)
    assert "corrective-pr exception for heart red is a contemporaneous human act" in inv


def test_ship_skills_link_the_exception():
    # Each ship gate points at the canonical section (link, not restatement).
    marker = "Corrective-PR exception for Heart RED"
    assert marker in SHIP_LIBRARY
    assert marker in SHIP_WORKSPACE
    assert marker in WORKFLOW


def test_ship_skills_do_not_duplicate_policy():
    # The exception's permitted/forbidden lists, record sinks and failure cases
    # live only in AUTONOMY.md; the ship skills reference the section by name and
    # must not carry a second copy that could drift. (Tokens checked here are
    # distinctive to the exception — not incidental words like "autonomy_log.md",
    # which ship_library legitimately uses for the calibration append.)
    for doc in (SHIP_LIBRARY, SHIP_WORKSPACE, WORKFLOW):
        norm = _norm(doc)
        assert "- corrective-red:" not in norm       # the active.md block form
        assert "park without shipping" not in norm    # the failure-case list
        assert "recovery sequence" not in norm        # the resume-release steps
