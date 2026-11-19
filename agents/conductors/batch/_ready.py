"""The readiness pass, `batch ready` (M3.3 slice 1, PyAutoBrain#671).

It walks Mind `queue.md`, resolves each entry to its next startable unit(s),
checks each unit's gates, and turns every gate into an inbox entry of kind
`ruling` for the human. The next launch is then `brief --new`, read, go,
instead of a kick-off chat that finds each epic's next unit and asks the
rulings one at a time.

Resolution (human decisions D3, 2026-11-18):

- an epic ledger (a prompt with `Epic:` and no `Phase:`) resolves to every
  open member of that epic at the lowest leading phase number (`5c` is 5),
  scanning `draft/` and `active/`. A member in `active/` is in flight, not
  gated. An epic with no open `Phase:` member is one ruling on the ledger,
  gate `no-next-phase`. The ledgers' free-form phase tables are not read;
- any other prompt resolves to itself, in flight when it is in `active/`.

Gates on each draft unit (Q5): `looks-shipped`, then `obsolete` (the premise
check, offline unless `--fetch`), and either one stops the rest. Then each of
`claimed`, `unattended`, `human-required`, `blocked-by` and `no-lane` that
applies is its own ruling. A `judge` unit gets a note (D4: a tier is not a
gate).

What it writes: nothing on a dry run. `queue` puts one `question-add` op per
new ruling in a slot's ledger, for the shift's one Mind writer, and records
`counters["rulings"]`; `apply` writes them into a session-branch Mind checkout
through Mind's own `questions_edit.add_text` (never on `main`, never a commit
or a push). A ruling still Open or Deferred on Mind `origin/main` for the same
task and gate is not filed again. Everything on the Mind side is read from the
local `origin/main` ref: no fetch.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import subprocess
from pathlib import Path

import _batch
import _mind_writer
import _questions
from _steer import read_queue_entries

WORKER = "readiness pass"
GATES = ("no-next-phase", "looks-shipped", "obsolete", "claimed", "unattended",
         "human-required", "blocked-by", "no-lane")
NOT_FILED_KIND = "Mind has no `ruling` inbox kind yet (PyAutoBrain#671)"
_KINDS_RE = re.compile(r"^QUESTION_KINDS\s*=\s*\(([^)]*)\)", re.M)


# --- reading the Mind ------------------------------------------------------------

def _git(mind, *args):
    return subprocess.run(["git", "-C", str(mind), *args], capture_output=True, text=True,
                          timeout=60)


def mind_has_ruling(mind, ref: str = "origin/main") -> str:
    """"" when Mind `ref`'s `scripts/lifecycle.py` lists `ruling` in its
    `QUESTION_KINDS` (a local `git show`, no fetch); else why rulings are not
    filed."""
    try:
        shown = _git(mind, "show", f"{ref}:scripts/lifecycle.py")
    except (OSError, subprocess.SubprocessError) as e:
        return f"Mind {ref} unreadable ({e})"[:200]
    if shown.returncode != 0:
        return f"Mind {ref}:scripts/lifecycle.py unreadable — {NOT_FILED_KIND}"
    m = _KINDS_RE.search(shown.stdout)
    return "" if m and re.search(r"['\"]ruling['\"]", m.group(1)) else NOT_FILED_KIND


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def resolve_ref(mind: Path, ref: str) -> str:
    """Where a queue ref's prompt is now, Mind-relative: itself, else the same
    file name in `draft/` or `active/`; "" when it is in neither."""
    if not ref:
        return ""
    if (mind / ref).is_file() and ref.startswith(("draft/", "active/")):
        return ref
    name = Path(ref).name
    hit = next(iter(sorted(mind.glob(f"draft/**/{name}"))), None) or (
        mind / "active" / name if (mind / "active" / name).is_file() else None)
    return hit.relative_to(mind).as_posix() if hit else ""


def epic_members(mind: Path, epic: str) -> list[dict]:
    """Every open (not done) member of `epic` with a `Phase:`, in `draft/` and
    `active/`: `{path, phase}`."""
    out = []
    files = [*sorted(mind.glob("draft/**/*.md")), *sorted(mind.glob("active/*.md"))]
    for f in files:
        if f.name == "README.md":
            continue
        text = _read(f)
        if _batch._epic_of(text) != epic or not _batch._phase_declared(text) \
                or _batch._is_done(text):
            continue
        out.append({"path": f.relative_to(mind).as_posix(), "phase": _batch._phase_of(text)})
    return out


def is_ledger(text: str) -> bool:
    """An epic ledger: `Status: campaign map` with `Epic:` and no `Phase:`
    (as intake's `_shipped` reads a map). A side task of an epic (`Epic:`, no
    `Phase:`, any other status) is an ordinary prompt. The planner's own
    test (`_batch.is_ledger_text`), so both read a ledger alike."""
    return _batch.is_ledger_text(text)


def origin_epic_members(mind: Path, epic: str, ref: str = "origin/main") -> list[dict] | None:
    """The open `Phase:` members of `epic` in `draft/` and `active/` on Mind
    `ref`, read locally (`git grep`, `git show`; no fetch): `{path, phase}`.
    None when the ref cannot be read (not a git checkout of its own)."""
    try:
        top = _git(mind, "rev-parse", "--show-toplevel")
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != Path(mind).resolve():
            return None
        hits = _git(mind, "grep", "-l", "-i", "-E", rf"^Epic:[[:space:]]*{re.escape(epic)}",
                    ref, "--", "draft/", "active/")
    except (OSError, subprocess.SubprocessError):
        return None
    if hits.returncode not in (0, 1):
        return None
    out = []
    for line in hits.stdout.splitlines():
        path = line.split(":", 1)[1] if line.startswith(f"{ref}:") else line
        if not path.endswith(".md") or Path(path).name == "README.md":
            continue
        shown = _git(mind, "show", f"{ref}:{path}")
        if shown.returncode != 0:
            continue
        text = shown.stdout
        if _batch._epic_of(text) != epic or not _batch._phase_declared(text) \
                or _batch._is_done(text):
            continue
        out.append({"path": path, "phase": _batch._phase_of(text)})
    return out


BEHIND = "Mind working tree behind origin/main — rerun after a pull"


def behind_origin(local: list[dict], origin: list[dict] | None) -> bool:
    """Whether origin/main has an open member the working tree lacks, or the
    two disagree on the lowest phase (None: origin not read, not behind)."""
    if origin is None:
        return False
    names = {Path(m["path"]).name for m in local}
    if any(Path(m["path"]).name not in names for m in origin):
        return True
    low = lambda ms: min((m["phase"] for m in ms), default=None)  # noqa: E731
    return low(local) != low(origin)


def _phase_label(p: float) -> str:
    return f"{p:g}" if p != float("inf") else "(unnumbered)"


# --- the rulings -------------------------------------------------------------------

def _options(*opts) -> list[str]:
    return [_questions.sanitise(o, _questions.OPTION_MAX) for o in opts if o][:3]


def ruling(task: str, gate: str, ask: str, options: list[str], shift: str,
           asked: str) -> dict:
    """One `question-add` entry of kind ruling (no `issue`)."""
    return {"task": task, "kind": _questions.RULING, "gate": gate,
            "ask": _questions.sanitise(ask, _questions.ASK_MAX), "options": options,
            "shift": shift, "asked": asked, "worker": WORKER}


def _gate_rulings(r: dict, stem: str, held, premise: dict | None) -> list[tuple]:
    """(gate, ask, options) for one draft unit, in the plan's order."""
    if r.get("looks_shipped"):
        return [("looks-shipped",
                 f"`{stem}` looks shipped ({_batch._shipped.FLAGS_FILE}): confirm and close "
                 "it, or dismiss the flag?",
                 _options("close it as shipped",
                          f"dismiss the flag ({_batch._shipped.DISMISS_FILE})",
                          "drop it from the queue"))]
    if premise and premise.get("status") == "obsolete":
        why = "; ".join(premise.get("reasons") or [])[:120] or "see `batch premise`"
        return [("obsolete", f"`{stem}`'s premise looks obsolete on main: {why}",
                 _options("retire the prompt", "rewrite its premise", "keep it as it is"))]
    out = []
    if held:
        repo, slug = held
        out.append(("claimed",
                    f"`{stem}` cannot start: repo {repo} is claimed by `{slug}` in active.md "
                    "with no coordination line naming it.",
                    _options(f"wait for {slug} to ship", "record a coordination line",
                             "drop it from the queue")))
    if r.get("unattended") != "ready":
        out.append(("unattended",
                    f"`{stem}` is Unattended: {r.get('unattended') or '?'}, so no shift "
                    "starts it.",
                    _options("make it ready (slice or size it)",
                             "keep it for an attended session", "drop it from the queue")))
    if r.get("autonomy") == "human-required":
        out.append(("human-required",
                    f"`{stem}` is Autonomy: human-required, so a shift worker would park "
                    "at ship.",
                    _options("lower it to supervised", "keep it for an attended session",
                             "drop it from the queue")))
    if r.get("blocked"):
        waits = "; ".join(r.get("blocked_by") or []) or "its Blocked-by"
        out.append(("blocked-by", f"`{stem}` waits for {waits} (its Blocked-by).",
                    _options(f"wait for {waits}", "remove the Blocked-by",
                             "drop it from the queue")))
    if not r.get("lane"):
        out.append(("no-lane",
                    f"`{stem}` has no valid Lane:, so every unattended pick fails closed.",
                    _options("declare Lane: any", "declare a laptop lane",
                             "drop it from the queue")))
    return out


