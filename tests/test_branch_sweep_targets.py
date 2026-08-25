"""tests/test_branch_sweep_targets.py — the org-wide sweep's target boundary.

The workflow refuses any target this module does not yield, so this is the
line between "a repo whose merged branches get deleted" and "a repo nobody
meant to touch".

Every fixture here uses invented repo names. That is not squeamishness: this
file is `.py` under a framework organ, so the tenant firewall scans it, and an
assertion naming a real satellite repo would be the same leak the module was
rewritten to avoid. Testing against a synthetic body map also tests the actual
contract — categories in, slugs out — rather than today's repo roster.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "branch_sweep_targets", BRAIN_HOME / "bin" / "branch_sweep_targets.py"
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _body_map(entries: dict) -> dict:
    return {"repos": entries}


def test_sweepable_categories_are_included():
    body = _body_map(
        {
            "Lib": {"github": "Org/Lib", "category": "library"},
            "Ws": {"github": "Org/Ws", "category": "workspace"},
            "WsTest": {"github": "Org/WsTest", "category": "workspace_test"},
            "WsDev": {"github": "Org/WsDev", "category": "workspace_developer"},
            "Howto": {"github": "Org/Howto", "category": "howto"},
        }
    )
    assert mod.targets(body) == [
        "Org/Lib",
        "Org/Ws",
        "Org/WsTest",
        "Org/WsDev",
        "Org/Howto",
    ]


def test_non_development_categories_are_excluded():
    """assistant/pipeline/project/admin are where the Never-touched repos live."""
    body = _body_map(
        {
            "Keep": {"github": "Org/Keep", "category": "library"},
            "Sci": {"github": "Org/Sci", "category": "assistant"},
            "Pipe": {"github": "Org/Pipe", "category": "pipeline"},
            "Site": {"github": "Org/Site", "category": "project"},
            "Admin": {"github": "Other/Admin", "category": "admin"},
        }
    )
    assert mod.targets(body) == ["Org/Keep"]


def test_self_sweeping_organs_are_excluded_by_role_not_name():
    """The Mind and the Brain host their own sweeper; two would collide."""
    body = _body_map(
        {
            "TheMind": {"github": "Org/TheMind", "category": "organ", "organ": "Mind"},
            "TheBrain": {"github": "Org/TheBrain", "category": "organ", "organ": "Brain"},
            "TheHeart": {"github": "Org/TheHeart", "category": "organ", "organ": "Heart"},
        }
    )
    assert mod.targets(body) == ["Org/TheHeart"]


def test_unknown_category_is_excluded_not_swept():
    """A category nobody has classified yet must fail closed."""
    body = _body_map(
        {
            "New": {"github": "Org/New", "category": "some_future_kind"},
            "Lib": {"github": "Org/Lib", "category": "library"},
        }
    )
    assert mod.targets(body) == ["Org/Lib"]


def test_missing_category_is_excluded():
    body = _body_map({"Odd": {"github": "Org/Odd"}, "Lib": {"github": "Org/Lib", "category": "library"}})
    assert mod.targets(body) == ["Org/Lib"]


def test_cli_prints_one_slug_per_line(tmp_path):
    import subprocess
    import sys

    import yaml

    path = tmp_path / "repos.yaml"
    path.write_text(
        yaml.safe_dump(
            _body_map(
                {
                    "Lib": {"github": "Org/Lib", "category": "library"},
                    "Sci": {"github": "Org/Sci", "category": "assistant"},
                }
            )
        )
    )
    proc = subprocess.run(
        [sys.executable, str(BRAIN_HOME / "bin" / "branch_sweep_targets.py"), str(path)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split() == ["Org/Lib"]


def test_cli_fails_loudly_on_a_missing_body_map(tmp_path):
    """Silently sweeping nothing would read as a clean run."""
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, str(BRAIN_HOME / "bin" / "branch_sweep_targets.py"), str(tmp_path / "nope.yaml")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "no body map" in proc.stderr
