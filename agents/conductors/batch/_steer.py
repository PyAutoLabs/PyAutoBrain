"""The human's two steering files in the Mind: `queue.md` and `goals.md`.

Readers only. `queue.md` is the ordered list of prompts the human wants done
(the planner's statement of importance); `goals.md` is the ordered list of
goals a shift brief copies into `goals:` (PyAutoMind#565). Both are written by
hand or by the Mind's `dashboard_input.yml` (the ★ and Goals box on the
published dashboard), and validated by the Mind's `lifecycle.py check`.

The grammar is the one `lifecycle.py` and `_batch.read_queue` read: a fenced
block is the schema's own example, any heading ends the entry above it, and
only a numbered `## <n>. <text>` heading starts one. The dashboard's client
(`intake/dashboard_edit.js`) parses the same way; a test holds them together.
"""

from __future__ import annotations

import re
from pathlib import Path

ENTRY_RE = re.compile(r"^##\s+\d+\.\s+(.+?)\s*$")
QUEUE_FIELD_RE = re.compile(r"^-\s+(kind|ref|note):\s*(.+?)\s*$")
GOAL_FIELD_RE = re.compile(r"^-\s+(epics|tags|note):\s*(.*?)\s*$")


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


def queued_names(entries: list[dict]) -> dict[str, int]:
    """{prompt basename: queue position} — how the lifecycle matches an entry
    (a `draft/` ref keeps its place once the prompt moves to `active/`)."""
    out: dict[str, int] = {}
    for e in entries:
        if e["kind"] == "prompt" and e["ref"]:
            out.setdefault(Path(e["ref"]).name, e["pos"])
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