def _premise_root() -> Path:
    return Path(os.environ.get("PYAUTO_ROOT") or _batch.pyauto_root()).resolve()


def run(mind, *, root=None, fetch: bool = False, shift: str = "", now=None,
        check_premise=None) -> dict:
    """The pass, read-only. Returns `{entries, found, rulings, skipped, open,
    not_filed, notes, shift}`: `found` is every gate as a ruling entry,
    `rulings` those to file (no ruling on the same task and gate in any state
    on Mind origin/main — once ruled, quiet — and none at all when Mind main
    has no `ruling` kind), `skipped` the `(entry, id)` already ruled, `open`
    the Open and Deferred rulings on Mind origin/main."""
    import _orchestrator as orch  # noqa: E402 — deferred: it imports this module
    mind = Path(mind)
    now = now or _dt.datetime.now(_dt.timezone.utc)
    asked = now.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    shift = shift or f"ready-{now.strftime('%Y-%m-%d')}"
    notes: list[str] = []
    if check_premise is None:
        import _premise
        try:
            proot = Path(root).resolve() if root is not None else _premise_root()
        except Exception as e:  # noqa: BLE001 — degrade: no premise check
            proot = None
            notes.append(f"premise check skipped: no workspace root ({e})")
        views: dict = {}

        def check_premise(path: Path):
            if proot is None:
                return None
            return _premise.safe_check(path, proot, fetch=fetch, offline=not fetch,
                                       views=views)
    queued = read_queue_entries(mind)
    # The survey grades every draft: only when the queue names one.
    records = {r["path"]: r for r in _batch.survey(mind)} if queued else {}
    claims = orch.origin_claims(mind)
    if claims is None:
        notes.append("claims not read: the Mind is not a git checkout of its own")
    elif "error" in claims:
        notes.append(f"claims not read: {claims['error']}")
    sections = (claims or {}).get("sections") or {} if claims and "error" not in claims \
        else None
    entries, found = [], []
    for q in queued:
        e = {"pos": q["pos"], "label": q["label"], "ref": q["ref"], "kind": q["kind"],
             "path": "", "units": [], "notes": []}
        entries.append(e)
        if q["kind"] != "prompt":
            e["notes"].append(f"kind {q['kind'] or '?'}: not a prompt, not resolved")
            continue
        path = resolve_ref(mind, q["ref"])
        e["path"] = path
        if not path:
            e["notes"].append("unresolved: its prompt is in neither draft/ nor active/")
            continue
        text = _read(mind / path)
        epic = _batch._epic_of(text)
        if is_ledger(text):
            members = epic_members(mind, epic)
            if behind_origin(members, origin_epic_members(mind, epic)):
                e["notes"].append(f"epic {epic}: {BEHIND}; no ruling filed")
                continue
            if not members:
                e["notes"].append(f"epic {epic}: no open Phase: member in draft/ or active/")
                found.append(ruling(
                    path, "no-next-phase",
                    f"Epic {epic} is queued but no next-phase prompt is filed (no open "
                    "Phase: member in draft/ or active/).",
                    _options("file the next phase's prompt", "close the epic",
                             "drop it from the queue"), shift, asked))
                continue
            low = min(m["phase"] for m in members)
            unit_paths = sorted(m["path"] for m in members if m["phase"] == low)
            e["notes"].append(f"epic {epic}: next phase {_phase_label(low)}")
        else:
            unit_paths = [path]
            if epic and _batch._phase_declared(text) and not _batch._is_done(text):
                # A Phase member queued directly that is not its epic's next
                # phase: a note, not a gate (PyAutoBrain#671 review, M3).
                low = min((m["phase"] for m in epic_members(mind, epic)),
                          default=float("inf"))
                mine = _batch._phase_of(text)
                if mine > low:
                    e["notes"].append(f"epic {epic} phase {_phase_label(mine)} is not next "
                                      f"— phase {_phase_label(low)} is")
                    continue
        for up in unit_paths:
            u = {"path": up, "state": "draft", "gates": [], "notes": []}
            e["units"].append(u)
            stem = Path(up).stem
            if up.startswith("active/"):
                u["state"] = "in flight"
                continue
            r = records.get(up)
            if r is None:
                u["notes"].append("not graded (not in the draft/ survey)")
                continue
            if r.get("done"):
                u["notes"].append("Status: says the work is done — retire it from the queue")
                continue
            if sections is not None and up not in claims["drafts"]:
                # The working tree is behind: origin/main has moved it.
                claim = orch.claim_of(sections, stem)
                u["state"] = "in flight" if claim else "moved"
                u["notes"].append(
                    f"not in draft/ on Mind origin/main — claimed by `{claim[0]}`" if claim
                    else "not in draft/ on Mind origin/main (moved or retired) — rerun "
                         "after a pull")
                continue
            if sections is not None and stem in claims["active"]:
                u["state"] = "in flight"
                u["notes"].append("claimed in active.md on Mind origin/main")
                continue
            held = orch._held_for(sections, stem, r.get("declared_repos") or r.get("repos")
                                  or []) if sections is not None else None
            premise = None
            if not r.get("looks_shipped"):
                premise = check_premise(mind / up)
            for gate, ask, opts in _gate_rulings(r, stem, held, premise):
                u["gates"].append(gate)
                if not any((f["task"], f["gate"]) == (up, gate) for f in found):
                    found.append(ruling(up, gate, ask, opts, shift, asked))
            if r.get("consequence") == "judge":
                u["notes"].append("judge tier: a human judges the result at review "
                                  "(a note, not a gate)")
    origin = _questions.read_origin(mind)
    if origin is None:
        notes.append("questions.md on Mind origin/main not read: open rulings not checked")
    open_ = sorted(({"task": t, "gate": x.get("gate", ""), "id": x["id"]}
                    for t, xs in (origin or {}).items() for x in xs
                    if _questions.is_ruling(x) and x["state"] in ("open", "deferred")),
                   key=lambda x: int(x["id"][1:]) if x["id"][1:].isdigit() else 0)
    # Once ruled, quiet (the human's L1 ruling, 2026-11-18): a ruling in any
    # state — Open, Deferred, Answered or Dropped — keeps its task and gate
    # from being filed again; `/questions` reopen asks again. An open one is
    # named first.
    ruled: dict = {}
    for t, xs in (origin or {}).items():
        for x in xs:
            if _questions.is_ruling(x):
                key = (t, x.get("gate", ""))
                if key not in ruled or x["state"] in ("open", "deferred"):
                    ruled[key] = x["id"] if x["state"] in ("open", "deferred") \
                        else f"{x['id']}, {x['state']}"
    rulings, skipped = [], []
    for f in found:
        have = ruled.get((Path(f["task"]).stem, f["gate"]))
        if have:
            skipped.append((f, have))
        else:
            rulings.append(f)
    not_filed = mind_has_ruling(mind)
    return {"mind": str(mind), "shift": shift, "entries": entries, "found": found,
            "rulings": [] if not_filed else rulings, "would_file": rulings,
            "skipped": skipped, "open": open_, "not_filed": not_filed, "notes": notes}


