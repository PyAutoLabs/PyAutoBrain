"""The keep-Heart-green lane (PyAutoBrain#625) — runs at brief time.

The human, 2026-11-13: "having the autonomous agent constantly trying to
ensure its green (without having it be overly eager doing releases)". So at
`batch brief --new` (and `batch green`, its dry run) this reads Heart's
verdict, sorts every RED, YELLOW and STALE reason into one of four classes by
the transparent RULES table below, and for the `fixable-dev` ones files at
most `cap` bug drafts and, on the human's opt-in (`pick`), offers them as
the brief's named tasks.

It runs at brief time, never in the watcher's tick: the tick's network
surface (AUTONOMY.md) does not read the Heart feed, and this lane must not
widen it.

What it may do: read Heart; write NEW draft prompts and its state file —
only when the caller allows it (never in a preview, never into the shared
canonical Mind: `_batch.write_hold`); return text for the brief. What it never
does: release, rehearse, dispatch any workflow, force, touch a freeze, add a
quarantine entry (that needs a human-filed bug task, ruling 2026-11-12 — it
may only PROPOSE one), write `queue.md`, or edit another prompt. It imports
no process or network module: Heart is read through `bin/heart_feed.py`
(published feed or `pyauto-heart readiness --json`, nothing else), and
`tests/test_batch_green.py` pins that.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import re
from pathlib import Path

from _sizing import (  # noqa: E402 — the caller puts the faculty on sys.path
    effective_difficulty, effective_unattended, normalise_repo,
    parse_prompt,
)

BRAIN = Path(__file__).resolve().parents[3]
CLASSES = ("fixable-dev", "local-checkout", "release-scope", "human-only")
MODES = ("off", "report", "file", "pick")
MODE_ENV = "PYAUTO_HEART_GREEN"
#: `file` by default; `pick` (naming drafts as the brief's tasks) is the
#: human's opt-in, `--green pick` or `$PYAUTO_HEART_GREEN=pick` (review of #625).
DEFAULT_MODE = "file"
DEFAULT_CAP = 3
MAX_AGE_HOURS = 6.0
STATE_NAME = "heart_green.json"
GOAL_PREFIX = "heart-green"
KEY_MARK = "<!-- heart-key: {} -->"

#: Manifest legs that judge TRACKED repo content on main, and so are a dev fix.
#: Empty on purpose: every leg Heart reports today runs `repos_sync.py` over
#: the checkouts on disk, other sessions' worktrees included (the 2026-11-13
#: "tenant firewall — 40 mismatch(es)" were all in one session's worktree).
MANIFEST_FIXABLE: tuple[str, ...] = ()

_CI = r"(?P<concl>failure|cancelled|timed_out|startup_failure|action_required|error)"
_R = r"(?P<repo>[\w.-]+)"

# (rule, class, regex, key template, lane, what the human or a worker does).
# First match wins. A class may be a {severity: class} map. `pick-only` rules
# never FILE a draft (their bug task already exists); they may pick it.
RULES = [
    # --- fixable-dev: a dev shift can make these go away ---------------------
    ("ci-red", "fixable-dev", rf"^{_R}: CI {_CI}$", "ci:{repo}", "any",
     "fix the red CI on main"),
    ("ci-red-workflow", "fixable-dev", rf"^{_R}: (?P<wf>.+?) {_CI} on main$",
     "ci:{repo}:{wf}", "any", "fix the red workflow on main"),
    ("ci-red-legacy", "fixable-dev", rf"^{_R}/(?P<wf>[\w .-]+): {_CI}$",
     "ci:{repo}:{wf}", "any", "fix the red workflow on main"),
    ("unit-test", {"red": "fixable-dev", "*": "human-only"},
     rf"^{_R}/(?P<path>[\w/.-]+\.py)::", "test:{repo}/{path}", "any",
     "red: fix the failing test on main; yellow/warn: flaky-test triage is yours"),
    ("workspace-script", "fixable-dev",
     r"^workspace validation (?:not passing|failing) \((?P<body>.*)\)$",
     "script:{script}", "local-dev", "reproduce and fix the failing workspace script"),
    ("floor-pypi", "fixable-dev",
     r"^(?P<ws>[\w.-]+): no installable (?P<lib>\S+) release on PyPI satisfies floor",
     "floor:{ws}:{lib}", "any", "fix the dependency floor"),
    ("floor-other", "fixable-dev",
     r"^(?P<ws>[\w.-]+): (?:unparseable (?:version|floor)|floor \S+ names a yanked)",
     "floor:{ws}", "any", "fix the dependency floor"),
    ("workflow-missing", "fixable-dev",
     rf"^{_R}: required workflow '(?P<wf>[^']+)' has no workflow file",
     "workflow-missing:{repo}:{wf}", "any", "add or rename the required workflow"),
    ("manifest-main", "fixable-dev",
     r"^manifest drift: (?P<label>"
     + ("|".join(map(re.escape, MANIFEST_FIXABLE)) or "(?!)") + r") — ",
     "manifest:{label}", "any", "fix the drift (repos_sync.py --check names each)"),
    ("url-hygiene", "fixable-dev", r"^URL hygiene: \d+ forbidden pattern",
     "url-hygiene", "any", "remove the forbidden URL patterns"),
    ("quarantine-active", "fixable-dev",
     r"^Stage 3 (?:quarantine active \(\d+/\d+\): (?P<label>\S+) \((?P<bug>[^,]+),"
     r"|rehearsal skipped (?P<label2>\S+) \(quarantined, (?P<bug2>[^)]+)\))",
     "quarantine:{label}", "", "pick-only: fix its bug task before the 7-day expiry"),
    # --- release-scope: only a rehearsal or a release clears these ----------
    ("floor-unsatisfiable", "release-scope",
     r"^(?P<ws>[\w.-]+): floor \S+ exceeds newest (?P<lib>\S+) release", "", "",
     "human: the floor waits on a release (or lower it by hand)"),
    ("rehearsal-rerun", "release-scope",
     r"^Stage 3 rehearsal skipped .+, but its quarantine is no longer active",
     "", "", "human: re-run the rehearsal"),
    ("release-validation", "release-scope", r"^(?:release validation|no release validation)",
     "", "", "human: /review_release for a failed stage, else rehearse when you choose"),
    ("install-verification", "release-scope", r"^install verification",
     "", "", "human: check F audits the RELEASED bootstrap — the next release clears it"),
    ("push-credential-stale", "release-scope",
     r"^release push credential (?:unverified|check)", "", "",
     "human: re-run Heart's token_push check"),
    # --- local-checkout: another session's work may be in progress ---------
    ("lib-branch", "local-checkout", rf"^{_R}: on branch \S+ \(not main\)$", "", "",
     "report only — never touch another session's checkout"),
    ("dirty", "local-checkout", r"^[\w./-]+: \d+ uncommitted (?:source change|file)",
     "", "", "report only — never touch another session's checkout"),
    ("behind", "local-checkout",
     rf"^{_R}(?:: \d+ commit\(s\) behind origin$|:behind: )", "", "",
     "report only — pull when no session is using it"),
    ("worktree-drift", "local-checkout", r"^Worktree drift:", "", "", "report only"),
    ("manifest", "local-checkout", r"^manifest drift: ", "", "",
     "report only — the leg reads checkouts on disk, other sessions' worktrees "
     "included"),
    # --- human-only: AUTONOMY.md reserves the call ---------------------------
    ("quarantine-doctrine", "human-only", r"^Stage 3 quarantine", "", "",
     "human: renew, remove or fix (quarantine doctrine)"),
    ("push-credential-refused", "human-only", r"^release push credential refused",
     "", "", "human: credentials"),
    ("open-pr", "human-only", r"(?:: open PR \d+d old|: PR×\d+)", "", "",
     "human: /prm or close it"),
    ("parked", "human-only", r"stale parked script|^Skipped-script census", "", "",
     "human: parking is your call"),
    ("timing", "human-only", r"script timing regression|slow script|^Unit-test timing",
     "", "", "human: is the slowdown real? (profiling)"),
    ("profiling-drift", "human-only", r"^profiling drift:", "", "",
     "human: library regression or stale pin"),
    ("parked-script-note", "human-only", r"^[\w.-]+_workspace\w*/\S+: ", "", "",
     "human: a parked/skipped script's note"),
    ("roll-up", "human-only", rf"^{_R}: (?:red|yellow|CI in_progress)$", "", "",
     "no action: a roll-up of the rows above, or a run in flight"),
]
_COMPILED = [(n, c, re.compile(rx), k, ln, a) for n, c, rx, k, ln, a in RULES]

#: Heart's own per-repo keys (`repository_reasons`) — they win over the text.
HEART_KEY_CLASS = {"lib_ci": "fixable-dev", "ws_ci": "fixable-dev",
                   "lib_branch": "local-checkout", "lib_dirty": "local-checkout",
                   "lib_behind": "local-checkout", "open_pr": "human-only"}


def _hf():
    spec = importlib.util.spec_from_file_location("_heart_feed_green",
                                                  BRAIN / "bin" / "heart_feed.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- read ---------------------------------------------------------------------

def from_doc(doc: dict) -> dict:
    """A Heart document — `readiness --json` or a published state.json — as
    {status, updated, reasons:[{severity, text, heart_key, repo}]}."""
    if "verdict" in doc:
        keyed = {r.get("text"): r for r in doc.get("repository_reasons") or []
                 if isinstance(r, dict)}
        reasons = [{"severity": sev, "text": t,
                    "heart_key": (keyed.get(t) or {}).get("key", ""),
                    "repo": (keyed.get(t) or {}).get("repo", "")}
                   for sev, field in (("red", "red_reasons"), ("yellow", "yellow_reasons"),
                                      ("stale", "stale_reasons"))
                   for t in doc.get(field) or [] if isinstance(t, str)]
        return {"status": str(doc.get("verdict", "")).lower() or "grey",
                "updated": doc.get("feed_ts") or doc.get("ts"), "reasons": reasons}
    reasons = [{"severity": {"info": "stale"}.get(i.get("severity"), i.get("severity")),
                "text": str(i.get("text", "")), "heart_key": "", "repo": ""}
               for i in doc.get("items") or [] if isinstance(i, dict)]
    return {"status": doc.get("status") or "grey", "updated": doc.get("updated"),
            "reasons": [r for r in reasons if r["severity"] in ("red", "yellow", "stale")]}


def read_heart(heart_json: str = "", now=None) -> dict:
    """Heart's release verdict: a saved document, else the local
    `pyauto-heart readiness --json` (it carries the per-repo keys), else the
    published feed — also when the local snapshot is over the 6 h age rule
    of `heart_feed.py` and the feed is fresher. The rule applies to all three."""
    hf = _hf()
    why = ""
    if heart_json:
        try:
            doc, source = json.loads(Path(heart_json).read_text()), f"file {heart_json}"
        except (OSError, ValueError) as exc:
            doc, source, why = None, "none", f"{heart_json} unreadable ({exc})"
    else:
        doc, why = hf.local_readiness()
        source = "local readiness"
        age = hf.age_hours(from_doc(doc)["updated"], now) if doc else None
        if doc is None or age is None or age > MAX_AGE_HOURS:
            url, uwhy = hf.feed_url()
            feed, fwhy = hf.fetch_feed(url) if url else (None, uwhy)
            fage = hf.age_hours(feed.get("updated"), now) if feed else None
            if feed and (doc is None or (fage is not None
                                         and (age is None or fage < age))):
                doc, source, why = feed, "published feed", ""
            elif doc is None:
                source, why = "none", f"{why}; {fwhy}"
    if not isinstance(doc, dict):
        return {"status": "grey", "source": "none", "why": why, "reasons": [],
                "updated": None, "age_hours": None}
    out = from_doc(doc)
    out.update(source=source, why=why, age_hours=hf.age_hours(out["updated"], now))
    return out


# --- classify -----------------------------------------------------------------

def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower())[:60].strip("_")


def classify(reason: dict) -> list[dict]:
    """One reason → its classified finding(s). A workspace-validation line
    naming several scripts becomes one finding per script."""
    text, sev = reason["text"], reason["severity"]
    for name, cls, rx, key, lane, action in _COMPILED:
        m = rx.search(text)
        if not m:
            continue
        if isinstance(cls, dict):
            cls = cls.get(sev, cls["*"])
        g = {k: (v or "").strip() for k, v in m.groupdict().items()}
        g["label"] = g.get("label") or g.get("label2", "")
        g["bug"] = g.get("bug") or g.get("bug2", "")
        base = dict(reason, rule=name, cls=cls, lane=lane, action=action,
                    file=bool(lane), repo=reason.get("repo") or g.get("repo", ""),
                    bug=g["bug"], needles=[text])
        hk = reason.get("heart_key")
        if hk in HEART_KEY_CLASS and HEART_KEY_CLASS[hk] != cls:
            base.update(cls=HEART_KEY_CLASS[hk], rule=f"heart-key {hk}",
                        file=False, lane="")
        if name == "workspace-script":
            scripts = [s.strip() for s in g["body"].split(":", 1)[1].split(", ")
                       if not s.strip().startswith("+")] if ":" in g["body"] else []
            if not scripts:
                return [dict(base, key="script:unnamed", needles=[text])]
            return [dict(base, key=f"script:{s.replace(' ', '/')}",
                         needles=[s.split(" ", 1)[-1]], script=s) for s in scripts]
        if name == "unit-test":
            base["needles"] = [g["path"]]
        if name == "quarantine-active":
            base["needles"] = [g["label"], g["bug"]]
        base["key"] = key.format(**g) if key else ""
        return [base]
    return [dict(reason, rule="unmatched", cls="human-only", key="", lane="",
                 file=False, action="no rule matched — fail closed: report, never file",
                 repo=reason.get("repo", ""), bug="", needles=[text])]


# --- dedupe -------------------------------------------------------------------

def _corpus(mind: Path) -> dict[str, str]:
    out = {}
    for sub in ("draft", "active"):
        for f in sorted((mind / sub).glob("**/*.md")):
            out[f.relative_to(mind).as_posix()] = f.read_text(encoding="utf-8",
                                                              errors="replace")
    return out


def load_state(path: Path | None) -> dict:
    try:
        data = json.loads(path.read_text()) if path else {}
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data.get("reasons"), dict) else {"version": 1, "reasons": {}}


_ISSUE_RE = re.compile(r"^Issue:\s*(\S+)", re.M)
_REF_RE = re.compile(r"(?:github\.com/)?(?:[\w.-]+/)?([\w.-]+)(?:#|/issues/)(\d+)$")


def _issue_id(ref: str):
    """`Repo#N`, `Owner/Repo#N` or an issue URL → ("repo", "N"); else None."""
    m = _REF_RE.search(ref.strip().rstrip("/"))
    return (m.group(1).lower(), m.group(2)) if m else None


def _match(f: dict, corpus: dict, queue: str) -> tuple[str, str]:
    """(how, path) — `exact`: the lane's own key mark, or (a quarantine) a
    prompt whose `Issue:` IS the entry's bug ref; `mentions`: the quoted
    reason or the script/test path; `queued`. A pick-only finding (its bug
    task exists) matches exactly or not at all — a mention is not its task."""
    mark, bug = KEY_MARK.format(f["key"]), _issue_id(f["bug"]) if f["bug"] else None
    for path, text in corpus.items():
        if mark in text or (bug and any(_issue_id(i) == bug
                                        for i in _ISSUE_RE.findall(text[:3000]))):
            return "exact", path
    if not f["file"]:
        return "", ""
    for path, text in corpus.items():
        if any(n and n in text for n in f["needles"]):
            return "mentions", path
    if any(n and n in queue for n in [f["key"], *f["needles"]]):
        return "queued", "queue.md"
    return "", ""


def _pickable(mind: Path, rel: str, lanes: list[str]) -> str:
    """Why the existing prompt at `rel` cannot be a brief pick, or ""."""
    if not rel.startswith("draft/"):
        return "in flight (active/) — another session's task"
    p = parse_prompt(mind / rel, mind)
    if not p.get("lane"):
        return "lane absent or invalid — unattended picks fail closed (M2.3)"
    if p["lane"] not in lanes:
        return f"lane {p['lane']} not in the brief's lanes ({' '.join(lanes)})"
    level, _s, factors, derived = effective_difficulty(p)
    if effective_unattended(p, level, factors, derived)[0] != "ready":
        return "sizing does not grade it Unattended: ready"
    return ""


# --- the lane -----------------------------------------------------------------

def draft_text(f: dict, heart: dict, today: str) -> str:
    repo = f.get("repo") or ""
    title = f"Heart green: {f['text'][:90]}"
    head = [f"# {title}", "", "Type: bug", f"Target: {repo or 'workspaces'}"]
    head += ["Repos:", f"- {repo}"] if repo else []
    # No `Difficulty:` (sizing derives it, `_file`) and no `Unattended:`: the
    # lane never grades its own drafts ready (review of #625).
    head += ["Autonomy: supervised",
             f"Priority: {'high' if f['severity'] == 'red' else 'normal'}",
             "Status: draft", f"Filed: {today}", "Consequence: judge",
             "Witness: after the fix merges, a fresh Heart read (under 6 h old) no "
             "longer lists the reason quoted below, and the fix's own CI is green",
             "Review-minutes: 10", f"Lane: {f['lane']}"]
    body = [
        "**Re-check first.** Filed from Heart's verdict of "
        f"{heart.get('updated')} ({heart.get('source')}). Before any work, re-read "
        "Heart (`bin/heart_feed.py`, or `pyauto-heart readiness --json`): if the "
        "reason below is gone, close this draft as already green and stop.",
        "", f"Heart reason ({f['severity']}, verbatim):", f"> {f['text']}", "",
        f"Rule `{f['rule']}` → fixable-dev: {f['action']}.", "",
        "Never: release, rehearse, dispatch a release or build workflow, force, or "
        "add a quarantine entry. A fix in a repo whose `main` CI is red needs the "
        "human's corrective exception to ship (AUTONOMY.md); this is judge tier, "
        "so the human runs `/prm`.", "", KEY_MARK.format(f["key"]),
        f"<!-- filed {today} by the keep-Heart-green lane (PyAutoBrain#625) -->"]
    return "\n".join(head) + "\n\n" + "\n".join(body) + "\n"


def _draft_path(mind: Path, f: dict) -> Path:
    folder = normalise_repo(f["repo"]) if f.get("repo") else "workspaces"
    name = "heart_green_" + _slugify(f["key"]) + ".md"
    return mind / "draft" / "bug" / folder / name


def _file(mind: Path, f: dict, heart: dict, today: str) -> str:
    """Write one draft; its `Difficulty:` is the sizing faculty's, not ours."""
    dest = _draft_path(mind, f)
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = draft_text(f, heart, today)
    dest.write_text(text, encoding="utf-8")
    level = effective_difficulty(parse_prompt(dest, mind))[0]
    dest.write_text(text.replace("\nAutonomy:", f"\nDifficulty: {level}\nAutonomy:", 1),
                    encoding="utf-8")
    return dest.relative_to(mind).as_posix()


