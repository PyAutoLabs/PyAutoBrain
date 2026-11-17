"""Shift briefs — parse and validate the `brief:` block of a batch record.

The schema is `PyAutoMind/batches/AGENTS.md` "Shift brief (2026-11-03)"; the
doctrine that makes a brief the launch act is `AUTONOMY.md` "Shift briefs and
unattended `glance`". This module only READS: `check` says whether a brief is
well-formed, and `scope` says which backlog records it admits. Nothing here
dispatches, merges or writes a file — those verbs are phase 3.

Every error names the key it is about (`brief.lanes: ...`), because the person
fixing a brief is reading the file, not this code.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

from _sizing import (  # noqa: E402 — the caller puts the faculty on sys.path
    CONSEQUENCE_TIERS, LANE_VALUES, effective_consequence, effective_difficulty,
    parse_prompt,
)

BACKLOG_POLICIES = ("none", "fill-idle", "scoped")
#: Optional usage caps (phase 3a) and their defaults when a brief omits them.
CAP_DEFAULTS = {"max-workers": 4, "max-sessions": 8}
#: Permission modes a real worker may run in (phase 3b). `auto` is the default
#: the human chose 2026-11-03: a worker that still needs a person shows
#: `blocked` and is parked. `bypassPermissions` is never a worker mode.
WORKER_MODES = ("auto", "dontAsk", "acceptEdits")
DEFAULT_WORKER_MODE = "auto"
SCOPED_KEYS = ("epics", "tags", "tiers")
#: The organs a shift runs on: its watcher and planner (Brain), its one Mind
#: writer (Mind) and its release path (Hands). A shift never changes them, so
#: the planner never dips a draft that targets one (PyAutoBrain#637, item 7).
#: A brief's named task is the human's own pick and is not gated.
SELF_ORGANS = ("PyAutoBrain", "PyAutoMind", "PyAutoHands")
#: The one size `backlog: scoped` may dip beyond `queue.md` (human ruling
#: 2026-11-16, PyAutoBrain#637, item 6): small and single-repo only.
SCOPED_REACH_DIFFICULTY = "small"
#: The late window (human ruling H2): the watcher's digest and late sweep run
#: from `review-at:` to this long after it, and then it stops ticking the slot
#: (M3.6a, PyAutoBrain#659). `batch watch --stream` ends at the same time.
LATE_WINDOW_S = 45 * 60
#: A shift issue: the brief's `issue:` value (M3.6a).
ISSUE_RE = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/issues/\d+")

_ITEM_RE = re.compile(r"^(\s*)-\s+(.*?)\s*$")
_KEY_RE = re.compile(r"^([a-z][a-z0-9-]*):\s*(.*)$")
# A trailing comment needs whitespace before the `#`, so `Repo#1554` and
# `#anchor` paths survive.
_COMMENT_RE = re.compile(r"\s+#\s.*$")


class BriefError(ValueError):
    """The file is not a batch record at all (unreadable, no bullets)."""


# --- parse ---------------------------------------------------------------------

def _tree(text: str) -> list[dict]:
    """The record's bullets as a tree: `{"text", "children"}` per item.

    Indentation decides nesting; the first `## ` heading (the digest, appended
    at collect) ends the record's terms.
    """
    root: list[dict] = []
    stack: list[tuple[int, list[dict]]] = [(-1, root)]
    for line in text.splitlines():
        if line.startswith("## "):
            break
        m = _ITEM_RE.match(line)
        if not m:
            continue
        indent, body = len(m.group(1).expandtabs(2)), _COMMENT_RE.sub("", m.group(2))
        while stack[-1][0] >= indent:
            stack.pop()
        node = {"text": body.strip(), "children": []}
        stack[-1][1].append(node)
        stack.append((indent, node["children"]))
    return root


def _keyed(nodes: list[dict]) -> dict[str, dict]:
    """First occurrence of each `key: value` node, by key."""
    out: dict[str, dict] = {}
    for n in nodes:
        m = _KEY_RE.match(n["text"])
        if m and m.group(1) not in out:
            out[m.group(1)] = {"value": m.group(2).strip(), "children": n["children"]}
    return out


def parse(text: str) -> dict:
    """The record's top-level keys, with the `brief:` block broken out."""
    nodes = _tree(text)
    if not nodes:
        raise BriefError("no `- key: value` bullets — not a batch record")
    top = _keyed(nodes)
    brief = top.get("brief")
    return {"top": top, "brief": _keyed(brief["children"]) if brief else None}


