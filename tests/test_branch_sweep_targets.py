"""tests/test_branch_sweep_targets.py — the sweep boundaries this module draws.

Two consumers, two boundaries. `targets()` is the org-wide *branch* sweep's:
the workflow refuses any target it does not yield, so it is the line between "a
repo whose merged branches get deleted" and "a repo nobody meant to touch".
`outside_owner()` is the *settings* sweep's complement: that workflow lists the
organisation from the GitHub API, and this supplies only what such a listing
cannot return — body-map repos under another account.

Every fixture here uses invented repo names. That is not squeamishness: this
file is `.py` under a framework organ, so the tenant firewall scans it, and an
assertion naming a real satellite repo would be the same leak the module was
rewritten to avoid. Testing against a synthetic body map also tests the actual
contract — categories in, slugs out — rather than today's repo roster.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
SCRIPT = str(BRAIN_HOME / "bin" / "branch_sweep_targets.py")
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


# --- outside_owner: the settings sweep's complement -------------------------


def test_outside_owner_yields_only_repos_under_another_account():
    body = _body_map(
        {
            "Lib": {"github": "Org/Lib", "category": "library"},
            "Mine": {"github": "Person/Mine", "category": "admin"},
            "Ws": {"github": "Org/Ws", "category": "workspace"},
        }
    )
    assert mod.outside_owner(body, "Org") == ["Person/Mine"]


def test_outside_owner_ignores_categories_on_purpose():
    """The org listing it complements has no category filter, so neither has this.

    Filtering here would drop precisely the repos the flag exists to find: the
    categories that end up under a personal account are the ones `targets()`
    excludes, so a category-filtered complement would always be empty.
    """
    body = _body_map(
        {
            "Sci": {"github": "Person/Sci", "category": "assistant"},
            "Admin": {"github": "Person/Admin", "category": "admin"},
            "Pipe": {"github": "Person/Pipe", "category": "pipeline"},
            "Site": {"github": "Person/Site", "category": "project"},
            "Odd": {"github": "Person/Odd", "category": "some_future_kind"},
            "InOrg": {"github": "Org/InOrg", "category": "library"},
        }
    )
    assert mod.outside_owner(body, "Org") == [
        "Person/Sci",
        "Person/Admin",
        "Person/Pipe",
        "Person/Site",
        "Person/Odd",
    ]


def test_outside_owner_is_empty_when_every_repo_is_in_the_org():
    body = _body_map(
        {
            "Lib": {"github": "Org/Lib", "category": "library"},
            "Sci": {"github": "Org/Sci", "category": "assistant"},
        }
    )
    assert mod.outside_owner(body, "Org") == []


def test_outside_owner_matches_on_the_whole_owner_not_a_prefix():
    """`Org` must not claim `OrgOther/…` — the split is on the slash."""
    body = _body_map(
        {
            "Near": {"github": "OrgOther/Near", "category": "library"},
            "Ours": {"github": "Org/Ours", "category": "library"},
        }
    )
    assert mod.outside_owner(body, "Org") == ["OrgOther/Near"]


# --- CLI --------------------------------------------------------------------


def _write_body_map(tmp_path, entries):
    import yaml

    path = tmp_path / "repos.yaml"
    # sort_keys=False: the output order is body-map order, and an alphabetised
    # dump would test the dumper instead of the module.
    path.write_text(yaml.safe_dump(_body_map(entries), sort_keys=False))
    return path


def test_cli_matches_the_function(tmp_path):
    path = _write_body_map(
        tmp_path,
        {
            "TheMind": {"github": "Org/TheMind", "category": "organ", "organ": "Mind"},
            "Lib": {"github": "Org/Lib", "category": "library"},
            "Mine": {"github": "Person/Mine", "category": "admin"},
        },
    )
    plain = subprocess.run([sys.executable, SCRIPT, str(path)], capture_output=True, text=True)
    assert plain.stdout.split() == ["Org/Lib"], plain.stderr

    complement = subprocess.run(
        [sys.executable, SCRIPT, "--outside-owner", "Org", str(path)],
        capture_output=True,
        text=True,
    )
    assert complement.stdout.split() == ["Person/Mine"], complement.stderr


def test_cli_outside_owner_without_a_value_never_answers(tmp_path):
    """A bare flag must not swallow the body-map path as the owner.

    It would otherwise report every repo as "outside <path>" — a wrong answer
    delivered with exit 0. Here the path is consumed as the owner, so no path
    argument survives and the usage guard fires; either way the contract is
    that it fails and prints no slug, not which message it chose.
    """
    path = _write_body_map(tmp_path, {"Lib": {"github": "Org/Lib", "category": "library"}})
    proc = subprocess.run(
        [sys.executable, SCRIPT, "--outside-owner", str(path)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert proc.stdout.strip() == ""
    assert proc.stderr.strip()


def test_cli_outside_owner_at_the_end_names_the_missing_owner(tmp_path):
    """Nothing follows the flag at all — the message should say what is missing."""
    proc = subprocess.run(
        [sys.executable, SCRIPT, "--outside-owner"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "needs an owner" in proc.stderr


def test_cli_rejects_the_retired_widening_flag(tmp_path):
    """`--include-self-sweeping` is gone; a stale caller must fail, not fall back.

    Reading it as "no flag" would silently sweep the narrow set — the wrong
    answer, delivered with exit 0.
    """
    path = _write_body_map(tmp_path, {"Lib": {"github": "Org/Lib", "category": "library"}})
    proc = subprocess.run(
        [sys.executable, SCRIPT, "--include-self-sweeping", str(path)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "usage:" in proc.stderr


def test_cli_rejects_an_unknown_flag(tmp_path):
    """A typo'd flag must not read as "no flag" and silently sweep the wrong set."""
    proc = subprocess.run(
        [sys.executable, SCRIPT, "--include-everything", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "usage:" in proc.stderr


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
    proc = subprocess.run([sys.executable, SCRIPT, str(path)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split() == ["Org/Lib"]


def test_cli_fails_loudly_on_a_missing_body_map(tmp_path):
    """Silently sweeping nothing would read as a clean run."""
    proc = subprocess.run(
        [sys.executable, SCRIPT, str(tmp_path / "nope.yaml")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "no body map" in proc.stderr