def _save(state: dict, state_path: Path | None, mode: str) -> None:
    if state_path and mode in ("file", "pick"):
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")


def run(mind: Path, heart: dict, *, mode: str = DEFAULT_MODE, cap: int = DEFAULT_CAP,
        lanes=("any",), state_path: Path | None = None, now=None,
        hold: str = "") -> dict:
    """Classify, dedupe, file at most `cap` drafts (mode file|pick) and choose
    picks (mode pick). Returns everything the brief's `## Heart` shows.

    `hold` (why writing is not allowed here — a preview, the shared Mind)
    turns file|pick into report: nothing is written, the state included."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%MZ")
    if hold and mode in ("file", "pick"):
        mode = "report"
    res = {"mode": mode, "cap": cap, "heart": heart, "findings": [], "filed": [],
           "picks": [], "note": "", "hold": hold}
    if mode == "off":
        res["note"] = f"lane off (--green off or ${MODE_ENV}=off)"
        return res
    status, age = heart.get("status"), heart.get("age_hours")
    findings = [f for r in heart.get("reasons") or [] for f in classify(r)]
    res["findings"] = findings
    if status == "grey" or heart.get("source") == "none":
        res["note"] = f"Heart unreadable ({heart.get('why')}) — the lane did nothing"
        return res
    if age is None or age > MAX_AGE_HOURS:
        res["note"] = ("Heart evidence " + ("of unknown age" if age is None else
                       f"{age:.1f} h old") + f", over the {MAX_AGE_HOURS:g} h rule — "
                       "STALE: re-check; nothing filed or picked")
        return res
    # A fresh, valid read: a key it no longer lists is cleared, so a later
    # recurrence files again (still deduped against open drafts and tasks).
    state = load_state(state_path)
    listed = {f["key"] for f in findings if f["key"]}
    for key in [k for k in state["reasons"] if k not in listed]:
        del state["reasons"][key]
    if status in ("green", "stale"):
        res["note"] = f"Heart {status.upper()} — nothing for a shift to fix"
        _save(state, state_path, mode)
        return res
    corpus, queue = _corpus(mind), ""
    try:
        queue = (mind / "queue.md").read_text(encoding="utf-8")
    except OSError:
        pass
    order = {"red": 0, "yellow": 1}
    seen, today = set(), now.date().isoformat()
    for f in sorted(findings, key=lambda f: order.get(f["severity"], 2)):
        if f["cls"] != "fixable-dev" or f["severity"] == "stale" or not f["key"]:
            continue
        if f["key"] in seen:
            f["outcome"] = "duplicate of a row above"
            continue
        seen.add(f["key"])
        row = state["reasons"].setdefault(f["key"], {"first_seen": stamp})
        row.update(last_seen=stamp, text=f["text"])
        how, path = _match(f, corpus, queue)
        if how == "queued":
            f["outcome"] = "already named in queue.md — not filed; the planner ranks it"
        elif how == "exact" or (how and not f["file"]):
            why = _pickable(mind, path, list(lanes))
            f["outcome"] = f"existing {path}" + (f" — not picked: {why}" if why else "")
            if not why and mode == "pick" and len(res["picks"]) < cap:
                res["picks"].append(path)
                f["outcome"] += " (picked)"
        elif how:
            f["outcome"] = f"mentioned by {path} — not filed (check it covers this)"
        elif not f["file"]:
            f["outcome"] = "its bug task is not in draft/ or active/ — not filed (pick-only)"
        elif row.get("filed"):
            f["outcome"] = (f"filed {row.get('filed_at')} as {row['filed']}, since left "
                            "the backlog while Heart still lists it — not re-filed until "
                            "a fresh read clears it")
        elif mode == "report":
            f["outcome"] = "would file (report mode)"
        elif len(res["filed"]) >= cap:
            f["outcome"] = f"deferred — cap {cap} reached; next brief"
        else:
            rel = _file(mind, f, heart, today)
            row.update(filed=rel, filed_at=today)
            res["filed"].append(rel)
            why = _pickable(mind, rel, list(lanes))
            f["outcome"] = f"filed {rel}" + (f" — not picked: {why}" if why else "")
            if not why and mode == "pick" and len(res["picks"]) < cap:
                res["picks"].append(rel)
                f["outcome"] += " (picked)"
    _save(state, state_path, mode)
    return res


# --- render -------------------------------------------------------------------

def section(res: dict) -> str:
    """The brief's `## Heart` section: reasons by class, what was filed or
    picked, and what needs the human."""
    h = res["heart"]
    age = h.get("age_hours")
    L = ["## Heart", "",
         f"Read {h.get('updated') or 'never'}"
         + (f" ({age:.1f} h old)" if age is not None else "")
         + f" from {h.get('source', 'none')}: **{str(h.get('status', 'grey')).upper()}**."
         f" Lane `{res['mode']}`, cap {res['cap']} new draft(s) per brief;"
         " it never releases, rehearses, dispatches, forces or quarantines."]
    if res.get("hold"):
        L += ["", f"Nothing written: {res['hold']}."]
    if res["note"]:
        L += ["", res["note"]]
    for cls in CLASSES:
        rows = [f for f in res["findings"] if f["cls"] == cls]
        if not rows:
            continue
        L += ["", f"### {cls} ({len(rows)})"]
        for f in rows:
            line = f"- [{f['severity']}] {f['text']}"
            line += f" [script {f['script']}]" if f.get("script") else ""
            line += f" — rule `{f['rule']}`"
            line += f" → {f['outcome']}" if f.get("outcome") else f" → {f['action']}"
            L.append(line)
    human = [f for f in res["findings"] if f["cls"] in ("release-scope", "human-only")
             and (f["severity"] != "stale" or f["cls"] == "release-scope")
             and not f["action"].startswith("no action")]
    L += ["", "### Needs the human"]
    by_action: dict[str, list[str]] = {}
    for f in human:
        by_action.setdefault(f["action"], []).append(f["text"])
    for action, texts in by_action.items():
        more = f"; +{len(texts) - 3} more" if len(texts) > 3 else ""
        L.append(f"- {action} — " + "; ".join(texts[:3]) + more)
    if not by_action:
        L.append("- nothing")
    if any(f["rule"] == "workspace-script" for f in res["findings"]):
        L.append("- proposal only: a failing Stage 3 script with a filed bug task "
                 "may be quarantined (your ruling 2026-11-12) — the lane never does it")
    L += ["", f"Filed: {', '.join(res['filed']) or 'none'} · picked: "
          f"{', '.join(res['picks']) or 'none'}"]
    return "\n".join(L) + "\n"
