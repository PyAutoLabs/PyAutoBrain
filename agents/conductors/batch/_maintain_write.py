"""The maintenance prompt writer — Phase 14.2 (PyAutoBrain#733).

Each `_maintain.Finding` (14.1) becomes a sized, tiered draft prompt that no
human writes: `draft/maintenance/<target>/maint_<slug(key)>.md`, with a
`Source-key: <key>` header and a `<!-- maint-key: <key> -->` mark, the
finding's evidence, a re-check-first step and the tier-raise rule.

It is the ONE filing path (human decision 3): `batch maintain --file` calls it
for every source, and the keep-Heart-green lane's `file`/`pick` modes call it
for the release source.

- **Read gating.** Nothing is filed from a source whose read is not `ok`, or
  is `stale` or `partial`, nor from a finding flagged `stale`; each is listed
  as skipped with its reason. Keys are cleared only for a source whose read
  is `ok`, not stale and not partial.
- **Classify.** Intake `analyse()` (never writes) gives the work type, target
  and lane; a lane refusal is a skip, never a filing. Sizing
  (`parse_prompt`, `effective_difficulty`, `effective_unattended`,
  `effective_review_minutes`) fills Difficulty, Unattended and
  Review-minutes. Consequence is the finding's tier floor (decision 2); a
  `judge` finding is always `Unattended: never` — sizing's
  `estimate_unattended` reads size, never consequence, so it would grade
  most of these `ready`.
- **Dedupe.** The key mark, the `Source-key:` header, `_green`'s legacy
  `<!-- heart-key: … -->` mark or a mention in `draft/`, `active/` or
  `queue.md`, or a state row that already filed it. At most `cap` new files
  per run.
- **State.** `maintain.json` beside the old `heart_green.json` (whose rows
  are migrated once): first_seen / last_seen / filed / filed_at per key.
- **Write guard.** Only into a Mind that is a linked worktree or not a git
  checkout (`_mind_guard`); never the shared canonical checkout. Every write
  is a NEW file; no existing prompt is edited.

Stdlib only; it reads no network (the loaders in `_maintain` do that) and
spawns only `git rev-parse` (the guard).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import sys
from pathlib import Path

import _green
import _maintain
from _mind_guard import in_git_checkout, is_linked_worktree
from _sizing import (  # noqa: E402 — the caller puts the faculty on sys.path
    effective_difficulty, effective_review_minutes, effective_unattended,
    normalise_repo, parse_prompt,
)

BRAIN = Path(__file__).resolve().parents[3]
STATE_NAME = _green.STATE_NAME           # maintain.json
LEGACY_STATE_NAME = _green.LEGACY_STATE_NAME  # heart_green.json, migrated once
DEFAULT_CAP = 3
KEY_MARK = "<!-- maint-key: {} -->"
WORK_TYPE = "maintenance"
_SOURCE_KEY_RX = re.compile(r"^Source-key:\s*(.+?)\s*$", re.M)

MAIN_CHECKOUT_HOLD = (
    "{} is a main git checkout, which may be the shared canonical Mind — the "
    "maintenance writer files only into a linked worktree (`git -C <mind> "
    "worktree add --detach <dir> origin/main`, then pass --mind <dir>) or a "
    "directory that is not a git checkout")

RECHECK = {
    "census": ("re-read the no-run census (`batch maintain --dry-run --sources census`) "
               "and the repo's `no_run.yaml`: if the entry is gone, close this draft as "
               "already fixed and stop."),
    "monitoring": ("re-read the Heart board (`batch maintain --dry-run --sources "
                   "monitoring`): if the key is absent or green, close this draft as "
                   "already fixed and stop."),
    "release": ("re-read Heart (`bin/heart_feed.py`, or `pyauto-heart readiness "
                "--json`): if the reason below is gone, close this draft as already "
                "green and stop."),
}


# --- intake (loaded on first use: it imports the dashboard stack) -------------

def _intake():
    if "_intake" not in sys.modules:
        d = str(BRAIN / "agents" / "conductors" / "intake")
        if d not in sys.path:
            sys.path.append(d)
    import _intake  # noqa: E402
    return _intake


# --- guard, state, marks ------------------------------------------------------

def write_hold(mind: Path) -> str:
    """Why the writer may not write into `mind`, or "" (linked worktree, or
    not a git checkout)."""
    mind = Path(mind)
    if not mind.is_dir():
        return f"{mind} is not a directory"
    if in_git_checkout(mind) and not is_linked_worktree(mind):
        return MAIN_CHECKOUT_HOLD.format(mind)
    return ""


def load_state(path: Path | None) -> dict:
    """`maintain.json`, migrating `heart_green.json`'s rows (as `release`
    keys) the first time — once, so a key cleared since never comes back."""
    try:
        data = json.loads(path.read_text()) if path else {}
    except (OSError, ValueError):
        data = {}
    state = data if isinstance(data.get("keys"), dict) else {"version": 1, "keys": {}}
    if path and not state.get("migrated"):
        legacy = path.parent / LEGACY_STATE_NAME
        try:
            old = json.loads(legacy.read_text()).get("reasons") or {}
        except (OSError, ValueError, AttributeError):
            old = {}
        for k, row in old.items():
            if isinstance(row, dict):
                state["keys"].setdefault(_maintain._norm_ci(k), dict(row, source="release"))
        state["migrated"] = LEGACY_STATE_NAME
    return state


def save_state(state: dict, path: Path | None) -> None:
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")


def key_marked(text: str, key: str) -> bool:
    """The writer's mark, a `Source-key:` header or `_green`'s legacy mark."""
    return (KEY_MARK.format(key) in text or _green.KEY_MARK.format(key) in text
            or key in _SOURCE_KEY_RX.findall(text))


def corpus(mind: Path) -> tuple[dict, str]:
    out = {}
    for sub in ("draft", "active"):
        for f in sorted((mind / sub).glob("**/*.md")):
            out[f.relative_to(mind).as_posix()] = f.read_text(encoding="utf-8",
                                                              errors="replace")
    try:
        queue = (mind / "queue.md").read_text(encoding="utf-8")
    except OSError:
        queue = ""
    return out, queue


def match(key: str, needles, docs: dict, queue: str) -> tuple[str, str]:
    """(how, path): `exact` (a key mark), `mentions` (a needle in a prompt),
    `queued` (the key or a needle in queue.md), or ("", "")."""
    for path, text in docs.items():
        if key_marked(text, key):
            return "exact", path
    for path, text in docs.items():
        if any(n and n in text for n in needles):
            return "mentions", path
    if any(n and n in queue for n in [key, *needles]):
        return "queued", "queue.md"
    return "", ""


def unusable(read: dict | None) -> str:
    """Why a source's read may not file (or clear), or ""."""
    if not read:
        return "source not read this run"
    if not read.get("ok"):
        return f"source read failed ({read.get('why') or read.get('status') or 'no data'})"
    if read.get("partial"):
        return f"partial read ({read.get('why') or 'incomplete'}) — never filed or cleared"
    if read.get("stale"):
        return "stale read (over the 6 h rule, or a stale verdict) — never filed or cleared"
    return ""


