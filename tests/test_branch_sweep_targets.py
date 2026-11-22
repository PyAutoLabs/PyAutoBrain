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

import subprocess
import sys
from pathlib import Path

import pytest

from _helpers import load_module

BRAIN_HOME = Path(__file__).resolve().parents[1]
SCRIPT = str(BRAIN_HOME / "bin" / "branch_sweep_targets.py")
mod = load_module("branch_sweep_targets", SCRIPT, register=False)


def _body_map(entries: dict) -> dict:
    return {"repos": entries}


_LIB = {"github": "Org/Lib", "category": "library"}


@pytest.mark.parametrize("entries, expected", [
    pytest.param({"Lib": _LIB,
                  "Ws": {"github": "Org/Ws", "category": "workspace"},
                  "WsTest": {"github": "Org/WsTest", "category": "workspace_test"},
                  "WsDev": {"github": "Org/WsDev", "category": "workspace_developer"},
                  "Howto": {"github": "Org/Howto", "category": "howto"}},
                 ["Org/Lib", "Org/Ws", "Org/WsTest", "Org/WsDev", "Org/Howto"],
                 id="sweepable-categories-are-included"),
    # assistant/pipeline/project/admin are where the Never-touched repos live.
    pytest.param({"Keep": {"github": "Org/Keep", "category": "library"},
                  "Sci": {"github": "Org/Sci", "category": "assistant"},
                  "Pipe": {"github": "Org/Pipe", "category": "pipeline"},
                  "Site": {"github": "Org/Site", "category": "project"},
                  "Admin": {"github": "Other/Admin", "category": "admin"}},
                 ["Org/Keep"], id="non-development-categories-are-excluded"),
    # The Mind and the Brain host their own sweeper; two would collide.
    pytest.param({"TheMind": {"github": "Org/TheMind", "category": "organ", "organ": "Mind"},
                  "TheBrain": {"github": "Org/TheBrain", "category": "organ", "organ": "Brain"},
                  "TheHeart": {"github": "Org/TheHeart", "category": "organ", "organ": "Heart"}},
                 ["Org/TheHeart"], id="self-sweeping-organs-are-excluded-by-role-not-name"),
    # A category nobody has classified yet must fail closed.
    pytest.param({"New": {"github": "Org/New", "category": "some_future_kind"}, "Lib": _LIB},
                 ["Org/Lib"], id="unknown-category-is-excluded-not-swept"),
    pytest.param({"Odd": {"github": "Org/Odd"}, "Lib": _LIB},
                 ["Org/Lib"], id="missing-category-is-excluded"),
])
def test_targets(entries, expected):
    assert mod.targets(_body_map(entries)) == expected


# --- outside_owner: the settings sweep's complement -------------------------


@pytest.mark.parametrize("entries, expected", [
    pytest.param({"Lib": _LIB,
                  "Mine": {"github": "Person/Mine", "category": "admin"},
                  "Ws": {"github": "Org/Ws", "category": "workspace"}},
                 ["Person/Mine"], id="yields-only-repos-under-another-account"),
    # The org listing it complements has no category filter, so neither has
    # this. Filtering here would drop precisely the repos the flag exists to
    # find: the categories that end up under a personal account are the ones
    # `targets()` excludes, so a category-filtered complement would always be
    # empty.
    pytest.param({"Sci": {"github": "Person/Sci", "category": "assistant"},
                  "Admin": {"github": "Person/Admin", "category": "admin"},
                  "Pipe": {"github": "Person/Pipe", "category": "pipeline"},
                  "Site": {"github": "Person/Site", "category": "project"},
                  "Odd": {"github": "Person/Odd", "category": "some_future_kind"},
                  "InOrg": {"github": "Org/InOrg", "category": "library"}},
                 ["Person/Sci", "Person/Admin", "Person/Pipe", "Person/Site", "Person/Odd"],
                 id="ignores-categories-on-purpose"),
    pytest.param({"Lib": _LIB, "Sci": {"github": "Org/Sci", "category": "assistant"}},
                 [], id="is-empty-when-every-repo-is-in-the-org"),
    # `Org` must not claim `OrgOther/…` — the split is on the slash.
    pytest.param({"Near": {"github": "OrgOther/Near", "category": "library"},
                  "Ours": {"github": "Org/Ours", "category": "library"}},
                 ["OrgOther/Near"], id="matches-on-the-whole-owner-not-a-prefix"),
])
def test_outside_owner(entries, expected):
    assert mod.outside_owner(_body_map(entries), "Org") == expected


# --- CLI --------------------------------------------------------------------


def _write_body_map(tmp_path, entries):
    import yaml

    path = tmp_path / "repos.yaml"
    # sort_keys=False: the output order is body-map order, and an alphabetised
    # dump would test the dumper instead of the module.
    path.write_text(yaml.safe_dump(_body_map(entries), sort_keys=False))
    return path


def _cli(*args):
    return subprocess.run([sys.executable, SCRIPT, *map(str, args)],
                          capture_output=True, text=True)


def test_cli_matches_the_function(tmp_path):
    path = _write_body_map(
        tmp_path,
        {
            "TheMind": {"github": "Org/TheMind", "category": "organ", "organ": "Mind"},
            "Lib": _LIB,
            "Mine": {"github": "Person/Mine", "category": "admin"},
        },
    )
    plain = _cli(path)
    assert plain.stdout.split() == ["Org/Lib"], plain.stderr
    complement = _cli("--outside-owner", "Org", path)
    assert complement.stdout.split() == ["Person/Mine"], complement.stderr


@pytest.mark.parametrize("args, message", [
    # A bare flag must not swallow the body-map path as the owner. It would
    # otherwise report every repo as "outside <path>" — a wrong answer
    # delivered with exit 0. Here the path is consumed as the owner, so no
    # path argument survives and the usage guard fires; either way the
    # contract is that it fails and prints no slug, not which message it chose.
    pytest.param(["--outside-owner", "{path}"], "", id="outside-owner-without-a-value"),
    # Nothing follows the flag at all — the message should say what is missing.
    pytest.param(["--outside-owner"], "needs an owner", id="outside-owner-at-the-end"),
    # A typo'd flag — or the retired `--include-self-sweeping` from a stale
    # caller — must not read as "no flag" and silently sweep the wrong set.
    pytest.param(["--include-everything", "{path}"], "usage:", id="unknown-flag"),
])
def test_cli_usage_errors_exit_2_and_print_no_slug(tmp_path, args, message):
    path = _write_body_map(tmp_path, {"Lib": _LIB})
    proc = _cli(*(a.format(path=path) for a in args))
    assert proc.returncode == 2
    assert proc.stdout.strip() == ""
    assert proc.stderr.strip() and message in proc.stderr


def test_cli_prints_one_slug_per_line(tmp_path):
    path = _write_body_map(tmp_path, {"Lib": _LIB,
                                      "Sci": {"github": "Org/Sci", "category": "assistant"}})
    proc = _cli(path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split() == ["Org/Lib"]


def test_cli_fails_loudly_on_a_missing_body_map(tmp_path):
    """Silently sweeping nothing would read as a clean run."""
    proc = _cli(tmp_path / "nope.yaml")
    assert proc.returncode == 1
    assert "no body map" in proc.stderr
