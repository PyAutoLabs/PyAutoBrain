#!/usr/bin/env python3
"""bin/public_names.py — does a change add or rename a public library name?
(PyAutoBrain#641)

    pyauto-brain public-names <owner/repo>#<n> [--json]
    pyauto-brain public-names --repo <path> --range <a>..<b> [--json]
    pyauto-brain public-names --repo-name <Repo> --before <dir> --after <dir> [--json]

WHY. AUTONOMY.md "Public-name narrowing of `glance` — 2026-11-16": a change
that adds or renames a public name in a library package goes to a human `/prm`,
whatever its declared `Consequence:`. The seeded audit's one amended row (row
08, `latent-profile-declarations`) added seven public `latent_*_from` helpers
that no CI, witness or reviewer leg caught. One implementation, run three
ways: deterministically by the shift watcher before it spawns any close-out
session (`_orchestrator.RealSpawner.spawn_closeout`: a hit or a cannot-tell
writes the refusal and no session starts), as a stop in the in-turn tiered
merge (`/prm` reference.md "Tiered merge", the ship skills) and again in the
close-out prompt; the review faculty lists the delta in its ReviewSurface.

WHAT IS PUBLIC (per module, parsed with `ast`, before and after):
  * a module-level `def`, `async def` or `class`, or a `NAME = …` assignment,
    whose name has no leading underscore — including ones under a module-level
    `if` / `try` / `with`;
  * in a package `__init__.py`, also every name it imports (a re-export) and
    every `__all__` entry (`=`, `+=`, `.extend(...)`, `.append(...)`); a
    `from x import *` counts as the name `* from x`.

WHICH REPOS. The libraries the ruling names, listed in `config/policy.yaml`
`public_name_libraries:` (a declared config surface), matched case-folded
(owner, repo and list). Membership is decided before the body map is read, so
a repo outside the list passes even when PyAutoMind is unreadable. A listed
library's package directory is its body-map `package:` (PyAutoMind
`repos.yaml`); no package, an unreadable map or config, or a package directory
missing on the head side cannot tell: the check fails closed rather than pass
a library it did not read.

WHAT IS COMPARED. Only `.py` files under that package directory. Ignored: other
repos (workspaces, organs, assistants), tests (`tests/`, `test_*.py`, `conftest.py`), private
modules (a path part with a leading underscore, other than a dunder file such
as `__init__.py`), private names, and every non-`.py` file — stubs (`.pyi`)
included. A package `__init__` that star-imports (`from .x import *`) a
module the diff changed cannot tell: what it re-exports is not read here.

THE VERDICT. `added` names (new in their module), and `renamed` ones: a public
name removed and another added in the same module, paired best-effort (same
kind, alike spelling). Either is a HIT. A removal with no
addition beside it is not covered by the ruling: it is listed as info. A file
that cannot be read or parsed on either side means the check cannot tell — it
fails closed (`/prm`), as does an unreadable `gh` reply.

Exit status: 0 CLEAN (or not a library repo), 1 HIT, 2 CANNOT-TELL, 64 usage.
`--json` prints one object. `gh` and `git` are behind the `run` seam (a
`subprocess.run`-shaped callable), so the tests are offline.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import json
import subprocess
import sys
import urllib.parse
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

import re

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ci_verdict import GhError, UsageError, _gh, parse_ref  # noqa: E402

BRAIN_HOME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN_HOME / "agents"))
import _pyauto_root  # noqa: E402
from _repo_paths import repo_path  # noqa: E402

CLEAN, HIT, CANNOT = "CLEAN", "HIT", "CANNOT-TELL"
EXIT = {CLEAN: 0, HIT: 1, CANNOT: 2}
EXIT_USAGE = 64

POLICY_PATH = BRAIN_HOME / "config" / "policy.yaml"
#: The Mind is an organ: its name is framework identity, not an instance fact.
MIND_REPO = "PyAuto" + "Mind"

#: Names listed before `+N more` in the one-line reason (the digest line).
REASON_NAMES = 8

#: `pulls/<n>/files` stops at this many files: a PR that reaches it is unread.
GH_FILES_CAP = 3000


class LibrariesError(RuntimeError):
    """The library list or its packages cannot be read: cannot tell."""


def _flow_list(text: str, key: str) -> list[str] | None:
    """A top-level `key: [a, b, …]` flow list, by a stdlib regex (no PyYAML —
    the close-out may run on a bare `python3`)."""
    m = re.search(rf"^{re.escape(key)}:\s*\[([^\]]*)\]", text, re.M)
    if not m:
        return None
    return [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]


def body_map_packages(text: str) -> dict[str, str]:
    """repo name → `package:` from the body map's two-level `repos:` block
    (two-space repo keys, four-space fields), without PyYAML."""
    out: dict[str, str] = {}
    in_repos, current = False, None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            in_repos, current = line.startswith("repos:"), None
            continue
        if not in_repos:
            continue
        m = re.match(r"^  ([A-Za-z0-9._-]+):\s*(#.*)?$", line)
        if m:
            current = m.group(1)
            continue
        m = re.match(r"^    package:\s*['\"]?([A-Za-z0-9_.]+)['\"]?\s*(#.*)?$", line)
        if m and current:
            out[current] = m.group(1)
    return out


def ruled_libraries(policy_path: Path = POLICY_PATH) -> list[str]:
    """The `public_name_libraries:` list. Raises LibrariesError without it."""
    try:
        names = _flow_list(Path(policy_path).read_text(encoding="utf-8"),
                           "public_name_libraries")
    except OSError as e:
        raise LibrariesError(f"config/policy.yaml unreadable: {e}") from e
    if not names:
        raise LibrariesError("no `public_name_libraries:` list in config/policy.yaml")
    return names


def _body_map(map_path: Path | None = None) -> dict[str, str]:
    """casefolded repo name → package, from the body map."""
    if map_path is None:
        map_path = repo_path(_pyauto_root.pyauto_root(), MIND_REPO) / "repos.yaml"
    try:
        text = Path(map_path).read_text(encoding="utf-8")
    except OSError as e:
        raise LibrariesError(f"the body map is unreadable: {e}") from e
    return {k.casefold(): v for k, v in body_map_packages(text).items()}


def load_libraries(policy_path: Path = POLICY_PATH, map_path: Path | None = None) -> dict:
    """{library repo: package directory} for every ruled library. Raises
    LibrariesError when the list, the body map or a package is missing."""
    names = ruled_libraries(policy_path)
    packages = _body_map(map_path)
    missing = [n for n in names if n.casefold() not in packages]
    if missing:
        raise LibrariesError("no body-map `package:` for " + ", ".join(missing))
    return {n: packages[n.casefold()] for n in names}


def repo_key(repo: str) -> str:
    """`Owner/Repo`, a path, a URL or a bare name → the casefolded repo name."""
    name = PurePosixPath(str(repo or "").rstrip("/")).name
    if name.endswith(".git"):
        name = name[:-4]
    return name.casefold()


def library_package(repo: str, libs: dict | None = None,
                    policy_path: Path = POLICY_PATH, map_path: Path | None = None) -> str | None:
    """The package directory of a ruled library repo, matched case-folded, or
    None for any repo the ruling does not cover. Membership comes from `libs`
    or the policy list first, so the body map is read only for a library;
    LibrariesError when a library's package cannot be found."""
    key = repo_key(repo)
    if libs is not None:
        return {k.casefold(): v for k, v in libs.items()}.get(key)
    match = [n for n in ruled_libraries(policy_path) if n.casefold() == key]
    if not match:
        return None
    package = _body_map(map_path).get(key)
    if not package:
        raise LibrariesError(f"no body-map `package:` for {match[0]}")
    return package


