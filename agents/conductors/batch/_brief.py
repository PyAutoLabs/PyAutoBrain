"""Shift briefs — parse and validate the `brief:` block of a batch record.

The schema is `PyAutoMind/batches/AGENTS.md` "Shift brief"; the doctrine that
makes a brief the launch act is `AUTONOMY.md` "Shift briefs and unattended
`glance`". This module only READS: `check` says whether a brief is
well-formed, and `scope` says which backlog records it admits. Nothing here
dispatches, merges or writes a file.

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
#: Optional usage caps and their defaults when a brief omits them.
CAP_DEFAULTS = {"max-workers": 4, "max-sessions": 8}
#: Permission modes a real worker may run in. `auto` is the default: a worker
#: that still needs a person shows `blocked` and is parked.
#: `bypassPermissions` is never a worker mode.
WORKER_MODES = ("auto", "dontAsk", "acceptEdits")
DEFAULT_WORKER_MODE = "auto"
SCOPED_KEYS = ("epics", "tags", "tiers", "sources")
#: `scoped: sources:` values. `maintenance` is a prompt the maintenance writer
#: generated (it carries a `Source-key:` header, Phase 14.2): a maintenance
#: brief's backlog dips stay within those (Phase 14.3).
SCOPED_SOURCES = ("maintenance",)
#: The `maintenance:` block of a maintenance brief (Phase 14.3,
#: PyAutoBrain#737): the board sources its tasks come from, how many it names
#: and the Consequence tiers it may name. `gate-open:` is the human's word that
#: the M3 gate is open, written only by `brief --new --maintenance --live
#: --gate-open`; a live maintenance brief without it is refused.
MAINTENANCE_SOURCES = ("census", "monitoring", "release", "hygiene", "timing")
MAINTENANCE_KEYS = ("sources", "cap", "tiers", "gate-open")
MAINTENANCE_DEFAULT_CAP = 5
#: Judge is nameable for a shadow shift; only glance ever merges unattended,
#: which the merge gates (not this list) enforce.
MAINTENANCE_DEFAULT_TIERS = ("glance", "judge")
#: The goal line that names a brief a maintenance shift (the digest reads it).
MAINTENANCE_GOAL_PREFIX = "maintenance:"
#: The gate a live maintenance shift waits on (human decision 1, 2026-11-27).
MAINTENANCE_GATE = "PyAutoBrain#574"
_SOURCE_KEY_HEADER_RE = re.compile(r"(?m)^Source-key:[ \t]*(\S.*?)\s*$")
#: `first:` values: `glance` sorts ready glance work first.
FIRST_VALUES = ("glance",)
#: The organs a shift runs on: its watcher and planner (Brain), its one Mind
#: writer (Mind) and its release path (Hands). A shift never changes them, so
#: the planner never dips a draft that targets one. A brief's named task is
#: the human's own pick and is not gated.
SELF_ORGANS = ("PyAutoBrain", "PyAutoMind", "PyAutoHands")
#: The one size `backlog: scoped` may dip beyond `queue.md`: small and
#: single-repo only.
SCOPED_REACH_DIFFICULTY = "small"
#: The late window: the watcher's digest and late sweep run from `review-at:`
#: to this long after it, and then it stops ticking the slot.
#: `batch watch --stream` ends at the same time.
LATE_WINDOW_S = 45 * 60
#: A shift issue: the brief's `issue:` value.
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


#: Tokens one worker session is assumed to need at least, for a session cap
#: derived from the budget: the cap is
#: `max(2 × max-workers, ceil(token-budget / SESSION_TOKEN_FLOOR))`, so the
#: token budget binds before the session count does.
SESSION_TOKEN_FLOOR = 150_000


def cap_of(brief: dict, key: str) -> int:
    """A usage cap from the brief, or its default when the brief omits it.
    With no `max-sessions:`, a brief with a `token-budget:` gets a cap derived
    from it and `max-workers:`, so a fixed session count never stops new
    starts while most of the budget is unspent."""
    value = _nonneg_int(brief.get(key, {}).get("value", ""))
    if value is not None:
        return value
    if key == "max-sessions":
        budget = _nonneg_int(brief.get("token-budget", {}).get("value", ""))
        if budget:
            return max(2 * cap_of(brief, "max-workers"), -(-budget // SESSION_TOKEN_FLOOR))
    return CAP_DEFAULTS[key]


def cap_source(brief: dict, key: str) -> str:
    """Where `cap_of` took a cap from: `brief`, `from token-budget` or `default`."""
    if _nonneg_int(brief.get(key, {}).get("value", "")) is not None:
        return "brief"
    if key == "max-sessions" and _nonneg_int(brief.get("token-budget", {}).get("value", "")):
        return "from token-budget"
    return "default"


#: The caps a `/cap` steering command may lower for one shift.
CAP_KEYS = ("merge-cap", "max-workers", "max-sessions", "token-budget")


def effective(brief: dict, counters: dict | None) -> dict:
    """The brief as this shift now runs it: a copy with each `/cap` override's
    value (`counters["caps"]`) swapped in, and each task the human `/add`ed
    (`counters["added"]`) appended to `tasks:` and taken out of `exclude:` —
    the human's newer word, as a brief that names a task again. The brief
    file is never changed; with nothing steered it is `brief` itself."""
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


def backend_of(brief: dict) -> str:
    return brief.get("worker-backend", {}).get("value", "claude")


def backend_errors(brief: dict) -> list[str]:
    backend = backend_of(brief)
    if backend not in {"claude", "codex"}:
        return ["brief.worker-backend: must be claude or codex"]
    errors = []
    if backend == "codex":
        model = brief.get("codex-model", {}).get("value", "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", model):
            errors.append("brief.codex-model: explicit Codex model id required")
        if worker_mode_of(brief) not in {"auto", "dontAsk"}:
            errors.append("brief.worker-mode: Codex supports auto or dontAsk; no acceptEdits equivalent")
        effort = brief.get("codex-effort", {}).get("value", "medium")
        if effort not in {"low", "medium", "high", "xhigh"}:
            errors.append("brief.codex-effort: must be low, medium, high or xhigh")
    elif any(k.startswith("codex-") for k in brief):
        errors.append("brief.worker-backend: codex settings require worker-backend: codex")
    return errors


def worker_mode_of(brief: dict) -> str:
    return brief.get("worker-mode", {}).get("value") or DEFAULT_WORKER_MODE


def maintenance_of(brief: dict) -> dict | None:
    """The `maintenance:` block as {sources, cap, tiers, gate_open}, with the
    defaults for what it omits; None when the brief has no such block."""
    node = (brief or {}).get("maintenance")
    if node is None:
        return None
    kv = _keyed(node["children"])
    cap = _nonneg_int(kv.get("cap", {}).get("value", ""))
    return {"sources": _csv(kv["sources"]["value"]) if "sources" in kv
            else list(MAINTENANCE_SOURCES),
            "cap": MAINTENANCE_DEFAULT_CAP if cap is None else cap,
            "tiers": _csv(kv["tiers"]["value"]) if "tiers" in kv
            else list(MAINTENANCE_DEFAULT_TIERS),
            "gate_open": kv.get("gate-open", {}).get("value", "")}


#: Why a generated maintenance prompt is kept out of a shift without the gate:
#: `check`, `scope()` and the watcher's `/add` say it in the same words.
M3_GATE_REASON = (f"a generated maintenance prompt (`Source-key:`) — runs live only "
                  f"behind the M3 gate ({MAINTENANCE_GATE}): a `maintenance:` block "
                  "with `gate-open:`")


def gate_open(brief: dict) -> bool:
    """Whether the brief carries the human's word that the M3 gate is open: a
    `maintenance:` block with `gate-open:`. Without it no generated
    maintenance prompt runs live, named or dipped."""
    m = maintenance_of(brief)
    return bool(m and m["gate_open"])


def generated_gate_errors(brief: dict, mind: Path) -> list[str]:
    """The M3 gate on the tasks, not only on the block: a live (non-shadow)
    brief without `gate-open:` may neither name a generated prompt (one with
    a `Source-key:`) nor scope or exclude by `sources: maintenance`."""
    if is_shadow(brief) or gate_open(brief):
        return []
    errors = []
    why = M3_GATE_REASON + ", or `shadow: yes`"
    for t in tasks_of(brief):
        f = _resolve(mind, t)
        if f is not None and source_key(f.read_text(encoding="utf-8", errors="replace")):
            errors.append(f"brief.tasks: {t} is a generated prompt (`Source-key:`) — {why}")
    _ex_paths, ex_keyed = excluded_of(brief)
    for where, vals in (("scoped", scoped_of(brief).get("sources", [])),
                        ("exclude", ex_keyed.get("sources", []))):
        if vals:
            errors.append(f"brief.{where}.sources: {', '.join(vals)} — {why}")
    return errors


def maintenance_goal(brief: dict) -> str:
    """The brief's maintenance goal line (`maintenance: …`), or ""."""
    node = (brief or {}).get("goals")
    for c in node["children"] if node else ():
        text = re.sub(r"^\d+\.\s*", "", c["text"])
        if text.lower().startswith(MAINTENANCE_GOAL_PREFIX):
            return text
    return ""


