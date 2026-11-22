"""The questions inbox, Brain side — readers only.

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
            "gate": f.get("gate", ""),
            "answered": (f.get("answered") or "").split(" ")[0],
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

#: The inbox kind the readiness pass files: a gate on a queued task for the
#: human to rule on. It is answered like a question but never holds or
#: releases a parked task, and the inbox line leaves it out.
RULING = "ruling"


def is_ruling(e: dict) -> bool:
    return (e.get("kind") or "") == RULING


def questions_only(entries) -> list[dict]:
    """The entries that are questions (or blocked), not rulings."""
    return [e for e in entries or [] if not is_ruling(e)]


def hold_for(task: str, shift: str, inbox: dict | None) -> tuple[str, dict | None]:
    """How the inbox rules on one task an earlier shift `shift` left parked:
    ("held", None) — no entry or no readable inbox;
    ("waiting", {ids}) — an entry is Open or Deferred;
    ("dropped", {ids}) — an entry was dropped: the task is shelved;
    ("answered", {ids, comments, answers}) — every entry is answered."""
    if inbox is None:
        return "held", None
    mine = [e for e in questions_only(inbox.get(task)) if e.get("shift") == shift]
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


def answered_since(task: str, inbox: dict | None, at: str) -> dict | None:
    """A fresh release for a task whose earlier release a shift used up at
    `at` (an ISO time): the entries answered after `at`, when none of the
    task's entries is still open, deferred or dropped; else None."""
    if inbox is None:
        return None
    mine = questions_only(inbox.get(task))
    if any(e["state"] != "answered" for e in mine):
        return None
    fresh = [e for e in mine if (e.get("answered") or "") > (at or "")]
    if not fresh:
        return None
    return {"ids": [e["id"] for e in fresh], "shift": fresh[-1].get("shift", ""),
            "comments": [e["comment"] for e in fresh if e.get("comment")],
            "answers": [e["answer"] for e in fresh if e.get("answer")]}


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
    (task, issue). A ruling goes in `counters["rulings"]["new"]` instead, once
    per (task, gate): the two are never counted together. True when it is new."""
    if is_ruling(entry):
        new = counters.setdefault("rulings", {}).setdefault("new", [])
        key = (Path(entry["task"]).stem, entry.get("gate", ""))
        if any((r.get("task"), r.get("gate")) == key for r in new):
            return False
        new.append({"task": key[0], "path": entry["task"], "gate": key[1]})
        return True
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


def unfiled_lines(counters: dict) -> list[str]:
    """One digest line per question the watcher could not file (no prompt, no
    shift issue, an issue that is not a URL): never a silent drop."""
    return [f"Inbox: not filed — `{u.get('task')}` ({u.get('kind')}): {u.get('why')}; "
            "see the task's issue or session yourself."
            for u in counters.get("inbox_unfiled") or []]


def inbox_line(counters: dict, slot_name: str, mind=None, origin=None) -> str:
    """The digest's one inbox line, "" when the shift added none: `Inbox: 2
    questions added to your inbox this shift (Q17, Q18), 5 open in all —
    <link>`. Ids and the open count come from Mind origin/main (`origin`,
    else read here); a question still queued for the writer is counted
    without its id."""
    added = counters.get("inbox") or []
    if not added:
        return ""
    if origin is None and mind is not None:
        origin = read_origin(mind)
    ids, open_n = [], None
    if origin is not None:
        # Rulings (the readiness pass's) are not questions: the digest's last
        # line counts them.
        mine = [e for es in origin.values() for e in questions_only(es)
                if e.get("shift") == slot_name]
        ids = [e["id"] for e in sorted(mine, key=lambda e: int(e["id"][1:]))]
        open_n = sum(e["state"] == "open" for es in origin.values()
                     for e in questions_only(es))
    n = len(added)
    line = f"Inbox: {n} question{'s' if n != 1 else ''} added to your inbox this shift"
    if ids:
        line += f" ({', '.join(ids)}" + (f"; {n - len(ids)} still being filed" if n > len(ids)
                                          else "") + ")"
    if open_n is not None:
        line += f", {open_n} open in all"
    link = dashboard_link(mind) if mind is not None else ""
    return line + (f" — {link}" if link else "") + "."