def is_library_module(path: str, package: str) -> bool:
    """Whether `path` (repo-relative, `/`-separated) is a public module of
    `package`: a `.py` under it, not a test, not under a private part."""
    parts = PurePosixPath(path).parts
    if len(parts) < 2 or parts[0] != package or not path.endswith(".py"):
        return False
    name = parts[-1]
    if name == "conftest.py" or name.startswith("test_") or name.endswith("_test.py"):
        return False
    for part in parts[1:]:
        if part in ("test", "tests"):
            return False
        stem = part[:-3] if part.endswith(".py") else part
        if stem.startswith("_") and not (stem.startswith("__") and stem.endswith("__")):
            return False
    return True


def module_name(path: str) -> str:
    """`autogalaxy/profiles/__init__.py` → `autogalaxy.profiles`."""
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


# --- the names one module makes public ---------------------------------------------

def _bound(target) -> Iterable[str]:
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            yield from _bound(elt)
    elif isinstance(target, ast.Starred):
        yield from _bound(target.value)


def _strings(node) -> list[str]:
    if isinstance(node, (ast.List, ast.Tuple)):
        return [e.value for e in node.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def _module_statements(body: list) -> Iterable[ast.stmt]:
    """Every statement at module level, through `if` / `try` / `with` blocks
    (never into a function or class body)."""
    for stmt in body:
        yield stmt
        blocks = []
        if isinstance(stmt, ast.If):
            blocks = [stmt.body, stmt.orelse]
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            blocks = [stmt.body]
        elif isinstance(stmt, ast.Try) or type(stmt).__name__ == "TryStar":
            blocks = [stmt.body, stmt.orelse, stmt.finalbody,
                      *[h.body for h in stmt.handlers]]
        for block in blocks:
            yield from _module_statements(block)


def public_names(source: str, is_init: bool = False) -> dict[str, str]:
    """The public names of one module's source, `{name: kind}` — kind is
    `def`, `class`, `assign`, `import` or `__all__`. Raises SyntaxError or
    ValueError when the source does not parse."""
    tree = ast.parse(source)
    names: dict[str, str] = {}
    for stmt in _module_statements(tree.body):
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names[stmt.name] = "def"
        elif isinstance(stmt, ast.ClassDef):
            names[stmt.name] = "class"
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            for t in targets:
                for n in _bound(t):
                    if n == "__all__" and is_init and stmt.value is not None:
                        for s in _strings(stmt.value):
                            names.setdefault(s, "__all__")
                    elif not isinstance(stmt, ast.AugAssign):
                        names[n] = "assign"
        elif (is_init and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
              and isinstance(stmt.value.func, ast.Attribute)
              and isinstance(stmt.value.func.value, ast.Name)
              and stmt.value.func.value.id == "__all__"
              and stmt.value.func.attr in ("extend", "append")):
            for arg in stmt.value.args:
                found = _strings(arg) if stmt.value.func.attr == "extend" else (
                    [arg.value] if isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str) else [])
                for s_ in found:
                    names.setdefault(s_, "__all__")
        elif is_init and isinstance(stmt, ast.Import):
            for a in stmt.names:
                names[a.asname or a.name.split(".")[0]] = "import"
        elif is_init and isinstance(stmt, ast.ImportFrom):
            if stmt.module == "__future__":
                continue
            src = "." * (stmt.level or 0) + (stmt.module or "")
            for a in stmt.names:
                if a.name == "*":
                    names[f"* from {src}"] = "import"
                else:
                    names[a.asname or a.name] = "import"
    return {n: k for n, k in names.items() if not n.startswith("_")}


