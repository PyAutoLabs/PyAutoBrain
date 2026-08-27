"""`gh` is not available on every surface, and the skills must say so.

The workflow was written on a developer box, so its GitHub steps are spelled as
`gh` commands — 19 skill bodies and 15 scripts here. A Claude Code remote
session has no `gh` at all; its GitHub access is the `mcp__github__*` tool
surface. Nothing said so anywhere, so each mobile run rediscovered it: load the
procedure, run the first `gh`, get `command not found`, re-derive the whole
thing through MCP.

Two rules, pinned here:

1. a skill body that drives `gh` — here or in PyAutoMind, the other repo that
   ships skills — points at `skills/GITHUB_ACCESS.md`, which maps each
   operation onto its MCP tool;
2. a script that needs `gh` says so in a way that names the alternative, rather
   than letting an empty command substitution be read as a real answer.
"""

import os
import re
import subprocess
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
SKILLS = BRAIN_HOME / "skills"
ACCESS_PAGE = SKILLS / "GITHUB_ACCESS.md"
GH_HELPER = BRAIN_HOME / "bin" / "_gh.sh"

# PyAutoMind ships skills too, and its bodies drive `gh` for the same reasons.
# The page lives here, so this repo's suite is the only one positioned to guard
# both; when the sibling is not checked out that leg simply does not run.
MIND_SKILLS = BRAIN_HOME.parent / "PyAutoMind" / "skills"

# A real `gh` invocation, not the word in prose.
GH_CALL = re.compile(r'\bgh (pr|api|issue|run|repo|workflow|auth|search|release)\b')

# Shared prose pages describe the surface rather than driving it.
EXEMPT = {"GITHUB_ACCESS.md", "COMMANDS.md", "WORKFLOW.md", "OPERATIONS.md"}


def _skill_bodies():
    """Every skill markdown body in the workspace, as (repo_home, path) pairs."""
    for root in (SKILLS, MIND_SKILLS):
        if not root.is_dir():
            continue  # sibling not checked out here
        for path in sorted(root.glob("*/*.md")):
            yield root.parent, path


def _gh_free_env(tmp_path):
    """A PATH with the tools these scripts call, minus `gh`."""
    lean = tmp_path / "nogh"
    lean.mkdir(exist_ok=True)
    for tool in ("bash", "git", "sed", "awk", "grep", "sort", "head", "cut",
                 "tr", "dirname", "basename", "cat", "wc", "env", "uniq"):
        path = subprocess.run(["bash", "-c", f"command -v {tool}"],
                              capture_output=True, text=True).stdout.strip()
        if path and not (lean / tool).exists():
            (lean / tool).symlink_to(path)
    env = dict(os.environ)
    env["PATH"] = str(lean)
    return env


def test_access_page_ships_and_maps_the_operations():
    assert ACCESS_PAGE.is_file()
    text = ACCESS_PAGE.read_text()
    # the operations a close-out cannot do without
    for tool in ("pull_request_read", "merge_pull_request", "issue_write",
                 "add_issue_comment", "actions_list", "get_file_contents"):
        assert tool in text, f"{tool} has no mapping"
    # and the honest limit
    assert "cannot" in text.lower()


def test_every_gh_driving_skill_points_at_the_mapping():
    offenders = []
    for home, path in _skill_bodies():
        if path.name in EXEMPT:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if not GH_CALL.search(text):
            continue
        if "GITHUB_ACCESS.md" not in text:
            offenders.append(str(path.relative_to(home.parent)))
    assert not offenders, (
        "these drive `gh` without telling a gh-less session what to do "
        "instead — add a pointer to skills/GITHUB_ACCESS.md:\n  "
        + "\n  ".join(offenders)
    )


def test_every_pointer_resolves():
    broken = []
    for home, path in _skill_bodies():
        text = path.read_text(encoding="utf-8", errors="replace")
        name = path.relative_to(home.parent)
        # A same-repo pointer is a relative markdown link.
        for rel in re.findall(r'\]\((\.\.?/[^)]*GITHUB_ACCESS\.md)\)', text):
            if not (path.parent / rel).is_file():
                broken.append(f"{name} -> {rel}")
        # A cross-repo one is a bare workspace path; ../.. would be noise.
        for rel in re.findall(r'(?<![(/\w])((?:\w[\w.-]*/)+GITHUB_ACCESS\.md)', text):
            if not (home.parent / rel).is_file():
                broken.append(f"{name} -> {rel}")
    assert not broken, broken


