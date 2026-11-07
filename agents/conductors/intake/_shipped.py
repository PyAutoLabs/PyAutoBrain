#!/usr/bin/env python3
"""agents/conductors/intake/_shipped.py — the close-out guard (`looks-shipped`).

`intake reconcile` ranks backlog prompts on VOCABULARY: words, rare identifiers
and record lines the prompt shares with the `complete/` archive. It is offline,
opt-in and weak by design (2026-08-25: 24 suspects of 138, mostly weak). The
2026-11-05 queue check-in found four of five picked tasks already shipped, and
a full sweep closed 27 drafts (PyAutoMind#539) — every one of which bypassed
`/prm`, the only path whose close-out runs reconcile at all:

  * fixed directly on main, with no issue or PR;
  * merged by a session that never ran the close-out;
  * re-filed as a duplicate of work a `complete/` record already holds.

This module is the detector for those shapes, graded ABOVE every vocabulary
signal because each leg is a fact someone can re-check, not a resemblance:

  (i)   **witness-exists** — the draft's `Witness:` names a test or function
        that is now DEFINED in one of its target repos and (where git history
        is readable) had NO definition on main at the moment the draft was
        filed. A test named in a witness and written afterwards is the witness
        being met; an edit to a class or test file that already existed is not
        (2026-11-07: 21 of 33 flags were such edits, none shipped).
  (ii)  **commit-names-draft** / **pr-names-draft** — a commit message on an
        organism repo's main since `Filed:` (or a merged PR body, from an
        optional JSON cache) names the draft's path, filename or distinctive
        slug. A Mind commit only counts when it changed something besides the
        ledger: filing, queueing and batching a draft name it all the time.
  (iii) **record-duplicates-draft** — a `complete/` record's `## Original
        prompt` is a near-copy of an open draft (title or body, stdlib difflib).

It only FLAGS. Retiring stays a human act, exactly as for `reconcile`: every
flag carries its evidence line, a one-line close command and a one-line
dismissal. Nothing here writes under `draft/` — the one file the `--apply` path
writes is the Mind's generated `looks_shipped.json`.

Dismissal: `looks_shipped_dismissed.md` in the Mind root, one bullet per draft a
human judged NOT shipped (`- draft/<…>.md — <date> — <why>`). A dismissed draft
is neither flagged nor held back from the batch planner. Confirming is just
closing the draft (`lifecycle.py close … --prompt <path>`): once it leaves
`draft/` it stops being flagged on its own.

Stdlib only; every git read degrades to "no evidence" when a checkout or its
history is absent (CI shallow clones, a laptop with half the organs).
"""
from __future__ import annotations

import datetime as _dt
import difflib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _repo_paths import iter_checkouts  # noqa: E402

FLAGS_FILE = "looks_shipped.json"
DISMISS_FILE = "looks_shipped_dismissed.md"
SCHEMA = 1
GRADE = "looks-shipped"

#: Work-type folders under draft/ that are not backlog (shipped work awaiting a
#: person) — the guard has nothing to say about them.
_SKIP_WORK_TYPES = ("human_review",)
_INDEX_NAMES = ("README.md", "index.md", "AGENTS.md")

# --- header / prompt parsing ---------------------------------------------------
_HEADER_RE = re.compile(r"^([A-Z][A-Za-z-]*):\s*(.*)$")


def parse_header(text: str) -> dict:
    """Top-of-file `Key: value` lines (first 40 lines), lower-cased keys, plus
    the `Repos:` bullet list. Deliberately small: the guard needs four keys."""
    out: dict = {"repos": []}
    in_repos = False
    for line in text.splitlines()[:40]:
        if in_repos:
            m = re.match(r"^\s*-\s+@?([A-Za-z0-9_.-]+)", line)
            if m:
                out["repos"].append(m.group(1))
                continue
            in_repos = False
        m = _HEADER_RE.match(line)
        if not m:
            continue
        key, value = m.group(1).lower(), m.group(2).strip()
        if key == "repos":
            in_repos = not value
            if value:
                out["repos"] += [v.strip().lstrip("@") for v in value.split(",")
                                 if v.strip()]
            continue
        out.setdefault(key, value)
    return out