# --- the comparison -----------------------------------------------------------------

#: How alike two spellings must be (difflib ratio) to be read as a rename.
RENAME_RATIO = 0.4


def _pair_renames(removed: dict[str, str], added: dict[str, str]):
    """Best-effort pairing of one module's removed and added names into
    renames: the same kind (`def`, `class`, ...) and alike spellings, the
    closest pair first. A name left unpaired stays added (a hit either way)
    or removed (info). Returns (renames [(old, new)], added left, removed
    left)."""
    removed, added = dict(removed), dict(added)
    renames = []
    pairs = sorted(
        ((difflib.SequenceMatcher(None, old, new).ratio(), old, new)
         for old in removed for new in added if removed[old] == added[new]),
        key=lambda p: (-p[0], p[1], p[2]))
    for ratio, old, new in pairs:
        if ratio >= RENAME_RATIO and old in removed and new in added:
            renames.append((old, new))
            del removed[old], added[new]
    return renames, added, removed


def star_sources(source: str, init_path: str) -> list[str]:
    """The modules a package `__init__` star-imports, as dotted names."""
    pkg = module_name(init_path).split(".")
    out = []
    for stmt in _module_statements(ast.parse(source).body):
        if isinstance(stmt, ast.ImportFrom) and any(a.name == "*" for a in stmt.names):
            level = stmt.level or 0
            base = pkg[:len(pkg) - (level - 1)] if level else []
            out.append(".".join(base + ([stmt.module] if stmt.module else [])))
    return out


