"""One Mind writer per shift (AUTONOMY.md, 2026-11-03) — the orchestrator's side.

Workers never commit to PyAutoMind. They describe each change as an *op file*
in the shift's `ledger/` directory (`bin/shift_ledger.py` writes them); the
orchestrator applies every pending op in a **temporary detached worktree** on
`origin/main`, commits once, and pushes. A rejected push means someone else
moved `main` (another session, the dashboard self-heal bot): the ops are
replayed on the new `origin/main` — a rebase of operations, not of diffs — at
most `PUSH_TRIES` times. The canonical checkout's working tree is never read
or written, nothing is reset, and nothing is forced.

Ops (one JSON object per file, applied in file-name order):

    {"op": "append",       "path": "active.md", "text": "..."}
    {"op": "write",        "path": "complete/2026/11/x.md", "text": "..."}   # must not exist
    {"op": "edit",         "path": "draft/a/b/x.md", "old": "...", "new": "..."}   # must exist
    {"op": "move",         "path": "draft/a/b/x.md", "to": "active/x.md"}
    {"op": "remove",       "path": "active/x.md"}
    {"op": "drop-section", "path": "active.md", "section": "task-name"}
    {"op": "table-append", "path": "autonomy_log.md", "heading": "## Unattended …", "row": "| … |"}
    {"op": "set-header",   "path": "draft/a/b/x.md", "key": "Verified", "value": "2026-11-12 abc123 (Repo)"}
    {"op": "jsonl-upsert", "path": "batches/pilot/pilot.jsonl", "key": "slot", "row": {...}}
    {"op": "table-upsert", "path": "batches/pilot/pilot.md", "key": "<slot>", "row": "| … |", "header": "…"}
    {"op": "record-key",   "path": "batches/<slot>.md", "key": "live", "value": "…"}
    {"op": "queue-retire", "path": "queue.md", "prompt": "x.md", "shipped_as": "<PR> → complete/…"}
    {"op": "question-add", "path": "questions.md", "entry": {"task": …, "issue": …, "kind": …,
                                                             "ask": …, "options": [...], "shift": …,
                                                             "asked": …, "worker": …}}
                    (kind `ruling`, from the readiness pass: `gate` required, `issue` optional)
    {"op": "question-retire", "path": "questions.md", "prompt": "x.md", "day": "YYYY-MM-DD", "by": "…"}

`queue-retire` moves every live `queue.md` entry whose `ref:` names the
prompt file `prompt` to the `## Retired` footer with `shipped-as:`, using
PyAutoMind's own `lifecycle.py` `queue_retire_text`, the function
`lifecycle.py close` runs. It is loaded from the tree being written, so
the rule is Mind's, never a copy. An unattended close-out queues it with
its complete record, and the watcher queues it again when it reaps the
merge (PyAutoBrain#634: after the first unattended merge its entry
stayed live, and `lifecycle.py check` then failed on the dangling ref). No
live entry naming the prompt is the usual case, and it is silent.

`question-add` lands one parked worker's question in the human's inbox
(M3.5, PyAutoBrain#645) through PyAutoMind's own `scripts/questions_edit.py`
`add_text`, loaded from the tree being written as `queue-retire` loads
`lifecycle.py` — so the id (the file's highest plus 1, worked out in that
tree) is right on a replay over a moved main, and an entry whose `(shift,
task, issue)` is already there is a skipped note. A question whose prompt is
in neither `draft/` nor `active/` any more is set aside, with its reason;
any other failure (a Mind main without the script) holds it pending.
`question-retire` answers the merged task's Open and Deferred questions
(`lifecycle.questions_close_text`, what `lifecycle.py close` runs), queued
beside every `queue-retire`: an unattended close-out never runs `close`.

`jsonl-upsert` keeps one JSON line per `row[key]`: the line with that key is
replaced (its other fields kept), else the row is appended. `table-upsert`
does the same for a Markdown table row keyed by its first cell, keeping any
old cell where the new one is `?` (the human's cells), and writes `header`
first into a missing file. Both are how the shift watcher writes its one pilot
row per shift and amends it on a late arrival (PyAutoBrain#610).

`record-key` sets one top-level `- key: value` line of a batch record — the
key's own line replaced, else inserted after `- issue:` (else `- review-at:`).
The watcher writes the dashboard's `- live:` status line this way
(PyAutoBrain#622); a record no longer on main is skipped, like `set-header`.

`write` only creates; `edit` changes a file that exists, replacing `old`,
which must appear in it exactly once, with `new` — an expected-base check, so
an edit never clobbers a concurrent change (M3.6d, PyAutoBrain#660: shift
2026-11-16-pm's `write` edits to existing drafts were set aside).

A worker's ops carry their `task` (`shift_ledger.py --task`). A task's
*closing* ops (`_closing`: its `complete/` record, `drop-section`, the
`active/` prompt's `remove`, `queue-retire`, `question-retire`, and any op on
a path one of them creates) apply after every other op, one group per task,
and are *withheld* — set aside with the task, never retried — when any
sibling op of that task was set aside for a human, this run or earlier in
the shift (a group that fails part-way is rolled back first); while a sibling
is *held* the group stays pending beside it. Mind never records a task
shipped while one of its changes is missing. An op that fails only because it is already true on main
(`MechanicalError`: an edit already applied, a write of the text the file
has, a remove of a file that is gone) is set aside as `needs: mechanical` —
a digest line, not a "needs you". `shift_ledger.py` refuses at queue time
what would fail (`queue_refusals`), so the worker can still switch.

`set-header` sets one `Key: value` line in a prompt's header block (replacing
the key's line if present) — how a shift worker records the premise check's
`Verified:` stamp (`batch premise --record`) without touching the file itself.

Every path must be *ledger* by PyAutoMind's own rule (`scripts/ledger_merge.py`
`is_ledger_path`, default deny), so a worker cannot route code through here.

One bad op never strands the rest (PyAutoBrain#632, B1 — a re-dispatched
worker re-queued its claim's `draft→active` move and every later op of the
shift stayed pending):

- a *repeat* is a skipped note — only a re-dispatched task's own claim (the
  caller names those tasks, `own_tasks`) whose earlier op this shift already
  committed (`ledger/committed/`) and whose content on main matches it: a
  `move` whose source is gone and destination present, a `## slug` section an
  `active.md` append already finds there;
- the same shape from anyone else is a *conflict*, set aside loudly;
- any other worker op that fails validation or cannot apply is *set aside* —
  moved to `ledger/set_aside/` with its reason — and the rest still commit;
- a *critical* op (`CRITICAL_OPS`: the digest and late lines on a batch
  record, the pilot row, the live line, a stage-2 row) is never set aside: it
  is *held* pending and retried on every tick.

Every note, set-aside, conflict and first hold is appended to
`ledger/report.jsonl`, which the digest and the late sweep read: none of them
lives only in `tick.log`. Only a push rejected `PUSH_TRIES` times leaves every
op pending.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

OPS = ("append", "write", "edit", "move", "remove", "drop-section", "table-append",
       "set-header", "jsonl-upsert", "table-upsert", "record-key", "queue-retire",
       "question-add", "question-retire")
#: A worker's task name, as `shift_ledger.py --task` tags its ops.
TASK_RE = re.compile(r"[A-Za-z0-9][\w.-]*")
#: The `needs` of a set-aside op: already true on main, or the human's call.
NEEDS_MECHANICAL, NEEDS_HUMAN = "mechanical", "human"
#: The keys a `question-add` entry carries; all strings but `options`.
QUESTION_KEYS = ("task", "issue", "kind", "ask", "options", "shift", "asked", "worker",
                 "gate")
#: A `ruling` (the readiness pass's, M3.3, PyAutoBrain#671) needs `gate` and
#: may have no `issue`; every other kind needs `issue` and has no `gate`.
QUESTION_RULING = "ruling"
#: What a watcher-run queue retirement says in the footer, in place of the
#: `lifecycle.py close` it did not run.
QUEUE_RETIRED_BY = "retired by the shift close-out (queue-retire)"
PUSH_TRIES = 3
LEDGER_DIR = "ledger"
COMMITTED_DIR = "committed"
#: Ops that could not apply (or were invalid), kept for the human with their
#: reason (`<op file>.why`) — never retried, never blocking the others.
SET_ASIDE_DIR = "set_aside"
#: What the writer did besides commit, one JSON line each (#632 review).
REPORT_FILE = "report.jsonl"
#: Op kinds only the watcher writes, and an `append` to a batch record: the
#: shift's own record (digest, late lines), pilot row, live line and stage-2
#: rows. Never set aside — held pending and retried (#632 review).
CRITICAL_KINDS = ("record-key", "jsonl-upsert", "table-upsert", "table-append",
                  # The questions inbox (#645): a question or its retirement
                  # is never lost to a passing fault (a Mind main without
                  # questions_edit.py yet) — held and retried; only a task
                  # whose prompt is gone sets a question aside (`GoneError`).
                  "question-add", "question-retire")


def is_critical(op) -> bool:
    """A watcher op (never set aside, held pending). A worker's own
    `table-append` (its calibration row, tagged with its `task`) is not: a
    bad one is set aside and told, never retried every tick (#660)."""
    if not isinstance(op, dict):
        return False
    if op.get("op") == "table-append" and op.get("task"):
        return False
    return (op.get("op") in CRITICAL_KINDS
            or (op.get("op") == "append" and str(op.get("path", "")).startswith("batches/")))


def _closing(op) -> bool:
    """A tagged op that records its task done: the `complete/` record, the
    `## slug` drop, the `active/` prompt's removal, the queue and questions
    retirements. Applied last, and withheld when a sibling was set aside."""
    if not isinstance(op, dict) or not op.get("task"):
        return False
    kind, path = op.get("op"), str(op.get("path", ""))
    return ((kind == "write" and path.startswith("complete/"))
            or (kind == "remove" and path.startswith("active/"))
            or kind in ("drop-section", "queue-retire", "question-retire"))


class ConflictError(RuntimeError):
    """A claim that looks already done, but not by this shift's own task."""


class MindWriteError(RuntimeError):
    pass


class MechanicalError(MindWriteError):
    """The op is already true on main (an edit already applied, a write of the
    text the file already has, a remove of a file that is gone): set aside
    with `needs: mechanical` — a digest line, nothing for the human."""


class GoneError(MindWriteError):
    """The op's subject is gone from Mind main (a question whose prompt was
    completed or retired): set aside even when the op is critical."""


def fetch(mind_repo: Path, remote: str = "origin", branch: str = "main") -> None:
    """The writer's one network read: `git fetch` of Mind `main` (refs and
    objects only — the working tree is never touched). The watcher also calls
    it once per shift before its first plan (#632, F4)."""
    _git(Path(mind_repo), "fetch", "-q", remote, branch)


def _ledger_merge(mind_repo: Path):
    """PyAutoMind's own `ledger_merge` module, from the checkout we write to.

    Compiled from source rather than imported: an import writes
    `scripts/__pycache__/` into the canonical checkout, and this module's
    promise is that the canonical working tree is never written."""
    path = Path(mind_repo) / "scripts" / "ledger_merge.py"
    if not path.is_file():
        raise MindWriteError(f"no scripts/ledger_merge.py under {mind_repo}")
    name = "_mind_ledger_merge"
    mod = types.ModuleType(name)
    mod.__file__ = str(path)
    sys.modules[name] = mod  # dataclasses and friends look the module up by name
    try:
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), mod.__dict__)
    finally:
        sys.modules.pop(name, None)
    return mod