def title_of(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def _git(repo: Path, *args, timeout: int = 120) -> str | None:
    """`git -C repo …` stdout, or None on any failure (absent git, a timeout,
    an unknown ref). Every caller treats None as "no evidence"."""
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                           text=True, timeout=timeout,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0",
                                "GIT_OPTIONAL_LOCKS": "0"})
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def filed_date(mind: Path, rel: str, header: dict) -> str:
    """`Filed:` from the header; else the date git first saw the file; else ""."""
    m = _ISO.search(header.get("filed", ""))
    if m:
        return m.group(1)
    out = _git(mind, "log", "--diff-filter=A", "--follow", "--format=%as",
               "--", rel)
    dates = (out or "").split()
    return dates[-1] if dates else ""


def slug_forms(rel: str) -> dict:
    """The ways a commit can name a draft: its path, filename and slug."""
    name = rel.rsplit("/", 1)[-1]
    stem = name[:-3] if name.endswith(".md") else name
    sans_draft = rel[len("draft/"):] if rel.startswith("draft/") else rel
    return {"path": rel, "sans_draft": sans_draft, "filename": name, "slug": stem}


def _slug_key(s: str) -> str:
    return "-".join(re.findall(r"[a-z0-9]+", s.lower()))


def filed_at(mind: Path, rel: str, filed: str) -> str:
    """The moment the draft was filed, as precisely as history allows.

    The commit that first added the file, when it falls on the `Filed:` day;
    else the start of that day. Day precision is not enough: a draft is very
    often filed by, or the same day as, the commit that motivated it, and that
    commit must not then count as evidence the draft shipped (2026-11-07: 9 of
    33 flags were exactly that).
    """
    # No `--follow`: drafts share a header template, so rename detection
    # happily "follows" a new draft back into an older sibling's history.
    out = _git(mind, "log", "--diff-filter=A", "--format=%aI", "--", rel)
    stamps = (out or "").split()
    if not filed:
        return stamps[-1] if stamps else ""
    on_day = [s for s in stamps if s[:10] == filed]
    return on_day[-1] if on_day else f"{filed}T00:00:00"


def distinctive_slug(stem: str) -> bool:
    """A bare slug only counts when it is specific: four or more words and
    twenty-plus characters. `dashboard_fix` names half the backlog, and a
    three-word slug is too often an identifier or a phrase in its own right
    (`jax_zero_contour` is a package, `group_los_halos` reads as prose);
    `close_out_guard_catch_shipped_work_whose` names one prompt."""
    parts = re.findall(r"[a-z0-9]+", stem.lower())
    return len(parts) >= 4 and len(stem) >= 20


def open_drafts(mind: Path, prefix: str = "") -> list:
    """Every backlog prompt under draft/ (human_review and indexes excluded).

    An epic's campaign map (`Status: campaign map …`) is excluded too: it is
    never issued itself, its phases ship one by one, and each shipped phase
    looks like evidence against the map (2026-11-07: `lenstwin_epic`).
    """
    out = []
    root = mind / "draft"
    if not root.is_dir():
        return out
    for f in sorted(root.rglob("*.md")):
        rel = f.relative_to(mind).as_posix()
        parts = rel.split("/")
        if f.name in _INDEX_NAMES or (len(parts) > 1 and parts[1] in _SKIP_WORK_TYPES):
            continue
        if prefix and not (rel.startswith(prefix) or
                           rel.startswith("draft/" + prefix.lstrip("/"))):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        header = parse_header(text)
        if header.get("status", "").lower().startswith("campaign map"):
            continue          # an epic's map: its phases ship, it never does
        filed = filed_date(mind, rel, header)
        out.append({
            "path": rel,
            "title": title_of(text),
            "text": text,
            "header": header,
            "target": parts[2] if len(parts) > 3 else "",
            "filed": filed,
            "filed_at": filed_at(mind, rel, filed),
        })
    return out


# --- dismissals and the reader every consumer shares ------------------------------
_DISMISS_RE = re.compile(r"^\s*[-*]\s+`?((?:draft/)?[^\s`]+\.md)`?")


