"""`pyauto-brain public-names` — added or renamed public library names go to a
human `/prm` (PyAutoBrain#641; AUTONOMY.md "Public-name narrowing of `glance`
— 2026-11-16").

The Witness cases: the seeded audit's row 08 diff (seven `latent_*_from` in
`autogalaxy/convert.py`) is refused; a private helper and a body-only change
pass; a rename is caught; a new `__init__` export is caught; a workspace repo is
ignored; a parse error cannot tell (exit 2); the close-out refusal reaches the
digest. Offline: local git repos in tmp_path, the row's real before/after files
(`fixtures/public_names/row08_latent/`, stored as `.py.txt` so the tenant
firewall does not read upstream library docstrings as organ code), and a fake
`gh` behind the `run` seam. Repo names here are invented (`LibGalaxy`): the
real list is `config/policy.yaml` `public_name_libraries:`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BRAIN_HOME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN_HOME / "bin"))

import public_names as pn  # noqa: E402
from _helpers import git_in as _git  # noqa: E402
from _repo_paths import repo_path  # noqa: E402 — public_names put agents/ on the path

FIXTURE = BRAIN_HOME / "tests" / "fixtures" / "public_names" / "row08_latent"
LATENT = sorted([
    "latent_shear_from", "latent_ellipse_from", "latent_multipole_from",
    "latent_scaled_multipole_from", "latent_light_multipole_3_from",
    "latent_light_multipole_4_from", "latent_light_multipoles_from"])
#: The row's merge commit in the real library checkout, when present.
ROW08_MERGE = "e92eea86a8b2a8345b0d0135876df634d05a7865"
LIBS = {"LibGalaxy": "autogalaxy", "LibLens": "autolens"}

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _real_libs():
    try:
        return pn.load_libraries()
    except pn.LibrariesError as e:
        pytest.skip(f"no body map here: {e}")


def _row08(tmp_path):
    """The fixture's before/after trees, with their real `.py` names."""
    for src in FIXTURE.rglob("*.py.txt"):
        dst = tmp_path / src.relative_to(FIXTURE).with_suffix("")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text())
    return tmp_path / "before", tmp_path / "after"


# --- row 08, the row that made the ruling ---------------------------------------------

def test_witness_row08_all_seven_latent_helpers_are_added_and_refused(tmp_path):
    before, after = _row08(tmp_path)
    v = pn.for_trees(before, after, "LibGalaxy", libs=LIBS)
    assert v["verdict"] == pn.HIT
    assert sorted(e["name"] for e in v["added"]) == LATENT
    assert {e["module"] for e in v["added"]} == {"autogalaxy.convert"}
    assert v["renamed"] == [] and v["removed"] == [] and v["cannot_tell"] == []
    # external_shear.py only gained a class attribute; _multipole_mixin.py is
    # a private module: neither is a public-name change.
    assert v["modules_compared"] == 2
    why = pn.reason(v)
    assert why.startswith("public name added/renamed: autogalaxy.convert.latent_")
    assert why.endswith(" → human /prm")


def test_witness_row08_cli_exits_1_and_prints_the_reason_first(tmp_path, capsys):
    before, after = _row08(tmp_path)
    rc = pn.main(["--repo-name", "LibGalaxy", "--before", str(before),
                  "--after", str(after)], libs=LIBS)
    out = capsys.readouterr().out.splitlines()
    assert rc == 1
    assert out[0].startswith("public name added/renamed:")
    assert sum(1 for line in out if line.startswith("  added:")) == 7


@needs_git
def test_witness_row08_from_the_real_merge_commit_range():
    libs = _real_libs()
    name = next((n for n, pkg in libs.items() if pkg == "autogalaxy"), None)
    assert name, "the ruled libraries include the autogalaxy package"
    import _pyauto_root
    repo = repo_path(_pyauto_root.pyauto_root(), name)
    have = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", ROW08_MERGE],
                          capture_output=True)
    if have.returncode != 0:
        pytest.skip("no library checkout holding row 08's merge commit")
    v = pn.for_range(repo, f"{ROW08_MERGE}^1..{ROW08_MERGE}", name=name, libs=libs)
    assert v["verdict"] == pn.HIT
    assert sorted(e["name"] for e in v["added"]) == LATENT
    assert v["renamed"] == []