def validate_op(op: dict, lm) -> list[str]:
    """Problems with one op; empty when it may be applied."""
    errs = []
    kind = op.get("op")
    if kind not in OPS:
        return [f"op: {kind!r} is not one of {', '.join(OPS)}"]
    paths = [op.get("path")] + ([op.get("to")] if kind == "move" else [])
    for p in paths:
        if not isinstance(p, str) or not p:
            errs.append(f"{kind}: a path is missing")
        elif p.startswith("/") or not lm.is_ledger_path(p):
            errs.append(f"{kind}: {p} is not a ledger path (scripts/ledger_merge.py)")
    if "task" in op and (not isinstance(op["task"], str)
                         or not TASK_RE.fullmatch(op["task"])):
        errs.append(f"{kind}: task must be one task name ([A-Za-z0-9][\\w.-]*)")
    if kind == "edit":
        old, new = op.get("old"), op.get("new")
        if not isinstance(old, str) or not old:
            errs.append("edit: old (the expected base text) is missing")
        if not isinstance(new, str):
            errs.append("edit: new is missing")
        elif new == old:
            errs.append("edit: new is the same as old — nothing to change")
    if kind in ("append", "write") and not isinstance(op.get("text"), str):
        errs.append(f"{kind}: text is missing")
    elif kind == "append" and op.get("path") == "active.md":
        errs += pr_key_errors(op["text"])
    if kind == "drop-section":
        if not op.get("section"):
            errs.append("drop-section: section is missing")
        elif op.get("path") not in lm.ENTRY_MERGED_FILES:
            errs.append(f"drop-section: {op.get('path')} is not a `## slug` registry")
    if kind == "table-append":
        if not str(op.get("heading", "")).startswith("## "):
            errs.append("table-append: heading must be a `## ` line")
        row = op.get("row")
        if not isinstance(row, str) or not row.startswith("|") or "\n" in row:
            errs.append("table-append: row must be one `| … |` line")
        if "unique" in op and (not isinstance(op["unique"], str) or not op["unique"]
                               or "\n" in op["unique"]):
            errs.append("table-append: unique must be one non-empty line")
    if kind == "jsonl-upsert":
        row, key = op.get("row"), op.get("key")
        if not str(op.get("path", "")).endswith(".jsonl"):
            errs.append("jsonl-upsert: path must be a .jsonl file")
        if not isinstance(key, str) or not isinstance(row, dict) \
                or not isinstance(row.get(key), str) or not row.get(key):
            errs.append("jsonl-upsert: row must be an object carrying its key")
    if kind == "table-upsert":
        row = op.get("row")
        if not str(op.get("path", "")).endswith(".md"):
            errs.append("table-upsert: path must be a .md file")
        if not isinstance(row, str) or not row.startswith("|") or "\n" in row:
            errs.append("table-upsert: row must be one `| … |` line")
        elif _cells(row)[0] != op.get("key"):
            errs.append("table-upsert: the row's first cell must be its key")
    if kind == "record-key":
        key, value, path = op.get("key"), op.get("value"), str(op.get("path", ""))
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", key):
            errs.append("record-key: key must be one lower-case record key")
        if not isinstance(value, str) or not value.strip() or "\n" in value:
            errs.append("record-key: value must be one non-empty line")
        if not (path.startswith("batches/") and path.endswith(".md")):
            errs.append("record-key: path must be a batch record (batches/*.md)")
    if kind == "queue-retire":
        prompt, shipped = op.get("prompt"), op.get("shipped_as")
        if op.get("path") != "queue.md":
            errs.append("queue-retire: path must be queue.md")
        if not isinstance(prompt, str) or not re.fullmatch(r"[^/\s]+\.md", prompt):
            errs.append("queue-retire: prompt must be a bare prompt file name (x.md)")
        if not isinstance(shipped, str) or not shipped.strip() or "\n" in shipped:
            errs.append("queue-retire: shipped_as must be one non-empty line")
    if kind == "question-add":
        entry = op.get("entry")
        if op.get("path") != "questions.md":
            errs.append("question-add: path must be questions.md")
        if not isinstance(entry, dict):
            errs.append("question-add: entry must be an object")
        else:
            extra = sorted(set(entry) - set(QUESTION_KEYS))
            if extra:
                errs.append(f"question-add: unknown entry keys {', '.join(extra)}")
            ruling = entry.get("kind") == QUESTION_RULING
            for k in QUESTION_KEYS:
                v = entry.get(k)
                if (k == "issue" and ruling and v is None) or (k == "gate" and not ruling
                                                               and v is None):
                    continue
                if k == "gate" and not ruling:
                    errs.append("question-add: gate is for kind ruling only")
                    continue
                if k == "options":
                    if not isinstance(v, list) or not all(isinstance(o, str) for o in v):
                        errs.append("question-add: options must be a list of strings")
                elif not isinstance(v, str) or not v.strip() or "\n" in v:
                    errs.append(f"question-add: {k} must be one non-empty line")
    if kind == "question-retire":
        if op.get("path") != "questions.md":
            errs.append("question-retire: path must be questions.md")
        if not isinstance(op.get("prompt"), str) or not re.fullmatch(r"[^/\s]+\.md",
                                                                     op["prompt"]):
            errs.append("question-retire: prompt must be a bare prompt file name (x.md)")
        if not isinstance(op.get("day"), str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",
                                                                  op["day"]):
            errs.append("question-retire: day must be YYYY-MM-DD")
        if not isinstance(op.get("by"), str) or not op["by"].strip() or "\n" in op["by"]:
            errs.append("question-retire: by must be one non-empty line")
    if kind == "set-header":
        key, value = op.get("key"), op.get("value")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Z][A-Za-z-]*", key):
            errs.append("set-header: key must be one capitalised header word")
        if not isinstance(value, str) or not value.strip() or "\n" in value:
            errs.append("set-header: value must be one non-empty line")
        if not str(op.get("path", "")).endswith(".md"):
            errs.append("set-header: path must be a prompt (.md)")
    return errs


