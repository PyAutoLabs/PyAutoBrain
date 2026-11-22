#!/usr/bin/env python3
"""agents/conductors/batch/_status.py — one reading of "is a batch in flight?".

The Mind's dashboard shows this as the Shift part of its Autopilot block: the
slot that is in flight, every member on one line, and — once there is
something to review — the button to its packet. The *reading* lives here and
the dashboard only supplies its facts.

Two constraints shape this module, and they are why it is a module at all:

- **Stdlib and `_theme` only.** It imports neither `_batch` (which imports
  `_sizing`, which reads the Mind's body map at import) nor any organ's
  script. It is imported BY `_batch.py`, never the other way round.
- **Nothing time-derived.** Every word in the box comes from a record line. A
  box that said "3h ago" would be drift on every re-render of an unchanged
  tree, and `dashboard --check` would report it as such.

The vocabulary (`RECORD_KEY`, `PENDING_RE`) lives here and
`_batch.py` imports it back, so the words the record is written in have one
definition.
"""

from __future__ import annotations

import html as _html
import re
import sys
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[3]

# The shared board theme: presentation only, and the one place that answers
# "what does a one-tap board look like" — same import shape as `_cortex.py`,
# for the same reason (that page renders with only Brain + Cortex present).
sys.path.insert(0, str(BRAIN_HOME / "board"))
from _theme import pills  # noqa: E402

# --------------------------------------------------------- the vocabulary ---
#: The batch record's own grammar. Kept byte-identical to `_batch.py`'s and
#: `_cortex.py`'s reader so all three organs read one record the same way.
RECORD_KEY = re.compile(r"^- ([a-z][a-z0-9-]*):(?:\s+(.*?))?\s*$")


#: An outcome that says the member had not finished when the record was
#: written. These are the words the ledger actually uses (`REFRESHED … still
#: carried`, `CARRIED to the next batch`), not a vocabulary invented here.
PENDING_RE = re.compile(r"\b(RUNNING|CARRIED|IN FLIGHT|REFRESHED|PENDING|"
                        r"DISPATCHED)\b", re.I)

#: The four things this box says about a member. They are display words, not
#: record states: the record's vocabulary differs per kind, the box's does not.
IN_PROGRESS = "in progress"
AWAITING = "awaiting review"
RULED = "ruled"
NOT_DELIVERED = "not delivered"

#: Tone per display word, as `_theme.pills` classes: go / caution / neutral.
_TONE = {IN_PROGRESS: "n", AWAITING: "y", RULED: "g", NOT_DELIVERED: "r"}


def read_record(text: str, member_re=None) -> dict:
    """One batch record as `{"keys": {k: [v, …]}, "members": [row, …]}`.

    Every value of every key is kept, in file order — the lossless reader the
    live-progress strip and this box both need (`- refreshed:` repeats once
    per pull and each one is history). `member_re` is the CALLER's member
    grammar: the dev and science records spell a member row differently, and
    neither spelling is invented here.
    """
    keys: dict[str, list[str]] = {}
    members: list[dict] = []
    in_members = False
    for lineno, raw in enumerate(text.split("\n"), 1):
        m = RECORD_KEY.match(raw)
        if m:
            in_members = m.group(1) == "members"
            keys.setdefault(m.group(1), []).append((m.group(2) or "").strip())
            continue
        if in_members and raw.startswith("  - "):
            row = {"lineno": lineno, "raw": raw}
            mm = member_re.match(raw.replace("--", "—")) if member_re else None
            if mm:
                row.update({k: (mm.groupdict().get(k) or "").strip()
                            for k in ("slug", "path", "runs", "minutes", "state")
                            if k in mm.groupdict()})
            members.append(row)
        elif raw.strip() and not raw.startswith("    ") and in_members:
            in_members = False
    return {"keys": keys, "members": members}


# ------------------------------------------------------------- the status ---
def _one(keys: dict, name: str) -> str:
    """The first value of a record key, `''` when the key is absent."""
    values = keys.get(name) or []
    return (values[0] or "").strip() if values else ""


def _head(text: str, limit: int = 72) -> str:
    """The head of an outcome sentence — one line, elided, never wrapped."""
    head = " ".join((text or "").split())
    return head if len(head) <= limit else head[:limit - 1].rstrip() + "…"