# --- a scratch library repo ----------------------------------------------------------

def _repo(tmp_path, name="LibGalaxy", package="autogalaxy", files=None):
    repo = tmp_path / name
    (repo / package).mkdir(parents=True)
    _git(tmp_path, "init", "-q", str(repo))
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _write(repo, files or {
        f"{package}/__init__.py": "from .convert import ell_from\n",
        f"{package}/convert.py": "def ell_from(a):\n    return a\n\nSCALE = 2\n",
    })
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _write(repo, files):
    for path, text in files.items():
        p = repo / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def _change(repo, files, remove=()):
    _write(repo, files)
    for path in remove:
        (repo / path).unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")
    return pn.for_range(repo, "HEAD~1..HEAD", libs=LIBS)


@needs_git
@pytest.mark.parametrize("files,expected", [
    pytest.param({"autogalaxy/convert.py":
                  "def _helper(a):\n    return a\n\n_CACHE = {}\n\n"
                  "def ell_from(a):\n    return _helper(a)\n\nSCALE = 2\n"},
                 {"added": [], "renamed": []}, id="a-private-helper-passes"),
    pytest.param({"autogalaxy/convert.py":
                  "def ell_from(a, b=1):\n    return a * b\n\nSCALE = 3\n"},
                 {"modules_compared": 1}, id="a-body-only-change-passes"),
    pytest.param({"autogalaxy/convert.pyi": "def stub_only() -> int: ...\n"},
                 {"modules_compared": 0}, id="stub-files-are-skipped"),
])
def test_a_change_that_adds_no_public_name_passes(tmp_path, files, expected):
    v = _change(_repo(tmp_path), files)
    assert v["verdict"] == pn.CLEAN
    assert {key: v[key] for key in expected} == expected


@needs_git
def test_a_method_or_class_attribute_is_not_a_module_level_name(tmp_path):
    repo = _repo(tmp_path, files={"autogalaxy/__init__.py": "",
                                  "autogalaxy/profile.py": "class P:\n    pass\n"})
    v = _change(repo, {"autogalaxy/profile.py":
                       "class P:\n    latent = {}\n\n    def new_method(self):\n"
                       "        def inner():\n            pass\n"})
    assert v["verdict"] == pn.CLEAN


@needs_git
def test_a_rename_is_caught(tmp_path):
    repo = _repo(tmp_path)
    v = _change(repo, {"autogalaxy/convert.py":
                       "def ell_comps_from(a):\n    return a\n\nSCALE = 2\n"})
    assert v["verdict"] == pn.HIT and v["added"] == []
    assert v["renamed"] == [{"module": "autogalaxy.convert", "old": "ell_from",
                             "new": "ell_comps_from", "kind": "def"}]
    assert "autogalaxy.convert.ell_comps_from (renamed from ell_from)" in pn.reason(v)


@needs_git
def test_a_new_init_export_is_caught(tmp_path):
    repo = _repo(tmp_path)
    v = _change(repo, {"autogalaxy/__init__.py":
                       "from .convert import ell_from\nfrom .convert import SCALE as scale\n"})
    assert v["verdict"] == pn.HIT
    assert v["added"] == [{"module": "autogalaxy", "name": "scale", "kind": "import"}]


@needs_git
@pytest.mark.parametrize("init,added", [
    pytest.param("from .convert import ell_from\nfrom .extra import *\n"
                 "__all__ = ['ell_from', 'Extra']\n",
                 {"* from .extra", "Extra"}, id="a-new-all-entry-and-star-import"),
    pytest.param("from .convert import ell_from\n__all__ = ['ell_from']\n"
                 "__all__.extend(['Extra'])\n__all__.append('More')\n"
                 "__all__ += ['Third']\n",
                 {"Extra", "More", "Third"}, id="all-extend-append-and-augmented-assign"),
])
def test_new_init_exports_are_read(tmp_path, init, added):
    v = _change(_repo(tmp_path), {"autogalaxy/__init__.py": init})
    assert {e["name"] for e in v["added"]} == added