#: The PR keys of an `active.md` row (PyAutoMind REFERENCE.md "The PR keys"),
#: and the keys a worker wrote in their place (PyAutoBrain#637, item 9: a bare
#: `pr:` made `lifecycle.py check` drift and left /prm nothing to merge).
PR_KEYS = ("library-pr", "workspace-pr")
_LOOSE_PR_KEY_RE = re.compile(r"^-\s+((?:[a-z]+[-_])?prs?|pull-request|pr-url)\s*:", re.I | re.M)


def pr_key_errors(text: str) -> list[str]:
    """A refusal for every PR line in an `active.md` row whose key is not one
    of `PR_KEYS` — `shift_ledger.py` refuses the op when it is queued, so
    the worker fixes it, and the writer sets it aside if one slips through."""
    bad = sorted({m.group(1) for m in _LOOSE_PR_KEY_RE.finditer(text or "")
                  if m.group(1).lower() not in PR_KEYS})
    return [f"append: active.md key `{k}:` — a PR line uses `library-pr:` or "
            "`workspace-pr:` (PyAutoMind REFERENCE.md \"The PR keys\"), one per PR"
            for k in bad]


def apply_op(tree: Path, op: dict, lm, ctx: dict | None = None) -> str | None:
    """Apply one validated op inside `tree`; raises MindWriteError if it cannot,
    ConflictError for a claim that is already on main but not this shift's own.

    Returns a note when the op was deliberately skipped: a `set-header` or
    `record-key` on a file no longer on main (a stamp must not hold the shift),
    a `table-append` whose `unique` key a row already carries, and a
    re-dispatched task's own repeat of a claim this shift already committed
    (`ctx`: {"own": task names, "prior": this shift's committed ops}, #632)."""
    target = tree / op["path"]
    kind = op["op"]
    ctx = ctx or {"own": set(), "prior": []}
    if kind == "append":
        target.parent.mkdir(parents=True, exist_ok=True)
        old = target.read_text(encoding="utf-8") if target.exists() else ""
        text, note = op["text"], None
        if op["path"] in getattr(lm, "ENTRY_MERGED_FILES", ()) and old:
            text, note = _new_sections(old, text, op["path"], lm, ctx)
            if not text:
                return note
        sep = "" if not old or old.endswith("\n") else "\n"
        target.write_text(old + sep + text, encoding="utf-8")
        return note
    elif kind == "write":
        if target.exists():
            if target.read_text(encoding="utf-8") == op["text"]:
                raise MechanicalError(f"write: {op['path']} already has this text on main")
            raise MindWriteError(f"write: {op['path']} already exists — `write` only "
                                 "creates; `edit` changes an existing file")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(op["text"], encoding="utf-8")
    elif kind == "edit":
        if not target.exists():
            raise MindWriteError(f"edit: {op['path']} does not exist on main")
        text = target.read_text(encoding="utf-8")
        target.write_text(edit_text(text, op["path"], op["old"], op["new"]),
                          encoding="utf-8")
    elif kind == "move":
        dest = tree / op["to"]
        if not target.exists() and dest.exists():
            # A re-dispatched worker re-queues its predecessor's claim (#632):
            # a repeat only when this shift itself committed that very move.
            task = Path(op["path"]).stem
            if task in ctx["own"] and any(
                    p.get("op") == "move" and p.get("path") == op["path"]
                    and p.get("to") == op["to"] for p in ctx["prior"]):
                return (f"move: {op['path']} → {op['to']} is already on main from this "
                        f"shift's own claim (re-dispatch of {task}) — skipped")
            raise ConflictError(f"move: {op['path']} is gone and {op['to']} exists on "
                                f"main, not from this shift's own claim of {task} — conflict")
        if not target.exists():
            raise MindWriteError(f"move: {op['path']} does not exist")
        if dest.exists():
            raise MindWriteError(f"move: {op['to']} already exists")
        dest.parent.mkdir(parents=True, exist_ok=True)
        _git(tree, "mv", op["path"], op["to"])
    elif kind == "remove":
        if not target.exists():
            raise MechanicalError(f"remove: {op['path']} does not exist (already gone)")
        _git(tree, "rm", "-q", op["path"])
    elif kind == "drop-section":
        preamble, entries = lm.split_entries(target.read_text(encoding="utf-8"))
        kept = [(s, b) for s, b in entries if s != f"## {op['section']}"]
        if len(kept) == len(entries):
            raise MindWriteError(f"drop-section: no `## {op['section']}` in {op['path']}")
        target.write_text(lm.join_entries(preamble, kept), encoding="utf-8")
    elif kind == "set-header":
        if not target.exists():
            return (f"set-header: {op['path']} is not on main (moved or retired "
                    f"since the check) — {op['key']}: skipped")
        target.write_text(set_header(target.read_text(encoding="utf-8"),
                                     op["key"], op["value"]), encoding="utf-8")
    elif kind == "record-key":
        if not target.exists():
            return f"record-key: {op['path']} is not on main — {op['key']}: skipped"
        target.write_text(record_key(target.read_text(encoding="utf-8"),
                                     op["key"], op["value"]), encoding="utf-8")
    elif kind == "table-append":
        text = target.read_text(encoding="utf-8") if target.exists() else ""
        if op.get("unique") and _section_has(text, op["heading"], op["unique"]):
            # A row re-queued after a crash between queue and counters (#632).
            return f"table-append: a row with {op['unique']!r} is already there — skipped"
        target.write_text(table_append(text, op["heading"], op["row"]), encoding="utf-8")
    elif kind == "queue-retire":
        if not target.exists():
            return None   # no queue on this Mind: nothing can dangle
        text = target.read_text(encoding="utf-8")
        try:
            new, moved = _mind_module(tree, "lifecycle").queue_retire_text(
                text, op["prompt"], op["shipped_as"])
        except MindWriteError:
            raise
        except Exception as exc:  # Mind main's lifecycle.py is not ours: any
            # failure in it (syntax, rename, its own bug) must stay this one
            # op's failure, never a tick crash that strands every other op.
            raise MindWriteError(f"queue-retire: lifecycle.queue_retire_text "
                                 f"failed: {type(exc).__name__}: {exc}") from exc
        if moved:
            target.write_text(_retired_by(new, len(moved)), encoding="utf-8")
    elif kind == "question-add":
        text = target.read_text(encoding="utf-8") if target.exists() else ""
        qe = _mind_module(tree, "questions_edit", deps=("lifecycle",))
        try:
            gone = qe.task_now(tree, op["entry"]["task"]) is None
        except Exception as exc:  # see queue-retire: Mind's script, not ours
            raise MindWriteError(f"question-add: questions_edit.task_now failed: "
                                 f"{type(exc).__name__}: {exc}") from exc
        if gone:
            raise GoneError(f"question-add: task {op['entry']['task']} is in neither draft/ "
                            "nor active/ on Mind main — set aside, nothing to resume")
        try:
            new, qid, added = qe.add_text(text, op["entry"], tree)
        except MindWriteError:
            raise
        except Exception as exc:  # Mind main's script is not ours (see queue-retire)
            raise MindWriteError(f"question-add: questions_edit.add_text refused: "
                                 f"{type(exc).__name__}: {exc}") from exc
        if not added:
            return f"question-add: already in questions.md as {qid} — skipped"
        target.write_text(new, encoding="utf-8")
    elif kind == "question-retire":
        if not target.exists():
            return None   # no inbox on this Mind: nothing can dangle
        try:
            new, ids = _mind_module(tree, "lifecycle").questions_close_text(
                target.read_text(encoding="utf-8"), op["prompt"], op["day"], by=op["by"])
        except Exception as exc:  # see queue-retire
            raise MindWriteError(f"question-retire: lifecycle.questions_close_text failed: "
                                 f"{type(exc).__name__}: {exc}") from exc
        if ids:
            target.write_text(new, encoding="utf-8")
    elif kind == "jsonl-upsert":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(jsonl_upsert(target.read_text(encoding="utf-8")
                                       if target.exists() else "",
                                       op["key"], op["row"]), encoding="utf-8")
    elif kind == "table-upsert":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(table_upsert(target.read_text(encoding="utf-8")
                                       if target.exists() else "",
                                       op["key"], op["row"], op.get("header", "")),
                          encoding="utf-8")