def _csv(value: str) -> list[str]:
    return [v for v in re.split(r"[,\s]+", value.strip()) if v]


def _iso(value: str):
    try:
        return _dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _nonneg_int(value: str):
    return int(value) if re.fullmatch(r"\d+", value.strip()) else None


def tasks_of(brief: dict) -> list[str]:
    node = brief.get("tasks")
    return [c["text"] for c in node["children"]] if node else []


def scoped_of(brief: dict) -> dict[str, list[str]]:
    node = brief.get("scoped")
    out = {}
    for k, v in _keyed(node["children"]).items() if node else ():
        out[k] = _csv(v["value"])
    return out


def excluded_of(brief: dict) -> tuple[set[str], dict[str, list[str]]]:
    """Excluded prompt paths, and excluded `epics:` / `tags:` lists."""
    node = brief.get("exclude")
    paths, keyed = set(), {}
    for c in node["children"] if node else ():
        m = _KEY_RE.match(c["text"])
        if m and m.group(1) in SCOPED_KEYS:
            keyed.setdefault(m.group(1), []).extend(_csv(m.group(2)))
        else:
            paths.add(c["text"])
    return paths, keyed


def cap_of(brief: dict, key: str) -> int:
    """A usage cap from the brief, or its default when the brief omits it."""
    value = _nonneg_int(brief.get(key, {}).get("value", ""))
    return CAP_DEFAULTS[key] if value is None else value


#: The caps a `/cap` steering command may lower for one shift (#644).
CAP_KEYS = ("merge-cap", "max-workers", "max-sessions", "token-budget")


def effective(brief: dict, counters: dict | None) -> dict:
    """The brief as this shift now runs it (PyAutoBrain#644): a copy with each
    `/cap` override's value (`counters["caps"]`) swapped in, and each task the
    human `/add`ed (`counters["added"]`) appended to `tasks:` and taken out of
    `exclude:` — the human's newer word, as a brief that names a task again.
    The brief file is never changed; with nothing steered it is `brief` itself."""
    caps = (counters or {}).get("caps") or {}
    added = (counters or {}).get("added") or {}
    if not brief or not (caps or added):
        return brief
    out = dict(brief)
    for key, ov in caps.items():
        if key in CAP_KEYS and isinstance(ov, dict) and "value" in ov:
            out[key] = {**(brief.get(key) or {"children": []}), "value": str(ov["value"])}
    prompts = [a["prompt"] for a in added.values() if isinstance(a, dict) and a.get("prompt")]
    if prompts:
        tasks = brief.get("tasks") or {"value": "", "children": []}
        have = {Path(c["text"]).name for c in tasks["children"]}
        out["tasks"] = {**tasks, "children": list(tasks["children"]) + [
            {"text": p, "children": []} for p in prompts if Path(p).name not in have]}
        names = {Path(p).name for p in prompts}
        if brief.get("exclude"):
            ex = brief["exclude"]
            out["exclude"] = {**ex, "children": [c for c in ex["children"]
                                                 if Path(c["text"]).name not in names]}
        out["added"] = {"value": " ".join(sorted(names)), "children": []}
    return out


def worker_mode_of(brief: dict) -> str:
    return brief.get("worker-mode", {}).get("value") or DEFAULT_WORKER_MODE


def is_shadow(brief: dict) -> bool:
    """A shadow shift (phase 4a) plans and records proposals but spawns nothing."""
    return brief.get("shadow", {}).get("value", "").lower() == "yes"