# --- writing -------------------------------------------------------------------------

def ops(res: dict) -> list[dict]:
    return [_questions.add_op(r) for r in res["rulings"]]


def record(res: dict, counters: dict) -> list[dict]:
    """Note the pass in `counters["rulings"]` (new rulings once per task and
    gate, the Open ones on origin, why none were filed); the entries new to
    this slot."""
    c = counters.setdefault("rulings", {})
    c.pop("error", None)
    fresh = [r for r in res["rulings"] if _questions.note_added(counters, r)]
    c["open"] = [{"task": o["task"], "gate": o["gate"], "id": o["id"]} for o in res["open"]]
    if res["not_filed"]:
        c["not_filed"] = f"{res['not_filed']} — {len(res['would_file'])} found"
    else:
        c.pop("not_filed", None)
    return fresh


class QueueRefused(Exception):
    pass


def slot_refusal(slot) -> str:
    """Why `--queue` may not write into `slot`, or "": it must be an existing
    watcher slot (its `counters.json` or Mind-writer ledger) whose digest is
    not yet posted. Nothing is created."""
    import _orchestrator as orch  # noqa: E402
    slot = Path(slot)
    if not slot.is_dir():
        return f"--queue: no slot directory {slot}"
    if not ((slot / orch.COUNTERS_FILE).is_file() or (slot / _mind_writer.LEDGER_DIR).is_dir()):
        return (f"--queue: {slot} is not a watcher slot (no {orch.COUNTERS_FILE} or "
                f"{_mind_writer.LEDGER_DIR}/)")
    if (slot / orch.DIGEST_MARKER).exists():
        return f"--queue: {slot.name}'s digest is already posted — the shift is closed"
    return ""