def source_key(text: str) -> str:
    """A prompt's `Source-key:` header (the maintenance writer's), or ""."""
    m = _SOURCE_KEY_HEADER_RE.search(text or "")
    return m.group(1) if m else ""


def maintenance_errors(brief: dict) -> list[str]:
    """`brief --check`'s refusals for a `maintenance:` block (none without one)."""
    node = brief.get("maintenance")
    if node is None:
        return []
    errors = []
    kv = _keyed(node["children"])
    for key in kv:
        if key not in MAINTENANCE_KEYS:
            errors.append(f"brief.maintenance.{key}: unknown — one of "
                          + ", ".join(MAINTENANCE_KEYS))
    m = maintenance_of(brief)
    bad = [x for x in m["sources"] if x not in MAINTENANCE_SOURCES]
    if bad or not m["sources"]:
        errors.append(f"brief.maintenance.sources: {', '.join(bad) or 'empty'} — a "
                      "subset of " + ", ".join(MAINTENANCE_SOURCES))
    if "cap" in kv and _nonneg_int(kv["cap"]["value"]) is None:
        errors.append(f"brief.maintenance.cap: not a whole number ({kv['cap']['value']!r})")
    bad = [t for t in m["tiers"] if t not in CONSEQUENCE_TIERS]
    if bad or not m["tiers"]:
        errors.append(f"brief.maintenance.tiers: {', '.join(bad) or 'empty'} — tiers are "
                      + " | ".join(CONSEQUENCE_TIERS))
    if not maintenance_goal(brief):
        errors.append(f"brief.goals: a maintenance brief names its goal "
                      f"`{MAINTENANCE_GOAL_PREFIX} board findings …` (the digest reads it)")
    if not is_shadow(brief) and not m["gate_open"]:
        errors.append(f"brief.maintenance.gate-open: missing on a live maintenance brief — "
                      f"the live run waits for the M3 gate ({MAINTENANCE_GATE}); set "
                      "`shadow: yes`, or re-make it with `brief --new --maintenance --live "
                      "--gate-open` once the human has opened the gate")
    return errors