def dev_status(slot: str, keys: dict, members: list, review_exists: bool,
               pages: str) -> dict | None:
    """The Mind's (development) reading.

    A dev batch is dispatched at once and reviewed at once: it is open until
    it has been reviewed, and the review button appears when `collect` has
    stamped `collected:` — that is when a packet exists to press it on.
    """
    if _one(keys, "reviewed-at") or review_exists:
        return None
    rows = []
    for m in members:
        outcome = (m.get("outcome") or "").strip()
        if not outcome:
            state, detail = NOT_DELIVERED, ""
        elif PENDING_RE.search(outcome):
            state, detail = IN_PROGRESS, _head(outcome)
        else:
            # A ruling word or a health reading —
            # either way the member ended and a human can read it.
            state, detail = AWAITING, _head(outcome)
        rows.append({"slug": m.get("slug", ""), "state": state,
                     "detail": detail})
    return _status(slot, "dev", keys, rows,
                   reviewable=bool(_one(keys, "collected")), pages=pages)


def _status(slot: str, kind: str, keys: dict, rows: list, reviewable: bool,
            pages: str) -> dict:
    return {
        "slot": slot,
        "kind": kind,
        "dispatched": _one(keys, "dispatched"),
        "members": rows,
        "in_progress": sum(1 for r in rows if r["state"] == IN_PROGRESS),
        "awaiting": sum(1 for r in rows if r["state"] == AWAITING),
        "reviewable": reviewable,
        "url": review_url(pages, slot) if reviewable else "",
        "packet": f"batches/packets/{slot}.html",
        # A running shift's status, as its watcher last wrote it into the
        # record (`- live:`) — a record line, not a clock.
        "live": _one(keys, "live"),
        "issue": issue_url(keys),
    }


def issue_url(keys: dict) -> str:
    """The shift issue a record names (`- issue:`, its trailing `# …` comment
    dropped), `''` when it names none."""
    m = re.match(r"https://\S+", _one(keys, "issue"))
    return m.group(0) if m else ""


def last_shift(records: list) -> dict | None:
    """`{"slot", "issue"}` of the latest-dispatched record, for the quiet line
    the dashboard shows once every shift has been reviewed. `records` are
    `(slot, keys)` pairs; one with no `- dispatched:` is not a shift."""
    shifts = [(_one(k, "dispatched"), slot, k) for slot, k in records if _one(k, "dispatched")]
    if not shifts:
        return None
    _when, slot, keys = max(shifts)
    return {"slot": slot, "issue": issue_url(keys)}


def pick_slot(rows: list) -> dict | None:
    """The one slot the box shows: the OPEN record with the latest dispatch.

    `rows` are the per-record readings (`None` for a record that is closed).
    Dispatch order, never the record NAME's order: `-night` sorts before `-pm`
    on the same date, so a lexical pick shows yesterday's evening slot while
    tonight's runs are still on the board.
    """
    live = [r for r in rows if r]
    if not live:
        return None
    return max(live, key=lambda r: (r["dispatched"], r["slot"]))


def review_url(pages: str, slot: str) -> str:
    """The packet's Pages URL, `''` when the site URL is underivable."""
    return f"{pages}packets/{slot}.html" if pages else ""


# ------------------------------------------------------------ the renders ---
#: The Shift sub-part's anchor on the dashboard.
ANCHOR = "shift"

#: What the Shift part says when the Mind has no shift record at all.
FIXTURE = "(no shift yet)"


def _counts(st: dict) -> str:
    return f"{st['in_progress']} in progress · {st['awaiting']} awaiting review"


def _mode(st: dict) -> str:
    """`LIVE`/`SHADOW` when the watcher's `- live:` line says the shift is
    running (it opens with the mode; a closed shift's line does not)."""
    word = (st.get("live") or "").split(" ", 1)[0]
    return word if word in ("LIVE", "SHADOW") else ""


def is_live(st: dict | None) -> bool:
    return bool(st) and bool(_mode(st) or st["in_progress"])


def to_review(st: dict | None) -> int:
    """Members a human still has to review once the shift has ended."""
    if not st:
        return 0
    return st["awaiting"] or (len(st["members"]) if st["reviewable"] else 0)


def active(st: dict | None) -> bool:
    """Running, or ended with something to review: the Shift part shows the
    detail. Otherwise it is one quiet line."""
    return bool(st) and (is_live(st) or bool(to_review(st)) or st["reviewable"])


def badge(st: dict | None) -> str:
    """The Autopilot badge's shift reading, `''` when the shift has nothing to
    say: `LIVE · N in progress` while running, `N to review` after."""
    if is_live(st):
        return f"{_mode(st) or 'LIVE'} · {st['in_progress']} in progress"
    n = to_review(st)
    if n or (st and st["reviewable"]):
        return f"{n} to review"
    return ""