# --- the prompt -----------------------------------------------------------------

def slug(key: str) -> str:
    return _green._slugify(key) or "finding"


def _surface_rule(f) -> str:
    repo = f.repo or "the repo"
    if f.source == "census":
        surface = f"`no_run.yaml` in {repo}"
        beyond = "the script itself, a library, a config or a workflow"
    else:
        surface = (", ".join(f"`{p}`" for p in f.paths) + f" in {repo}") if f.paths \
            else "the failing check named above"
        beyond = "any other file or repo"
    return (f"**Tier rule (Phase 14.1).** `Consequence: {f.tier_floor}` is this finding's "
            f"floor and holds only while the fix touches nothing beyond its own surface. "
            f"If your diff touches anything other than {surface} ({beyond}), raise "
            "`Consequence:` to `judge` before shipping and say why in the PR; never "
            "lower it.")


def _priority(f) -> str:
    ev = f.evidence or {}
    return "high" if "red" in (ev.get("severity"), ev.get("status")) else "normal"


def draft_text(f, read: dict, today: str, *, target: str, lane: str,
               difficulty: str, unattended: str, review_minutes) -> str:
    ev = f.evidence or {}
    lead = "Heart green" if f.source == "release" else "Maintenance"
    title = f"{lead}: {(ev.get('text') or f.summary)[:90]}"
    head = [f"# {title}", "", f"Type: {WORK_TYPE}", f"Target: {target}"]
    head += ["Repos:", f"- {f.repo}"] if f.repo else []
    head += [f"Difficulty: {difficulty}", "Autonomy: supervised",
             f"Priority: {_priority(f)}", "Status: draft", f"Filed: {today}",
             f"Consequence: {f.tier_floor}", f"Witness: {f.witness}",
             f"Review-minutes: {review_minutes}", f"Lane: {lane}",
             f"Unattended: {unattended}", f"Source-key: {f.key}"]
    when = read.get("age_hours")
    read_line = (f"Filed from the `{f.source}` source ({read.get('source') or '?'}, "
                 + ("age unknown" if when is None else f"{when:.1f} h old") + ").")
    body = [f"**Re-check first.** {read_line} Before any work, "
            + RECHECK.get(f.source, "re-read the source; if the finding is gone, stop."),
            "", f"Finding (`{f.source}`, key `{f.key}`):", f"> {f.summary}", ""]
    if f.source == "release":
        body += [f"Heart reason ({ev.get('severity')}, verbatim):", f"> {ev.get('text')}",
                 "", f"Rule `{ev.get('rule')}` → fixable-dev: {ev.get('action')}.", ""]
    body += ["Evidence:", "```json",
             json.dumps(ev, indent=1, sort_keys=True, default=str)[:3000], "```", ""]
    if f.paths:
        body += ["Paths: " + ", ".join(f"`{p}`" for p in f.paths), ""]
    body += [_surface_rule(f), "",
             "Never: release, rehearse, dispatch a release or build workflow, force, or "
             "add a quarantine entry. A fix in a repo whose `main` CI is red needs the "
             "human's corrective exception to ship (AUTONOMY.md).", "",
             KEY_MARK.format(f.key),
             f"<!-- filed {today} by the maintenance writer (PyAutoBrain#733) -->"]
    return "\n".join(head) + "\n\n" + "\n".join(body) + "\n"