def star_import_hazards(package: str, changes, after: Callable[[str], str]) -> list[str]:
    """Each package `__init__` (after the change) that star-imports a module
    the diff changed: what it re-exports is not read here — cannot tell. An
    `__init__` that cannot be read is no package file (a namespace package)."""
    changed = {module_name(p) for pair in changes for p in pair
               if p and p.endswith(".py") and PurePosixPath(p).parts[:1] == (package,)}
    inits = {"/".join(m.split(".")[:i]) + "/__init__.py"
             for m in changed for i in range(1, len(m.split(".")))}
    out = []
    for init in sorted(inits):
        try:
            source = after(init)
        except Exception:
            continue
        try:
            stars = star_sources(source, init)
        except (SyntaxError, ValueError) as e:
            out.append(f"{init} (after) does not parse: {type(e).__name__}")
            continue
        for src in stars:
            if src in changed:
                out.append(f"{init} star-imports `{src}`, which the diff changed")
    return out


def compare(package: str, changes: Iterable[tuple[str | None, str | None]],
            before: Callable[[str], str], after: Callable[[str], str]) -> dict:
    """The public-name delta over the changed files.

    `changes` are (path before, path after) — None where the file did not
    exist on that side; a renamed file has both. `before` / `after` read a
    path's source on that side (they raise to say it could not be read).
    Only library modules of `package` are compared."""
    changes = list(changes)
    added, renamed, removed = [], [], []
    cannot = star_import_hazards(package, changes, after)
    modules = 0
    for old, new in changes:
        old = old if old and is_library_module(old, package) else None
        new = new if new and is_library_module(new, package) else None
        if not old and not new:
            continue
        modules += 1
        sides = {}
        for side, path, read in (("before", old, before), ("after", new, after)):
            if not path:
                sides[side] = {}
                continue
            try:
                sides[side] = public_names(read(path), path.endswith("__init__.py"))
            except (SyntaxError, ValueError, UnicodeDecodeError) as e:
                cannot.append(f"{path} ({side}) does not parse: "
                              f"{type(e).__name__}: {str(e)[:120]}")
            except Exception as e:   # an unreadable side: fail closed
                cannot.append(f"{path} ({side}) could not be read: {str(e)[:160]}")
        if len(sides) < 2:
            continue
        b, a = sides["before"], sides["after"]
        if old and new and old != new:
            # A moved module: its names are new at the new path.
            for n, k in sorted(a.items()):
                added.append({"module": module_name(new), "name": n, "kind": k})
            for n, k in sorted(b.items()):
                removed.append({"module": module_name(old), "name": n, "kind": k})
            continue
        mod = module_name(new or old)
        gone = {n: k for n, k in b.items() if n not in a}
        new_names = {n: k for n, k in a.items() if n not in b}
        pairs, new_names, gone = _pair_renames(gone, new_names)
        renamed += [{"module": mod, "old": o, "new": n, "kind": a[n]} for o, n in pairs]
        added += [{"module": mod, "name": n, "kind": k} for n, k in sorted(new_names.items())]
        removed += [{"module": mod, "name": n, "kind": k} for n, k in sorted(gone.items())]
    verdict = CANNOT if cannot else HIT if (added or renamed) else CLEAN
    return {"verdict": verdict, "added": added, "renamed": renamed, "removed": removed,
            "cannot_tell": cannot, "modules_compared": modules}