_STATUS_RE = re.compile(r"\s*—\s*status:\s*(https://\S+)\s*$")
_ISSUE_RE = re.compile(r"/issues/(\d+)")


def _issue_label(url: str) -> str:
    issue = _ISSUE_RE.search(url)
    return f"shift issue #{issue.group(1)}" if issue else "shift status"


def _live_parts(live: str) -> tuple[str, str]:
    """(text, url) of a `- live:` line: the watcher's words, and its trailing
    `— status: <url>`, to be linked by issue number rather than printed raw."""
    m = _STATUS_RE.search(live)
    return (live[:m.start()], m.group(1)) if m else (live, "")


def _quiet(st: dict | None, last: dict | None) -> tuple[str, str]:
    """(text, url) of the one quiet line an idle Shift part shows."""
    if st:
        return (f"last shift {st['slot']} — closed, nothing to review",
                st.get("issue") or _live_parts(st.get("live") or "")[1])
    if last:
        return f"last shift {last['slot']} — reviewed", last.get("issue", "")
    return FIXTURE[1:-1], ""


def render_html(st: dict | None, last: dict | None = None) -> str:
    """The Shift sub-part of the dashboard's Autopilot block, in the page's
    conventions: an `<h3>` with a quiet `facets` note, `facets` lines, the
    members as a list with their state pills, and — when nothing is running
    or awaiting review — one muted parenthesised line linking the issue."""
    esc = _html.escape
    if not active(st):
        text, url = _quiet(st, last)
        link = f' · <a href="{esc(url)}">{esc(_issue_label(url))}</a>' if url else ""
        return (f'<h3 id="{ANCHOR}">Shift</h3>\n'
                f'<p class="muted">({esc(text)}{link})</p>')
    H = [f'<h3 id="{ANCHOR}">Shift <span class="facets">({esc(st["slot"])} — '
         f"{esc(_counts(st))})</span></h3>"]
    text, url = _live_parts(st.get("live") or "")
    url = url or st.get("issue", "")
    if text or url:
        line = f"Live: {esc(text)}" if text else ""
        if url:
            line += (" · " if line else "") + f'<a href="{esc(url)}">{esc(_issue_label(url))}</a>'
        H.append(f'<p class="facets">{line}</p>')
    if st["members"]:
        items = []
        for r in st["members"]:
            line = (f'<code>{esc(r["slug"])}</code>'
                    f'{pills((r["state"], _TONE.get(r["state"], "n")))}')
            if r["detail"]:
                line += f'<span class="facets"> — {esc(r["detail"])}</span>'
            items.append(f"<li>{line}</li>")
        H.append("<ul>" + "".join(items) + "</ul>")
    if st["url"]:
        H.append(f'<p><a class="go" href="{esc(st["url"])}">Review this batch '
                 "→</a></p>")
    elif st["reviewable"]:
        # Reviewable, but no Pages site to link into: name the packet by path
        # rather than render a button that goes nowhere.
        H.append(f'<p class="muted">Review packet: <code>'
                 f'{esc(st["packet"])}</code></p>')
    else:
        H.append('<p class="muted">(nothing to review yet)</p>')
    return "\n".join(H)


def render_md(st: dict | None, last: dict | None = None) -> str:
    """The same sub-part in markdown — the same words, in the same order, so
    the two versions of a board read as one page."""
    if not active(st):
        text, url = _quiet(st, last)
        return "**Shift**\n\n_(" + text + (f" · [{_issue_label(url)}]({url})" if url else "") + ")_"
    L = [f"**Shift** ({st['slot']} — {_counts(st)})", ""]
    text, url = _live_parts(st.get("live") or "")
    url = url or st.get("issue", "")
    if text or url:
        line = f"Live: {text}" if text else ""
        if url:
            line += (" · " if line else "") + f"[{_issue_label(url)}]({url})"
        L += [line, ""]
    for r in st["members"]:
        line = f"- `{r['slug']}` — {r['state']}"
        if r["detail"]:
            line += f" — {r['detail']}"
        L.append(line)
    if st["members"]:
        L.append("")
    if st["url"]:
        L.append(f"[Review this batch →]({st['url']})")
    elif st["reviewable"]:
        L.append(f"Review packet: `{st['packet']}`")
    else:
        L.append("_(nothing to review yet)_")
    return "\n".join(L)
