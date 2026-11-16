"""The questions inbox, Brain side (M3.5, PyAutoBrain#645) — readers only.

PyAutoMind `questions.md` holds the questions shift workers parked on, one
`### Q<n>. <task> — <short ask>` entry each under `## Open`, `## Deferred`,
`## Answered` or `## Dropped` (the section is the state). Its schema and every
write are the Mind's (`scripts/questions_edit.py`): the watcher adds entries
only through its one Mind writer's `question-add` op, which runs Mind's own
`add_text` from the tree it writes, and the human answers in a `/questions`
chat. This module reads the same grammar for three consumers:

- the watcher's parked hold (`read_origin`: the file on Mind `origin/main`, a
  local `git show` after the shift's one fetch — no network of its own);
- the shift digest's one inbox line and the status comment's count;
- the Mind dashboard's read-only inbox section (`read`: the checkout's file).

It also turns what a parked worker left (its `.question.json` sidecar) into
the entry the op carries, sanitised: one line, clipped, no `@`, no leading
`#` or `-`. A test parses one fixture with this reader and with Mind's parser,
so the two cannot drift.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

FILE = "questions.md"
SECTIONS = ("Open", "Deferred", "Answered", "Dropped")
_SECTION_RE = re.compile(r"^##\s+(Open|Deferred|Answered|Dropped)\b")
_HEAD_RE = re.compile(r"^###\s+Q(\d+)\.\s+(.+?)\s*$")
_FIELD_RE = re.compile(r"^-\s+([a-z][a-z-]*):[ \t]*(.*?)\s*$")

#: What the sidecar may carry, and its limits (DESIGN §4.2).
ASK_MAX, OPTION_MAX, OPTIONS_MAX = 200, 120, 4
SIDECAR_SUFFIX = ".question.json"
NO_SIDECAR_ASK = "see the question on the issue"


# --- the grammar ---------------------------------------------------------------

def parse(text: str) -> list[dict]:
    """The entries of a `questions.md` text, in file order: `{id, n, title,
    state, fields}`. The Mind's `lifecycle.questions_parse` reads the same
    grammar; a heading that is not a `Q<n>` entry, or an entry outside the four
    sections, is skipped here (the Mind's check reports it)."""
    out: list[dict] = []
    state, cur, fenced = None, None, False
    for line in (text or "").split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if line.startswith("#"):
            if cur is not None:
                out.append(cur)
                cur = None
            if line.startswith("## ") or line.startswith("# "):
                m = _SECTION_RE.match(line)
                state = m.group(1).lower() if m else None
            elif line.startswith("### ") and state is not None:
                m = _HEAD_RE.match(line)
                if m:
                    cur = {"id": f"Q{int(m.group(1))}", "n": int(m.group(1)),
                           "title": m.group(2), "state": state, "fields": {}}
            continue
        if cur is not None:
            m = _FIELD_RE.match(line)
            if m and m.group(1) not in cur["fields"]:
                cur["fields"][m.group(1)] = m.group(2)
    if cur is not None:
        out.append(cur)
    return out


def task_of(entry: dict) -> str:
    """The task id (prompt stem) an entry is about — the watcher's key."""
    return Path(entry["fields"].get("task") or "").stem


def read(mind) -> list[dict]:
    """The entries of the checkout's `questions.md`; [] when absent."""
    try:
        return parse((Path(mind) / FILE).read_text(encoding="utf-8", errors="replace"))
    except (OSError, TypeError):
        return []


def by_task(entries: list[dict]) -> dict[str, list[dict]]:
    """`{task: [{id, shift, issue, state, answer, comment}]}`."""
    out: dict[str, list[dict]] = {}
    for e in entries:
        f = e["fields"]
        out.setdefault(task_of(e), []).append({
            "id": e["id"], "shift": f.get("shift", ""), "issue": f.get("issue", ""),
            "state": e["state"], "answer": f.get("answer", ""),
            "comment": f.get("answer-comment", ""), "kind": f.get("kind", ""),
            "task": f.get("task", "")})
    return out


def read_origin(mind, ref: str = "origin/main", fetch=None, run=None) -> dict | None:
    """`questions.md` on Mind `origin/main`, as `by_task`, read locally and
    read-only after the shift's one fetch (`fetch`, the writer's own, run first
    when given). `{}` when the ref has no such file (nothing asked yet). None
    when it cannot be read — not a Mind checkout of its own, or git failed — so
    the caller keeps every hold (fail closed)."""
    run = run or subprocess.run

    def git(*args):
        return run(["git", "-C", str(mind), *args], capture_output=True, text=True,
                   timeout=60)
    try:
        top = git("rev-parse", "--show-toplevel")
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != Path(mind).resolve():
            return None
        if fetch is not None:
            fetch()
        shown = git("show", f"{ref}:{FILE}")
        if shown.returncode != 0:
            listed = git("ls-tree", "--name-only", ref, "--", FILE)
            if listed.returncode == 0 and not listed.stdout.strip():
                return {}
            return None
    except (OSError, subprocess.SubprocessError):
        return None
    return by_task(parse(shown.stdout))


# --- the parked hold -------------------------------------------------------------

def hold_for(task: str, shift: str, inbox: dict | None) -> tuple[str, dict | None]:
    """How the inbox rules on one task an earlier shift `shift` left parked:
    ("held", None) — no entry (a park from before M3.5) or no readable inbox;
    ("waiting", {ids}) — an entry is Open or Deferred;
    ("dropped", {ids}) — an entry was dropped: the task is shelved (H9 a);
    ("answered", {ids, comments, answers}) — every entry is answered."""
    if inbox is None:
        return "held", None
    mine = [e for e in inbox.get(task, []) if e.get("shift") == shift]
    if not mine:
        return "held", None
    dropped = [e["id"] for e in mine if e["state"] == "dropped"]
    if dropped:
        return "dropped", {"ids": dropped}
    waiting = [e["id"] for e in mine if e["state"] in ("open", "deferred")]
    if waiting:
        return "waiting", {"ids": waiting}
    return "answered", {"ids": [e["id"] for e in mine], "shift": shift,
                        "comments": [e["comment"] for e in mine if e.get("comment")],
                        "answers": [e["answer"] for e in mine if e.get("answer")]}


# --- the sidecar and the op entry ------------------------------------------------

def sanitise(text, limit: int) -> str:
    """One line, at most `limit` characters, no `@` (a mention would notify),
    and no leading `#` or `-` (it must not read as a heading or a key)."""
    out = re.sub(r"\s+", " ", str(text or "")).strip().replace("@", "")
    if out[:1] in ("#", "-"):
        out = "\\" + out
    return out if len(out) <= limit else out[:limit - 1].rstrip() + "…"


def sidecar(lease_dir: Path, task: str, issue: str) -> tuple[str, list[str]]:
    """(ask, options) from the worker's `{task}.question.json`, when it names
    this issue (or no issue); else the no-sidecar ask and no options. The
    watcher never reads the issue itself."""
    try:
        raw = json.loads((Path(lease_dir) / f"{task}{SIDECAR_SUFFIX}").read_text(
            encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return NO_SIDECAR_ASK, []
    if not isinstance(raw, dict) or (raw.get("issue") and raw.get("issue") != issue):
        return NO_SIDECAR_ASK, []
    ask = sanitise(raw.get("ask"), ASK_MAX) or NO_SIDECAR_ASK
    opts = raw.get("options") if isinstance(raw.get("options"), list) else []
    return ask, [o for o in (sanitise(x, OPTION_MAX) for x in opts[:OPTIONS_MAX]) if o]


def add_op(entry: dict) -> dict:
    """The Mind writer op that lands one question (`question-add`)."""
    return {"op": "question-add", "path": FILE, "entry": entry}


def note_added(counters: dict, entry: dict) -> bool:
    """Record one question this shift added (`counters["inbox"]`), once per
    (task, issue). True when it is new."""
    seen = counters.setdefault("inbox", [])
    key = (Path(entry["task"]).stem, entry["issue"])
    if any((q.get("task"), q.get("issue")) == key for q in seen):
        return False
    seen.append({"task": key[0], "issue": entry["issue"], "kind": entry["kind"],
                 "asked": entry["asked"]})
    return True


# --- the digest line and the dashboard link --------------------------------------

def dashboard_link(mind) -> str:
    """The Mind dashboard's inbox anchor on Pages (`…/#inbox`), from the Mind's
    own `repos.yaml` — no org is written here (the tenant firewall). "" when
    it cannot be derived."""
    try:
        text = (Path(mind) / "repos.yaml").read_text(encoding="utf-8", errors="replace")
    except (OSError, TypeError):
        return ""
    m = re.search(r"^\s{2}PyAutoMind:[ \t]*\n(?:[ \t]{4,}.*\n)*?[ \t]{4,}github:"
                  r"[ \t]*([^\s#/]+)/([^\s#]+)", text, re.M)
    return f"https://{m.group(1).lower()}.github.io/{m.group(2)}/#inbox" if m else ""


def inbox_line(counters: dict, slot_name: str, mind=None, origin=None) -> str:
    """The digest's one inbox line (Decision H7 a), "" when the shift added
    none: `Inbox: 2 questions added to your inbox this shift (Q17, Q18), 5
    open in all — <link>`. Ids and the open count come from Mind origin/main
    (`origin`, else read here); a question still queued for the writer is
    counted without its id."""
    added = counters.get("inbox") or []
    if not added:
        return ""
    if origin is None and mind is not None:
        origin = read_origin(mind)
    ids, open_n = [], None
    if origin is not None:
        mine = [e for es in origin.values() for e in es if e.get("shift") == slot_name]
        ids = [e["id"] for e in sorted(mine, key=lambda e: int(e["id"][1:]))]
        open_n = sum(e["state"] == "open" for es in origin.values() for e in es)
    n = len(added)
    line = f"Inbox: {n} question{'s' if n != 1 else ''} added to your inbox this shift"
    if ids:
        line += f" ({', '.join(ids)}" + (f"; {n - len(ids)} still being filed" if n > len(ids)
                                          else "") + ")"
    if open_n is not None:
        line += f", {open_n} open in all"
    link = dashboard_link(mind) if mind is not None else ""
    return line + (f" — {link}" if link else "") + "."


# --- the one-off backfill (Build B, step 1) --------------------------------------

def _origin_path(mind, prompt: str, ref: str = "origin/main", run=None) -> str:
    """Where `prompt` is on Mind origin/main now: itself, else `active/<name>`,
    else "" (completed or retired)."""
    run = run or subprocess.run
    for cand in (prompt, f"active/{Path(prompt).name}"):
        try:
            res = run(["git", "-C", str(mind), "cat-file", "-e", f"{ref}:{cand}"],
                      capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return ""
        if res.returncode == 0:
            return cand
    return ""


def _done_at(slot: Path, task: str) -> str:
    """When the watcher reaped `task` as done (its tick's `at`), from tick.log."""
    try:
        lines = (slot / "tick.log").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in lines:
        try:
            t = json.loads(line)
        except ValueError:
            continue
        if any(isinstance(e, dict) and e.get("task") == task
               and e.get("event") in ("done", "parked") for e in t.get("reaped") or []):
            return (t.get("at") or "")[:16] + "Z" if t.get("at") else ""
    return ""


def _proof_ask(slot: Path, task: str, issue: str) -> str:
    """The proof packet's sentence that best states the question, for the
    lead's review of the backfill only (the watcher itself never guesses): one
    with a `?`, else one that asks for a choice (choose, decide, which,
    whether), else one that says it parked on the issue; the no-sidecar ask
    when none does. Issue links read "the issue"."""
    try:
        text = (slot / "proofs" / f"{task}.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return NO_SIDECAR_ASK
    body = " ".join(re.sub(r"^-\s+[a-z][a-z /-]*:\s*", "", ln.strip())
                    for ln in text.splitlines() if ln.strip() and not ln.startswith("#"))
    body = re.sub(re.escape(issue) + r"(?:#\S*)?", "the issue", body)
    sentences = re.split(r"(?<=[.!?])\s+", body)
    for test in (lambda x: "?" in x,
                 lambda x: re.search(r"\b(choose|decide|which|whether)\b", x, re.I),
                 lambda x: "the issue" in x and re.search(r"question|park", x, re.I)):
        hit = next((x for x in sentences if test(x)), None)
        if hit:
            return sanitise(hit, ASK_MAX)
    return NO_SIDECAR_ASK


def _record_issue(mind, slot_name: str) -> str:
    try:
        text = (Path(mind) / "batches" / f"{slot_name}.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r"^- issue:[ \t]*(https://\S+)", text, re.M)
    return m.group(1) if m else ""


def backfill(home: Path, mind, origin: dict | None = None) -> list[str]:
    """`questions_edit.py add` lines for every task an earlier shift left
    parked and still held today (the watcher's own `parked_elsewhere`, as if a
    new shift were planning), one per question it parked on, oldest shift
    first. Prints only — the lead reviews, then runs them. A task whose prompt
    is no longer in `draft/` or `active/` on Mind origin/main, or whose
    question is already in the inbox, is a `#` comment line instead."""
    import shlex
    import _orchestrator as orch  # noqa: E402 — deferred: it imports this module
    home = Path(home)
    held = orch.parked_elsewhere(home / ".backfill-probe")
    origin = read_origin(mind) if origin is None else origin
    slots = sorted(d for d in home.iterdir() if d.is_dir()
                   and (d / orch.COUNTERS_FILE).is_file()) if home.is_dir() else []
    rows = []
    for task in held:
        # The last slot that parked it is the one whose hold stands.
        for d in reversed(slots):
            c = orch._safe_counters(d) or {}
            o = (c.get("outcomes") or {}).get(task)
            if (isinstance(o, dict) and o.get("questions")) or task in (c.get("parked") or []):
                break
        else:
            continue
        o = (c.get("outcomes") or {}).get(task) or {}
        prompt = ((c.get("picks") or {}).get(task) or {}).get("prompt") or ""
        worker = next((w.get("key") for w in reversed(c.get("workers") or [])
                       if w.get("task") == task), "") or "unknown"
        if o.get("questions"):
            asks = [(url, "question", _proof_ask(d, task, url)) for url in o["questions"]]
        else:
            asks = [(_record_issue(mind, d.name), "blocked",
                     f"the worker stopped at a prompt nobody answered (session {worker})")]
        rows.append((d.name, task, prompt, worker, _done_at(d, task) or d.name, asks))
    out = [f"# questions backfill: {len(rows)} held task(s) in {home} — review, then run "
           "each line from a temporary Mind worktree on origin/main"]
    for shift, task, prompt, worker, asked, asks in sorted(rows):
        now = _origin_path(mind, prompt) if prompt else ""
        if not now:
            out.append(f"# skipped: {task} (shift {shift}) — its prompt {prompt or '?'} is "
                       "no longer in draft/ or active/ on Mind origin/main; nothing to resume")
            continue
        for issue, kind, ask in asks:
            if not issue:
                out.append(f"# skipped: {task} (shift {shift}) — no issue to file it on")
                continue
            have = [e["id"] for e in (origin or {}).get(task, []) if e.get("shift") == shift
                    and e.get("issue") == issue]
            if have:
                out.append(f"# skipped: {task} (shift {shift}) — already in the inbox as "
                           + ", ".join(have))
                continue
            out.append(" ".join(["python3 scripts/questions_edit.py add",
                                 "--task", shlex.quote(now), "--issue", shlex.quote(issue),
                                 "--kind", kind, "--ask", shlex.quote(ask),
                                 "--shift", shlex.quote(shift), "--asked", shlex.quote(asked),
                                 "--worker", shlex.quote(worker)]))
    return out
