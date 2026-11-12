"""The premise check — does a draft's premise still hold on a fresh `main`?

Programme task M1.3, slice 1 (PyAutoBrain#608). In the one live shift that
worked (2026-11-06-pm), 2 of 3 dispatched tasks were obsolete on `main`: one
named a harness deleted five weeks earlier, the other a smoke-cap overrun the
timing record had not shown for days. Both workers noticed and stopped, but
each had been paid for as a full run. The planner's close-out guard looks for
work that ARRIVED; it cannot see a premise that has GONE AWAY. This can.

It is mechanical and cheap — git reads plus, optionally, one `gh api` per
named issue; never an LLM call. For each repo the draft names it views `main`
(fetched first unless told not to, or as it stood at `--at <ISO time>` for a
replay), then checks what the draft names:

- **paths** (backticked tokens with a `/` or a file extension): found on main,
  or GONE (deleted on main — the deleting commit is the evidence), or MOVED
  (renamed, or untracked into `.gitignore` — not gone), or absent with no
  history (a file the work may be meant to create: never evidence);
- **functions** (backticked `name()`): defined on main, or removed (the
  pickaxe commit is the evidence), or never defined;
- **issues and PRs** (`Repo#N`, GitHub URLs): their state, reported only;
- **a timing premise**: a title that claims a smoke duration ("330–354 s")
  against the Heart's permanent smoke-timing record for each named script —
  decisive only when the record is fresh (FRESH_DAYS).

The verdict is one of `ok | obsolete | unknown`:

- `obsolete` — a timing premise the record contradicts, or a GONE artefact the
  title or `Witness:` names (the work cannot be done as written), or every
  named path is gone (two or more — one alone is `unknown`);
- `ok` — something was checked, nothing is gone or contradicted;
- `unknown` — nothing checkable, no repo resolved, or something is gone only
  in the body (the worker reads the evidence and decides).

For a bug, it also says what a worker must reproduce before fixing anything.
Stdlib-only; no instance fact is written here — owners come from each
checkout's own `origin` remote.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import shutil
import subprocess
from pathlib import Path

STATUSES = ("ok", "obsolete", "unknown")
VERIFIED_KEY = "Verified"

#: Extensions that make a backticked token a path even without a `/`.
PATH_EXTS = (".py", ".sh", ".md", ".txt", ".yml", ".yaml", ".json", ".jsonl",
             ".toml", ".ipynb", ".cfg", ".ini", ".rst", ".html", ".js", ".css",
             ".csv", ".fits", ".cjs")
#: Mind-relative record paths — the Mind's own ledger, not a repo's code.
MIND_PREFIXES = ("draft/", "active/", "complete/", "batches/", "planned/")
_TICK_RE = re.compile(r"`([^`\n]{2,200})`")
_PATH_RE = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_./+-]*$")
_FUNC_RE = re.compile(r"^((?:[A-Za-z_]\w*\.)*)([A-Za-z_]\w{2,})\((?:[^()]*)\)$")
_REF_RE = re.compile(r"(?<![\w/#])([A-Za-z][\w.-]*[A-Za-z0-9_])#(\d{1,6})\b")
_URL_RE = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)/(?:issues|pull)/(\d+)")
_SECONDS_RE = re.compile(r"(\d{2,5})(?:\s*[–-]\s*(\d{2,5}))?\s*s\b")
_LINE_SUFFIX_RE = re.compile(r":\d+(?:[-:]\d+)*$")
#: How many of the newest timing rows decide a timing premise.
TIMING_ROWS = 6
#: A timing record older than this (days before the check) decides nothing.
FRESH_DAYS = 14
#: Caps that keep the check cheap on a draft that names everything.
MAX_PATHS, MAX_FUNCS, MAX_REFS = 40, 12, 8


def _git(path: Path, *args, run=subprocess.run, timeout: float = 60) -> str | None:
    try:
        res = run(["git", "-C", str(path), *args], capture_output=True, text=True,
                  timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return res.stdout if res.returncode == 0 else None


# --- the draft ------------------------------------------------------------------

def _header(text: str, key: str) -> str:
    for line in text.splitlines()[:40]:
        if line.lower().startswith(key.lower() + ":"):
            return line.split(":", 1)[1].strip()
    return ""


def _title(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def declared_repos(text: str) -> list[str]:
    """`Repos:` bullets, then `Target:` — as written, resolved later."""
    out: list[str] = []
    m = re.search(r"^Repos:\n((?:- .+\n?)+)", text, re.M)
    if m:
        out += [ln[1:].strip().split()[0] for ln in m.group(1).splitlines() if ln.strip()]
    target = _header(text, "target")
    if target:
        out.append(target.split()[0])
    seen, uniq = set(), []
    for r in out:
        if r.lower() not in seen:
            seen.add(r.lower())
            uniq.append(r)
    return uniq


def _clean_path(token: str) -> str:
    token = token.strip().split("#", 1)[0]
    token = _LINE_SUFFIX_RE.sub("", token)
    while token.startswith("./"):
        token = token[2:]
    return token.rstrip("/")


def _is_path(token: str) -> bool:
    if not _PATH_RE.match(token) or ".." in token or "//" in token:
        return False
    if token.startswith(MIND_PREFIXES) or token.startswith(("http", "-")):
        return False
    name = token.rsplit("/", 1)[-1]
    if "/" in token:
        return bool(name) and not token.startswith("/")
    return name.endswith(PATH_EXTS) and name.rsplit(".", 1)[0] != ""


def extract(text: str) -> dict:
    """What the draft names: paths, functions, issue/PR references."""
    paths, funcs = [], []
    for raw in _TICK_RE.findall(text):
        token = raw.strip()
        fm = _FUNC_RE.match(token)
        if fm and fm.group(2) not in funcs:
            funcs.append(fm.group(2))
            continue
        token = token.split()[0] if token.split() else ""
        cleaned = _clean_path(token)
        if cleaned and _is_path(cleaned) and cleaned not in paths:
            paths.append(cleaned)
    refs = []
    for owner, repo, num in _URL_RE.findall(text):
        key = (f"{owner}/{repo}", int(num))
        if key not in refs:
            refs.append(key)
    for repo, num in _REF_RE.findall(text):
        key = (repo, int(num))
        if key not in refs and not any(r[0].endswith("/" + repo) and r[1] == key[1]
                                       for r in refs):
            refs.append(key)
    return {"paths": paths[:MAX_PATHS], "functions": funcs[:MAX_FUNCS],
            "refs": refs[:MAX_REFS]}


# --- a repo at main -------------------------------------------------------------

class RepoView:
    """One checkout's `main` (or `main` as of `at`): its sha and file tree."""

    def __init__(self, name: str, path: Path, *, fetch: bool, at: str | None, run):
        self.name, self.path, self.run = name, path, run
        self.notes: list[str] = []
        if fetch:
            if _git(path, "fetch", "-q", "origin", "main", run=run, timeout=90) is None:
                self.notes.append(f"{name}: fetch failed — using the cached origin/main")
        base = next((b for b in ("origin/main", "main")
                     if _git(path, "rev-parse", "--verify", "-q", b, run=run)), None)
        self.base = base
        sha = None
        if base and at:
            sha = (_git(path, "rev-list", "-1", f"--before={at}", base, run=run) or "").strip()
        elif base:
            sha = (_git(path, "rev-parse", base, run=run) or "").strip()
        self.sha = sha or None
        listing = _git(path, "ls-tree", "-r", "--name-only", self.sha, run=run) \
            if self.sha else None
        self.files = set((listing or "").splitlines())
        self.dirs = {f.rsplit("/", i)[0] for f in self.files
                     for i in range(1, f.count("/") + 1)}
        self.by_name: dict[str, list[str]] = {}
        for f in self.files:
            self.by_name.setdefault(f.rsplit("/", 1)[-1], []).append(f)

    @property
    def ok(self) -> bool:
        return self.sha is not None

    def short(self) -> str:
        return (self.sha or "?")[:8]

    def locate(self, token: str) -> str | None:
        """The path on main this token names, or None."""
        if token in self.files or token in self.dirs:
            return token
        if "scripts/" + token in self.files:
            return "scripts/" + token
        name = token.rsplit("/", 1)[-1]
        for f in sorted(self.by_name.get(name, [])):
            if "/" not in token or f.endswith("/" + token):
                return f
        if "/" in token:
            hits = sorted(d for d in self.dirs if d.endswith("/" + token))
            if hits:
                return hits[0]
        return None

    def deleted(self, token: str) -> dict | None:
        """The newest commit on main that deleted — or renamed away — the file
        this token names."""
        name = token.rsplit("/", 1)[-1]
        out = _git(self.path, "log", self.sha, "--diff-filter=DR", "-M", "--name-status",
                   "--date=short", "--format=%x00%h %ad %s", "--",
                   f":(glob)**/{name}", run=self.run)
        for block in (out or "").split("\x00")[1:]:
            lines = [ln for ln in block.splitlines() if ln.strip()]
            if not lines:
                continue
            for entry in lines[1:]:
                parts = entry.split("\t")
                if len(parts) < 2:
                    continue
                p = parts[1]
                # `token.endswith("/" + p)` only for a p WITH a directory: a
                # deleted root-level `__init__.py` says nothing about the
                # `pkg/new_module/__init__.py` a draft means to create.
                if p == token or p.endswith("/" + token) \
                        or ("/" in p and token.endswith("/" + p)) \
                        or ("/" not in token and p.rsplit("/", 1)[-1] == token):
                    commit = lines[0]
                    renamed = parts[2] if parts[0].startswith("R") and len(parts) > 2 else None
                    return {"commit": commit, "path": p,
                            "moved_to": renamed or self._moved_to(commit.split()[0], p),
                            "ignored": False if renamed else self._ignored(p)}
        return None

    def _moved_to(self, commit: str, path: str) -> str | None:
        """Where a "deletion" actually went. A pathspec-limited log cannot pair
        a rename (its other side is outside the pathspec), so the deleting
        commit is re-read whole, with rename detection."""
        out = _git(self.path, "show", "-M", "--name-status", "--format=", commit,
                   run=self.run)
        for line in (out or "").splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[0].startswith("R") and parts[1] == path:
                return parts[2]
        return None

    def _ignored(self, path: str) -> bool:
        """A path main stopped TRACKING because it is generated (now in
        `.gitignore`) is not gone — read from the checkout's ignore rules."""
        try:
            res = self.run(["git", "-C", str(self.path), "check-ignore", "-q",
                            "--no-index", path], capture_output=True, text=True,
                           timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return res.returncode == 0

    def defines(self, func: str) -> str | None:
        out = _git(self.path, "grep", "-n", "-E", rf"(def|class) {func}\b",
                   self.sha, "--", "*.py", run=self.run)
        first = (out or "").splitlines()[:1]
        return first[0].split(":", 1)[1] if first else None

    def removed(self, func: str, since: str | None = None) -> str | None:
        """The newest commit since `since` whose diff adds or drops `def func(`.
        A removal older than the draft is history the author wrote against,
        not evidence that its premise went away."""
        args = ["log", self.sha, "-1", "--date=short", "--format=%h %ad %s",
                f"-Sdef {func}("]
        if since:
            args.append(f"--since={since}")
        out = _git(self.path, *args, "--", "*.py", run=self.run, timeout=120)
        return (out or "").strip() or None

    def show(self, rel: str) -> str | None:
        return _git(self.path, "show", f"{self.sha}:{rel}", run=self.run)

    def slug(self) -> str | None:
        url = (_git(self.path, "remote", "get-url", "origin", run=self.run) or "").strip()
        m = re.search(r"[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?$", url)
        return f"{m.group(1)}/{m.group(2)}" if m else None


def checkouts(root: Path) -> dict[str, Path]:
    """Every checkout under the workspace root, by lower-cased name."""
    import sys
    agents = Path(__file__).resolve().parents[2]
    if str(agents) not in sys.path:
        sys.path.insert(0, str(agents))
    from _repo_paths import iter_checkouts
    try:
        return {p.name.lower(): p for p in iter_checkouts(root)}
    except (OSError, ValueError):
        return {}


def code_repos(found_co: dict[str, Path]) -> list[Path]:
    """The local library and organ checkouts — where a function a draft names
    may live even when its `Repos:` header points elsewhere. Read from the
    body map's `category:`; every checkout when there is no body map."""
    mind = found_co.get("pyautomind")
    manifest = mind / "repos.yaml" if mind else None
    if manifest is None or not manifest.is_file():
        return list(found_co.values())
    keep, current = set(), None
    for line in manifest.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
        if m:
            current = m.group(1).lower()
            continue
        m = re.match(r"^    category:\s*(\w+)", line)
        if m and current and m.group(1) in ("library", "organ"):
            keep.add(current)
    return [p for name, p in found_co.items() if name in keep]


def live_definition(path: Path, func: str, at: str | None, run) -> str | None:
    """`def func` / `class func` on this checkout's main (as of `at`), cheaply:
    one ref lookup and one `git grep`, no fetch and no tree listing."""
    base = next((b for b in ("origin/main", "main")
                 if _git(path, "rev-parse", "--verify", "-q", b, run=run)), None)
    if base is None:
        return None
    ref = ((_git(path, "rev-list", "-1", f"--before={at}", base, run=run) or "").strip()
           if at else base)
    if not ref:
        return None
    out = _git(path, "grep", "-l", "-E", rf"(def|class) {func}\b", ref, "--", "*.py",
               run=run)
    first = (out or "").splitlines()[:1]
    return first[0].split(":", 1)[1] if first else None


def _since(text: str, at: str | None) -> str:
    """The evidence bound for a removal: the draft's `Filed:` (else
    `Issued:`) date, else 180 days before the check."""
    for key in ("filed", "issued"):
        day = _parse_day(_header(text, key))
        if day is not None:
            return day.isoformat()
    ref = _parse_day(at or "") or _dt.date.today()
    return (ref - _dt.timedelta(days=180)).isoformat()


# --- the probes -----------------------------------------------------------------

def _claimed_seconds(title: str) -> int | None:
    nums = []
    for a, b in _SECONDS_RE.findall(title):
        nums += [int(a)] + ([int(b)] if b else [])
    nums = [n for n in nums if n >= 60]
    return min(nums) if nums else None


def _parse_day(value: str):
    try:
        return _dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def timing_probe(title: str, scripts: list[tuple[str, str]], heart,
                 now: _dt.date | None = None) -> dict | None:
    """A title that claims a duration, against the Heart's timing record.

    `scripts` is `(repo, path on main)` for every named `.py` that resolved.
    Returns None when the draft makes no timing claim or nothing is recorded.
    Only rows newer than FRESH_DAYS before `now` decide anything: a script
    dropped from the smoke list leaves its last rows behind for ever.
    """
    now = now or _dt.date.today()
    claimed = _claimed_seconds(title)
    # The Heart's record is the SMOKE profile; a release-profile claim (an
    # 1800 s or 3600 s override) is not comparable with it.
    if claimed is None or "smoke" not in title.lower() or not scripts \
            or heart is None or not heart.ok:
        return None
    for repo, script in scripts:
        rel = f"timings/scripts/{repo}.jsonl"
        raw = heart.show(rel)
        if not raw:
            continue
        rows = []
        for line in raw.splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            entry = (rec.get("entries") or {}).get(script)
            if entry:
                rows.append((rec.get("at", ""), float(entry[0]), str(entry[1])))
        if not rows:
            continue
        rows = sorted(rows)[-TIMING_ROWS:]
        secs = [s for _, s, _ in rows]
        span = f"{min(secs):g}–{max(secs):g} s" if len(secs) > 1 else f"{secs[0]:g} s"
        line = (f"PyAutoHeart@{heart.short()} {rel}: the newest {len(rows)} smoke "
                f"runs of {script} took {span} ({rows[0][0][:10]} → {rows[-1][0][:10]}) "
                f"against the title's claimed ≥{claimed} s")
        newest = _parse_day(rows[-1][0])
        if newest is None or (now - newest).days > FRESH_DAYS:
            return {"verdict": "stale-record",
                    "evidence": line + f" — older than {FRESH_DAYS} days, so not decisive"}
        if max(secs) < claimed / 2:
            return {"verdict": "contradicted", "evidence": line}
        if max(secs) >= 0.8 * claimed:
            return {"verdict": "reproduced", "evidence": line}
        return {"verdict": "inconclusive", "evidence": line}
    return None


def _gh_state(slug: str, num: int, run) -> str:
    try:
        res = run(["gh", "api", f"repos/{slug}/issues/{num}", "--jq",
                   '[.state, (if .pull_request then "pr" else "issue" end), '
                   '(.pull_request.merged_at // "")] | @tsv'],
                  capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return "unreadable"
    if res.returncode != 0:
        return "missing" if "Not Found" in (res.stderr or "") else "unreadable"
    parts = res.stdout.strip().split("\t")
    state, kind = parts[0], parts[1] if len(parts) > 1 else "issue"
    merged = len(parts) > 2 and parts[2]
    return f"{kind} {'merged' if merged else state}"


# --- the check ------------------------------------------------------------------

def check(draft: Path, root: Path, *, fetch: bool = True, at: str | None = None,
          offline: bool = False, run=subprocess.run, text: str | None = None,
          views: dict | None = None) -> dict:
    """The premise verdict for one draft. Reads only; writes nothing.

    `views` is a cache shared across drafts (a brief names several that share
    repos), so each repo is fetched and listed once.
    """
    text = draft.read_text(encoding="utf-8", errors="replace") if text is None else text
    title, witness = _title(text), _header(text, "witness")
    work_type = _header(text, "type").lower()
    named = extract(text)
    found_co = checkouts(root)
    views = {} if views is None else views

    def view(name: str):
        key = name.lower()
        if key not in found_co:
            return None
        if key not in views:
            views[key] = RepoView(found_co[key].name, found_co[key], fetch=fetch,
                                  at=at, run=run)
        return views[key]

    evidence: list[str] = []
    declared = declared_repos(text)
    repos = [v for v in (view(r) for r in declared) if v is not None and v.ok]
    # `Target:` may be a category (`workspaces`), not a checkout: only a
    # `Repos:` entry that resolves to nothing is worth saying.
    listed = re.search(r"^Repos:\n((?:- .+\n?)+)", text, re.M)
    listed = {ln[1:].strip().split()[0].lower()
              for ln in (listed.group(1).splitlines() if listed else []) if ln.strip()}
    unresolved = [r for r in declared if r.lower() in listed
                  and (view(r) is None or not view(r).ok)]
    if unresolved:
        evidence.append("unresolved repo(s): " + ", ".join(unresolved))

    found, gone, absent, moved = [], [], [], []
    scripts: list[tuple[str, str]] = []
    for token in named["paths"]:
        targets, tok = repos, token
        head = token.split("/", 1)
        if len(head) == 2 and view(head[0]) is not None and view(head[0]).ok:
            targets, tok = [view(head[0])], head[1]
        if not targets:
            continue
        hit = next(((v, v.locate(tok)) for v in targets if v.locate(tok)), None)
        if hit:
            v, where = hit
            if f"{v.name}:{where}" in found:
                continue
            found.append(f"{v.name}:{where}")
            if where.endswith(".py"):
                scripts.append((v.name, where))
            continue
        dele = next(((v, d) for v in targets if (d := v.deleted(tok))), None)
        if dele and dele[1]["moved_to"]:
            v, d = dele
            moved.append(f"{token} → {v.name}:{d['moved_to']} ({d['commit'].split()[0]})")
        elif dele and dele[1]["ignored"]:
            v, d = dele
            moved.append(f"{token} → untracked, now in {v.name}'s .gitignore "
                         f"({d['commit'].split()[0]})")
        elif dele:
            v, d = dele
            gone.append({"token": token, "repo": v.name, "path": d["path"],
                         "commit": d["commit"]})
        else:
            absent.append(token)

    funcs_found, funcs_gone = [], []
    since = _since(text, at)
    elsewhere = None
    for func in named["functions"]:
        hit = next(((v, d) for v in repos if (d := v.defines(func))), None)
        if hit:
            funcs_found.append(f"{func} ({hit[0].name})")
            continue
        # Not in the declared repos: a live definition in ANY library or organ
        # checkout means the draft just named the wrong repo, not that the
        # function is gone.
        if elsewhere is None:
            declared_paths = {v.path for v in repos}
            elsewhere = [p for p in code_repos(found_co) if p not in declared_paths]
        live = next(((p, f) for p in elsewhere
                     if (f := live_definition(p, func, at, run))), None)
        if live:
            funcs_found.append(f"{func} ({live[0].name}:{live[1]})")
            continue
        rm = next(((v, c) for v in repos if (c := v.removed(func, since))), None)
        if rm:
            funcs_gone.append({"token": f"{func}()", "repo": rm[0].name,
                               "commit": rm[1]})

    refs = []
    if not offline and shutil.which("gh"):
        for repo, num in named["refs"]:
            slug = repo if "/" in repo else (view(repo).slug() if view(repo) else None)
            if slug:
                refs.append(f"{repo}#{num}: {_gh_state(slug, num, run)}")
    elif named["refs"]:
        evidence.append(f"{len(named['refs'])} issue/PR reference(s) not read "
                        "(offline or no gh)")

    timing = timing_probe(title, scripts, view("PyAutoHeart"),
                          now=_parse_day(at) if at else None)

    # The verdict.
    pinned = f"{title}\n{witness}"
    gone_all = gone + funcs_gone
    gone_pinned = [g for g in gone_all if g["token"].rstrip("()") in pinned]
    reasons = []
    if timing and timing["verdict"] == "contradicted":
        reasons.append("the timing record contradicts the title's duration")
    if gone_pinned:
        reasons.append("a file or function the title or Witness: names is gone on main")
    if len(gone) >= 2 and not found and not moved:
        reasons.append("every named path is gone on main")
    checked = len(found) + len(funcs_found) + len(gone_all) + len(moved)
    if reasons:
        status = "obsolete"
    elif not repos or checked == 0:
        status = "unknown"
        reasons.append("nothing checkable resolved" if repos else "no named repo resolved")
    elif gone_all:
        status = "unknown"
        reasons.append("something the body names is gone on main — read the evidence")
    else:
        status = "ok"

    for g in gone_all:
        where = f"{g['repo']}:{g.get('path', g['token'])}"
        evidence.append(f"GONE {g['token']} — {where} removed in {g['commit']}")
    if timing:
        evidence.append(f"timing {timing['verdict']}: {timing['evidence']}")
    if found:
        evidence.append(f"found on main ({len(found)}): " + ", ".join(found[:8])
                        + (" …" if len(found) > 8 else ""))
    if funcs_found:
        evidence.append("defined on main: " + ", ".join(funcs_found[:8]))
    if moved:
        evidence.append("moved, not gone: " + "; ".join(moved[:6]))
    if absent:
        evidence.append("absent, no history (may be work to create): "
                        + ", ".join(absent[:8]))
    evidence += refs
    for v in repos:
        evidence += v.notes

    reproduce = ""
    if work_type == "bug" or "/bug/" in str(draft):
        reproduce = (f"reproduce before fixing: {title}"
                     + (f" — the defect is fixed when: {witness}" if witness else ""))

    return {
        "path": str(draft), "status": status, "reasons": reasons,
        "evidence": evidence, "reproduce": reproduce,
        "repos": {v.name: v.short() for v in repos},
        "at": at or "", "date": (at or _dt.date.today().isoformat())[:10],
    }


def safe_check(draft: Path, root: Path, **kw) -> dict:
    """`check`, but a crash is `unknown (check failed: …)`, never an exit 1:
    only a real `obsolete` may stop a worker."""
    try:
        return check(draft, root, **kw)
    except Exception as e:  # noqa: BLE001 — any failure degrades to unknown
        at = kw.get("at") or ""
        return {"path": str(draft), "status": "unknown",
                "reasons": [f"check failed: {type(e).__name__}: {e}"],
                "evidence": [], "reproduce": "", "repos": {}, "at": at,
                "date": (at or _dt.date.today().isoformat())[:10]}


def verified_value(result: dict) -> str:
    """`<date> <sha>` per repo — the `Verified:` header's value."""
    shas = ", ".join(f"{sha} ({repo})" for repo, sha in sorted(result["repos"].items()))
    return f"{result['date']} {shas}".strip()


def report(result: dict) -> str:
    failed = next((r for r in result["reasons"] if r.startswith("check failed")), "")
    lines = [f"premise: {result['status']}" + (f" ({failed})" if failed else "")
             + f" — {result['path']}"]
    if result["repos"]:
        lines.append("  main: " + ", ".join(f"{r}@{s}" for r, s in result["repos"].items())
                     + (f" (as of {result['at']})" if result["at"] else ""))
    for r in result["reasons"]:
        lines.append(f"  why: {r}")
    for e in result["evidence"]:
        lines.append(f"  - {e}")
    if result["reproduce"]:
        lines.append(f"  {result['reproduce']}")
    if result["status"] == "obsolete":
        lines.append("  → a dispatched worker stops here and reports this evidence")
    return "\n".join(lines)