def maintenance_line(brief: dict) -> str:
    """The digest's line naming a maintenance shift, or "" for any other."""
    m = maintenance_of(brief)
    if m is None:
        return ""
    goal = maintenance_goal(brief) or MAINTENANCE_GOAL_PREFIX + " board findings"
    return (f"Maintenance shift — goal: {goal} (cap {m['cap']}; tiers "
            f"{', '.join(m['tiers'])})")


def is_shadow(brief: dict) -> bool:
    """A shadow shift plans and records proposals but spawns nothing."""
    return brief.get("shadow", {}).get("value", "").lower() == "yes"


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

    No one pulls the working tree mid-shift, but a check-in pushed from a
    linked worktree of the canonical checkout moves the local `origin/main`
    ref at once, so the next tick counts it. Nothing is fetched: the
    watcher's network surface is unchanged."""
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
                      "tags, tiers or sources")
    for key in scoped:
        if key not in SCOPED_KEYS:
            errors.append(f"brief.scoped.{key}: unknown — one of "
                          + ", ".join(SCOPED_KEYS))
    bad_tiers = [t for t in scoped.get("tiers", []) if t not in CONSEQUENCE_TIERS]
    if bad_tiers:
        errors.append(f"brief.scoped.tiers: {', '.join(bad_tiers)} — tiers are "
                      + " | ".join(CONSEQUENCE_TIERS))
    _ex_paths, ex_keyed = excluded_of(brief)
    for where, vals in (("scoped", scoped.get("sources", [])),
                        ("exclude", ex_keyed.get("sources", []))):
        bad_src = [x for x in vals if x not in SCOPED_SOURCES]
        if bad_src:
            errors.append(f"brief.{where}.sources: {', '.join(bad_src)} — one of "
                          + ", ".join(SCOPED_SOURCES))
    errors.extend(maintenance_errors(brief))
    errors.extend(generated_gate_errors(brief, mind))

    for key in ("review-minutes", "merge-cap", "token-budget"):
        if key not in brief:
            errors.append(f"brief.{key}: missing")
        elif _nonneg_int(brief[key]["value"]) is None:
            errors.append(f"brief.{key}: not a whole number "
                          f"({brief[key]['value']!r})")

    for key in CAP_DEFAULTS:
        if key in brief and _nonneg_int(brief[key]["value"]) is None:
            errors.append(f"brief.{key}: not a whole number ({brief[key]['value']!r})")

    errors.extend(backend_errors(brief))
    if "worker-mode" in brief and brief["worker-mode"]["value"] not in WORKER_MODES:
        errors.append(f"brief.worker-mode: {brief['worker-mode']['value']} — one of "
                      + ", ".join(WORKER_MODES)
                      + (" (bypassPermissions is never a worker mode)"
                         if brief["worker-mode"]["value"] == "bypassPermissions" else ""))
    # `first: glance`: ready glance work starts before named judge tasks.
    if "first" in brief and brief["first"]["value"] not in FIRST_VALUES:
        errors.append(f"brief.first: {brief['first']['value'] or 'empty'} — only "
                      + " | ".join(FIRST_VALUES) + " (or leave the line out)")
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
    maint = "maintenance" in brief
    for t in tasks_of(brief):
        f = _resolve(mind, t)
        if f is None:
            warnings.append(f"brief.tasks: {t} resolves to no prompt in draft/ or active/")
        else:
            tiers.append(_tier(f, mind))
            if maint and not source_key(f.read_text(encoding="utf-8", errors="replace")):
                warnings.append(f"brief.tasks: {t} has no `Source-key:` — a maintenance "
                                "brief names only generated prompts, none by hand")
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

    # The digest, once collect has appended one.
    import _digest  # noqa: E402 — deferred: _digest imports this module
    errors += _digest.validate(path.read_text(encoding="utf-8", errors="replace"))

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def launch_errors(top: dict, brief: dict | None) -> list[str]:
    """What only a launch needs: `batch brief --check` adds these to `check`;
    the watcher does not. A live brief (not `shadow: yes`) needs its shift
    issue: the status comment, the steering commands and the digest all go
    there."""
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