def edit_text(text: str, path: str, old: str, new: str) -> str:
    """`text` with its one `old` replaced by `new`. `MechanicalError` when the
    edit is already there (a non-empty `new` present and every `old` inside
    it);
    `MindWriteError` when `old` is not there exactly once (the base moved)."""
    n, done = text.count(old), (text.count(new) if new else 0)
    if done and n == done * new.count(old):
        raise MechanicalError(f"edit: {path} already has the new text on main")
    if n != 1:
        raise MindWriteError(f"edit: expected base not found in {path}" if not n else
                             f"edit: expected base ambiguous in {path} ({n} matches)")
    return text.replace(old, new, 1)


def _main_text(mind: Path, path: str, ref: str = "origin/main") -> str | None:
    """`path` as Mind's `origin/main` has it (no fetch: the writer fetches
    each tick); None when it is not there. Raises MindWriteError when git
    cannot read the ref at all."""
    if _git(Path(mind), "rev-parse", "--verify", "-q", ref, check=False).returncode:
        raise MindWriteError(f"no {ref} in {mind}")
    res = _git(Path(mind), "show", f"{ref}:{path}", check=False)
    return res.stdout if res.returncode == 0 else None


def _ledger_ops(ledger_dir: Path) -> list[dict]:
    """This shift's pending ops, in order. Committed ops are already on
    origin/main (the writer fetches each tick, and its push moves the
    tracking ref): replaying them would undo a later change by someone else."""
    return [op for f in sorted(Path(ledger_dir).glob("*.json")) if (op := _op_of(f))]