def queue(res: dict, slot, counters: dict | None = None, now=None) -> list[dict]:
    """Queue one `question-add` op per new ruling into `slot`'s ledger and
    record them. With `counters` (finish_shift's, inside its tick), they are
    updated in place and not written. Else (`--queue`) the slot must pass
    `slot_refusal`, and the slot's tick lock is taken, non-blocking, around
    the read and write of its `counters.json` (QueueRefused while a tick
    holds it)."""
    import _orchestrator as orch  # noqa: E402
    slot = Path(slot)
    if counters is not None:
        fresh = record(res, counters)
        for r in fresh:
            _mind_writer.queue_op(slot / _mind_writer.LEDGER_DIR, _questions.add_op(r))
        return fresh
    why = slot_refusal(slot)
    if why:
        raise QueueRefused(why)
    now = now or _dt.datetime.now(_dt.timezone.utc)
    if not orch._take_lock(slot, now):
        raise QueueRefused(f"--queue: {slot.name}'s tick lock is held — a tick is running; "
                           "try again in a minute")
    try:
        if (slot / orch.DIGEST_MARKER).exists():
            raise QueueRefused(f"--queue: {slot.name}'s digest is already posted")
        counters = orch.read_counters(slot)
        fresh = record(res, counters)
        for r in fresh:
            _mind_writer.queue_op(slot / _mind_writer.LEDGER_DIR, _questions.add_op(r))
        orch._write_counters(slot, counters)
    finally:
        orch._drop_lock(slot)
    return fresh


