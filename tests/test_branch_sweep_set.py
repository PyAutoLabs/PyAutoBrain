"""tests/test_branch_sweep_set.py — the org-wide sweep's target list.

`bin/branch_sweep_set.txt` is the only thing standing between the org-wide
sweep and a repo nobody meant to touch: the workflow refuses any target not in
this file. That makes the file a safety boundary, and a safety boundary that
drifts silently from the prose describing it is worth less than none.

So: shape (every line resolves to a real repo), and the two exclusions that
carry a reason — the skill's Never-touched entries, and the two repos that
sweep themselves.
"""

from __future__ import annotations

from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
SET_FILE = BRAIN_HOME / "bin" / "branch_sweep_set.txt"

# skills/repo_cleanup/SKILL.md → "Never touched". Named here so a future
# addition to the sweep set has to argue with a test, not just a comment.
NEVER_TOUCHED = {
    "PyAutoLabs/euclid_strong_lens_modeling_pipeline",
    "PyAutoLabs/autolens_assistant",
}

# Each hosts its own branch_sweep.yml and sweeps itself with its own
# GITHUB_TOKEN; listing them centrally would give one repo two sweepers.
SELF_SWEEPING = {"PyAutoLabs/PyAutoMind", "PyAutoLabs/PyAutoBrain"}


def _entries() -> list[str]:
    lines = SET_FILE.read_text().splitlines()
    return [s for line in lines if (s := line.strip()) and not s.startswith("#")]


def test_every_entry_is_a_well_formed_slug():
    for slug in _entries():
        owner, sep, repo = slug.partition("/")
        assert sep and owner and repo and "/" not in repo, f"malformed entry: {slug!r}"


def test_no_duplicates():
    entries = _entries()
    assert len(entries) == len(set(entries)), "a repo is listed twice"


def test_never_touched_repos_are_absent():
    """The skill's Never-touched list is a decision, not a default."""
    listed = set(_entries())
    assert not (listed & NEVER_TOUCHED), (
        "these are on skills/repo_cleanup/SKILL.md's Never-touched list and must "
        f"not be swept centrally: {sorted(listed & NEVER_TOUCHED)}"
    )


def test_self_sweeping_repos_are_absent():
    listed = set(_entries())
    assert not (listed & SELF_SWEEPING), (
        "these host their own branch_sweep.yml; sweeping them centrally too "
        f"gives one repo two sweepers on different credentials: {sorted(listed & SELF_SWEEPING)}"
    )


def test_every_entry_exists_in_the_body_map():
    """A slug that names no real repo would fail at clone time, mid-sweep."""
    import yaml

    path = BRAIN_HOME.parent / "PyAutoMind" / "repos.yaml"
    if not path.is_file():
        return  # body map not checked out here

    known = {entry["github"] for entry in yaml.safe_load(path.read_text())["repos"].values()}
    unknown = [slug for slug in _entries() if slug not in known]
    assert not unknown, (
        "these are not in PyAutoMind/repos.yaml, so they either do not exist or "
        f"the body map is stale — resolve before sweeping them: {unknown}"
    )