def _expected(mind: Path, path: str, ops: list[dict]) -> str | None:
    """`path` once this shift's queued ops apply over origin/main: what a new
    op on it will meet (a `draft/ → active/` move, then an edit of it)."""
    state: dict = {}

    def get(p):
        if p not in state:
            state[p] = _main_text(mind, p)
        return state[p]

    for o in ops:
        kind, p = o.get("op"), o.get("path")
        if not isinstance(p, str):
            continue
        if kind == "write" and isinstance(o.get("text"), str):
            state[p] = o["text"]
        elif kind == "remove":
            state[p] = None
        elif kind == "move" and isinstance(o.get("to"), str) and get(p) is not None:
            state[o["to"]], state[p] = get(p), None
        elif kind == "edit" and get(p) is not None:
            try:
                state[p] = edit_text(get(p), p, o.get("old") or "", o.get("new") or "")
            except MindWriteError:
                pass   # already applied, or will be set aside: main's text stands
    return get(path)


def queue_refusals(mind: Path, op: dict, ledger_dir: Path) -> list[str]:
    """Why `shift_ledger.py` refuses to queue `op`, checked against Mind
    `origin/main` and this shift's queued ops — so the worker, still running,
    can switch (#660). Empty when it may be queued, and when git cannot be
    read: then apply time is the backstop."""
    kind, path = op.get("op"), op.get("path")
    if kind not in ("write", "edit", "table-append") or not isinstance(path, str):
        return []
    try:
        text = _expected(Path(mind), path, _ledger_ops(ledger_dir))
    except MindWriteError:
        return []
    if kind == "write" and text is not None:
        if text == op.get("text"):
            return []   # already true: set aside as mechanical, a note
        return [f"write: {path} already exists on Mind origin/main (or a queued op "
                "creates it) — use `edit` to change it (`write` only creates)"]
    if kind == "edit":
        if text is None:
            return [f"edit: {path} is not on Mind origin/main — use `write` to create it"]
        try:
            edit_text(text, path, op.get("old") or "", op.get("new") or "")
        except MechanicalError as e:
            return [f"{e} — nothing to queue"]
        except MindWriteError as e:
            return [f"{e} — `old` must appear exactly once in {path} as it is on "
                    "Mind origin/main"]
    if kind == "table-append":
        if text is None:
            return [f"table-append: {path} is not on Mind origin/main"]
        try:
            table_append(text, str(op.get("heading", "")), str(op.get("row", "")))
        except MindWriteError as e:
            return [f"{e} in {path} on Mind origin/main"]
    return []


def _mind_module(tree: Path, name: str, deps: tuple = ()):
    """A PyAutoMind `scripts/<name>.py`, compiled from `tree` (the temporary
    worktree on origin/main) as `_ledger_merge` compiles its own: no import,
    so no `__pycache__` is written anywhere.

    `deps` are the sibling scripts it imports (`questions_edit` imports
    `lifecycle`): each is compiled from the same tree and served under its own
    name while the module runs, then removed — as is any `sys.path` entry the
    module adds — so nothing from one tree outlives the op."""
    path = Path(tree) / "scripts" / f"{name}.py"
    if not path.is_file():
        raise MindWriteError(f"no scripts/{name}.py on Mind main")
    saved_path = list(sys.path)
    saved = {d: sys.modules.get(d) for d in deps}
    for d in deps:
        sys.modules[d] = _mind_module(tree, d)
    mod_name = f"_mind_{name}"
    mod = types.ModuleType(mod_name)
    mod.__file__ = str(path)
    sys.modules[mod_name] = mod
    try:
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), mod.__dict__)
    finally:
        sys.modules.pop(mod_name, None)
        sys.path[:] = saved_path
        for d, m in saved.items():
            if m is None:
                sys.modules.pop(d, None)
            else:
                sys.modules[d] = m
    return mod