def test_require_gh_names_the_alternative(tmp_path):
    """The failure must be actionable, and carry a command-not-found status."""
    r = subprocess.run(
        ["bash", "-c", f'. "{GH_HELPER}"; require_gh demo'],
        capture_output=True, text=True, env=_gh_free_env(tmp_path), timeout=60)
    assert r.returncode == 127, r
    assert "demo" in r.stderr
    assert "gh" in r.stderr
    assert "GITHUB_ACCESS.md" in r.stderr


def test_have_gh_is_false_without_gh(tmp_path):
    r = subprocess.run(
        ["bash", "-c", f'. "{GH_HELPER}"; have_gh && echo yes || echo no'],
        capture_output=True, text=True, env=_gh_free_env(tmp_path), timeout=60)
    assert r.stdout.strip() == "no"


def test_helper_locates_itself_without_readlink(tmp_path):
    """The scripts run under a lean PATH; the helper must not need one more tool.

    Sourcing via `readlink` broke `branch_sweep.sh` in exactly the environment
    whose whole point is "gh is missing" — the helper died before it could say
    why.
    """
    env = _gh_free_env(tmp_path)
    assert not (tmp_path / "nogh" / "readlink").exists(), "fixture links readlink"
    r = subprocess.run(
        ["bash", str(BRAIN_HOME / "bin" / "branch_sweep.sh"),
         "--repo", str(BRAIN_HOME), "--owner", "o", "--name", "n"],
        capture_output=True, text=True, env=env, timeout=60)
    assert "command not found" not in r.stderr, r.stderr
    assert "GITHUB_ACCESS.md" in r.stderr


def test_waiting_for_ci_prefers_being_woken_over_polling():
    """A poll costs a turn every 90s; a wake costs one per event.

    The MCP surface is usually a *reduced* `gh`, so the one operation where it
    is strictly better is easy to leave unused. `/prm` is where a run would
    otherwise sit in a loop, so its wait step must offer the subscription
    first, and the mapping page must carry the tool that provides it.
    """
    access = ACCESS_PAGE.read_text()
    for tool in ("subscribe_pr_activity", "unsubscribe_pr_activity"):
        assert tool in access, f"{tool} is unmapped"

    prm = (SKILLS / "prm" / "prm.md").read_text()
    wait = prm.split("## 3. Wait, or stop")[1].split("## 4.")[0]
    assert "subscribe_pr_activity" in wait, "the wait step never mentions waking"
    assert wait.index("subscribe_pr_activity") < wait.index("~90s"), (
        "polling is offered before the cheaper wake path")
    # And the subscription must be dropped, or later sessions wake on a PR
    # nobody is driving.
    assert "unsubscribe_pr_activity" in prm.split("## 4.")[1]


def test_the_close_out_carries_its_own_mcp_calls():
    """The mobile lane must not cost two pages to read.

    `/prm` is ~4k words of `gh` mechanics; a run without `gh` used to load them
    AND the mapping page, then translate step by step. The calls that close a
    task out are few and stable enough to name inline, so the mapping page is
    the index, not a required second read.
    """
    prm = (SKILLS / "prm" / "prm.md").read_text()
    lane = prm.split("### The `mcp` lane")[1].split("## 1.")[0]
    for call in ("pull_request_read", "actions_list", "get_job_logs",
                 "merge_pull_request", "add_issue_comment", "issue_write",
                 "subscribe_pr_activity", "get_file_contents"):
        assert call in lane, f"the mcp lane never names {call}"
    # The two traps that cost a run its turns, not just a lookup.
    assert "head_sha" in lane, "nothing warns that runs cannot be filtered by sha"
    assert "state_reason" in lane, "closing an issue without a reason mislabels it"
