"""The Homeostasis (maintenance orchestrator) section of the Brain board —
PyAutoBrain#747.

Homeostasis is the maintenance orchestrator of the Physiology layer. Its board
lives here, on the Brain board, until Physiology is cut out of the Brain. It
lists every maintenance finding and where each one stands:

- findings come from `batch maintain`'s own read path
  (`agents/conductors/batch/_maintain.read_sources`): the same sources, the
  same dedupe, the same read flags. An unread, stale or partial source is
  shown as such, never as zero findings;
- each finding's status comes from the Mind checkout the board already reads
  (`PyAutoMind` beside the Brain: a sibling clone of `main` in
  `brain_board.yml`, the workspace's Mind locally), matched by the key marks
  the writer puts in a prompt (`Source-key:`, `<!-- maint-key: -->`, `_green`'s
  legacy `<!-- heart-key: -->`; `_maintain_write.generated_keys`: the header
  and the mark together, or the legacy mark):

  open         no prompt or record carries the key, or only a glance draft does
               (Homeostasis's own queue; it needs no human)
  promoted     a judge prompt in `draft/` carries it (it needs the human)
  in-progress  a prompt in `active/` carries it
  done         a `complete/` record carries it, and no live prompt does
  cleared      a key in a Mind prompt or record that a fresh, complete read of
               its source no longer reports (listed apart: not a finding)

A pure render: nothing is carried between runs, so the `homeostasis.json`
sidecar `--apply` writes beside board.json needs no fetch or merge (unlike the
hygiene ledger). It writes nothing else and never files a prompt.

Collection is opt-in (`BOARD_HOMEOSTASIS=1`, set by `brain_board.yml`), like
the hygiene pre-scan, so a terminal `pyauto-brain board` stays instant. Any
failure here fails this section only, never the board.
"""

from __future__ import annotations

import os
import re
import sys
import threading
from pathlib import Path

TITLE = "Homeostasis (maintenance orchestrator)"
ANCHOR = "homeostasis"
SIDECAR = "homeostasis.json"
ENV = "BOARD_HOMEOSTASIS"
#: Saved inputs for a hermetic or replayed render (the `batch maintain`
#: flags of the same names); unset, each source is read as `batch maintain
#: --dry-run` reads it. The hygiene ledger defaults to the board's own
#: `BOARD_HYGIENE_LEDGER` (today's line, just written by this render).
INPUT_ENV = {"board_json": "BOARD_MAINTAIN_BOARD_JSON",
             "census_json": "BOARD_MAINTAIN_CENSUS_JSON",
             "heart_json": "BOARD_MAINTAIN_HEART_JSON",
             "hygiene_json": "BOARD_MAINTAIN_HYGIENE_JSON"}
STATUSES = ("open", "promoted", "in-progress", "done")
#: An open finding whose key a complete/ record mentions without the writer's
#: mark: the task was closed (a `lifecycle.py close` record carries no
#: `Source-key:`), and the source has not yet read it fixed.
CLOSED_NOTE = "closed task, awaiting a fresh read"
#: The whole collection's time bound; past it the section renders UNREAD.
TIMEOUT_ENV = "BOARD_HOMEOSTASIS_TIMEOUT"
DEFAULT_TIMEOUT = 180.0
#: Set by `brain_board.yml`: the release source reads Heart's published feed
#: only, never a local `pyauto-heart readiness` (`_maintain.load_release`).
FEED_ONLY_ENV = "BOARD_HEART_FEED_ONLY"
CLEARED = "cleared"
MIND_DIRS = ("draft", "active", "complete")
_CONSEQUENCE_RX = re.compile(r"^Consequence:\s*(\w+)", re.M)

BRAIN_HOME = Path(__file__).resolve().parents[1]