def _retired_by(text: str, n: int) -> str:
    """`queue_retire_text` notes its entries as retired by `lifecycle.py
    close`; the `n` it just put at the head of the footer were retired here."""
    old = "retired by `lifecycle.py close`"
    m = re.search(r"^## Retired[ \t]*$", text, re.M)   # the heading line, not prose
    head = m.start() if m else -1
    if head < 0:
        return text
    body = text[head:].replace(old, QUEUE_RETIRED_BY, n)
    return text[:head] + body


def _new_sections(old: str, text: str, path: str, lm,
                  ctx: dict) -> tuple[str, str | None]:
    """`text` without the `## slug` sections `old` already has, and a note
    naming them; ("", note) when every section is already there. Text with
    no `## ` section is appended as it is. A section already there is a
    repeat only when its task is a re-dispatch of this shift (`ctx["own"]`)
    and main's section is exactly the one this shift committed before
    (`ctx["prior"]`); any other is a ConflictError (#632 review)."""
    pre, entries = lm.split_entries(text)
    if not entries:
        return text, None
    have = dict(lm.split_entries(old)[1])
    dup = [slug for slug, _ in entries if slug in have]
    if not dup:
        return text, None
    ours = {}
    for p in ctx["prior"]:
        if p.get("op") == "append" and p.get("path") == path:
            ours.update(lm.split_entries(p.get("text") or "")[1])
    bad = [slug for slug in dup if slug[3:].strip() not in ctx["own"]
           or ours.get(slug) != have[slug]]
    if bad:
        raise ConflictError(f"append: {', '.join(bad)} already in {path}, not this "
                            "shift's own claim — conflict")
    note = (f"append: {', '.join(dup)} already in {path} from this shift's own claim "
            "— skipped")
    rest = [body for slug, body in entries if slug not in have]
    return (pre + "".join(rest) if rest else ""), note


def record_key(text: str, key: str, value: str,
               after: tuple[str, ...] = ("issue", "review-at")) -> str:
    """`text` with one top-level `- key: value` line above the first `## `
    heading: the key's line replaced if present, else inserted after the
    first of `after` present, else after the title. Every other line is kept."""
    lines = text.split("\n")
    end = next((i for i, ln in enumerate(lines) if ln.startswith("## ")), len(lines))
    new = f"- {key}: {value}"
    for i in range(end):
        if lines[i].startswith(f"- {key}:"):
            lines[i] = new
            return "\n".join(lines)
    at = next((i + 1 for i, ln in enumerate(lines) if ln.startswith("# ")), 0)
    for anchor in after:
        hit = next((i for i in range(end) if lines[i].startswith(f"- {anchor}:")), None)
        if hit is not None:
            at = hit + 1
            break
    lines.insert(at, new)
    return "\n".join(lines)


def _section_has(text: str, heading: str, needle: str) -> bool:
    """Whether a table row under the `## ` heading starting `heading` holds `needle`."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith(heading)), None)
    if start is None:
        return False
    for ln in lines[start + 1:]:
        if ln.startswith("## "):
            break
        if ln.startswith("|") and needle in ln:
            return True
    return False


def table_append(text: str, heading: str, row: str) -> str:
    """`row` inserted after the last table line under the `## ` heading that
    starts with `heading` — whatever follows that section stays where it is."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith(heading)), None)
    if start is None:
        raise MindWriteError(f"table-append: no heading {heading!r}")
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")),
               len(lines))
    rows = [i for i in range(start + 1, end) if lines[i].startswith("|")]
    if not rows:
        raise MindWriteError(f"table-append: no table under {heading!r}")
    lines.insert(rows[-1] + 1, row)
    return "\n".join(lines) + "\n"


def jsonl_upsert(text: str, key: str, row: dict) -> str:
    """`text` (JSON lines) with exactly one line whose `key` is `row[key]`."""
    out, hit = [], False
    for line in text.splitlines():
        try:
            old = json.loads(line)
        except ValueError:
            old = None
        if isinstance(old, dict) and old.get(key) == row[key]:
            if not hit:
                out.append(json.dumps({**old, **row}, sort_keys=True))
                hit = True
            continue  # a duplicate from before: dropped, one line per key
        out.append(line)
    if not hit:
        out.append(json.dumps(row, sort_keys=True))
    return "\n".join(out) + "\n"


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def table_upsert(text: str, key: str, row: str, header: str = "") -> str:
    """`text` with the table row whose first cell is `key` replaced by `row`
    (an old cell kept wherever the new one is `?`), else `row` appended."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("|") and _cells(line)[0] == key:
            old, new = _cells(line), _cells(row)
            if len(old) == len(new):
                new = [o if n == "?" else n for o, n in zip(old, new)]
            lines[i] = "| " + " | ".join(new) + " |"
            return "\n".join(lines) + "\n"
    if not text.strip():
        return header + row + "\n"
    return text + ("" if text.endswith("\n") else "\n") + row + "\n"


_HEADER_LINE_RE = re.compile(r"^[A-Z][A-Za-z-]*:(\s|$)")


def header_span(lines: list[str]) -> tuple[int, int] | None:
    """`(start, end)` of a prompt's header block: the contiguous `Key: value`
    lines (with their `- item` continuations) below the `# ` title, ending at
    the first blank line. None when the prompt has no header block."""
    i = 0
    while i < len(lines) and not _HEADER_LINE_RE.match(lines[i]):
        if i > 6 and lines[i].strip() and not lines[i].startswith("#"):
            return None  # prose before any header: there is no block
        i += 1
    if i >= len(lines):
        return None
    end = i
    while end < len(lines) and lines[end].strip() and (
            _HEADER_LINE_RE.match(lines[end]) or lines[end].startswith(("- ", "  "))):
        end += 1
    return i, end


def set_header(text: str, key: str, value: str,
               after: tuple[str, ...] = ("Unattended", "Review-minutes")) -> str:
    """`text` with `key: value` in its header block — the key's own line
    replaced if present, else inserted after the first of `after` present,
    else at the end of the block. A prompt with no block gets one under its
    title. Every other line is left byte-for-byte as it was."""
    lines = text.split("\n")
    new = f"{key}: {value}"
    span = header_span(lines)
    if span is None:
        at = next((i + 1 for i, ln in enumerate(lines) if ln.startswith("# ")), 0)
        return "\n".join(lines[:at] + ([""] if at else []) + [new]
                         + ([""] if at < len(lines) and lines[at].strip() else [])
                         + lines[at:])
    start, end = span
    for i in range(start, end):
        if lines[i].lower().startswith(key.lower() + ":"):
            lines[i] = new
            return "\n".join(lines)
    at = end
    for anchor in after:
        hit = next((i for i in range(start, end)
                    if lines[i].lower().startswith(anchor.lower() + ":")), None)
        if hit is not None:
            at = hit + 1
            while at < end and lines[at].startswith(("- ", "  ")):
                at += 1
            break
    lines.insert(at, new)
    return "\n".join(lines)


def _git(cwd: Path, *args, check=True) -> subprocess.CompletedProcess:
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise MindWriteError(f"git {' '.join(args)}: {(res.stderr or res.stdout).strip()}")
    return res


def queue_op(ledger_dir: Path, op: dict) -> Path:
    """Write one op file into a ledger directory, atomically, in arrival order."""
    import os
    import time
    d = Path(ledger_dir)
    d.mkdir(parents=True, exist_ok=True)
    name = f"{time.time_ns():020d}-{os.getpid()}-{op['op']}.json"
    tmp = d / (name + ".tmp")
    tmp.write_text(json.dumps(op, indent=2), encoding="utf-8")
    tmp.replace(d / name)
    return d / name


def pending_ops(slot: Path) -> list[Path]:
    d = Path(slot) / LEDGER_DIR
    return sorted(f for f in d.glob("*.json")) if d.is_dir() else []


def _set_aside(slot: Path, f: Path, why: str, needs: str = NEEDS_HUMAN) -> dict:
    """Move one op file out of the way with its reason; returns its record,
    with the op's `task` (when tagged) and whose move it is (`needs`)."""
    d = Path(slot) / LEDGER_DIR / SET_ASIDE_DIR
    d.mkdir(parents=True, exist_ok=True)
    op = _op_of(f)
    (d / (f.name + ".why")).write_text(why + "\n", encoding="utf-8")
    f.replace(d / f.name)
    out = {"file": f.name, "op": op.get("op"), "path": op.get("path"), "why": why,
           "needs": needs}
    if isinstance(op.get("task"), str):
        out["task"] = op["task"]
    return out