# --- the organ rule for a named task ---------------------------------------------

#: The shift's own code, per organ it runs on: its watcher and planner (Brain),
#: its one Mind writer and lifecycle (Mind) and its release path (all of Hands,
#: so the empty prefix). A named task that names a path here is refused at
#: `brief --check`: a shift never changes what runs it.
SELF_PATHS = {
    "PyAutoBrain": ("agents/conductors/batch/",),
    "PyAutoMind": ("scripts/", ".github/workflows/"),
    "PyAutoHands": ("",),
}
#: Self prefixes no other repo has: unprefixed, they still name that organ's
#: code (`.github/workflows/` and `scripts/` are every repo's).
DISTINCT_PREFIXES = ("agents/conductors/batch/",)
_SELF_PREFIXES = {pre.lower() for pres in SELF_PATHS.values() for pre in pres if pre}
#: Path candidates in a prompt: any backticked token, and an unbackticked
#: token that looks like a file path (segments and a lettered extension).
_TICKED_RE = re.compile(r"`([^`\s]+)`")
_BARE_PATH_RE = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)+[\w.-]+\.[A-Za-z]\w*)")
#: Mind's own records: a prompt that cites another prompt or record says
#: nothing about which code it changes, so such a path is neutral.
MIND_DOCS = ("draft/", "active/", "complete/", "batches/")


def _path_parts(token: str) -> tuple[list[str], bool] | None:
    """(lower-cased path segments, glob) of a token, or None when it is not a
    file path: a URL, `Repo#N`, an `action@ref`, a slash command (`/prm`), a
    bare `/`, or a two-segment token with no extension (`origin/main`). A
    `:line` suffix and a leading `@` or `./` are dropped; a glob keeps the
    segments before its first `*`."""
    t = token.strip().rstrip(".,;)").removeprefix("@")
    if "://" in t or "#" in t or "@" in t:
        return None
    t = re.sub(r":\d[\d,-]*$", "", t).removeprefix("./")
    glob = "*" in t
    if glob:
        t = t.split("*", 1)[0].rsplit("/", 1)[0] + "/"
    parts = [x.lower() for x in t.split("/") if x and x not in (".", "..")]
    # A self prefix written without its slash (`.github/workflows`, `scripts`)
    # is still that directory.
    if "/".join(parts) + "/" in _SELF_PREFIXES or "/".join(parts[1:]) + "/" in _SELF_PREFIXES:
        t = t.rstrip("/") + "/"
    is_dir = t.endswith("/")
    if not parts or (len(parts) == 1 and not is_dir):
        return None
    if len(parts) == 2 and not is_dir and not glob and "." not in parts[-1]:
        return None
    return parts + ([""] if is_dir else []), glob


