"""Contract tests for the Clone Agent's `sync` mode.

Hermetic: builds a throwaway workspace of three fake assistants (plus the
library directories `reference_library()` resolves names against) with real
`git init` repos, and never touches the live checkouts or the network.

What the mode promises, and therefore what is asserted here:

1. it is **not** a blind overwrite — a sibling that adapted the reference's
   prose keeps its own text, and the hunks that no longer fit are REPORTED as
   rejected rather than forced;
2. the reference's names are rewritten for each sibling, so a synced line reads
   as a born one would (`autolens` -> `autocti`, `al_` -> `ac_`, and the
   UPPERCASE env-var form birth forgets);
3. a dry run writes nothing;
4. "since the sibling's last sync" is read from the sibling's own history via
   the `Clone-sync: <reference>@<sha>` commit trailer.
"""

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

CLONE = (
    Path(__file__).resolve().parents[1]
    / "agents" / "conductors" / "clone" / "_clone.py"
)

REFERENCE = "autolens_assistant"

README_V1 = """# wiki/project/

A running journal for *this clone* of autolens_assistant.

- profile.md — who is working on this clone.
- Dated entries — YYYY-MM-DD-<slug>.md, one per meaningful session.

## File naming

YYYY-MM-DD-<short-slug>.md, five words at most in the slug.

## How to read this folder

Skim the recent entries first, then grep for dataset names.
"""

README_V2 = README_V1.replace(
    "- profile.md — who is working on this clone.",
    "- profile.md — who is working on this clone.\n"
    "- state.md — the head pointer, REWRITTEN each session, never appended.",
).replace(
    "Skim the recent entries first, then grep for dataset names.",
    "Read state.md first, then skim the recent entries, then grep for dataset names.",
)

SKILL_V1 = """# Start New Project

Point $AUTOLENS_ASSISTANT at a local autolens_assistant clone.
Promotion upstream is deliberate, via al_ingest_paper from the assistant clone.
"""

SKILL_V2 = SKILL_V1.replace(
    "# Start New Project\n",
    "# Start New Project\n\n## Session start — do this first, every session\n\n"
    "Read wiki/project/profile.md, wiki/project/state.md, then the newest entry.\n",
)

STATE_TEMPLATE = """---
title: Project state
---

# Project state

## Where we are now
## In flight
"""


def _load():
    spec = importlib.util.spec_from_file_location("_clone_sync_under_test", CLONE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo),
         "-c", "user.email=t@example.invalid", "-c", "user.name=t",
         "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, text=True,
    )


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _commit(repo, message):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    out = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def _init(root):
    root.mkdir(parents=True, exist_ok=True)
    _git(root.parent, "init", "-q", "-b", "main", root.name)
    return root


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A miniature PyAutoLabs: three assistants + the libraries they name."""
    clone = _load()
    monkeypatch.setattr(clone, "PYAUTO_ROOT", tmp_path)

    # `reference_library()` resolves autolens -> PyAutoLens by directory name.
    for lib in ("PyAutoLens", "PyAutoCTI", "PyAutoGalaxy"):
        (tmp_path / lib).mkdir()

    ref = _init(tmp_path / REFERENCE)
    _write(ref, "wiki/project/README.md", README_V1)
    _write(ref, "skills/start-new-project.md", SKILL_V1)
    base = _commit(ref, "reference v1")

    # Both siblings are born from v1 with the birth substitutions applied.
    cti = _init(tmp_path / "autocti_assistant")
    _write(cti, "wiki/project/README.md",
           README_V1.replace("autolens", "autocti"))
    # ... but this one never received the skill file: the reference's change to
    # it must report `absent`, not explode.
    _commit(cti, "born")

    gal = _init(tmp_path / "autogalaxy_assistant")
    # This sibling ADAPTED the exact prose the reference is about to change, so
    # its hunks must be rejected rather than forced.
    _write(gal, "wiki/project/README.md", """# wiki/project/

A running journal for *this clone* of autogalaxy_assistant.

- profile.md — the morphology-fitting user's background and goals.
- Dated entries — one per session; see the galaxy-decomposition examples.

## File naming

Dated slugs, kept short.

## How to read this folder