@needs_git
def test_a_new_module_and_a_module_level_if_block_count(tmp_path):
    repo = _repo(tmp_path)
    v = _change(repo, {"autogalaxy/new.py":
                       "try:\n    import jax\n    HAS_JAX = True\nexcept ImportError:\n"
                       "    HAS_JAX = False\n\nclass Thing:\n    pass\n"})
    assert sorted(e["name"] for e in v["added"]) == ["HAS_JAX", "Thing"]


@needs_git
def test_a_removal_alone_is_info_not_a_hit(tmp_path):
    repo = _repo(tmp_path)
    v = _change(repo, {"autogalaxy/convert.py": "def ell_from(a):\n    return a\n"})
    assert v["verdict"] == pn.CLEAN
    assert v["removed"] == [{"module": "autogalaxy.convert", "name": "SCALE",
                             "kind": "assign"}]
    assert "info — removed" in pn.summary(v)


@needs_git
def test_tests_and_files_outside_the_package_are_ignored(tmp_path):
    repo = _repo(tmp_path)
    v = _change(repo, {"test_autogalaxy/test_convert.py": "def test_new():\n    pass\n",
                       "autogalaxy/tests/helpers.py": "def helper():\n    pass\n",
                       "autogalaxy/test_more.py": "def thing():\n    pass\n",
                       "scripts/tool.py": "def tool():\n    pass\n"})
    assert v["verdict"] == pn.CLEAN and v["modules_compared"] == 0


@needs_git
def test_a_workspace_or_organ_repo_is_ignored(tmp_path):
    for name in ("galaxy_workspace", "OrganBrain", "galaxy_assistant"):
        repo = _repo(tmp_path, name=name, package="autogalaxy")
        v = _change(repo, {"autogalaxy/convert.py": "def brand_new():\n    pass\n"})
        assert v["verdict"] == pn.CLEAN and v.get("not_library"), name
    assert pn.main(["--repo", str(tmp_path / "OrganBrain"), "--range", "HEAD~1..HEAD"],
                   libs=LIBS) == 0


@needs_git
def test_a_parse_error_cannot_tell_and_exits_2(tmp_path, capsys):
    repo = _repo(tmp_path)
    _change(repo, {"autogalaxy/convert.py": "def ell_from(a:\n    return a\n"})
    rc = pn.main(["--repo", str(repo), "--range", "HEAD~1..HEAD"], libs=LIBS)
    out = capsys.readouterr().out
    assert rc == 2
    assert out.startswith("public-name check could not tell: autogalaxy/convert.py (after) "
                          "does not parse")
    assert out.splitlines()[0].endswith("→ human /prm")


@needs_git
def test_an_unreadable_range_cannot_tell(tmp_path):
    repo = _repo(tmp_path)
    v = pn.for_range(repo, "HEAD~1..HEAD", libs=LIBS)   # there is no HEAD~1
    assert v["verdict"] == pn.CANNOT


def test_usage_errors_exit_64(capsys):
    assert pn.main([]) == pn.EXIT_USAGE
    assert pn.main(["not-a-ref"]) == pn.EXIT_USAGE


def test_the_library_list_is_policy_config_with_body_map_packages(tmp_path):
    policy = tmp_path / "policy.yaml"
    body = tmp_path / "repos.yaml"
    policy.write_text("other: 1\npublic_name_libraries: [LibGalaxy, 'LibLens']\n")
    body.write_text("repos:\n  LibGalaxy:\n    path: g/LibGalaxy\n    package: autogalaxy\n"
                    "  LibLens:\n    package: \"autolens\"  # the lens package\n"
                    "  galaxy_workspace:\n    category: workspace\ncategories: {}\n")
    libs = pn.load_libraries(policy, body)
    assert libs == LIBS
    assert pn.library_package("ExampleOrg/LibLens", libs) == "autolens"
    assert pn.library_package("/x/LibGalaxy.git", libs) == "autogalaxy"
    assert pn.library_package("ExampleOrg/galaxy_workspace", libs) is None
    body.write_text("repos:\n  LibGalaxy:\n    package: autogalaxy\n")
    with pytest.raises(pn.LibrariesError, match="LibLens"):
        pn.load_libraries(policy, body)   # a ruled library with no package: fail closed
    policy.write_text("other: 1\n")
    with pytest.raises(pn.LibrariesError):
        pn.load_libraries(policy, body)