def is_sandbox(brief: dict) -> bool:
    return brief.get("sandbox", {}).get("value", "").lower() == "yes"


def lanes_of(brief: dict) -> list[str]:
    node = brief.get("lanes")
    return _csv(node["value"]) if node else []


# --- check ---------------------------------------------------------------------

def _resolve(mind: Path, path: str) -> Path | None:
    """A named task's prompt: where the brief says, or moved to `active/`."""
    for cand in (mind / path, mind / "active" / Path(path).name):
        if cand.is_file():
            return cand
    return None


def _tier(path: Path, mind: Path) -> str:
    p = parse_prompt(path, mind)
    _level, _score, factors, _derived = effective_difficulty(p)
    return effective_consequence(p, factors)[0]


def _previous_record(mind: Path, this: Path) -> Path | None:
    """The newest batch record before this one, by its date-sorted name."""
    batches = mind / "batches"
    try:
        here = this.resolve()
    except OSError:
        here = this
    older = sorted(f for f in batches.glob("*.md")
                   if f.name != "AGENTS.md" and f.resolve() != here
                   and f.name < this.name)
    return older[-1] if older else None


def _has_minutes(text: str) -> bool:
    try:
        return bool(parse(text)["top"].get("review-minutes-actual", {}).get("value"))
    except BriefError:
        return False