class ApplyRefused(Exception):
    pass


def apply(res: dict, mind) -> list[str]:
    """Write the rulings into the `mind` checkout's `questions.md` with Mind's
    own `questions_edit.add_text`, loaded from that checkout. Refused on branch
    `main` (the shift never writes Mind main); never commits or pushes."""
    mind = Path(mind)
    branch = _git(mind, "rev-parse", "--abbrev-ref", "HEAD")
    if branch.returncode != 0:
        raise ApplyRefused(f"--apply: {mind} is not a git checkout")
    if branch.stdout.strip() == "main":
        raise ApplyRefused(f"--apply: {mind} is on branch main — write the rulings from a "
                           "session branch (or queue them with --queue); never Mind main")
    if res["not_filed"]:
        raise ApplyRefused(f"--apply: rulings not filed: {res['not_filed']}")
    try:
        qe = _mind_writer._mind_module(mind, "questions_edit", deps=("lifecycle",))
    except _mind_writer.MindWriteError as e:
        raise ApplyRefused(f"--apply: {e}") from e
    target = mind / _questions.FILE
    text = _read(target)
    out = []
    for r in res["rulings"]:
        text, qid, added = qe.add_text(text, r, mind)
        out.append(f"{qid} {'added' if added else 'already there'}: "
                   f"{Path(r['task']).stem} ({r['gate']})")
    if res["rulings"]:
        target.write_text(text, encoding="utf-8")
    return out