def _own_files(mind: Path) -> dict[str, set[str]]:
    """File names of the shift's own code, per organ, for a prompt that names
    one bare (`_orchestrator.py`, `worker_template.md`): this conductor's
    directory (bar its AGENTS.md) and Mind's `scripts/`."""
    def names(d: Path, keep) -> set[str]:
        return {f.name for f in d.iterdir() if f.is_file() and keep(f)} if d.is_dir() else set()
    return {"PyAutoBrain": names(Path(__file__).parent, lambda f: f.name != "AGENTS.md"),
            "PyAutoMind": names(Path(mind) / "scripts", lambda f: f.suffix in (".py", ".sh"))}


def _classify(parts: list[str], hit: list[str], only_self: bool, organs: dict,
              known, declared: set[str]) -> str:
    """"own" | "maybe" | "other" | "neutral" for one path's segments."""
    from _sizing import normalise_repo  # noqa: E402
    # `parts` ends in "" for a directory token: its last name may then be a
    # repo (`PyAutoBrain/`), which the attribution below reads.
    rel = "/".join(x for x in parts if x) + "/"
    if rel.startswith(MIND_DOCS):
        return "neutral"          # a Mind record, wherever its folder is named
    # An explicit repo segment (never the file name itself) attributes the path.
    at = next((i for i, seg in enumerate(parts[:-1])
               if normalise_repo(seg) in organs or normalise_repo(seg) in known), None)
    if at is not None:
        organ = organs.get(normalise_repo(parts[at]))
        rest = "/".join(x for x in parts[at + 1:] if x) + "/"
        if rest == "/":
            return "neutral"                       # the repo itself, not a path in it
        if organ and any(rest.startswith(pre.lower()) for pre in SELF_PATHS[organ]):
            return "own"
        if organ == "PyAutoMind" and rest.startswith(MIND_DOCS):
            return "neutral"
        # A path in a repo the task declares shows what it changes; one in a
        # repo it does not declare shows nothing either way.
        return "other" if normalise_repo(parts[at]) in declared else "neutral"
    # A multi-segment self prefix found anywhere (a worktree or absolute path).
    # Inside a longer path only (a worktree or an absolute path), and only
    # for an organ this task targets: at the start it is plainly unprefixed,
    # which `cands` judges below (another repo's `.github/workflows/` is not
    # Mind's).
    # A prefix only that organ has (`DISTINCT_PREFIXES`) is its code at the
    # start of a path too, whatever else the task declares.
    deep = any(rel.startswith(pre) or f"/{pre}" in rel[1:] for pre in DISTINCT_PREFIXES) \
        or any(f"/{pre.lower()}" in rel[1:]
               for o in hit for pre in SELF_PATHS[o] if pre.count("/") > 1)
    cands = [o for o in hit if any(rel.startswith(pre.lower()) for pre in SELF_PATHS[o])]
    if deep or (cands and only_self):
        return "own"
    return "maybe" if cands else "other"