Grep for the galaxy name first; the entries are decomposition-ordered.
""")
    _write(gal, "skills/start-new-project.md",
           SKILL_V1.replace("AUTOLENS", "AUTOGALAXY")
                   .replace("autolens", "autogalaxy")
                   .replace("al_", "ag_"))
    _commit(gal, "born")

    # The reference moves on: two edits and one new file, all generic.
    _write(ref, "wiki/project/README.md", README_V2)
    _write(ref, "skills/start-new-project.md", SKILL_V2)
    _write(ref, "wiki/project/_state_template.md", STATE_TEMPLATE)
    head = _commit(ref, "reference v2: state.md")

    return argparse.Namespace(
        clone=clone, root=tmp_path, ref=ref, cti=cti, gal=gal,
        base=base, head=head,
    )


def _args(**kw):
    defaults = dict(reference=REFERENCE, target=None, since=None,
                    until="HEAD", apply=False, json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _results(report, target):
    return {row["path"]: row for row in report["targets"][target]["files"]}


def test_discovers_the_siblings_and_not_the_reference(workspace):
    found = workspace.clone.discover_targets(REFERENCE)
    assert found == ["autocti_assistant", "autogalaxy_assistant"]


def test_dry_run_reports_and_writes_nothing(workspace):
    before = (workspace.cti / "wiki/project/README.md").read_text()
    report, rejected = workspace.clone.run_sync(
        _args(since=workspace.base, target=["autocti_assistant"])
    )
    rows = _results(report, "autocti_assistant")

    assert report["dry_run"] is True
    assert rows["wiki/project/README.md"]["result"] == "applied"
    assert rows["wiki/project/_state_template.md"]["result"] == "created"
    # The sibling never had the skill file; that is a report, not a crash.
    assert rows["skills/start-new-project.md"]["result"] == "absent"
    assert rejected is False
    assert (workspace.cti / "wiki/project/README.md").read_text() == before
    assert not (workspace.cti / "wiki/project/_state_template.md").exists()


def test_apply_writes_with_the_names_rewritten(workspace):
    report, rejected = workspace.clone.run_sync(
        _args(since=workspace.base, target=["autocti_assistant"], apply=True)
    )
    assert rejected is False
    text = (workspace.cti / "wiki/project/README.md").read_text()
    assert "state.md — the head pointer" in text
    assert "Read state.md first" in text
    # Substitution: nothing lensing-shaped may leak into the CTI sibling.
    assert "autolens" not in text
    assert (workspace.cti / "wiki/project/_state_template.md").exists()


def test_divergent_sibling_keeps_its_prose_and_reports_rejects(workspace):
    """Apply is per hunk, the way `patch` has always worked: what fits lands,
    what does not is written out as a `.rej` for a human. The sibling's own
    adapted prose is never overwritten to make the reference's text fit."""
    report, rejected = workspace.clone.run_sync(
        _args(since=workspace.base, target=["autogalaxy_assistant"], apply=True)
    )
    rows = _results(report, "autogalaxy_assistant")

    assert rejected is True
    assert rows["wiki/project/README.md"]["result"] == "rejected"
    assert "hunks" in rows["wiki/project/README.md"]["detail"]
    text = (workspace.gal / "wiki/project/README.md").read_text()
    # The adaptation the reference's hunk collided with survives verbatim...
    assert "Grep for the galaxy name first" in text
    assert "Read state.md first" not in text
    # ... and the conflict is left on disk for a human, not resolved silently.
    assert (workspace.gal / "wiki/project/README.md.rej").exists()


def test_substitution_rewrites_the_uppercase_env_var(workspace):
    """Birth omits the UPPERCASE rule; sync must not repeat that."""
    subs = workspace.clone.sync_substitutions(REFERENCE, "autocti_assistant")
    line = "point `$AUTOLENS_ASSISTANT` at a local autolens_assistant clone (al_setup)"
    out = workspace.clone.substitute(line, subs)
    assert "$AUTOCTI_ASSISTANT" in out
    assert "autocti_assistant" in out
    assert "ac_setup" in out
    assert "AUTOLENS" not in out


def test_word_anchor_does_not_rewrite_mid_word(workspace):
    subs = workspace.clone.sync_substitutions(REFERENCE, "autocti_assistant")
    assert workspace.clone.substitute("total_draws external_shear", subs) == (
        "total_draws external_shear"
    )


def test_since_falls_back_to_the_commit_trailer(workspace):
    assert workspace.clone.last_sync_rev(workspace.cti, REFERENCE) is None

    _write(workspace.cti, "NOTES.md", "a sync landed here\n")
    _commit(
        workspace.cti,
        f"chore: sync generic files from the reference\n\n"
        f"Clone-sync: {REFERENCE}@{workspace.base}",
    )
    assert workspace.clone.last_sync_rev(workspace.cti, REFERENCE) == workspace.base

    # With no --since the run resolves the range from that trailer.
    report, _ = workspace.clone.run_sync(_args(target=["autocti_assistant"]))
    assert report["targets"]["autocti_assistant"]["since"] == workspace.base


def test_first_sync_without_since_is_reported_not_guessed(workspace):
    report, rejected = workspace.clone.run_sync(_args(target=["autocti_assistant"]))
    block = report["targets"]["autocti_assistant"]
    assert block["since"] is None
    assert "--since" in block["error"]
    assert rejected is True


def test_only_generic_files_are_synced(workspace):
    """A domain file the reference changed must never cross the boundary."""
    _write(workspace.ref, "wiki/core/lensing.md", "domain content\n")
    _commit(workspace.ref, "reference: a domain page")
    report, _ = workspace.clone.run_sync(
        _args(since=workspace.base, target=["autocti_assistant"])
    )
    assert "wiki/core/lensing.md" not in _results(report, "autocti_assistant")