def _op_of(f: Path) -> dict:
    try:
        op = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return op if isinstance(op, dict) else {}


def report(slot: Path) -> list[dict]:
    """Every entry of `ledger/report.jsonl`, oldest first: {kind: skipped |
    set-aside | conflict | withheld | held, file, op, path, why, and for a
    set-aside op its `needs` (mechanical | human) and `task` when tagged}."""
    f = Path(slot) / LEDGER_DIR / REPORT_FILE
    out = []
    for line in (f.read_text(encoding="utf-8").splitlines() if f.is_file() else ()):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _report(slot: Path, entries: list[dict]) -> None:
    if not entries:
        return
    f = Path(slot) / LEDGER_DIR / REPORT_FILE
    with open(f, "a", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e, sort_keys=True) + "\n")


def committed_ops(slot: Path) -> list[dict]:
    """The ops this shift has already committed (`ledger/committed/`)."""
    d = Path(slot) / LEDGER_DIR / COMMITTED_DIR
    return [op for f in sorted(d.glob("*.json"))
            if (op := _op_of(f))] if d.is_dir() else []


def _apply_one(tree: Path, op: dict, lm, ctx: dict) -> tuple[str, object]:
    """Apply one op: ("ok", note), ("held", entry) or ("failed", entry), an
    entry being (kind, why, needs)."""
    crit = is_critical(op)
    try:
        return "ok", apply_op(tree, op, lm, ctx)
    except ConflictError as e:
        out = ("held" if crit else "conflict", str(e), NEEDS_HUMAN)
    except GoneError as e:
        return "failed", ("set-aside", str(e), NEEDS_HUMAN)
    except MechanicalError as e:
        out = ("held" if crit else "set-aside", str(e), NEEDS_MECHANICAL)
    except (MindWriteError, OSError, KeyError, TypeError, ValueError) as e:
        out = ("held" if crit else "set-aside", str(e) or type(e).__name__, NEEDS_HUMAN)
    return ("held" if crit else "failed"), out


def _withheld(task: str, cause: str) -> tuple:
    return ("withheld", f"{task}: held with its task — {cause} set aside; not "
            "recorded shipped", NEEDS_HUMAN)


def _apply_group(tree: Path, task: str, group: list, lm, ctx: dict,
                 failed: dict, held: dict, deferred: set) -> list:
    """Apply one task's closing ops as a unit; returns their notes. If one
    fails for a human (or is held), every file the group touched is put back
    as it was and the rest are withheld (or kept pending): the record never
    lands alone. A mechanical failure is a note-like set-aside and does not
    stop the group."""
    paths = {op["path"] for _f, op in group}
    before = {p: ((tree / p).read_bytes() if (tree / p).is_file() else None) for p in paths}
    notes = []
    for i, (f, op) in enumerate(group):
        where, out = _apply_one(tree, op, lm, ctx)
        if where == "ok":
            if out:
                notes.append((f, op, out))
            continue
        if where == "failed" and out[2] == NEEDS_MECHANICAL:
            failed[f] = out
            continue
        for p, data in before.items():   # roll the group back
            target = tree / p
            if data is None:
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        (held if where == "held" else failed)[f] = out
        for g, _op in group:
            if g == f or (g in failed and failed[g][2] == NEEDS_MECHANICAL):
                continue
            if where == "held":
                deferred.add(g)
            else:
                failed[g] = _withheld(task, f.name)
        return []
    return notes