def organ_findings(name: str, path: Path, mind: Path) -> tuple[list[str], list[str], list[str]]:
    """(errors, warnings, notes) of the organ rule for one named task.

    A named task is the human's pick, so the dip rule (`_batch.self_organ_why`)
    does not gate it; this says at launch whether it would change what runs
    the shift, for a task that targets an organ the shift runs on:

    - refused when it names the shift's own code: a path under an organ's
      `SELF_PATHS` with that organ written in it, under a multi-segment self
      prefix anywhere in the path, unprefixed when the task declares only
      self organs, or a bare file name of that code;
    - a warning when an unprefixed path could be a self organ's own code but
      the task also declares another repo (the human's call), or when it names
      no path that shows what it changes;
    - otherwise passed, with a line saying so. A path in an undeclared repo,
      a repo name alone and a Mind record (`MIND_DOCS`) show nothing either way."""
    from _sizing import KNOWN_REPOS, normalise_repo  # noqa: E402 — on sys.path
    p = parse_prompt(path, mind)
    text = p.get("text") or ""
    organs = {normalise_repo(o): o for o in SELF_ORGANS}
    # The `Target:` header (every repo it names), else `parse_prompt`'s
    # target (the draft's folder); then the `Repos:` block.
    head = re.search(r"(?m)^Target:[ \t]*(.+)$", text)
    targets = re.findall(r"[\w.-]+", head.group(1)) if head else [p.get("target") or ""]
    declared = {normalise_repo(x) for x in [*targets,
                                            *re.findall(r"(?m)^- (\S+)", _repos_block(p))] if x}
    hit = [organs[k] for k in organs if k in declared]
    if not hit:
        return [], [], []
    only_self = declared <= set(organs)
    own_files = _own_files(mind)
    bare_names = {n for o in hit for n in own_files.get(o, ())}
    own, maybe, paths = [], [], []
    for n in sorted(bare_names):
        if re.search(rf"(?<![\w/.-]){re.escape(n)}(?![\w-])", text):
            own.append(n)
    for tok in dict.fromkeys(_TICKED_RE.findall(text) + _BARE_PATH_RE.findall(text)):
        got = _path_parts(tok)
        if got is None:
            continue
        kind = _classify(got[0], hit, only_self, organs, KNOWN_REPOS, declared)
        rel = "/".join(x for x in got[0] if x)
        if kind == "own":
            own.append(rel)
        elif kind == "maybe":
            maybe.append(rel)
        elif kind == "other" and not got[1]:
            paths.append(rel)
    if own:
        return [f"organ rule: {name} names {own[0]} — the shift's own watcher, writer "
                "or release path; a shift never changes it (run it in chat)"], [], []
    if maybe:
        return [], [f"organ rule: {name} names {maybe[0]}, which may be "
                    f"{'/'.join(hit)} code the shift runs on, and declares other repos "
                    "too — the human decides"], []
    if not paths:
        return [], [f"organ rule: {name} targets {', '.join(hit)} and names no path that "
                    "shows what it changes — the human decides whether it touches the "
                    "watcher, writer or release path"], []
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
    # `/add`ed this shift (`effective`): no `exclude:` rule holds it back.
    added = set(_csv(brief.get("added", {}).get("value", "")))
    # The M3 gate on the backlog: without `gate-open:` no generated
    # maintenance prompt is ever dipped, whatever the dip policy.
    gated = not gate_open(brief)
    shadow = is_shadow(brief)

    kept, rejected = [], []
    for r in records:
        name = Path(r["path"]).name
        themes = set(r.get("themes") or [])
        if name not in added and (name in ex_names or r.get("epic") in ex_keyed.get("epics", [])
                                  or themes & set(ex_keyed.get("tags", []))
                                  or _source_match(r, ex_keyed.get("sources", []))):
            rejected.append((r["path"], "excluded by the brief"))
            continue
        # The M3 gate before every exemption: a generated prompt runs live
        # only behind `gate-open:` — named, resumed after an answer, `/add`ed
        # or dipped alike. A shadow brief's named tasks are only proposals.
        if gated and r.get("source_key") \
                and not (shadow and name in named_names):
            rejected.append((r["path"], M3_GATE_REASON))
            continue
        # A task an answer released (the inbox) is the human's word, as
        # naming it would be: no dip policy keeps it out.
        if name not in named_names and not r.get("resume"):
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


def _source_match(record: dict, sources: list[str]) -> str:
    """The `sources:` value a record carries, or "": `maintenance` is a
    prompt with a `Source-key:` header (survey's `source_key`)."""
    if "maintenance" in sources and record.get("source_key"):
        return "maintenance"
    return ""


def _scoped_match(record: dict, scoped: dict[str, list[str]]) -> str:
    """The `scoped:` rule a record matches, as the digest names it; "" if none.

    `sources:` narrows the others: with it, a record must carry one of those
    sources, AND match an `epics:`/`tags:`/`tiers:` rule when any is given."""
    sources = scoped.get("sources", [])
    if sources:
        src = _source_match(record, sources)
        if not src:
            return ""
        rest = {k: v for k, v in scoped.items() if k != "sources" and v}
        if not rest:
            return f"scoped source {src}"
        rule = _scoped_match(record, rest)
        return f"{rule} · source {src}" if rule else ""
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
    queue.md position first; below the queue, priority, then cheapest review,
    then the path — so a tie is alphabetical, and says so."""
    parts = []
    if record.get("queued"):
        parts.append(f"queue.md #{record['queue_rank'] + 1}"
                     + (f" via epic {record['queued_via']}" if record.get("queued_via") else ""))
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
