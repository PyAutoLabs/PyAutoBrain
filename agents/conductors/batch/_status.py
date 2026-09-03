#!/usr/bin/env python3
"""agents/conductors/batch/_status.py — one reading of "is a batch in flight?".

Both dashboards open with the same box: the slot that is in flight, every
member on one line, and — once there is something to review — the button to
its packet. The Mind's page and the Cortex's page render it from different
state, so the *reading* lives here and each organ only supplies its facts.

Three constraints shape this module, and they are why it is a module at all:

- **Stdlib and `_theme` only.** The Cortex renderer runs bare inside
  PyAutoCortex's own `dashboard_refresh.yml`, with only the Cortex and the
  Brain checked out and nothing installed. So this module imports neither
  `_batch` (which imports `_sizing`, which reads the Mind's body map at
  import) nor the Cortex script. It is imported BY `_batch.py`, never the
  other way round.
- **One renderer, two organs.** `render_html`/`render_md` are written once so
  the two boards' `--check` runs stay byte-consistent with each other and a
  reader who knows one page can read the other.
- **Nothing time-derived.** Every word in the box comes from a record line or
  a phase file. A box that said "3h ago" would be drift on every re-render of
  an unchanged tree, and `dashboard --check` would report it as such.

The vocabulary (`RECORD_KEY`, `RULING_WORDS`, `PENDING_RE`,
`CORTEX_BOARD_STATES`) lives here and `_batch.py` imports it back, so the
words the record is written in have one definition.
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

#: Outcome tokens a human (or an earlier collect) already ruled with. A record
#: line opening with one of these is a VERDICT, and `--apply` leaves it alone.
RULING_WORDS = {"DELIVERED", "NOT-DELIVERED", "FAILED", "MERGED", "PARKED",
                "CARRIED", "SUSPECT", "REJECTED", "ACCEPTED", "UNREVIEWED",
                "STRUCTURE-OK", "LEAVE-TO-FINISH", "TWEAK", "DEFER", "PENDING",
                "HEALTHY", "MERGE", "REJECT", "DROP", "DROPPED", "RERUN",
                "ACCEPT"}

#: An outcome that says the member had not finished when the record was
#: written. These are the words the ledger actually uses (`REFRESHED … still
#: carried`, `CARRIED to the next batch`), not a vocabulary invented here.
PENDING_RE = re.compile(r"\b(RUNNING|CARRIED|IN FLIGHT|REFRESHED|PENDING|"
                        r"DISPATCHED)\b", re.I)

#: The four states a science member is on the board in. `ready` and `planned`
#: are scope; `accepted`, `rerun` and `dropped` are history the rulings ledger
#: carries. A slot whose every non-carried member has left these is closed.
CORTEX_BOARD_STATES = ("submitted", "running", "pulled", "awaiting-ruling")

#: The four things this box says about a member. They are display words, not
#: record states: the record's vocabulary differs per kind, the box's does not.
IN_PROGRESS = "in progress"
AWAITING = "awaiting review"
RULED = "ruled"
PULLED = "pulled, awaiting collect"
NOT_DELIVERED = "not delivered"

#: Tone per display word, as `_theme.pills` classes: go / caution / neutral.
_TONE = {IN_PROGRESS: "n", AWAITING: "y", RULED: "g", PULLED: "n",
         NOT_DELIVERED: "r"}

#: What the box says when nothing is in flight. A fixed sentence, so an
#: unchanged tree renders an unchanged page.
FIXTURE = "No batch in flight."


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


def _first_word(text: str) -> str:
    words = (text or "").split()
    return words[0].strip("(,.").upper() if words else ""


def _carried_slugs(keys: dict, members: list) -> set:
    """The members a `- carried:` line hands to the next slot.

    A carried member is on the NEXT board, not this one, so it must not hold
    this slot open — `carried: refs_v1_… — still submitted at review` closes a
    slot whose other three members are ruled. Only the head of the line (what
    comes before the em-dash that opens the human's reason) names slugs.
    """
    slugs = {m.get("slug") for m in members if m.get("slug")}
    out = set()
    for value in keys.get("carried") or []:
        head = re.split(r"\s+[—–-]\s+", value.replace("--", "—"), 1)[0]
        for token in re.split(r"[\s,;]+", head):
            token = token.strip("`'\"()")
            if token in slugs:
                out.add(token)
    return out


def dev_status(slot: str, keys: dict, members: list, review_exists: bool,
               pages: str) -> dict | None:
    """The Mind's (development) reading — today's behaviour, unchanged.

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
            # A ruling word (`RULING_WORDS`) or a collect health reading —
            # either way the member ended and a human can read it.
            state, detail = AWAITING, _head(outcome)
        rows.append({"slug": m.get("slug", ""), "state": state,
                     "detail": detail})
    return _status(slot, "dev", keys, rows,
                   reviewable=bool(_one(keys, "collected")), pages=pages)


def cortex_status(slot: str, keys: dict, members: list, states: dict,
                  live: dict, pages: str) -> dict | None:
    """The Cortex's (science) reading — a rolling board, not one sitting.

    A science slot stays open while anything is still ON the board: members
    join it as their runs finish and leave it as they are ruled. `states` is
    the phase file's own `State:` per slug (the census join — the phase file
    is the state, the record is only how the member got here) and `live` the
    per-slug progress note. Members named on a `- carried:` line are excluded
    from the open test: they belong to the next board.
    """
    carried = _carried_slugs(keys, members)
    rows, on_board = [], False
    for m in members:
        slug = m.get("slug", "")
        state = (states.get(slug) or m.get("state") or "").strip().lower()
        if state in ("submitted", "running"):
            row = (IN_PROGRESS, live.get(slug, ""))
        elif state == "pulled":
            row = (PULLED, "")
        elif state == "awaiting-ruling":
            row = (AWAITING, "")
        elif state in ("accepted", "rerun", "dropped"):
            row = (RULED, state)
        else:
            row = (RULED, state) if state else (NOT_DELIVERED, "")
        if state in CORTEX_BOARD_STATES and slug not in carried:
            on_board = True
        rows.append({"slug": slug, "state": row[0], "detail": row[1]})
    if not on_board:
        return None
    return _status(slot, "cortex", keys, rows,
                   reviewable=any(r["state"] == AWAITING for r in rows),
                   pages=pages)


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
    }


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
def _headline(st: dict) -> str:
    counts = [f"{st['in_progress']} in progress", f"{st['awaiting']} awaiting "
              "review"]
    return f"Batch {st['slot']} — " + " · ".join(counts)