def _batch():
    """The batch conductor's maintenance modules (`_maintain`,
    `_maintain_write`), imported read-only with the paths they expect."""
    for d in (BRAIN_HOME / "agents", BRAIN_HOME / "agents" / "faculties" / "sizing",
              BRAIN_HOME / "agents" / "conductors" / "batch"):
        if str(d) not in sys.path:
            sys.path.append(str(d))
    import _maintain  # noqa: E402
    import _maintain_write  # noqa: E402
    return _maintain, _maintain_write


def enabled() -> bool:
    return os.environ.get(ENV) == "1"


# --- the Mind side -------------------------------------------------------------

def closed_mentions(mind: Path, keys) -> dict:
    """{key: path} of a `complete/` record that mentions an unmarked key
    anywhere in its text (as a whole token, `_maintain_write.mentions`)."""
    _m, W = _batch()
    keys = [k for k in keys if k]
    out: dict = {}
    base = Path(mind) / "complete"
    if not keys or not base.is_dir():
        return out
    for f in sorted(base.rglob("*.md")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for k in keys:
            if k not in out and k in text and W.mentions(k, text):
                out[k] = f.relative_to(mind).as_posix()
        if len(out) == len(keys):
            break
    return out


def mind_marks(mind: Path) -> dict:
    """{key: [{where, path, tier, source}]} for every prompt (`draft/`,
    `active/`) and record (`complete/`) in `mind` that carries a key mark.
    `tier` is the prompt's `Consequence:`; `source` the "Filed from the
    `<source>` source" line (`_maintain_write.source_of`), or ""."""
    _m, W = _batch()
    out: dict = {}
    for where in MIND_DIRS:
        base = Path(mind) / where
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*.md")):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            keys = W.generated_keys(text)
            if not keys:
                continue
            m = _CONSEQUENCE_RX.search(text)
            row = {"where": where, "path": f.relative_to(mind).as_posix(),
                   "tier": m.group(1).lower() if m else "", "source": W.source_of(text)}
            for k in keys:
                out.setdefault(k, []).append(row)
    return out


def status_of(marks: list) -> tuple[str, str]:
    """(status, path) of a REPORTED finding from its Mind marks: active wins,
    then a judge draft (promoted), then a glance draft (open — Homeostasis's
    own queue), then a complete/ record (done); none is open."""
    by = {w: [r for r in marks or [] if r["where"] == w] for w in MIND_DIRS}
    if by["active"]:
        return "in-progress", by["active"][0]["path"]
    judge = [r for r in by["draft"] if r["tier"] != "glance"]
    if judge:
        return "promoted", judge[0]["path"]
    if by["draft"]:
        return "open", by["draft"][0]["path"]
    if by["complete"]:
        return "done", by["complete"][0]["path"]
    return "open", ""


def cleared_keys(marks: dict, listed: set, reads: dict) -> list:
    """[{key, where, path, source}] — keys the Mind carries that no source
    lists now, where a fresh, complete read of the key's source says so: its
    own source when the prompt names one (a hygiene key: that mode), else
    every requested source. A key no read could have reported stays out."""
    _m, W = _batch()
    usable = {s for s, r in reads.items() if not W.unusable(r)}
    out = []
    for key in sorted(marks):
        if key in listed:
            continue
        for row in marks[key]:
            src = row["source"]
            ok = (src in usable) if src else bool(reads) and set(reads) <= usable
            if ok:
                out.append({"key": key, **row})
                break
    return out


# --- plain words: what each finding is, and what happens next --------------------

#: (kind, heading, one sentence) in page order: what the problem is and what
#: fixing it means. A key's prefix names its kind; any other prefix is "other".
KINDS = (
    ("no_run", "Scripts skipped in smoke tests",
     "These scripts are marked slow or broken, so the smoke tests never run them. "
     "Fixing one means making it pass within the smoke time limit, then removing "
     "the marker."),
    ("smoke", "Smoke scripts failing or timing out",
     "These scripts fail, or run out of time, in the smoke tests. Fixing one means "
     "reproducing the failure and making the script pass."),
    ("ci", "Failing CI workflows",
     "These workflows are red on main. Fixing one means finding why the latest run "
     "failed and making it pass again."),
    ("timing", "Slow tests and CI gates",
     "These tests and CI checks got slower than their usual time. Fixing one means "
     "checking the slowdown is real, then speeding it up or resetting its usual time."),
    ("escapes", "LaTeX escape warnings in docstrings",
     "Python reads parts of the LaTeX in these docstrings as escape codes, so the "
     "maths comes out wrong. Fixing one means making the docstring a raw string."),
    ("docstrings", "Docstring formatting",
     "These scripts have two docstrings in a row, so one of them is never shown. "
     "Fixing one means merging them or turning one into a comment."),
    ("refs", "Broken references in docs",
     "These docs point at files or folders that no longer exist. Fixing one means "
     "updating or removing the reference."),
    ("deps", "Dependency gaps",
     "A smoke test needs an optional package that is not installed, or a script "
     "uses one without a skip guard. Fixing one means adding the install or the "
     "guard."),
    ("other", "Other",
     "Problems that fit none of the groups above. Each row says what was found."),
)
KIND_TITLE = {k: t for k, t, _s in KINDS}
_KIND_PREFIX = {"no_run": "no_run", "smoke": "smoke", "ci": "ci", "timing": "timing",
                "escapes": "escapes", "docstrings": "docstrings", "refs": "refs",
                "optdeps": "deps", "extras": "deps"}
#: The "Next" column: the finding's status in plain words.
NEXT_PROMOTED = "Waiting on you — in Mind"
NEXT_GLANCE = "Could run in a maintenance shift"
NEXT_JUDGE = "Needs you — not filed yet"
NEXT_ACTIVE = "Being fixed"
NEXT_DONE = "Fixed"
NEXT_CLOSED = "Task closed — waiting for a fresh check"
NEXT_UNKNOWN = "Not known — Mind not read"
WHAT_MAX = 64
WHY_MAX = 170


def kind_of(key: str) -> str:
    """The group a finding's key belongs to (`KINDS`), from its prefix."""
    return _KIND_PREFIX.get(str(key).partition(":")[0], "other")


def next_of(row: dict) -> str:
    """What happens next to a finding, in plain words, from its status."""
    status = row.get("status")
    if status == "promoted":
        return NEXT_PROMOTED
    if status == "in-progress":
        return NEXT_ACTIVE
    if status == "done":
        return NEXT_DONE
    if status == "unknown":
        return NEXT_UNKNOWN
    if row.get("note") == CLOSED_NOTE:
        return NEXT_CLOSED
    if row.get("mind_path") or row.get("tier") == "glance":
        return NEXT_GLANCE  # Homeostasis's own queue: a glance draft, or one to come
    return NEXT_JUDGE


def _parts(key: str) -> list:
    """The name parts of a key's subject, outermost first (a path's folders,
    then its file), with a `.py` dropped."""
    prefix, _sep, rest = str(key).partition(":")
    kind = kind_of(key)
    if kind == "no_run":
        name = rest.partition("/")[2] or rest
    elif kind == "smoke":
        name = rest.partition(":")[2] or rest
    elif kind == "ci":
        name = rest.partition(":")[2] or "CI"
    elif kind == "timing":
        sub = rest.split(":", 2)
        name = sub[2] if len(sub) == 3 else rest
        if sub[0] == "unit" and "::" in name:
            name = name.rsplit("::", 1)[1]
    elif kind in ("escapes", "docstrings", "refs", "deps"):
        _repo, file, ref = (rest.split(":", 2) + ["", ""])[:3]
        name = file or ref
    else:
        name = rest.rsplit(":", 1)[-1] or rest
    parts = [p for p in name.split("/") if p] or [name]
    parts[-1] = re.sub(r"\.py$", "", parts[-1])
    return parts


def _clip(text: str, n: int, tail: bool = False) -> str:
    text = str(text)
    if len(text) <= n:
        return text
    return "…" + text[-(n - 1):] if tail else text[:n - 1].rstrip() + "…"


def repo_of(key: str) -> str:
    """The repo a key names (a cleared key carries no `repo` field)."""
    kind, rest = kind_of(key), str(key).partition(":")[2]
    if kind == "no_run":
        return rest.partition("/")[0]
    if kind == "timing":
        return (rest.split(":") + ["", ""])[1]
    return rest.partition(":")[0] if kind != "other" else ""


def _label(parts: list, depth: int) -> str:
    """The last `depth` name parts; past two, the outermost one, an ellipsis
    and the last two ("imaging/…/pixelization/likelihood_function")."""
    if depth <= 2:
        return "/".join(parts[-depth:])
    return f"{parts[-depth]}/…/" + "/".join(parts[-2:])


def name_rows(rows: list) -> None:
    """Give each row a short `what`: its file or workflow name and its repo.
    Rows of one kind and repo sharing a name get just enough of their
    folders to tell them apart, so no long path is printed."""
    parts = {id(r): _parts(r["key"]) for r in rows}
    repo = {id(r): r.get("repo") or repo_of(r["key"]) for r in rows}
    for r in rows:
        mine = parts[id(r)]
        others = [parts[id(o)] for o in rows if o is not r
                  and o.get("kind") == r.get("kind") and repo[id(o)] == repo[id(r)]]
        depth = 1
        while depth < len(mine) and any(o[-depth:] == mine[-depth:] for o in others):
            depth += 1
        label = _clip(_label(mine, depth), WHAT_MAX, tail=True)
        r["what"] = f"{label} · {repo[id(r)]}" if repo[id(r)] else label


_ABS_RX = re.compile(r"(?<![\w.~])/(?:[^\s/,;()'\"`]+/)+([^\s/,;()'\"`]+)")
_LONG_PATH_RX = re.compile(r"[^\s`'\"()]*/[^\s`'\"()]*/[^\s`'\"()]+")
_TAG_RX = re.compile(r"^\[[\w -]+\]\s*")


def no_abs_paths(text: str) -> str:
    """An absolute path (a CI runner's checkout) cut to its file name."""
    return _ABS_RX.sub(lambda m: m.group(1), str(text or ""))


_TIMING_RX = re.compile(r"([\d.]+s) vs ([\d.]+s) baseline \(x([\d.]+)\)")
_WHERE_RX = re.compile(r" in \S+$")


def _short_path(m) -> str:
    token = m.group(0)
    if len(token) <= 40:
        return token
    tail = "/".join(token.split("/")[-2:])
    return "…/" + (tail if len(tail) <= 50 else token.split("/")[-1])


def why_of(row: dict) -> str:
    """The finding's own summary for the Why column: its `[status]` tag
    dropped, a path the What column already names dropped, other long paths
    cut to their last parts, trimmed."""
    text = _TAG_RX.sub("", no_abs_paths(row.get("summary") or ""))
    kind = row.get("kind") or kind_of(row.get("key", ""))
    if kind == "ci" and " — " in text:
        text = "Latest run: " + text.rsplit(" — ", 1)[1]
    elif kind == "timing" and _TIMING_RX.search(text):
        now, usual, x = _TIMING_RX.search(text).groups()
        text = f"Takes {now}, usually {usual} ({x} times slower)"
    elif kind in ("escapes", "docstrings", "refs", "deps"):
        text = _WHERE_RX.sub("", text)
    elif kind == "no_run":
        text = "Marked " + text
    text = _LONG_PATH_RX.sub(_short_path, text)
    return _clip(text[:1].upper() + text[1:], WHY_MAX)


def _kind_counts(rows) -> dict:
    out = {k: sum(1 for r in rows if r.get("kind") == k) for k, _t, _s in KINDS}
    return {k: n for k, n in out.items() if n}


# --- collect ---------------------------------------------------------------------

def _inputs() -> dict:
    out = {k: os.environ.get(v, "") for k, v in INPUT_ENV.items()}
    if not out["hygiene_json"]:
        out["hygiene_json"] = os.environ.get("BOARD_HYGIENE_LEDGER", "")
    return out


def _read_row(name: str, r: dict) -> dict:
    return {"source": name, "ok": bool(r.get("ok")), "stale": bool(r.get("stale")),
            "partial": bool(r.get("partial")), "from": r.get("source") or "none",
            "why": r.get("why") or "", "age_hours": r.get("age_hours"),
            **({"verdict": r["status"]} if r.get("status") else {})}


def _count(rows, key) -> dict:
    out: dict = {}
    for r in rows:
        out[r[key]] = out.get(r[key], 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def build(reads: dict, raw: dict, findings: list, mind: Path | None,
          mind_why: str = "") -> dict:
    """The section (and the sidecar's body) from one `read_sources` result
    and the Mind. Pure: no network, no writes."""
    marks = mind_marks(mind) if mind is not None else None
    listed = {f.key for fs in raw.values() for f in fs}
    closed = closed_mentions(mind, [f.key for f in findings if f.key not in marks]) \
        if marks is not None else {}
    rows = []
    for f in findings:
        status, prompt = status_of((marks or {}).get(f.key)) if marks is not None \
            else ("unknown", "")
        note = ""
        if status == "open" and not prompt and f.key in closed:
            note, prompt = CLOSED_NOTE, closed[f.key]
        row = {"key": f.key, "source": f.source, "tier": f.tier_floor,
               "repo": f.repo, "status": status, "note": note, "mind_path": prompt,
               "stale": bool(f.stale), "witness": f.witness,
               "summary": f.summary}
        rows.append(dict(row, kind=kind_of(f.key), next=next_of(row)))
    name_rows(rows)
    cleared = cleared_keys(marks, listed, reads) if marks is not None else []
    for r in cleared:
        r["kind"] = kind_of(r["key"])
    name_rows(cleared)
    unread = [s for s, r in reads.items() if not r.get("ok")]
    stale = [s for s, r in reads.items()
             if r.get("ok") and (r.get("stale") or r.get("partial"))]
    status_counts = {s: sum(1 for r in rows if r["status"] == s)
                     for s in STATUSES + (("unknown",) if marks is None else ())}
    status_counts[CLEARED] = len(cleared)
    return {
        "title": TITLE,
        "count": len(rows),
        "unread": unread,
        "stale": stale,
        "mind": "read" if marks is not None else (mind_why or "unread"),
        "reads": [_read_row(n, r) for n, r in reads.items()],
        "counts": {"source": _count(rows, "source"), "tier": _count(rows, "tier"),
                   "status": status_counts, "kind": _kind_counts(rows)},
        "findings": rows,
        "cleared": cleared,
    }


def _timeout() -> float:
    try:
        return float(os.environ.get(TIMEOUT_ENV) or DEFAULT_TIMEOUT)
    except ValueError:
        return DEFAULT_TIMEOUT


def _collect(mind, reader) -> dict:
    M, _w = _batch()
    if reader is None:
        def reader():
            return M.read_sources(M.SOURCES, **_inputs())
    reads, raw, findings = reader()
    why = ""
    if mind is None or not Path(mind).is_dir():
        why = f"no Mind checkout at {mind}" if mind is not None else "no Mind checkout"
        mind = None
    return build(reads, raw, findings, mind, why)


def collect(mind: Path | None, *, reader=None, timeout: float | None = None) -> dict:
    """The section for one board render. `reader` returns `read_sources`'s
    (reads, raw, findings) — default: `batch maintain --dry-run`'s read of
    every source, with the saved inputs `INPUT_ENV` names (`brain_board.yml`
    sets `FEED_ONLY_ENV`, so CI reads Heart's published feed only). Never
    raises and never hangs the board: an exception or `SystemExit`, or no answer within `timeout`
    seconds (`TIMEOUT_ENV`, default 180), is `{"title", "error"}`, rendered as
    this section UNREAD. The read runs in a daemon thread, so one past the
    bound is abandoned, not waited for."""
    box: dict = {}

    def run():
        try:
            box["section"] = _collect(mind, reader)
        except (Exception, SystemExit) as exc:  # noqa: BLE001 — this section fails soft
            box["error"] = f"{exc.__class__.__name__}: {str(exc)[:160]}"

    t = threading.Thread(target=run, name="homeostasis", daemon=True)
    t.start()
    limit = _timeout() if timeout is None else timeout
    t.join(limit)
    if t.is_alive():
        return {"title": TITLE, "error": f"timed out after {limit:g} s"}
    if "error" in box:
        return {"title": TITLE, "error": box["error"]}
    return box["section"]


def sidecar(section: dict) -> dict:
    """homeostasis.json: the whole section."""
    return dict(section, schema=1)


def summary(section: dict | None) -> dict | None:
    """What board.json carries: everything but the two lists, which live in
    the sidecar."""
    if not section:
        return section
    return {**{k: v for k, v in section.items() if k not in ("findings", "cleared")},
            **({"sidecar": SIDECAR} if "findings" in section else {})}


# --- render ------------------------------------------------------------------------

#: The page's opening words: what this section is, and that nothing runs here.
INTRO = (
    f"{TITLE} is the process that keeps the PyAuto software healthy. "
    "Below are the problems the health boards (Heart, the hygiene ledger and the CI "
    "timings) report right now. Nothing runs from this page. "
    "\"Could run unattended\" means a maintenance shift may fix and merge it on its "
    "own once unattended shifts are switched on (the M3 gate). "
    "\"Needs you\" means it waits for you: once filed, it appears in Mind's "
    "\"Promoted from Homeostasis\" group.")
CLEARED_TITLE = "No longer reported"
CLEARED_TEXT = ("The boards stopped reporting these, but a Mind prompt for each is still "
                "open. The problem is probably fixed and the prompt can be closed.")
#: Each source's plain name (`batch maintain`'s source ids).
SOURCE_NAMES = {
    "census": "Heart's list of skipped smoke scripts",
    "monitoring": "Heart board",
    "release": "Heart release check",
    "timing": "CI timings on the Heart board",
    "hygiene": "hygiene ledger",
    "hygiene:refs": "hygiene ledger: broken references",
    "hygiene:docstrings": "hygiene ledger: docstring formatting",
    "hygiene:escapes": "hygiene ledger: LaTeX escapes",
    "hygiene:optdeps": "hygiene ledger: optional dependencies",
    "hygiene:extras": "hygiene ledger: install extras",
}
_DAY_RX = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def mind_links(org: str) -> dict:
    """The Mind's prompt blobs and its dashboard's promoted group, for `org`
    (none without one: prompts are then named, not linked)."""
    if not org:
        return {}
    return {"blob": f"https://github.com/{org}/PyAutoMind/blob/main/",
            "promoted": f"https://{org.lower()}.github.io/PyAutoMind/#promoted-homeostasis"}


def _age(hours) -> str:
    if hours is None:
        return "age unknown"
    return f"{hours:.1f} h old" if hours < 10 else f"{hours:.0f} h old"


def source_name(source: str) -> str:
    return SOURCE_NAMES.get(source, source)


def read_line(r: dict) -> str:
    """One source read, in plain words: its name, day and age, and any flag
    (UNREAD, out of date, incomplete). Never an absolute path."""
    name = source_name(r["source"])
    if not r["ok"]:
        why = no_abs_paths(r["why"] or r.get("verdict") or "no data")
        return f"{name}: UNREAD — {why}. Problems from it are not all-clear."
    day = _DAY_RX.search(str(r.get("from") or ""))
    line = name + (f", {day.group(1)}" if day else "") + f" ({_age(r.get('age_hours'))}"
    line += (f", verdict {r['verdict']})" if r.get("verdict") else ")")
    if r["stale"]:
        line += " — STALE: out of date, so its problems are listed but never filed or cleared"
    if r.get("partial"):
        line += (f" — PARTIAL ({no_abs_paths(r['why'])}): incomplete, so nothing is "
                 "marked fixed from it")
    return line


def counts_line(section: dict) -> str:
    """The section's numbers in plain words."""
    st, tier = section["counts"]["status"], section["counts"]["tier"]
    bits = [f"{section['count']} problem{'s' if section['count'] != 1 else ''} reported",
            f"{tier.get('glance', 0)} could run unattended",
            f"{sum(n for t, n in tier.items() if t != 'glance')} need you"]
    for n, words in ((st.get("promoted", 0), "waiting on you in Mind"),
                     (st.get("in-progress", 0), "being fixed"),
                     (st.get("done", 0), "fixed"),
                     (st.get("unknown", 0), "status not known"),
                     (st.get(CLEARED, 0), "no longer reported")):
        if n or words == "waiting on you in Mind":
            bits.append(f"{n} {words}")
    return " · ".join(bits)


def headline(section: dict | None) -> str:
    if section is None:
        return (f"{TITLE}: not collected this render — `BOARD_HOMEOSTASIS=1` collects "
                "it; `batch maintain --dry-run` lists the findings")
    if section.get("error"):
        return f"{TITLE}: UNREAD this render ({section['error']}) — not all-clear"
    head = counts_line(section)
    if section["unread"]:
        head += (f" — {len(section['unread'])} source(s) UNREAD "
                 f"({', '.join(section['unread'])}): incomplete, not all-clear")
    if section.get("stale"):
        head += (f" — {len(section['stale'])} source(s) stale/partial "
                 f"({', '.join(section['stale'])}): not all-clear")
    if section["mind"] != "read":
        head += f" — statuses unknown ({section['mind']})"
    return head


def all_clear_reads(section: dict | None) -> bool:
    """Every source read fresh and complete and the Mind read: only then may
    the section's count read green (0 findings is all-clear only then)."""
    return bool(section) and not section.get("error") and not section["unread"] \
        and not section.get("stale") and section["mind"] == "read"


def _groups(rows: list):
    """(kind, heading, sentence, rows) for each kind with a finding, in page
    order."""
    for kind, title, text in KINDS:
        mine = [r for r in rows if r.get("kind", kind_of(r["key"])) == kind]
        if mine:
            yield kind, title, text, mine


def _row_fields(r: dict) -> dict:
    """A row's display fields, for a sidecar written before the plain-word
    fields existed as much as for a fresh one."""
    r = dict(r)
    r.setdefault("kind", kind_of(r["key"]))
    r.setdefault("next", next_of(r))
    if "what" not in r:
        name_rows([r])
    return r


def _link_label(path: str) -> str:
    return "Mind record" if str(path).startswith("complete/") else "Mind prompt"


def render_md(section: dict | None, org: str = "") -> list:
    L = ["", f"## {TITLE}"]
    if section is None or section.get("error"):
        return L + [headline(section)]
    links = mind_links(org)

    def mind_link(path):
        if not path:
            return ""
        label = _link_label(path)
        return f" ([{label}]({links['blob']}{path}))" if links else f" ({label})"

    def cell(text):
        return str(text).replace("|", "\\|")

    L += ["", INTRO, "", f"**{headline(section)}**"]
    rows = [_row_fields(r) for r in section["findings"]]
    for _kind, title, text, mine in _groups(rows):
        L += ["", f"### {title} ({len(mine)})", "", text, "",
              "| What | Why | Next |", "|------|-----|------|"]
        for r in mine:
            nxt = r["next"] + ("*" if r["stale"] else "") + mind_link(r["mind_path"])
            L.append(f"| `{cell(r['what'])}` | {cell(why_of(r))} | {cell(nxt)} |")
    if any(r["stale"] for r in rows):
        L += ["", "\\* out of date: listed, never filed"]
    if section["cleared"]:
        L += ["", f"### {CLEARED_TITLE} ({len(section['cleared'])})", "", CLEARED_TEXT, ""]
        L += [f"- `{_row_fields(r)['what']}`{mind_link(r['path'])}"
              for r in section["cleared"]]
    L += ["", "<details><summary>Sources read</summary>", ""]
    L += [f"- {read_line(r)}" for r in section["reads"]]
    L += ["", "</details>"]
    return L


def render_html(section: dict | None, esc, pills, plain, org: str = "") -> list:
    """The section's HTML: an intro, the counts in plain words, one collapsed
    block per kind of problem (what · why · next), the keys no longer
    reported, and the sources read. Keys, witnesses and full paths are
    tooltips, never a table cell."""
    H = [f'<a id="{ANCHOR}"></a><h2>{esc(TITLE)}</h2>']
    if section is None or section.get("error"):
        return H + [plain(esc(headline(section)) + pills(("unread", "y")))]
    links = mind_links(org)

    def mind_link(path):
        if not path:
            return ""
        label = esc(_link_label(path))
        if not links:
            return f' <span class="facets" title="{esc(path)}">({label})</span>'
        return f' <a href="{esc(links["blob"] + path)}" title="{esc(path)}">{label}</a>'

    intro = esc(INTRO)
    if links:
        group = esc('"Promoted from Homeostasis" group')
        intro = intro.replace(group, f'<a href="{esc(links["promoted"])}">{group}</a>')
    H.append(f'<p class="muted">{intro}</p>')
    tone = "g" if all_clear_reads(section) else "y"
    H.append(plain(esc(headline(section)) + pills((f"{section['count']} problems", tone))))
    rows = [_row_fields(r) for r in section["findings"]]
    for kind, title, text, mine in _groups(rows):
        H.append(f'<details id="{ANCHOR}-{kind}"><summary>{esc(title)} ({len(mine)})'
                 "</summary>")
        H.append(f'<p class="muted">{esc(text)}</p>')
        # The page's one table style (`table.recent`): rows on a phone.
        H.append('<table class="recent homeostasis">')
        for r in mine:
            tip = esc(f"{r['key']}\nDone when: {r['witness']}")
            nxt = esc(r["next"]) + ("*" if r["stale"] else "")
            H.append(f'<tr><td class="hname" title="{tip}"><code>{esc(r["what"])}</code></td>'
                     f'<td title="{esc(r.get("summary") or "")}">{esc(why_of(r))}</td>'
                     f'<td class="hnext">{nxt}{mind_link(r["mind_path"])}</td></tr>')
        H.append("</table></details>")
    if any(r["stale"] for r in rows):
        H.append('<p class="muted">* out of date: listed, never filed</p>')
    if section["cleared"]:
        H.append(f"<details id=\"{ANCHOR}-cleared\"><summary>{CLEARED_TITLE} "
                 f"({len(section['cleared'])})</summary>")
        H.append(f'<p class="muted">{esc(CLEARED_TEXT)}</p>')
        for r in section["cleared"]:
            H.append(plain(f'<code title="{esc(r["key"])}">{esc(_row_fields(r)["what"])}'
                           f"</code>{mind_link(r['path'])}"))
        H.append("</details>")
    H.append(f"<details><summary>Sources read ({len(section['reads'])})</summary>")
    for r in section["reads"]:
        H.append(plain(f'<span title="{esc(r["source"])}">{esc(read_line(r))}</span>'
                       + pills(("ok", "g") if r["ok"] and not r["stale"]
                               and not r.get("partial")
                               else ("unread", "y") if not r["ok"] else ("stale", "y"))))
    H.append("</details>")
    H.append(f'<p class="muted"><a href="{SIDECAR}">{SIDECAR}</a> (every finding, '
             "as data)</p>")
    return H