def classify(f, read: dict, mind: Path, today: str) -> dict:
    """Intake + sizing for one finding: {rel, text, target, lane, difficulty,
    unattended, refusal}. Never writes."""
    target0 = normalise_repo(f.repo) if f.repo else "workspaces"
    probe = draft_text(f, read, today, target=target0, lane=f.lane or "any",
                       difficulty="medium", unattended="never", review_minutes=10)
    # Intake reads the probe with no Lane/Difficulty/Unattended of its own: the
    # finding's lane is the explicit one, the rest are sizing's.
    probe_in = re.sub(r"^(Lane|Difficulty|Unattended|Review-minutes):.*\n", "", probe,
                      flags=re.M)
    dec = _intake().analyse(probe_in, f"maintain:{f.key}", lane=f.lane or None)
    if dec.get("lane_refusal"):
        return {"refusal": f"intake lane refusal: {dec['lane_refusal'][:120]}"}
    work_type = dec["work_type"] if dec.get("classification_confidence") != "low" \
        else WORK_TYPE
    target = dec["target"] if dec.get("target_source") == "declared" else target0
    lane = dec["lane"]
    rel = f"draft/{work_type}/{target}/maint_{slug(f.key)}.md"
    if (mind / rel).exists():
        rel = rel[:-3] + "_" + hashlib.sha1(f.key.encode()).hexdigest()[:8] + ".md"
    text = draft_text(f, read, today, target=target, lane=lane, difficulty="medium",
                      unattended="never", review_minutes=10)
    p = parse_prompt(mind / rel, mind, text=text)
    p.update(declared_difficulty=None, declared_unattended=None,
             declared_review_minutes=None)
    level, _score, factors, derived = effective_difficulty(p)
    grade = effective_unattended(p, level, factors, derived)[0]
    if f.tier_floor == "judge":
        grade = "never"  # explicit: sizing never raises a judge finding to ready
    minutes = effective_review_minutes(p, f.tier_floor, level)[0]
    text = draft_text(f, read, today, target=target, lane=lane, difficulty=level,
                      unattended=grade, review_minutes=minutes)
    return {"rel": rel, "text": text, "target": target, "lane": lane,
            "work_type": work_type, "difficulty": level, "unattended": grade,
            "refusal": ""}


# --- the writer -----------------------------------------------------------------