def test_an_unreadable_library_list_cannot_tell(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise pn.LibrariesError("config/policy.yaml unreadable")
    monkeypatch.setattr(pn, "ruled_libraries", boom)
    v = pn.for_trees(tmp_path, tmp_path, "AnyRepo")
    assert v["verdict"] == pn.CANNOT and "policy" in v["cannot_tell"][0]
    monkeypatch.setattr(pn, "ruled_libraries", lambda *a, **k: ["LibGalaxy"])
    monkeypatch.setattr(pn, "_body_map", lambda *a, **k: {})
    v = pn.for_trees(tmp_path, tmp_path, "LibGalaxy")   # a library with no package
    assert v["verdict"] == pn.CANNOT and "package" in v["cannot_tell"][0]


def test_the_real_config_rules_the_five_library_packages():
    libs = _real_libs()
    assert sorted(libs.values()) == ["autoarray", "autocti", "autofit", "autogalaxy",
                                     "autolens"]


# --- the PR read: `gh api`, read-only, behind the `run` seam --------------------------

class FakeGh:
    def __init__(self, files, sources, fail=None, merge_base="m" * 40, packages=("autolens",)):
        self.files, self.sources, self.fail, self.calls = files, sources, fail, []
        self.merge_base, self.packages = merge_base, packages

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        path = next(a for a in argv[2:] if a.startswith("repos/"))
        if self.fail and self.fail in path:
            return subprocess.CompletedProcess(argv, 1, "", "HTTP 502")
        if path.endswith("/pulls/7"):
            out = json.dumps({"base": "b" * 40, "head": "h" * 40})
        elif "/compare/" in path:
            out = json.dumps({"sha": self.merge_base})
        elif "/pulls/7/files" in path:
            out = "\n".join(json.dumps(f) for f in self.files)
        elif "/contents/" in path:
            fpath, ref = path.split("/contents/", 1)[1].split("?ref=")
            key = (fpath, ref[0])
            if "--jq" in argv and fpath in self.packages and ref[0] == "h":
                out = json.dumps({"t": "array"})   # the package directory listing
            elif key not in self.sources:
                return subprocess.CompletedProcess(argv, 1, "", "HTTP 404")
            else:
                out = self.sources[key]
        else:
            raise AssertionError(path)
        return subprocess.CompletedProcess(argv, 0, out, "")


def test_a_pr_is_read_from_its_merge_base_and_head():
    gh = FakeGh(
        files=[{"filename": "autolens/lens.py", "status": "modified"},
               {"filename": "autolens/new.py", "status": "added"},
               {"filename": "docs/x.rst", "status": "modified"}],
        sources={("autolens/lens.py", "m"): "def a():\n    pass\n",
                 ("autolens/lens.py", "h"): "def a():\n    return 1\n",
                 ("autolens/new.py", "h"): "class New:\n    pass\n"})
    v = pn.for_pr("ExampleOrg/LibLens#7", run=gh, libs=LIBS)
    assert v["verdict"] == pn.HIT and v["base"] == "m" * 40
    assert [e["name"] for e in v["added"]] == ["New"]
    assert all(c[:2] == ["gh", "api"] for c in gh.calls)   # read-only: gh api only


def test_an_unreadable_gh_reply_cannot_tell():
    gh = FakeGh(files=[], sources={}, fail="/compare/")
    assert pn.for_pr("ExampleOrg/LibLens#7", run=gh, libs=LIBS)["verdict"] == pn.CANNOT
    gh = FakeGh(files=[{"filename": "autolens/lens.py", "status": "modified"}],
                sources={("autolens/lens.py", "m"): "X = 1\n"})
    v = pn.for_pr("ExampleOrg/LibLens#7", run=gh, libs=LIBS)   # head contents 404
    assert v["verdict"] == pn.CANNOT and "could not be read" in v["cannot_tell"][0]


def test_a_non_library_pr_asks_github_nothing():
    gh = FakeGh(files=[], sources={})
    assert pn.main(["ExampleOrg/lens_workspace#7"], run=gh, libs=LIBS) == 0
    assert gh.calls == []


# --- wired: the close-out, the tiered merge, the review surface -----------------------

def test_the_closeout_prompt_runs_the_check_on_its_pr(tmp_path):
    sys.path.insert(0, str(BRAIN_HOME / "tests"))
    from test_orchestrator_closeout import PR1, orch
    tmpl = (BRAIN_HOME / "agents/conductors/batch/closeout_template.md").read_text()
    assert "{public_names_cmd}" in tmpl and "public name added/renamed" in tmpl
    prompt = orch.closeout_prompt("t1", PR1, "draft/x/t1.md", tmp_path / "b.md",
                                  tmp_path / "leases")
    assert f"pyauto-brain public-names {PR1}" in prompt


def test_the_closeout_refusal_reaches_the_digest(tmp_path):
    sys.path.insert(0, str(BRAIN_HOME / "tests"))
    import test_orchestrator_closeout as tc
    before, after = _row08(tmp_path / "row08")
    v = pn.for_trees(before, after, "LibGalaxy", libs=LIBS)
    why = pn.reason(v)
    mind, brief, home, sp = tc._shift(tmp_path)
    tc._tick(brief, mind, home, sp, 1)
    tc._verdict(home, brief, "named", result="refused", pr=tc.PR1, why=why, gate="",
                model="claude-opus-5-5")
    tc._tick(brief, mind, home, sp, 2)
    slot = tc.orch.slot_dir(brief, home)
    c = tc.orch.read_counters(slot)
    assert c["closeouts"][tc.PR1] == {**c["closeouts"][tc.PR1], "state": "refused",
                                      "why": why}
    assert c["glance_auto_merges"] == 0
    d = tc._digest.build(tc._brief.parse(brief.read_text())["brief"], slot, c,
                         health=tc.t._health)
    assert f"awaiting /prm — close-out refused: {why}</sub>" in d


def test_the_tiered_merge_and_ship_skills_refuse_on_a_hit():
    ref = (BRAIN_HOME / "skills/prm/reference.md").read_text()
    tiered = ref.split("## Tiered merge", 1)[1].split("\n## ", 1)[0]
    assert "pyauto-brain public-names" in tiered and "Exit 1" in tiered
    for skill in ("ship_library", "ship_workspace"):
        text = (BRAIN_HOME / "skills" / skill / f"{skill}.md").read_text()
        assert "public-names` exit 1 or 2" in text.replace("\n  ", " ")


def test_the_cli_is_dispatched_by_pyauto_brain(tmp_path):
    libs = _real_libs()
    name = next(n for n, pkg in libs.items() if pkg == "autogalaxy")
    before, after = _row08(tmp_path)
    r = subprocess.run([str(BRAIN_HOME / "bin" / "pyauto-brain"), "public-names",
                        "--repo-name", name, "--before", str(before),
                        "--after", str(after)], capture_output=True, text=True)
    assert r.returncode == 1 and r.stdout.startswith("public name added/renamed:")


@needs_git
def test_the_review_surface_lists_the_public_name_delta(tmp_path, monkeypatch):
    sys.path.insert(0, str(BRAIN_HOME / "agents" / "faculties" / "review"))
    import _review
    monkeypatch.setattr(pn, "ruled_libraries", lambda *a, **k: list(LIBS))
    monkeypatch.setattr(pn, "_body_map",
                        lambda *a, **k: {k_.casefold(): v for k_, v in LIBS.items()})
    repo = _repo(tmp_path)
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _change(repo, {"autogalaxy/convert.py":
                   "def ell_from(a):\n    return a\n\ndef latent_from(a):\n    pass\n"})
    s = _review.repo_surface(repo)
    assert "public-name-added-or-renamed" in s["risk_flags"]
    assert s["public_names"]["verdict"] == pn.HIT
    assert [e["name"] for e in s["public_names"]["added"]] == ["latent_from"]
    assert [e["name"] for e in s["public_names"]["removed"]] == ["SCALE"]
    ws = _repo(tmp_path, name="galaxy_workspace")
    _git(ws, "update-ref", "refs/remotes/origin/main", "HEAD")
    _change(ws, {"autogalaxy/convert.py": "def other():\n    pass\n"})
    assert "public_names" not in _review.repo_surface(ws)


# --- review round 1 (4605a26): case, the watcher gate, packages, stars, merge-base ----

def test_repo_names_match_case_folded_owner_repo_and_list(tmp_path):
    assert pn.library_package("examplelabs/libgalaxy#656".split("#")[0], LIBS) == "autogalaxy"
    assert pn.library_package("EXAMPLE/LIBLENS", LIBS) == "autolens"
    policy, body = tmp_path / "policy.yaml", tmp_path / "repos.yaml"
    policy.write_text("public_name_libraries: [libgalaxy]\n")
    body.write_text("repos:\n  LibGalaxy:\n    package: autogalaxy\n")
    assert pn.library_package("examplelabs/LIBGALAXY", policy_path=policy,
                              map_path=body) == "autogalaxy"
    gh = FakeGh(files=[{"filename": "autolens/new.py", "status": "added"}],
                sources={("autolens/new.py", "h"): "def brand_new():\n    pass\n"})
    assert pn.main(["examplelabs/liblens#7"], run=gh, libs=LIBS) == 1


def test_a_non_library_passes_before_the_body_map_is_read(tmp_path):
    policy = tmp_path / "policy.yaml"
    policy.write_text("public_name_libraries: [LibGalaxy]\n")
    gone = tmp_path / "no-mind" / "repos.yaml"
    assert pn.library_package("x/galaxy_workspace", policy_path=policy, map_path=gone) is None
    with pytest.raises(pn.LibrariesError, match="unreadable"):
        pn.library_package("x/LibGalaxy", policy_path=policy, map_path=gone)


def test_a_non_library_pr_passes_when_mind_is_unreadable(monkeypatch):
    monkeypatch.setattr(pn, "_body_map", lambda map_path=None: (_ for _ in ()).throw(
        pn.LibrariesError("the body map is unreadable")))
    gh = FakeGh(files=[], sources={})
    assert pn.main(["ExampleOrg/some_workspace#7"], run=gh) == 0 and gh.calls == []


def test_a_package_directory_missing_at_the_head_cannot_tell(tmp_path):
    before, after = tmp_path / "b", tmp_path / "a"
    (before / "autogalaxy").mkdir(parents=True)
    (after / "galaxy").mkdir(parents=True)   # a stale `package:`
    v = pn.for_trees(before, after, "LibGalaxy", libs=LIBS)
    assert v["verdict"] == pn.CANNOT and "package directory" in v["cannot_tell"][0]
    gh = FakeGh(files=[], sources={}, packages=())
    v = pn.for_pr("ExampleOrg/LibLens#7", run=gh, libs=LIBS)
    assert v["verdict"] == pn.CANNOT and "package directory" in v["cannot_tell"][0]


@needs_git
def test_a_stale_package_in_a_range_cannot_tell(tmp_path):
    repo = _repo(tmp_path, package="galaxy", files={"galaxy/__init__.py": ""})
    _change(repo, {"galaxy/x.py": "def y():\n    pass\n"})
    v = pn.for_range(repo, "HEAD~1..HEAD", libs=LIBS)   # LIBS says autogalaxy
    assert v["verdict"] == pn.CANNOT and "package directory" in v["cannot_tell"][0]


def test_an_empty_merge_base_cannot_tell():
    gh = FakeGh(files=[], sources={}, merge_base="")
    v = pn.for_pr("ExampleOrg/LibLens#7", run=gh, libs=LIBS)
    assert v["verdict"] == pn.CANNOT and "merge-base" in v["cannot_tell"][0]


@needs_git
@pytest.mark.parametrize("base,change,why", [
    pytest.param({"autogalaxy/__init__.py": "from ._impl import *\n",
                  "autogalaxy/_impl.py": "def a():\n    pass\n"},
                 {"autogalaxy/_impl.py": "def a():\n    pass\n\ndef b():\n    pass\n"},
                 "autogalaxy/__init__.py star-imports `autogalaxy._impl`, a private",
                 id="of-a-changed-private-module"),
    pytest.param({"autogalaxy/__init__.py": "from ... import *\n",
                  "autogalaxy/agg.py": "def a():\n    pass\n"},
                 {"autogalaxy/agg.py": "def a():\n    return 1\n"},
                 "cannot be resolved", id="that-cannot-be-resolved"),
])
def test_a_star_import_cannot_tell(tmp_path, base, change, why):
    v = _change(_repo(tmp_path, files=base), change)
    assert v["verdict"] == pn.CANNOT
    assert why in v["cannot_tell"][0]


@needs_git
def test_a_star_import_of_a_changed_public_module_is_compared_directly(tmp_path):
    repo = _repo(tmp_path, files={"autogalaxy/__init__.py": "from .agg import *\n",
                                  "autogalaxy/agg.py": "def a():\n    pass\n"})
    v = _change(repo, {"autogalaxy/agg.py": "def a():\n    return 1\n"})
    assert v["verdict"] == pn.CLEAN and v["cannot_tell"] == []
    v = _change(repo, {"autogalaxy/agg.py": "def a():\n    return 1\n\ndef b():\n    pass\n"})
    assert v["verdict"] == pn.HIT and [e["name"] for e in v["added"]] == ["b"]


class _Check:
    """A stand-in for the public_names module behind the watcher's gate."""

    def __init__(self, verdict):
        self.verdict = verdict

    def for_pr(self, url):
        return self.verdict

    reason = staticmethod(pn.reason)


def test_the_watcher_gate_says_why_or_nothing():
    gate = sys.modules["test_orchestrator_closeout"].orch.public_names_gate \
        if "test_orchestrator_closeout" in sys.modules else None
    if gate is None:
        sys.path.insert(0, str(BRAIN_HOME / "tests"))
        from test_orchestrator_closeout import orch
        gate = orch.public_names_gate
    clean = {"verdict": pn.CLEAN, "added": [], "renamed": [], "cannot_tell": []}
    assert gate("u", check=_Check(clean)) == ""
    hit = {"verdict": pn.HIT, "added": [{"module": "m", "name": "n"}], "renamed": [],
           "cannot_tell": []}
    assert gate("u", check=_Check(hit)) == "public name added/renamed: m.n → human /prm"
    cannot = {"verdict": pn.CANNOT, "added": [], "renamed": [], "cannot_tell": ["x"]}
    assert gate("u", check=_Check(cannot)) == "public-name check could not tell: x → human /prm"


def test_the_watcher_refuses_a_public_name_pr_before_any_closeout_session(tmp_path):
    sys.path.insert(0, str(BRAIN_HOME / "tests"))
    import test_orchestrator_closeout as tc
    before, after = _row08(tmp_path / "row08")
    why = pn.reason(pn.for_trees(before, after, "LibGalaxy", libs=LIBS))
    launched = []

    def no_claude(argv, **kw):
        launched.append(argv)
        raise AssertionError("no close-out session may start")

    real = tc.orch.RealSpawner(tmp_path / "b.md", "auto", run=no_claude,
                               public_names=lambda url: why if url == tc.PR1 else "")

    class Gated(tc.Spawner):
        def spawn_closeout(self, task, pr_url, prompt_path, lease_dir, **_kw):
            self.closeouts.append((task, pr_url))
            if pr_url != tc.PR1:
                return super().spawn_closeout(task, pr_url, prompt_path, lease_dir)
            return real.spawn_closeout(task, pr_url, prompt_path, lease_dir)

    mind = tc.t._mind(tmp_path / "mind")
    brief = tmp_path / "shift.md"
    brief.write_text(tc.t.BRIEF.format(issue=tc.t.ISSUE, packet=""))
    home, sp = tmp_path / "home", Gated()
    tc.orch.tick(brief, mind, home=home, now=tc.t.NOW, spawner=sp, agents=tc.Agents(),
                 health=tc._health({}))
    tc._tick(brief, mind, home, sp, 1)   # green: the gate refuses PR1
    tc._tick(brief, mind, home, sp, 2)   # the refusal is reaped
    assert launched == []
    slot = tc.orch.slot_dir(brief, home)
    c = tc.orch.read_counters(slot)
    co = c["closeouts"][tc.PR1]
    assert co["state"] == "refused" and co["why"] == why and co.get("agent_id") is None
    assert c["glance_auto_merges"] == 0
    d = tc._digest.build(tc._brief.parse(brief.read_text())["brief"], slot, c,
                         health=tc.t._health)
    assert f"awaiting /prm — close-out refused: {why}</sub>" in d
