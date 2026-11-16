"""The human's two steering files in the Mind: `queue.md` and `goals.md`.

Readers only. `queue.md` is the ordered list of prompts the human wants done
(the planner's statement of importance); `goals.md` is the ordered list of
goals a shift brief copies into `goals:` (PyAutoMind#565). Both are written by
the human alone, by hand or in a `/queue` chat (Brain `skills/queue`, through
the Mind's `scripts/queue_edit.py`), and validated by the Mind's
`lifecycle.py check`. The dashboard only reads them.

The grammar is the one `lifecycle.py` and `_batch.read_queue` read: a fenced
block is the schema's own example, any heading ends the entry above it, and
only a numbered `## <n>. <text>` heading starts one.
"""

from __future__ import annotations

import re
from pathlib import Path

ENTRY_RE = re.compile(r"^##\s+\d+\.\s+(.+?)\s*$")
QUEUE_FIELD_RE = re.compile(r"^-\s+(kind|ref|note):\s*(.+?)\s*$")
GOAL_FIELD_RE = re.compile(r"^-\s+(epics|tags|note):\s*(.*?)\s*$")


# --- the planner's queue reader (was `_batch.read_queue`; `_batch` re-exports
# it). The Mind dashboard ranks its read-only ★ with it too (PyAutoBrain#640),
# so the page's `#n` is the planner's order by construction.
#: A `queue.md` section heading — `## <n>. <label>`. The digits matter: the
#: file documents its own schema in a fenced block whose heading is the literal
#: `## <n>. <label>`, and a reader that took it would rank a placeholder.
QUEUE_HEAD_RE = re.compile(r"^##\s+\d+\.\s+(.+?)\s*$")
PLANNER_QUEUE_FIELD_RE = re.compile(r"^-\s+(kind|ref):\s*(.+?)\s*$")


def read_queue(mind: Path) -> list[str]:
    """`queue.md` as prompt paths, top of the file first.

    The one file the human maintains (by hand or in a `/queue` chat), and the only statement of
    IMPORTANCE the planner has — everything else it reads is a property of the
    work, not a preference about it. Order is priority: moving an entry up is
    the act of prioritising it, so the list is returned in file order and
    nothing here re-sorts it.

    Only `kind: prompt` entries carry a path anyone can plan against. A
    `retired` entry is history the human left in place, and the other kinds
    name an epic or a theme rather than a file — they are skipped rather than
    resolved, because resolving them is a decision (which phase? which chip?)
    and this function is a reader.
    """
    try:
        text = (mind / "queue.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[str] = []
    kind, ref, fenced, entry = "", "", False, False
    def flush() -> None:
        if kind == "prompt" and ref and ref not in out:
            out.append(ref)
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if line.startswith("#"):
            # Any heading ends the entry above it. Only a numbered `## <n>.`
            # one starts a new entry: the `## Retired` footer's `### …`
            # entries carry `- ref:` lines too, and until 2026-11-12 the last
            # of them overwrote the final live entry's ref.
            flush()
            kind, ref = "", ""
            entry = bool(QUEUE_HEAD_RE.match(line))
            continue
        m = PLANNER_QUEUE_FIELD_RE.match(line)
        if not m or not entry:
            continue
        value = m.group(2).split("#")[0].strip()
        if m.group(1) == "kind":
            kind = value
        else:
            ref = value
    flush()
    return out


def queue_ranks(queue: list[str]) -> dict[str, int]:
    """{prompt basename: 1-based rank} from `read_queue` — the planner's order.

    Matched by basename as `_batch.queue_rank` matches: an entry written
    against `draft/…` keeps its rank once the prompt moves to `active/`."""
    out: dict[str, int] = {}
    for n, ref in enumerate(queue, 1):
        out.setdefault(Path(ref).name, n)
    return out


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _entries(text: str, field_re: re.Pattern) -> list[dict]:
    out: list[dict] = []
    cur, fenced = None, False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if line.startswith("#"):
            m = ENTRY_RE.match(line)
            cur = {"text": m.group(1), "fields": {}} if m else None
            if cur is not None:
                out.append(cur)
            continue
        m = field_re.match(line) if cur is not None else None
        if m and m.group(1) not in cur["fields"]:
            cur["fields"][m.group(1)] = m.group(2)
    return out


def read_queue_entries(mind: Path) -> list[dict]:
    """The live `queue.md` entries, top first: `{pos, label, kind, ref, note}`.

    Every numbered entry is listed (its position is its place in the file);
    only `kind: prompt` entries carry a `ref` the planner reads. An absent
    file is an empty list."""
    out = []
    for n, e in enumerate(_entries(_read(mind / "queue.md"), QUEUE_FIELD_RE), 1):
        f = e["fields"]
        out.append({"pos": n, "label": e["text"],
                    "kind": f.get("kind", "").split("#")[0].strip(),
                    "ref": f.get("ref", "").split("#")[0].strip(),
                    "note": f.get("note", "")})
    return out


def _csv(value: str) -> list[str]:
    return [v for v in re.split(r"[,\s]+", value.split(" #")[0].strip()) if v]


def read_goals(mind: Path) -> list[dict]:
    """`goals.md`'s goals, top first: `{n, text, epics, tags, note}`. An
    absent file is an empty list."""
    out = []
    for n, e in enumerate(_entries(_read(mind / "goals.md"), GOAL_FIELD_RE), 1):
        f = e["fields"]
        out.append({"n": n, "text": e["text"], "epics": _csv(f.get("epics", "")),
                    "tags": _csv(f.get("tags", "")),
                    "note": f.get("note", "").split(" #")[0].strip()})
    return out