def file_findings(findings, reads: dict, mind: Path, *, cap: int = DEFAULT_CAP,
                  state_path: Path | None = None, now=None, guard: bool = True,
                  only=None, needles: dict | None = None) -> dict:
    """File at most `cap` new prompts for `findings` (every finding the reads
    listed). `reads` maps a source name to its read ({ok, stale, partial, …}).

    `only` (keys) limits which findings may be filed — the keep-Heart-green
    lane passes the ones its own dedupe left — while every finding still
    counts as listed for clearing. `needles` maps a key to the strings whose
    mention counts as covered (default: the key). `guard=False` is for a
    caller that already refused anything but a linked worktree
    (`_batch.write_hold`).

    Returns {filed: [{key, path, tier, unattended, difficulty, lane}],
    skipped: [{key, source, reason}], cleared: [keys], hold}."""
    mind = Path(mind)
    now = now or _dt.datetime.now(_dt.timezone.utc)
    stamp, today = now.strftime("%Y-%m-%dT%H:%MZ"), now.date().isoformat()
    res = {"filed": [], "skipped": [], "cleared": [], "hold": "", "cap": cap}
    hold = write_hold(mind) if guard else ""
    if hold:
        res["hold"] = hold
        res["skipped"] = [{"key": f.key, "source": f.source, "reason": "write refused: " + hold}
                          for f in findings]
        return res
    state = load_state(state_path)
    fresh = {s for s, r in reads.items() if not unusable(r)}
    present = {f.key for f in findings if f.source in fresh}
    for key, row in list(state["keys"].items()):
        if row.get("source", "release") in fresh and key not in present:
            del state["keys"][key]
            res["cleared"].append(key)
    docs, queue = corpus(mind)
    seen = set()
    for f in findings:
        if f.key in seen or (only is not None and f.key not in only):
            continue
        seen.add(f.key)

        def skip(reason, f=f):
            res["skipped"].append({"key": f.key, "source": f.source, "reason": reason})

        read = reads.get(f.source)
        why = unusable(read)
        if why:
            skip(why)
            continue
        if f.stale:
            skip("stale finding (Heart marks its row not fresh) — never filed")
            continue
        row = state["keys"].setdefault(f.key, {"first_seen": stamp})
        row.update(last_seen=stamp, source=f.source, summary=f.summary[:160])
        how, path = match(f.key, (needles or {}).get(f.key) or [f.key], docs, queue)
        if how == "exact":
            skip(f"existing {path}")
        elif how == "mentions":
            skip(f"mentioned by {path} — not filed (check it covers this)")
        elif how == "queued":
            skip("already named in queue.md — not filed; the planner ranks it")
        elif row.get("filed"):
            skip(f"filed {row.get('filed_at')} as {row['filed']}, since left the backlog "
                 "while the source still lists it — not re-filed until a fresh read "
                 "clears it")
        elif len(res["filed"]) >= cap:
            skip(f"deferred — cap {cap} reached; next run")
        else:
            c = classify(f, read, mind, today)
            if c["refusal"]:
                skip(c["refusal"])
                continue
            dest = mind / c["rel"]
            if dest.exists():
                skip(f"{c['rel']} already exists — never overwritten")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "x", encoding="utf-8") as fh:
                fh.write(c["text"])
            row.update(filed=c["rel"], filed_at=today, tier=f.tier_floor)
            res["filed"].append({"key": f.key, "path": c["rel"], "tier": f.tier_floor,
                                 "unattended": c["unattended"],
                                 "difficulty": c["difficulty"], "lane": c["lane"]})
    save_state(state, state_path)
    return res


def render(res: dict) -> str:
    L = ["", f"Filed ({len(res['filed'])}, cap {res.get('cap')}):"]
    L += [f"  {r['path']}  [{r['tier']}, Unattended {r['unattended']}, "
          f"{r['difficulty']}, lane {r['lane']}]  {r['key']}" for r in res["filed"]] \
        or ["  none"]
    if res.get("hold"):
        L += ["", f"Write refused: {res['hold']}"]
    L += ["", f"Skipped ({len(res['skipped'])}):"]
    L += [f"  {r['key']} ({r['source']}): {r['reason']}" for r in res["skipped"]] \
        or ["  none"]
    L += ["", f"Cleared ({len(res['cleared'])}): " + (", ".join(res["cleared"]) or "none")]
    return "\n".join(L) + "\n"
