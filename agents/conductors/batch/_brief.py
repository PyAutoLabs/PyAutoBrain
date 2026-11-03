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
CAP_DEFAULTS = {"max-workers": 2, "max-sessions": 6}
SCOPED_KEYS = ("epics", "tags", "tiers")

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
        if prev is not None:
            prev_top = parse(prev.read_text(encoding="utf-8", errors="replace"))["top"]
            if not prev_top.get("review-minutes-actual", {}).get("value"):
                errors.append(f"review-minutes-actual: missing on the previous "
                              f"record {prev.name} — measure it before a new brief")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


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

    kept, rejected = [], []
    for r in records:
        name = Path(r["path"]).name
        themes = set(r.get("themes") or [])
        if name in ex_names or r.get("epic") in ex_keyed.get("epics", []) \
                or themes & set(ex_keyed.get("tags", [])):
            rejected.append((r["path"], "excluded by the brief"))
            continue
        if name not in named_names:
            if backlog == "none":
                rejected.append((r["path"], "outside the brief (backlog: none)"))
                continue
            if backlog == "scoped" and not (
                    r.get("epic") in scoped.get("epics", [])
                    or themes & set(scoped.get("tags", []))
                    or r.get("consequence") in scoped.get("tiers", [])):
                rejected.append((r["path"], "outside the brief's scoped backlog"))
                continue
        if (r.get("lane") or "any") not in lanes:
            rejected.append((r["path"], f"lane {r.get('lane')} not in the brief's lanes"))
            continue
        kept.append(r)
    return kept, rejected, named