def commit_ledger(slot: Path, mind_repo: Path, message: str,
                  remote: str = "origin", branch: str = "main",
                  own_tasks=()) -> dict:
    """Commit every pending op in `<slot>/ledger/` to PyAutoMind as one commit.

    Returns {"committed": sha | None, "ops": n, "tries": k, "skipped": notes,
    "set_aside": [{file, op, path, why, kind, needs, task?}], "held": [...]}. `own_tasks`
    are the tasks this shift re-dispatched: only their repeated claims may be
    skipped as already done (#632 review). A worker op that is invalid or
    cannot apply is set aside (a claim already on main from someone else as a
    `conflict`); a critical op is held pending instead. Only a push rejected
    `PUSH_TRIES` times raises, with every op left pending.

    A task's closing ops (`_closing`, and any op on a path one of them
    creates) apply after every other op, task by task, as one group: when one
    of the task's ops was set aside for a human (this run or in an earlier
    `report`) or is in conflict, the group is `withheld` — set aside with it,
    not retried; when one of them is *held* (retried), the group stays pending
    beside it. A group that fails part-way is rolled back, so a record never
    lands without the rest of its group.
    """
    mind_repo = Path(mind_repo)
    files = pending_ops(slot)
    if not files:
        return {"committed": None, "ops": 0, "tries": 0}
    lm = _ledger_merge(mind_repo)
    ctx = {"own": set(own_tasks), "prior": committed_ops(slot)}
    ops, invalid, unready = [], {}, {}
    for f in files:
        try:
            op = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:
            invalid[f] = ("set-aside", f"not JSON ({e})", NEEDS_HUMAN)
            continue
        errs = validate_op(op, lm) if isinstance(op, dict) else ["not a JSON object"]
        if errs:
            (unready if is_critical(op) else invalid)[f] = (
                "held" if is_critical(op) else "set-aside", "; ".join(errs), NEEDS_HUMAN)
            continue
        ops.append((f, op))
    # A task's ops land together: its closing ops go last, grouped by task.
    creates: dict = {}
    for _f, op in ops:
        if _closing(op) and op.get("op") == "write":
            creates.setdefault(op["task"], set()).add(op["path"])
    closing = {f for f, op in ops
               if _closing(op) or op.get("path") in creates.get(op.get("task"), ())}
    groups: dict = {}
    for f, op in ops:
        if f in closing:
            groups.setdefault(op["task"], []).append((f, op))
    ops = [x for x in ops if x[0] not in closing]
    recorded = {op["task"] for op in ctx["prior"] if isinstance(op.get("task"), str)
                and op.get("op") == "write" and str(op.get("path", "")).startswith("complete/")}
    earlier = report(slot)
    seen_held = {(e.get("file"), e.get("kind")) for e in earlier}
    blocked_before = {e["task"]: e.get("file") for e in earlier
                      if isinstance(e.get("task"), str)
                      and e.get("kind") in ("set-aside", "conflict", "withheld")
                      and e.get("needs") != NEEDS_MECHANICAL}

    for attempt in range(1, PUSH_TRIES + 1):
        fetch(mind_repo, remote, branch)
        tmp = Path(tempfile.mkdtemp(prefix="mind-writer-"))
        tree = tmp / "tree"
        try:
            _git(mind_repo, "worktree", "add", "-q", "--detach", str(tree),
                 f"{remote}/{branch}")
            notes, failed, held, deferred = [], dict(invalid), dict(unready), set()
            blocked = dict(blocked_before)
            for f in invalid:
                task = _op_of(f).get("task")
                if isinstance(task, str):
                    blocked.setdefault(task, f.name)
            for f, op in ops:
                where, out = _apply_one(tree, op, lm, ctx)
                if where == "ok":
                    if out:
                        notes.append((f, op, out))
                    continue
                (held if where == "held" else failed)[f] = out
                if where == "failed" and out[2] != NEEDS_MECHANICAL \
                        and isinstance(op.get("task"), str):
                    blocked.setdefault(op["task"], f.name)
            waiting = {_op_of(f).get("task") for f in held} - {None}
            for task, group in groups.items():
                if task in blocked:
                    for f, _op in group:
                        failed[f] = _withheld(task, blocked[task])
                    continue
                if task in waiting:   # a sibling is held: wait beside it
                    deferred.update(f for f, _op in group)
                    continue
                notes += _apply_group(tree, task, group, lm, ctx, failed, held, deferred)
            for f in failed:
                task = _op_of(f).get("task")
                kind, why, needs = failed[f]
                if task in recorded and needs != NEEDS_MECHANICAL:
                    failed[f] = (kind, why, needs, "on-main")
            _git(tree, "add", "-A")
            if not _git(tree, "status", "--porcelain").stdout.strip():
                sha = None  # every op was already true on main (or set aside)
            else:
                _git(tree, "commit", "-q", "-m", message)
                sha = _git(tree, "rev-parse", "HEAD").stdout.strip()
                pushed = _git(tree, "push", "-q", remote, f"HEAD:{branch}", check=False)
                if pushed.returncode != 0:
                    continue  # main moved: replay the ops on the new origin/main
            aside = []
            for f, (kind, why, needs, *record) in sorted(failed.items()):
                aside.append({**_set_aside(slot, f, why, needs), "kind": kind,
                              **({"record": record[0]} if record else {})})
            held_out = [{"file": f.name, "op": _op_of(f).get("op"),
                         "path": _op_of(f).get("path"), "why": why, "kind": "held"}
                        for f, (_k, why, _n) in sorted(held.items())]
            _report(slot, [{"kind": "skipped", "file": f.name, "op": op.get("op"),
                            "path": op.get("path"), "why": n} for f, op, n in notes]
                    + aside + [h for h in held_out if (h["file"], "held") not in seen_held])
            for a in aside + held_out:
                print(f"mind-writer: {a['kind']} {a['file']}: {a['why']}", file=sys.stderr)
            done = Path(slot) / LEDGER_DIR / COMMITTED_DIR
            done.mkdir(parents=True, exist_ok=True)
            for f in files:
                if f not in failed and f not in held and f not in deferred:
                    f.replace(done / f.name)
            return {"committed": sha,
                    "ops": len(files) - len(failed) - len(held) - len(deferred),
                    "tries": attempt, "skipped": [n for _f, _o, n in notes],
                    "set_aside": aside, "held": held_out}
        finally:
            # Our own throwaway tree. A failed apply can leave it dirty, so
            # delete the directory and prune the registration, no force flag.
            if _git(mind_repo, "worktree", "remove", str(tree), check=False).returncode:
                shutil.rmtree(tmp, ignore_errors=True)
                _git(mind_repo, "worktree", "prune", check=False)
            shutil.rmtree(tmp, ignore_errors=True)
    raise MindWriteError(f"push rejected {PUSH_TRIES} times; ops left pending")