# --- reading it back -----------------------------------------------------------------

def needed(counters: dict) -> int:
    """New rulings plus those still Open or Deferred on Mind origin/main, once
    per task and gate."""
    c = counters.get("rulings") or {}
    keys = {(r.get("task"), r.get("gate")) for r in c.get("new") or []}
    open_ = c.get("open") or []
    keys |= {(o.get("task"), o.get("gate")) for o in open_} if isinstance(open_, list) \
        else set()
    return len(keys) + (open_ if isinstance(open_, int) else 0)


def digest_lines(counters: dict) -> list[str]:
    """The digest's closing lines: why the pass failed or filed nothing, then
    "The next shift needs N rulings from you." — nothing for a shift whose
    watcher predates the pass (no `counters["rulings"]`)."""
    if "rulings" not in counters:
        return []
    c = counters["rulings"] or {}
    out = [""]
    if c.get("error"):
        out.append(f"Readiness pass failed: {c['error']}")
    if c.get("not_filed"):
        out.append(f"Rulings not filed: {c['not_filed']}")
    n = needed(counters)
    out.append(f"The next shift needs {n} ruling{'s' if n != 1 else ''} from you.")
    return out


def report(res: dict, *, written: list[str] | None = None, queued: list | None = None,
           slot=None) -> str:
    """The dry run's (and every mode's) plain report."""
    lines = [f"batch ready — {res['mind']} (shift `{res['shift']}`)"]
    lines += [f"note: {n}" for n in res["notes"]]
    by_task: dict = {}
    for f in res["found"]:
        by_task.setdefault(f["task"], []).append(f)
    skipped = {(s["task"], s["gate"]): q for s, q in res["skipped"]}
    shown: set = set()
    for e in res["entries"]:
        lines.append(f"{e['pos']}. {e['label']} — {e['path'] or e['ref'] or '(no ref)'}")
        lines += [f"   {n}" for n in e["notes"]]
        if e["path"] and not e["units"]:
            for f in by_task.get(e["path"], []):
                lines.append(_ruling_line(f, skipped, "   ", shown))
        for u in e["units"]:
            lines.append(f"   unit {u['path']} ({u['state']})"
                         + ("" if u["gates"] or u["state"] != "draft" else " — ready"))
            lines += [f"     note: {n}" for n in u["notes"]]
            for f in by_task.get(u["path"], []):
                lines.append(_ruling_line(f, skipped, "     ", shown))
    n_new, n_skip = len(res["would_file"]), len(res["skipped"])
    if res["not_filed"]:
        lines.append(f"Rulings not filed: {res['not_filed']} — {n_new} found.")
    elif queued is not None:
        lines.append(f"Queued {len(queued)} ruling(s) in {slot}; {n_skip} skipped as already "
                     "ruled.")
    elif written is not None:
        lines += [f"  {w}" for w in written]
        lines.append(f"Applied {len(written)} ruling(s) (not committed); {n_skip} skipped as "
                     "already ruled.")
    else:
        lines.append(f"Dry run: would file {n_new} ruling(s); {n_skip} skipped as already "
                     "ruled; nothing written.")
    lines.append(f"Open or deferred rulings on Mind origin/main: {len(res['open'])}.")
    return "\n".join(lines)


def _ruling_line(f: dict, skipped: dict, pad: str, shown: set) -> str:
    key = (f["task"], f["gate"])
    if key in shown:
        return f"{pad}ruling {f['gate']} (listed above)"
    shown.add(key)
    q = skipped.get(key)
    head = f"{pad}ruling {f['gate']}" + (f" (already in your inbox as {q})" if q else "")
    return f"{head} — {f['ask']} [{' | '.join(f['options'])}]"