def read_dismissed(mind: Path) -> dict:
    """`looks_shipped_dismissed.md` -> {draft path: the bullet's text}."""
    try:
        text = (Path(mind) / DISMISS_FILE).read_text(encoding="utf-8",
                                                      errors="replace")
    except OSError:
        return {}
    out, fenced = {}, False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = _DISMISS_RE.match(line)
        if m:
            path = m.group(1)
            if not path.startswith("draft/"):
                path = "draft/" + path
            out[path] = line.strip()[2:].strip()
    return out


def active_flags(mind: Path) -> list:
    """The flags a human still has to answer: the generated file, minus drafts a
    human dismissed and minus drafts that have since left `draft/` (confirmed
    and closed). This is what the dashboard renders and the planner obeys —
    reading it at use time means a dismissal or a close takes effect at once,
    not at the next scheduled run."""
    mind = Path(mind)
    try:
        data = json.loads((mind / FLAGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    dismissed = read_dismissed(mind)
    out = []
    for f in (data.get("flags") or []) if isinstance(data, dict) else []:
        path = f.get("path", "") if isinstance(f, dict) else ""
        if not path or path in dismissed or not (mind / path).is_file():
            continue
        out.append(f)
    return out


def flagged_paths(mind: Path) -> set:
    return {f["path"] for f in active_flags(mind)}


# --- organism checkouts -------------------------------------------------------------
def _norm(name: str) -> str:
    """Repo identity folding, aligned with the sizing faculty when it loads.

    `autothing`, `PyAutoThing` and `pyautothing` must meet: the draft folder is
    the package name, the checkout directory is the repo name.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]
                               / "faculties" / "sizing"))
        from _sizing import normalise_repo  # noqa: WPS433
        key = normalise_repo(name)
    except Exception:  # noqa: BLE001 — a missing body map must not break the guard
        key = name.strip().lstrip("@").lower()
    return key[len("pyauto"):] if key.startswith("pyauto") and len(key) > 6 else key


def local_repos(root: Path, mind: Path) -> dict:
    """{repo name: checkout path} for every organism checkout under `root`.

    The Mind under scan is always included as `PyAutoMind` (it may be a
    worktree elsewhere). Linked worktrees (`.git` is a file) and dot-dirs are
    skipped: a worktree is a second view of a repo already listed, and scanning
    it twice would double every piece of evidence.
    """
    repos = {"PyAutoMind": Path(mind)}
    try:
        found = iter_checkouts(Path(root)) if root else []
    except (ValueError, OSError):
        found = []
    for p in found:
        if p.name.startswith(".") or p.name in repos or (p / ".git").is_file():
            continue
        if p.resolve() == Path(mind).resolve():
            continue
        repos[p.name] = p
    return repos


def main_ref(repo: Path) -> str:
    """The ref that is `main` here: origin/main, else main, else HEAD."""
    for ref in ("origin/main", "main", "origin/master", "master"):
        if _git(repo, "rev-parse", "--verify", "--quiet", ref + "^{commit}") is not None:
            return ref
    return "HEAD"


# --- leg (i): the witness names something that now exists ----------------------------
_TEST_NAME = re.compile(r"\b(test_[A-Za-z0-9_]{4,})\b")
_TICKED = re.compile(r"`([^`\n]{3,120})`")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("
                     r"|^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b")
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".tox", ".venv", "venv",
              "build", "dist", "site-packages", ".mypy_cache", ".pytest_cache",
              "dataset", "datasets", "output", "data"}


def witness_names(witness: str) -> set:
    """The tests and functions a witness names.

    Any `test_*` word, plus backticked callables: `fit_from()`,
    `module.func`, `tests/x.py::test_y`, `CamelCase`, `snake_case_name`.
    Paths, flags and prose in backticks are dropped.
    """
    names = set(_TEST_NAME.findall(witness))
    for raw in _TICKED.findall(witness):
        token = raw.strip()
        if " " in token or token.startswith("-") or "=" in token:
            continue
        token = token.split("::")[-1]
        token = re.sub(r"\(.*\)?$", "", token)
        if "/" in token or token.endswith((".py", ".md", ".yml", ".yaml",
                                           ".json", ".toml", ".txt", ".csv")):
            continue
        token = token.rsplit(".", 1)[-1]
        if not _IDENT.match(token):
            continue
        snake = "_" in token.strip("_") and len(token) >= 8
        camel = bool(re.match(r"^[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+$", token))
        called = raw.rstrip().endswith(")")
        if snake or camel or (called and len(token) >= 6):
            names.add(token)
    return names


def definitions(repo: Path, names: set) -> dict:
    """name -> ['relpath:line', …] for `def name(` / `class name` in .py files,
    plus a test FILE whose stem is the name (`test_x` -> `tests/test_x.py:1`):
    a witness says "test_repos_sync_standards_block passes" about a module as
    often as about a function."""
    found: dict = {}
    if not names:
        return found
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames
                       if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            p = Path(dirpath) / fn
            rel = p.relative_to(repo).as_posix()
            if fn.startswith("test_") and fn[:-3] in names:
                found.setdefault(fn[:-3], []).append(f"{rel}:1")
            try:
                with p.open(encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, 1):
                        if "def " not in line and "class " not in line:
                            continue
                        m = _DEF_RE.match(line)
                        if not m:
                            continue
                        name = m.group(1) or m.group(2)
                        if name in names:
                            found.setdefault(name, []).append(f"{rel}:{i}")
            except OSError:
                continue
    return found


def defined_at(repo: Path, name: str, commit: str) -> bool:
    """Did `name` have a definition anywhere in the repo's .py files at
    `commit`? A `def name(` / `class name`, or a test FILE `name.py`."""
    pat = (r"^[[:space:]]*(async[[:space:]]+)?def[[:space:]]+" + name +
           r"[[:space:]]*\(|^[[:space:]]*class[[:space:]]+" + name +
           r"([^A-Za-z0-9_]|$)")
    out = _git(repo, "grep", "-l", "-E", pat, commit, "--", "*.py", timeout=300)
    if out and out.strip():
        return True
    if name.startswith("test_"):
        files = _git(repo, "ls-tree", "-r", "--name-only", commit, timeout=300)
        return any(f == f"{name}.py" or f.endswith(f"/{name}.py")
                   for f in (files or "").splitlines())
    return False


def added_since(repo: Path, name: str, where: list, since: str,
                ref: str) -> str | None:
    """Did the thing the witness names come into existence after `since`?

    Returns `"added by <sha> <date> <subject>"`, "" when history is readable
    and says no, or None when there is no readable history at all.

    A name the witness merely mentions — the class a bug lives in, the test
    file a new case will join, a helper that already existed — was there when
    the draft was filed, and later edits to it are not the witness being met:
    on 2026-11-07, 21 of 33 flags were exactly that (`FitInterferometer`,
    `LensCalc`, `test_presentation`, …), and none had shipped. So the name
    must have had NO definition on main at `since` — the draft's filing
    moment — and have one now. A same-named definition added elsewhere does
    not count either, for the same reason.
    """
    if _git(repo, "rev-parse", "--git-dir") is None:
        return None
    base = _git(repo, "rev-list", "-1", f"--before={since}", ref)
    if base is None:
        return None
    base = base.strip()
    if base and defined_at(repo, name, base):
        return ""
    since_arg = f"--since={since}"
    fmt = "--format=%h %as %s"
    for needle in (f"def {name}(", f"class {name}"):
        out = _git(repo, "log", ref, since_arg, "-S", needle, fmt, "--",
                   "*.py", timeout=300)
        if out is None:
            return None
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        if lines:
            return "added by " + lines[-1]
    for w in where[:3]:
        rel = w.rpartition(":")[0]
        if rel.rsplit("/", 1)[-1] == f"{name}.py":
            out = _git(repo, "log", ref, since_arg, "--diff-filter=A", fmt,
                       "--", rel)
            lines = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
            if lines:
                return "added by " + lines[-1]
    return ""


def _draft_repos(d: dict, repos: dict) -> list:
    """The local checkouts a draft targets: its folder target + `Repos:`."""
    want = {_norm(x) for x in [d["target"], *d["header"].get("repos", [])] if x}
    return [(name, path) for name, path in repos.items() if _norm(name) in want]


def leg_witness(drafts: list, repos: dict) -> dict:
    """(i) path -> [signal, …]."""
    wanted: dict = {}
    for d in drafts:
        names = witness_names(d["header"].get("witness", ""))
        if not names or not d["filed"]:
            continue
        for name, path in _draft_repos(d, repos):
            wanted.setdefault(name, (path, set()))[1].update(names)
    defs = {name: definitions(path, names) for name, (path, names) in wanted.items()}
    refs: dict = {}
    out: dict = {}
    for d in drafts:
        names = witness_names(d["header"].get("witness", ""))
        if not names or not d["filed"]:
            continue
        for repo_name, path in _draft_repos(d, repos):
            for name in sorted(names):
                where = defs.get(repo_name, {}).get(name)
                if not where:
                    continue
                if repo_name not in refs:
                    refs[repo_name] = main_ref(path)
                how = added_since(path, name, where, d["filed_at"] or d["filed"],
                                  refs[repo_name])
                if how == "":
                    continue          # it existed when the draft was filed
                if how is None and not name.startswith("test_"):
                    continue          # no history: only a named TEST is enough
                ev = (f"Witness names `{name}`, defined in {repo_name} "
                      f"{where[0]}")
                ev += (f"; {how} (Filed {d['filed']})" if how
                       else " (no git history to date it)")
                out.setdefault(d["path"], []).append({
                    "kind": "witness-exists", "repo": repo_name,
                    "evidence": ev})
    return out


# --- leg (ii): a commit / merged PR names the draft ------------------------------
#: Words that make a mention a pointer to still-open work, not a claim it shipped.
_FOLLOWUP = ("follow-up", "follow up", "followup", "filed", "file ", "files ",
             "deferred", "todo", "to do", "later", "remain", "next step",
             "blocked", "parked", "queue", "re-scope", "rescope", "split", "not ",
             "phase", "partial", "pending", "unrun", "duplicate", "same shape",
             "not yet", "still")
#: Words that make a mention a claim the work landed, matched as whole words
#: ON THE LINE THAT NAMES THE DRAFT. A message line merely NAMING a draft is
#: how audits, sweeps and status notes read — measured on the live Mind
#: (2026-11-05) that alone flagged 14 drafts, none of them shipped. A
#: `fix:`/`feat:` subject no longer lends the claim to a body line: a code
#: commit names the draft it FILED as often as one it fixed ("…; remove once
#: the cost is found (draft/…md)"), which was 7 of 33 flags on 2026-11-07,
#: none shipped. `add` is not a ship word — "add a follow-up" is filing.
_SHIP_RE = re.compile(r"\b(?:fix(?:e[sd])?|implement(?:s|ed)?|ship(?:s|ped)?|"
                      r"close[sd]?|resolve[sd]?|land(?:s|ed)?|complete[sd]?|"
                      r"done|deliver(?:s|ed)?|retire[sd]?|finish(?:es|ed)?)\b",
                      re.I)
#: A subject that says the commit RECORDED intent. Mind filings and status
#: notes name drafts constantly and ship none of them.
_LEDGER_SUBJECT = re.compile(r"^(?:prompt|intake|ledger|queue|batch|shift|sweep|"
                             r"mind|close|epic|registry|status)\b", re.I)
_MERGE_BRANCH = re.compile(r"^Merge pull request #\d+ from \S+?/(\S+)")
#: A message naming this many drafts is an audit list, not a ship.
_LIST_MAX = 2
#: Mind paths that are bookkeeping: a commit touching only these is the Mind
#: recording intent (filing, queueing, batching), never shipping it.
_MIND_LEDGER_DIRS = ("draft/", "active/", "complete/", "batches/")


def _mind_ledger_only(files: list) -> bool:
    for f in files:
        if f.startswith(_MIND_LEDGER_DIRS):
            continue
        if "/" not in f and f.endswith((".md", ".json", ".html")):
            continue
        return False
    return True


def _names(line: str, d: dict) -> bool:
    forms = slug_forms(d["path"])
    if forms["sans_draft"] in line or forms["filename"] in line:
        return True
    # `-`/`_`/`/` all fold to `-`, so a branch `feature/close-out-guard-…`
    # meets the slug `close_out_guard_…`. Only for a distinctive slug.
    return (distinctive_slug(forms["slug"]) and
            f"-{_slug_key(forms['slug'])}-" in f"-{_slug_key(line)}-")


def _mention(message: str, d: dict) -> str | None:
    """The message line that claims draft `d` shipped, or None.

    A line qualifies when it names the draft and either carries a ship word
    itself, or is the PR-merge line whose branch is the draft's slug.
    Follow-up wording on the line disqualifies it, and a ledger subject
    (`prompt:`, `intake:`, …) disqualifies the commit.
    """
    lines = message.splitlines()
    subject = lines[0].strip() if lines else ""
    if _LEDGER_SUBJECT.match(subject):
        return None
    for line in lines:
        if not _names(line, d):
            continue
        low = line.lower()
        if any(w in low for w in _FOLLOWUP):
            continue
        merge = _MERGE_BRANCH.match(line.strip())
        if merge and _names(merge.group(1), d):
            return line.strip()
        if _SHIP_RE.search(line):
            return line.strip()
    return None


def read_commits(repo: Path, since: str, ref: str, with_files: bool) -> list:
    """[{sha, date, message, files}] on `ref` since `since`."""
    fmt = "%x1e%h%x1f%as%x1f%B%x1f"
    args = ["log", ref, f"--since={since}T00:00:00", f"--format={fmt}"]
    if with_files:
        args.append("--name-only")
    out = _git(repo, *args, timeout=300)
    commits = []
    for chunk in (out or "").split("\x1e"):
        if not chunk.strip():
            continue
        parts = chunk.split("\x1f")
        if len(parts) < 3:
            continue
        files = [f for f in (parts[3] if len(parts) > 3 else "").split("\n") if f.strip()]
        commits.append({"sha": parts[0].strip(), "date": parts[1].strip(),
                        "message": parts[2], "files": files})
    return commits


def leg_commits(drafts: list, repos: dict, mind: Path) -> dict:
    """(ii) path -> [signal, …] from commit messages on each checkout's main."""
    dated = [d for d in drafts if d["filed"]]
    if not dated:
        return {}
    since = min(d["filed"] for d in dated)
    out: dict = {}
    mind_res = Path(mind).resolve()
    for repo_name, path in sorted(repos.items()):
        is_mind = Path(path).resolve() == mind_res
        for c in read_commits(path, since, main_ref(path), with_files=is_mind):
            if is_mind and _mind_ledger_only(c["files"]):
                continue
            named = [d for d in dated if c["date"] >= d["filed"]
                     and any(_names(ln, d) for ln in c["message"].splitlines())]
            if len(named) > _LIST_MAX:
                continue
            for d in named:
                line = _mention(c["message"], d)
                if line is None:
                    continue
                out.setdefault(d["path"], []).append({
                    "kind": "commit-names-draft", "repo": repo_name,
                    "evidence": f"{repo_name}@{c['sha']} ({c['date']}): {line[:160]}"})
    return out


def leg_prs(drafts: list, cache: Path | None) -> dict:
    """(ii, PR leg) path -> [signal, …] from a merged-PR JSON cache.

    The cache is a list of `{repo, number, merged_at, title, body, url}` — what
    a networked job (or a human with the GitHub MCP tools) can dump. Absent or
    unreadable cache: no evidence, never an error, so the offline path works.
    """
    if not cache:
        return {}
    try:
        prs = json.loads(Path(cache).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if isinstance(prs, dict):
        prs = prs.get("prs") or []
    out: dict = {}
    for pr in prs if isinstance(prs, list) else []:
        if not isinstance(pr, dict) or not pr.get("merged_at"):
            continue
        merged = str(pr["merged_at"])[:10]
        message = f"{pr.get('title', '')}\n{pr.get('body') or ''}"
        for d in drafts:
            if not d["filed"] or merged < d["filed"]:
                continue
            line = _mention(message, d)
            if line is None:
                continue
            ref = f"{pr.get('repo', '?')}#{pr.get('number', '?')}"
            out.setdefault(d["path"], []).append({
                "kind": "pr-names-draft", "repo": pr.get("repo", ""),
                "evidence": f"{ref} merged {merged}: {line[:160]}"})
    return out


# --- leg (iii): a completion record already holds this prompt -------------------------
_ORIGINAL = re.compile(r"^##\s+Original prompt\s*$", re.M | re.I)
TITLE_RATIO = 0.93
BODY_RATIO = 0.80
_BODY_PREFILTER = 0.45
_BODY_MIN_WORDS = 40


def _prompt_words(text: str) -> list:
    """Prompt prose as words: header lines, comments and the title dropped."""
    keep = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# ") or s.startswith("<!--") or _HEADER_RE.match(s):
            continue
        if re.match(r"^\s*-\s+\S+$", line) and len(s) < 40:
            continue                         # header list bullets (Repos/Themes)
        keep.append(s)
    return re.findall(r"[a-z0-9_]+", " ".join(keep).lower())


def _title_key(title: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", title.lower()))


def _numbers(title: str) -> set:
    return set(re.findall(r"\d+", title))


def records(mind: Path) -> list:
    """[{path, title, words}] for every complete/ record with an Original prompt."""
    out = []
    root = Path(mind) / "complete"
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*.md")):
        if p.name in _INDEX_NAMES:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = _ORIGINAL.search(text)
        if not m:
            continue
        prompt = text[m.end():]
        out.append({"path": p.relative_to(mind).as_posix(),
                    "title": title_of(prompt), "words": _prompt_words(prompt)})
    return out


def leg_records(drafts: list, recs: list) -> dict:
    """(iii) path -> [signal, …]: a record's Original prompt duplicates a draft.

    Title: near-identical (difflib >= TITLE_RATIO) with the same numbers — a
    phased series differs ONLY in its numbers, and `Phase 2` is not a
    duplicate of `Phase 1`. Body: a word-level difflib ratio >= BODY_RATIO
    over prose of at least _BODY_MIN_WORDS words, behind a cheap set-overlap
    prefilter.
    """
    out: dict = {}
    rec_keys = [(r, _title_key(r["title"]), set(r["words"])) for r in recs]
    for d in drafts:
        dkey = _title_key(d["title"])
        dwords = _prompt_words(d["text"])
        dset = set(dwords)
        best = None
        for r, rkey, rset in rec_keys:
            ev = None
            if (dkey and rkey and len(dkey.split()) >= 3
                    and _numbers(d["title"]) == _numbers(r["title"])):
                ratio = difflib.SequenceMatcher(None, dkey, rkey).ratio()
                if ratio >= TITLE_RATIO:
                    ev = ("title", ratio)
            if ev is None and len(dwords) >= _BODY_MIN_WORDS and len(r["words"]) >= _BODY_MIN_WORDS:
                inter = len(dset & rset)
                union = len(dset | rset) or 1
                if inter / union >= _BODY_PREFILTER:
                    sm = difflib.SequenceMatcher(None, dwords, r["words"],
                                                 autojunk=False)
                    if sm.quick_ratio() >= BODY_RATIO:
                        ratio = sm.ratio()
                        if ratio >= BODY_RATIO:
                            ev = ("body", ratio)
            if ev and (best is None or ev[1] > best[1][1]):
                best = (r, ev)
        if best:
            r, (what, ratio) = best
            out.setdefault(d["path"], []).append({
                "kind": "record-duplicates-draft", "repo": "PyAutoMind",
                "evidence": (f"{r['path']} `## Original prompt` matches this "
                             f"draft's {what} ({ratio:.2f}): "
                             f"\"{r['title'][:100]}\"")})
    return out


# --- the detector ----------------------------------------------------------------------
def close_command(path: str, today: str) -> str:
    slug = path.rsplit("/", 1)[-1][:-3].replace("_", "-")
    return (f"python3 scripts/lifecycle.py close {slug} --date {today} "
            f"--from-file <record-body.md> --prompt {path} --apply")


def dismiss_command(path: str, today: str) -> str:
    return (f"echo '- {path} — {today} — <why it is not shipped>' "
            f">> {DISMISS_FILE}")


def detect(mind: Path, root: Path | None = None, prefix: str = "",
           pr_cache: Path | None = None, today: str | None = None) -> dict:
    """Flag open drafts with strong evidence their work already shipped.

    Read-only. `root` is the directory holding the organism checkouts as
    siblings (flat or one family deep); absent checkouts are skipped silently.
    """
    mind = Path(mind)
    today = today or _dt.date.today().isoformat()
    dismissed = read_dismissed(mind)
    drafts = [d for d in open_drafts(mind, prefix) if d["path"] not in dismissed]
    repos = local_repos(root, mind) if root else {"PyAutoMind": mind}
    legs = [leg_witness(drafts, repos), leg_commits(drafts, repos, mind),
            leg_prs(drafts, pr_cache), leg_records(drafts, records(mind))]
    flags = []
    for d in drafts:
        signals = [s for leg in legs for s in leg.get(d["path"], [])]
        if not signals:
            continue
        # One line per (kind, repo) is enough to judge; the rest is a count.
        seen, shown = set(), []
        for s in signals:
            k = (s["kind"], s.get("repo", ""))
            if k in seen:
                continue
            seen.add(k)
            n = sum(1 for x in signals if (x["kind"], x.get("repo", "")) == k)
            if n > 1:
                s = {**s, "evidence": s["evidence"] + f" (+{n - 1} more)"}
            shown.append(s)
        flags.append({
            "path": d["path"], "title": d["title"], "grade": GRADE,
            "filed": d["filed"],
            "signals": shown,
            "close": close_command(d["path"], today),
            "dismiss": dismiss_command(d["path"], today),
        })
    flags.sort(key=lambda f: (-len({s["kind"] for s in f["signals"]}), f["path"]))
    return {"schema": SCHEMA, "generated": today, "scanned": len(drafts),
            "repos": sorted(repos), "dismissed": len(dismissed),
            "flags": flags}


def _body(text: str) -> str:
    """The file minus its `generated` stamp — what decides a rewrite."""
    try:
        obj = json.loads(text)
    except ValueError:
        return text
    if isinstance(obj, dict):
        obj.pop("generated", None)
        for f in obj.get("flags") or []:
            # The close/dismiss commands embed today's date; a re-run on an
            # unchanged Mind must not count as a change.
            if isinstance(f, dict):
                f.pop("close", None)
                f.pop("dismiss", None)
    return json.dumps(obj, sort_keys=True)


def write(mind: Path, res: dict) -> bool:
    """Write `looks_shipped.json` when its content changed; True if written.

    The only write in this module, and never under `draft/`. Idempotent on an
    unchanged Mind, so the daily job commits nothing on a quiet night.
    """
    target = Path(mind) / FLAGS_FILE
    new = json.dumps(res, indent=2) + "\n"
    try:
        old = target.read_text(encoding="utf-8")
    except OSError:
        old = ""
    if old and _body(old) == _body(new):
        return False
    target.write_text(new, encoding="utf-8")
    return True


def emit(res: dict, written: bool | None = None):
    print(f"== Looks shipped (strong evidence): {len(res['flags'])} of "
          f"{res['scanned']} open draft(s) ==")
    print(f"   checkouts read: {', '.join(res['repos']) or '(none)'}"
          + (f" · {res['dismissed']} dismissed" if res.get("dismissed") else ""))
    if not res["flags"]:
        print("  no open draft carries strong evidence of having shipped.")
    for f in res["flags"]:
        print(f"[{GRADE}] {f['path']}")
        for s in f["signals"]:
            print(f"    {s['kind']}: {s['evidence']}")
        print(f"    close:   {f['close']}")
        print(f"    dismiss: {f['dismiss']}")
    if written is not None:
        print(f"\n{FLAGS_FILE}: " + ("written" if written else "unchanged"))
    print("\nA flag is evidence for a human, not a verdict: read the cited "
          "line, then close the\ndraft (confirm) or add it to "
          f"{DISMISS_FILE} (dismiss). Nothing is retired here.")