def label(entry: dict) -> str:
    if "old" in entry:
        return f"{entry['module']}.{entry['new']} (renamed from {entry['old']})"
    return f"{entry['module']}.{entry['name']}"


def reason(v: dict) -> str:
    """The one-line refusal reason the close-out writes as its `why` (and the
    digest shows); empty for a CLEAN."""
    if v["verdict"] == CANNOT:
        return ("public-name check could not tell: " + "; ".join(v["cannot_tell"][:2])
                + (f"; +{len(v['cannot_tell']) - 2} more" if len(v["cannot_tell"]) > 2 else "")
                + " → human /prm")
    if v["verdict"] == HIT:
        names = [label(e) for e in v["renamed"]] + [label(e) for e in v["added"]]
        shown = ", ".join(names[:REASON_NAMES])
        more = f" +{len(names) - REASON_NAMES} more" if len(names) > REASON_NAMES else ""
        return f"public name added/renamed: {shown}{more} → human /prm"
    return ""


def summary(v: dict) -> str:
    head = v.get("subject") or "?"
    if v.get("not_library"):
        return (f"{CLEAN}: {head} is not a library repo — the public-name ruling "
                "does not apply")
    if v["verdict"] == CLEAN:
        lines = [f"{CLEAN}: no public name added or renamed in {head} "
                 f"({v['modules_compared']} library module(s) compared)"]
    else:
        lines = [reason(v)]
        for e in v["renamed"]:
            lines.append(f"  renamed: {e['module']}.{e['old']} → {e['new']} ({e['kind']})")
        for e in v["added"]:
            lines.append(f"  added:   {e['module']}.{e['name']} ({e['kind']})")
        for c in v["cannot_tell"]:
            lines.append(f"  cannot tell: {c}")
    for e in v["removed"]:
        lines.append(f"  info — removed (not covered by the ruling): "
                     f"{e['module']}.{e['name']} ({e['kind']})")
    return "\n".join(lines)


def missing_package(package: str) -> str:
    return (f"package directory `{package}/` is missing at the head — the body "
            "map's `package:` may be stale")


def _cannot(subject: str, why: str) -> dict:
    return {"subject": subject, "verdict": CANNOT, "added": [], "renamed": [],
            "removed": [], "cannot_tell": [why], "modules_compared": 0}


def _not_library(subject: str) -> dict:
    return {"subject": subject, "verdict": CLEAN, "not_library": True, "added": [],
            "renamed": [], "removed": [], "cannot_tell": [], "modules_compared": 0}


# --- the reads: a local checkout, two trees, or a PR via `gh` -----------------------

def _git(run, repo: Path, *args: str) -> str:
    res = run(["git", "-C", str(repo), *args], capture_output=True, text=True,
              timeout=120)
    if res.returncode != 0:
        tail = ((res.stderr or res.stdout or "").strip().splitlines() or ["no output"])[-1]
        raise RuntimeError(f"git {' '.join(args[:2])} exited {res.returncode}: {tail[:200]}")
    return res.stdout


def repo_name(repo: Path, run=None) -> str:
    """The repo a checkout holds: its `origin` remote's name, else the folder's
    (a task worktree folder is named for its repo)."""
    run = run or subprocess.run
    try:
        url = _git(run, repo, "remote", "get-url", "origin").strip()
        if url:
            return PurePosixPath(url.rstrip("/").replace(":", "/")).name.removesuffix(".git")
    except Exception:
        pass
    return Path(repo).resolve().name