def origin_text(mind: Path, rel: str, ref: str = "origin/main") -> str | None:
    """`rel` as Mind's local `ref` holds it — a local, read-only `git show`,
    never a fetch. None when `mind` is not a git checkout of its own or the
    ref has no such file."""
    import subprocess
    try:
        top = subprocess.run(["git", "-C", str(mind), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=30)
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != Path(mind).resolve():
            return None
        res = subprocess.run(["git", "-C", str(mind), "show", f"{ref}:{rel}"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if res.returncode == 0 else None


def _measured(mind: Path, prev: Path) -> bool:
    """Whether the previous record carries `review-minutes-actual:` — in the
    canonical working tree, or on Mind's local `origin/main` ref.

    PyAutoBrain#637, item 5: the gate read only the working tree, which no
    one pulls mid-shift. A check-in pushed from a linked worktree of the
    canonical checkout (`prompt_sync_push`, the one Mind writer) moves the
    local `origin/main` ref at once, whether or not the working tree is
    fast-forwarded after it, so the next tick counts it. Nothing is fetched:
    the watcher's network surface is unchanged."""
    if _has_minutes(prev.read_text(encoding="utf-8", errors="replace")):
        return True
    text = origin_text(mind, f"batches/{prev.name}")
    return bool(text) and _has_minutes(text)


def check(path: Path, mind: Path) -> dict:
    """Validate one brief. `errors` refuse it; `warnings` do not."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        rec = parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, BriefError) as e:
        return {"ok": False, "errors": [f"{path}: {e}"], "warnings": []}
    top, brief = rec["top"], rec["brief"]

    # The shift: the grant expires at review-at, so without it there is none.
    disp = _iso(top["dispatched"]["value"]) if "dispatched" in top else None
    if "dispatched" not in top:
        errors.append("dispatched: missing")
    elif disp is None:
        errors.append(f"dispatched: not an ISO timestamp ({top['dispatched']['value']!r})")
    if "review-at" not in top:
        errors.append("review-at: missing — a brief without it grants nothing "
                      "(AUTONOMY.md, \"What a batch launch is\")")
    else:
        at = _iso(top["review-at"]["value"])
        if at is None:
            errors.append(f"review-at: not an ISO timestamp ({top['review-at']['value']!r})")
        elif disp is not None and at <= disp:
            errors.append("review-at: not after dispatched:")

    if brief is None:
        errors.append("brief: missing — this is a batch record, not a shift brief")
        return {"ok": False, "errors": errors, "warnings": warnings}

    if not (brief.get("goals") and brief["goals"]["children"]):
        errors.append("brief.goals: missing or empty — name at least one goal")

    backlog = brief.get("backlog", {}).get("value", "")
    if backlog not in BACKLOG_POLICIES:
        errors.append(f"brief.backlog: {backlog or 'missing'!s} — one of "
                      + " | ".join(BACKLOG_POLICIES))
    scoped = scoped_of(brief)
    if backlog == "scoped" and not scoped:
        errors.append("brief.scoped: missing — `backlog: scoped` needs epics, "
                      "tags or tiers")
    for key in scoped:
        if key not in SCOPED_KEYS:
            errors.append(f"brief.scoped.{key}: unknown — one of "
                          + ", ".join(SCOPED_KEYS))
    bad_tiers = [t for t in scoped.get("tiers", []) if t not in CONSEQUENCE_TIERS]
    if bad_tiers:
        errors.append(f"brief.scoped.tiers: {', '.join(bad_tiers)} — tiers are "
                      + " | ".join(CONSEQUENCE_TIERS))

    for key in ("review-minutes", "merge-cap", "token-budget"):
        if key not in brief:
            errors.append(f"brief.{key}: missing")
        elif _nonneg_int(brief[key]["value"]) is None:
            errors.append(f"brief.{key}: not a whole number "
                          f"({brief[key]['value']!r})")

    for key in CAP_DEFAULTS:
        if key in brief and _nonneg_int(brief[key]["value"]) is None:
            errors.append(f"brief.{key}: not a whole number ({brief[key]['value']!r})")

    if "worker-mode" in brief and brief["worker-mode"]["value"] not in WORKER_MODES:
        errors.append(f"brief.worker-mode: {brief['worker-mode']['value']} — one of "
                      + ", ".join(WORKER_MODES)
                      + (" (bypassPermissions is never a worker mode)"
                         if brief["worker-mode"]["value"] == "bypassPermissions" else ""))
    for key in ("sandbox", "shadow"):
        if key in brief and brief[key]["value"].lower() not in ("yes", "no"):
            errors.append(f"brief.{key}: {brief[key]['value']} — yes or no")

    lanes = lanes_of(brief)
    if not lanes:
        errors.append("brief.lanes: missing — any subset of "
                      + " ".join(LANE_VALUES))
    bad = [ln for ln in lanes if ln not in LANE_VALUES]
    if bad:
        errors.append(f"brief.lanes: {', '.join(bad)} — not a lane; one of "
                      + " ".join(LANE_VALUES))
    if "ral" in lanes:
        allow = _keyed(brief["ral-allowance"]["children"]) if "ral-allowance" in brief else {}
        if not allow:
            errors.append("brief.ral-allowance: missing — `lanes:` includes ral")
        for key in ("packets", "partition", "cpu-hours"):
            if allow and key not in allow:
                errors.append(f"brief.ral-allowance.{key}: missing")
        for key in ("packets", "cpu-hours"):
            if key in allow and _nonneg_int(allow[key]["value"]) is None:
                errors.append(f"brief.ral-allowance.{key}: not a whole number")

    # Named tasks. An unresolved path warns rather than refuses: a brief kept
    # as an example outlives the prompts it names.
    tiers = []
    for t in tasks_of(brief):
        f = _resolve(mind, t)
        if f is None:
            warnings.append(f"brief.tasks: {t} resolves to no prompt in draft/ or active/")
        else:
            tiers.append(_tier(f, mind))
    cap = _nonneg_int(brief.get("merge-cap", {}).get("value", ""))
    if cap and tiers and all(t == "judge" for t in tiers) and backlog == "none":
        errors.append(f"brief.merge-cap: {cap} but every named task is judge and "
                      "backlog: none — nothing this shift may merge unattended; "
                      "set 0")

    # Calibration (batches/AGENTS.md): no new brief while the last record is
    # unmeasured. Only for a record that lives among the records.
    if path.parent.resolve() == (mind / "batches").resolve():
        prev = _previous_record(mind, path)
        if prev is not None and not _measured(mind, prev):
            errors.append(f"review-minutes-actual: missing on the previous "
                          f"record {prev.name} — measure it before a new brief")

    # The digest, once collect has appended one (phase 3d).
    import _digest  # noqa: E402 — deferred: _digest imports this module
    errors += _digest.validate(path.read_text(encoding="utf-8", errors="replace"))

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def launch_errors(top: dict, brief: dict | None) -> list[str]:
    """What only a launch needs (M3.6a, PyAutoBrain#659): `batch brief --check`
    adds these to `check`; the watcher does not. A live brief (not `shadow:
    yes`) needs its shift issue: the status comment, the steering commands and
    the digest all go there, and shift 2026-11-16-pm had none."""
    if brief is None or is_shadow(brief):
        return []
    issue = (top.get("issue") or {}).get("value", "").strip()
    if not issue:
        return ["issue: missing — a live brief needs its shift issue "
                "(batch brief --new creates it)"]
    if not ISSUE_RE.fullmatch(issue):
        return [f"issue: {issue!r} is not a GitHub issue URL — a live brief needs its "
                "shift issue (batch brief --new creates it)"]
    return []


# --- the organ rule for a named task (M3.6b) -------------------------------------

#: The shift's own code, per organ it runs on: its watcher and planner (Brain),
#: its one Mind writer and lifecycle (Mind) and its release path (all of Hands,
#: so the empty prefix). A named task that names a path here is refused at
#: `brief --check`: a shift never changes what runs it.
SELF_PATHS = {
    "PyAutoBrain": ("agents/conductors/batch/",),
    "PyAutoMind": ("scripts/", ".github/workflows/"),
    "PyAutoHands": ("",),
}
#: A backticked token with a `/` in it, read as a path (URLs excluded).
_PATH_RE = re.compile(r"`([^`\s]*/[^`\s]*)`")


def organ_findings(name: str, path: Path, mind: Path) -> tuple[list[str], list[str], list[str]]:
    """(errors, warnings, notes) of the organ rule for one named task.

    The organ rule was a dip rule only (`_batch.self_organ_why`); a named task
    is the human's pick, and in shift 2026-11-16-pm the human had to rule in
    chat that a renderer is not the watcher, writer or release path. This says
    it at launch instead: a task that targets an organ the shift runs on and
    names a path in that organ's own code is refused; one that names only
    other paths passes with a line saying so; one that names no path is a
    warning, because only the human can tell."""
    from _sizing import normalise_repo  # noqa: E402 — the faculty is on sys.path
    p = parse_prompt(path, mind)
    organs = {normalise_repo(o): o for o in SELF_ORGANS}
    declared = {normalise_repo(x) for x in [p.get("target") or "",
                                            *re.findall(r"(?m)^- (\S+)", _repos_block(p))]}
    hit = [organs[k] for k in organs if k in declared]
    if not hit:
        return [], [], []
    paths = sorted({m.rstrip(".,;:)").split(":")[0]
                    for m in _PATH_RE.findall(p.get("text") or "") if "://" not in m})
    if not paths:
        return [], [f"organ rule: {name} targets {', '.join(hit)} and names no path — "
                    "the human decides whether it touches the watcher, writer or "
                    "release path"], []
    own = []
    for rel in paths:
        head, _, rest = rel.partition("/")
        cands = [o for o in hit if normalise_repo(head) == normalise_repo(o)]
        rel_in, check = (rest, cands) if cands else (rel, hit)
        if any(rel_in.startswith(pre) for o in check for pre in SELF_PATHS[o]):
            own.append(rel)
    if own:
        return [f"organ rule: {name} names {own[0]} — the shift's own watcher, writer "
                "or release path; a shift never changes it (run it in chat)"], [], []
    return [], [], [f"organ rule: {name} targets {', '.join(hit)} but names only "
                     f"{', '.join(paths[:3])}" + (" …" if len(paths) > 3 else "")
                     + " — not the watcher, writer or release path; passes"]


def _repos_block(p: dict) -> str:
    m = re.search(r"^Repos:\n((?:- .+\n)+)", p.get("text") or "", re.M)
    return m.group(1) if m else ""


# --- scope ---------------------------------------------------------------------

def scope(records: list[dict], brief: dict) -> tuple[list[dict], list[tuple[str, str]], list[str]]:
    """Split survey records into what the brief admits and what it does not.

    Named tasks first (returned as the order the planner must honour), then
    the dip policy. Backlog the brief does not cover is never dipped.
    """
    named = tasks_of(brief)
    named_names = {Path(t).name for t in named}
    backlog = brief.get("backlog", {}).get("value", "none")
    scoped = scoped_of(brief)
    ex_paths, ex_keyed = excluded_of(brief)
    ex_names = {Path(p).name for p in ex_paths}
    lanes = set(lanes_of(brief)) or {"any"}
    # `/add`ed this shift (`effective`, #644): no `exclude:` rule holds it back.
    added = set(_csv(brief.get("added", {}).get("value", "")))

    kept, rejected = [], []
    for r in records:
        name = Path(r["path"]).name
        themes = set(r.get("themes") or [])
        if name not in added and (name in ex_names or r.get("epic") in ex_keyed.get("epics", [])
                                  or themes & set(ex_keyed.get("tags", []))):
            rejected.append((r["path"], "excluded by the brief"))
            continue
        if name not in named_names:
            if backlog == "none":
                rejected.append((r["path"], "outside the brief (backlog: none)"))
                continue
            if backlog == "scoped" and not _scoped_match(r, scoped):
                rejected.append((r["path"], "outside the brief's scoped backlog"))
                continue
        if (r.get("lane") or "any") not in lanes:
            rejected.append((r["path"], f"lane {r.get('lane')} not in the brief's lanes"))
            continue
        kept.append(r)
    return kept, rejected, named


def _scoped_match(record: dict, scoped: dict[str, list[str]]) -> str:
    """The `scoped:` rule a record matches, as the digest names it; "" if none."""
    if record.get("epic") in scoped.get("epics", []):
        return f"scoped epic {record['epic']}"
    tags = sorted(set(record.get("themes") or []) & set(scoped.get("tags", [])))
    if tags:
        return f"scoped tag {tags[0]}"
    if record.get("consequence") in scoped.get("tiers", []):
        return f"scoped tier {record['consequence']}"
    return ""


def pick_reason(record: dict, brief: dict) -> str:
    """Why the brief admits this record, then why it ranked where it did — the
    digest's one-line `why:`.

    Recorded at dispatch, when the record is in hand: by `review-at:` the
    prompt may have moved to `complete/` and its headers with it.
    """
    if Path(record["path"]).name in {Path(t).name for t in tasks_of(brief)}:
        return "named task"
    backlog = brief.get("backlog", {}).get("value", "none")
    if backlog == "fill-idle":
        rule = "backlog: fill-idle"
    elif backlog == "scoped":
        rule = _scoped_match(record, scoped_of(brief))
        if not rule:
            return "NOT RECORDED"
    else:
        return "NOT RECORDED"
    rank = rank_note(record)
    return f"{rule} · {rank}" if rank else rule


def rank_note(record: dict) -> str:
    """The planner's order, as it applied to this record (`_batch.plan`):
    queue.md position first; below the queue, priority, then cheapest review
    (M2.3, 2026-11-12), then the path — so a tie is alphabetical, and says so."""
    parts = []
    if record.get("queued"):
        parts.append(f"queue.md #{record['queue_rank'] + 1}")
    elif "queue_rank" in record:
        parts.append("not in queue.md")
        parts.append(f"priority {record.get('priority') or 'normal'}")
        if record.get("review_minutes") is not None:
            parts.append(f"~{record['review_minutes']} review-min")
    if record.get("epic"):
        phase = record.get("phase")
        parts.append(f"epic {record['epic']}" + (f" phase {phase:g}" if isinstance(phase, (int, float))
                                                 and phase != float("inf") else ""))
    return " · ".join(parts)