def render_html(st: dict | None) -> str:
    """The box as one `verdict` banner — the theme's existing class."""
    if st is None:
        return f'<div class="verdict ok"><b>{FIXTURE}</b></div>'
    esc = _html.escape
    tone = "warn" if st["reviewable"] else "ok"
    H = [f'<div class="verdict {tone}"><b>{esc(_headline(st))}</b>']
    for r in st["members"]:
        line = (f'<code>{esc(r["slug"])}</code>'
                f'{pills((r["state"], _TONE.get(r["state"], "n")))}')
        if r["detail"]:
            line += f'<span class="facets"> — {esc(r["detail"])}</span>'
        H.append(f"<p>{line}</p>")
    if st["url"]:
        H.append(f'<p><a class="go" href="{esc(st["url"])}">Review this batch '
                 "→</a></p>")
    elif st["reviewable"]:
        # Reviewable, but no Pages site to link into: name the packet by path
        # rather than render a button that goes nowhere.
        H.append(f'<p class="muted">Review packet: <code>'
                 f'{esc(st["packet"])}</code></p>')
    else:
        H.append('<p class="muted">Nothing to review yet.</p>')
    return "".join(H) + "</div>"


def render_md(st: dict | None) -> str:
    """The same box in markdown, as a blockquote — the same words, in the
    same order, so the two versions of a board read as one page."""
    if st is None:
        return f"> **{FIXTURE}**"
    L = [f"> **{_headline(st)}**", ">"]
    for r in st["members"]:
        line = f"> - `{r['slug']}` — {r['state']}"
        if r["detail"]:
            line += f" — {r['detail']}"
        L.append(line)
    L.append(">")
    if st["url"]:
        L.append(f"> [Review this batch →]({st['url']})")
    elif st["reviewable"]:
        L.append(f"> Review packet: `{st['packet']}`")
    else:
        L.append("> _Nothing to review yet._")
    return "\n".join(L)