def name_status_changes(text: str) -> list[tuple[str | None, str | None]]:
    """`git diff --name-status -M` lines → (before path, after path) pairs."""
    out = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        st = parts[0][:1]
        if st in "RC" and len(parts) >= 3:
            out.append((parts[1] if st == "R" else None, parts[2]))
        elif st == "A":
            out.append((None, parts[1]))
        elif st == "D":
            out.append((parts[1], None))
        else:
            out.append((parts[1], parts[1]))
    return out


def for_range(repo: Path, rng: str, name: str = "", run=None,
              libs: dict | None = None) -> dict:
    """The check over `a..b` (or `a...b`) in a local checkout: the before
    side is `merge-base a b`, as a PR's diff is."""
    run = run or subprocess.run
    repo = Path(repo)
    name = name or repo_name(repo, run)
    subject = f"{name} {rng}"
    try:
        package = library_package(name, libs)
    except LibrariesError as e:
        return _cannot(subject, str(e))
    if not package:
        return _not_library(subject)
    sep = "..." if "..." in rng else ".."
    a, _, b = rng.partition(sep)
    if not a or not b:
        raise UsageError(f"not a range: {rng!r} (want <a>..<b>)")
    try:
        base = _git(run, repo, "merge-base", a, b).strip() or a
        head = _git(run, repo, "rev-parse", "--verify", f"{b}^{{commit}}").strip()
        changes = name_status_changes(
            _git(run, repo, "diff", "--name-status", "-M", base, head, "--", package))
    except Exception as e:
        return _cannot(subject, f"the range could not be read: {e}")
    try:
        _git(run, repo, "cat-file", "-e", f"{head}:{package}")
    except Exception:
        return _cannot(subject, missing_package(package))
    v = compare(package, changes, lambda p: _git(run, repo, "show", f"{base}:{p}"),
                lambda p: _git(run, repo, "show", f"{head}:{p}"))
    return {"subject": subject, "base": base, "head": head, **v}


def for_trees(before: Path, after: Path, name: str, libs: dict | None = None) -> dict:
    """The check over two trees on disk (each a copy of the repo root)."""
    subject = f"{name} {before} → {after}"
    try:
        package = library_package(name, libs)
    except LibrariesError as e:
        return _cannot(subject, str(e))
    if not package:
        return _not_library(subject)
    before, after = Path(before), Path(after)
    if not (after / package).is_dir():
        return _cannot(subject, missing_package(package))
    paths = set()
    for root in (before, after):
        pkg = root / package
        if pkg.is_dir():
            paths |= {p.relative_to(root).as_posix() for p in pkg.rglob("*.py")}
    changes = []
    for p in sorted(paths):
        b, a = before / p, after / p
        if b.is_file() and a.is_file() and b.read_bytes() == a.read_bytes():
            continue
        changes.append((p if b.is_file() else None, p if a.is_file() else None))
    v = compare(package, changes, lambda p: (before / p).read_text(encoding="utf-8"),
                lambda p: (after / p).read_text(encoding="utf-8"))
    return {"subject": subject, **v}


