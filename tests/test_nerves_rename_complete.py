"""tests/test_nerves_rename_complete.py — the PyAutoConf → PyAutoNerves rename
stays finished.

PyAutoBrain#267: the repo/package rename (``PyAutoConf`` → ``PyAutoNerves``,
``autoconf`` → ``autonerves``) was completed in the reader-facing docs but left
live sites behind — a policy alias resolving to a key the body map does not
know, a refactor witness pointing at a deleted repo path, the nightly activity
gate polling the old repo name, and ``/hygiene`` timing an import that no longer
exists. Every one of those was silent: nothing failed, the surfaces just stopped
seeing the Nerves repo.

This test is the prompt's grep acceptance, enforced. The old spellings are
allowed to survive only where they are deliberately *about* the rename — the
history note, the back-compat aliases, and the tests that pin them.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]

# Paths where a pre-rename spelling is deliberate. Each entry is a reason, not a
# waiver: deleting the reason means deleting the entry.
DELIBERATE = {
    # The organism's own record of the rename having happened.
    "ORGANISM.md",
    # The back-compat alias table — old @-mentions in ~150 archived Mind prompts
    # must keep routing to the Nerves repo.
    "config/policy.yaml",
    # The intake conductor's own legacy alias, labelled as such.
    "agents/conductors/intake/_intake.py",
    # The tests that pin the aliases and the gate's repo set.
    "tests/test_policy_seams.py",
    "tests/test_activity_gate.py",
    "tests/test_nerves_rename_complete.py",
}

# `autoconf` also appears inside unrelated words in third-party contexts (GNU
# autoconf, `auto_config`), so match the PyAuto spellings as whole tokens.
STALE = re.compile(r"(?<![A-Za-z0-9_])(PyAutoConf|autoconf)(?![A-Za-z0-9_])")


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(BRAIN_HOME), "ls-files"],
        capture_output=True, text=True, check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def test_no_undeclared_pyautoconf_references():
    offenders: dict[str, list[str]] = {}
    for rel in _tracked_files():
        if rel in DELIBERATE:
            continue
        path = BRAIN_HOME / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue  # binary or a submodule pointer — nothing to grep
        hits = [
            f"{rel}:{n}: {line.strip()}"
            for n, line in enumerate(text.splitlines(), 1)
            if STALE.search(line)
        ]
        if hits:
            offenders[rel] = hits

    assert not offenders, (
        "pre-rename PyAutoConf/autoconf spellings outside the deliberate set — "
        "rename them, or add the path to DELIBERATE with the reason:\n"
        + "\n".join(h for hits in offenders.values() for h in hits)
    )


def test_deliberate_set_has_no_dead_entries():
    """A path that no longer carries the old spelling must leave DELIBERATE.

    Otherwise the allowlist silently grows into a blanket waiver.
    """
    tracked = set(_tracked_files())
    dead = []
    for rel in sorted(DELIBERATE):
        if rel not in tracked:
            dead.append(f"{rel} (not tracked)")
            continue
        if not STALE.search((BRAIN_HOME / rel).read_text(encoding="utf-8")):
            dead.append(f"{rel} (no longer mentions it)")
    assert not dead, "stale DELIBERATE entries: " + ", ".join(dead)