def _gh_raw(run, repo: str, path: str, ref: str) -> str:
    """One file's source at `ref`, read-only, through the contents API."""
    argv = ["gh", "api", "-H", "Accept: application/vnd.github.raw",
            f"repos/{repo}/contents/{urllib.parse.quote(path)}?ref={ref}"]
    res = run(argv, capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        tail = ((res.stderr or res.stdout or "").strip().splitlines() or ["no output"])[-1]
        raise GhError(f"contents {path}@{ref[:10]} exited {res.returncode}: {tail[:160]}")
    return res.stdout


def for_pr(ref: str, run=None, libs: dict | None = None) -> dict:
    """The check over one pull request, read-only through `gh api`: the
    before side is the merge base of its base and head, as GitHub's diff is."""
    run = run or subprocess.run
    repo, number = parse_ref(ref)
    subject = f"{repo}#{number}"
    try:
        package = library_package(repo, libs)
    except LibrariesError as e:
        return _cannot(subject, str(e))
    if not package:
        return _not_library(subject)
    try:
        got = _gh(run, f"repos/{repo}/pulls/{number}", "--jq",
                  "{base: .base.sha, head: .head.sha}")
        pr = got[0] if got and isinstance(got[0], dict) else {}
        base_sha, head = str(pr.get("base") or ""), str(pr.get("head") or "")
        if not base_sha or not head:
            return _cannot(subject, "the PR read gave an empty base or head sha")
        mb = _gh(run, f"repos/{repo}/compare/{base_sha}...{head}", "--jq",
                 "{sha: .merge_base_commit.sha}")
        base = str((mb[0] if mb and isinstance(mb[0], dict) else {}).get("sha") or "")
        if not base:
            return _cannot(subject, "the compare read gave an empty merge-base sha")
        try:
            _gh(run, f"repos/{repo}/contents/{package}?ref={head}", "--jq", "{t: type}")
        except GhError:
            return _cannot(subject, missing_package(package))
        files = _gh(run, "--paginate", f"repos/{repo}/pulls/{number}/files?per_page=100",
                    "--jq", ".[] | {filename, status, previous_filename}")
    except GhError as e:
        return _cannot(subject, f"gh could not be read: {e}")
    if len(files) >= GH_FILES_CAP:
        return _cannot(subject, f"the PR lists {len(files)} files — GitHub's cap; "
                       "the diff cannot be read whole")
    changes = []
    for f in files:
        st, path = f.get("status"), f.get("filename")
        if st == "added":
            changes.append((None, path))
        elif st == "removed":
            changes.append((path, None))
        elif st == "renamed":
            changes.append((f.get("previous_filename") or None, path))
        elif st == "copied":
            changes.append((None, path))
        else:
            changes.append((path, path))
    v = compare(package, changes, lambda p: _gh_raw(run, repo, p, base),
                lambda p: _gh_raw(run, repo, p, head))
    return {"subject": subject, "base": base, "head": head, **v}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"public-names: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def main(argv=None, run=None, libs: dict | None = None) -> int:
    p = _Parser(prog="pyauto-brain public-names",
                description="Does a change add or rename a public library name? "
                            "Exit 0 CLEAN, 1 HIT (a human /prm), 2 cannot tell.")
    p.add_argument("pr", nargs="?", help="owner/repo#N, owner/repo/pull/N or the PR URL")
    p.add_argument("--repo", help="a local checkout (with --range)")
    p.add_argument("--range", dest="rng", help="<a>..<b> in --repo")
    p.add_argument("--repo-name", default="",
                   help="the repo's name (default: --repo's origin remote or folder)")
    p.add_argument("--before", help="a tree before the change (with --after, --repo-name)")
    p.add_argument("--after", help="a tree after the change")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    a = p.parse_args(argv)
    try:
        if a.pr and not (a.repo or a.before or a.after):
            v = for_pr(a.pr, run=run, libs=libs)
        elif a.repo and a.rng and not (a.pr or a.before or a.after):
            v = for_range(Path(a.repo), a.rng, name=a.repo_name, run=run, libs=libs)
        elif a.before and a.after and a.repo_name and not (a.pr or a.repo):
            v = for_trees(Path(a.before), Path(a.after), a.repo_name, libs=libs)
        else:
            raise UsageError("pass a PR, or --repo <path> --range <a>..<b>, "
                             "or --repo-name <Repo> --before <dir> --after <dir>")
    except UsageError as e:
        print(f"public-names: {e}", file=sys.stderr)
        return EXIT_USAGE
    if a.json:
        print(json.dumps({**v, "reason": reason(v)}, indent=2))
    else:
        print(summary(v))
    return EXIT[v["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
