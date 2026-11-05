"""agents/conductors/batch/_slice.py — `batch slice`, the decomposition pass.

A `needs-slicing` prompt is too large to run unattended; this verb turns it
into two to four children that each are. It does NOT invent the cut: deciding
where a piece of work divides is a semantic judgement no stdlib heuristic can
make honestly. The candidate slices are DECLARED — by the parent prompt's own
`## Slices` (or `## Phases`) section, or by an agent-authored plan file passed
with `--slices FILE` — and this verb does the parts that are mechanical:

  * parse the declared slices (numbered items; `*Witness:*`, `*Repos:*`,
    `*Consequence:*`, `*Difficulty:*`, `*Lane:*`, `*Depends:*` inline fields);
  * render each as a child prompt with an explicit seam;
  * have the sizing faculty judge every child against the seam rules
    (`_sizing.judge_slices`) — a child with no witness is refused as "a smaller
    judge task, not a slice";
  * under `--apply`, write the children beside the parent plus an `epics.md`
    entry naming the parent as the ledger.

The parent is never renamed, retired or edited: that is the human's call.
Stdlib-only and offline.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

from _sizing import (  # noqa: E402  (sys.path set by _batch)
    effective_difficulty, effective_unattended, judge_slices, normalise_repo,
    parse_prompt,
)

SECTION_RE = re.compile(r"^(#{2,3})\s+(Slices|Phases)\b", re.I)
HEADING_RE = re.compile(r"^(#{1,6})\s")
ITEM_RE = re.compile(r"^(\d+)[a-z]?[.)]\s+(.*)$")
FIELDS = ("witness", "repos", "consequence", "difficulty", "lane", "depends",
          "review-minutes")
FIELD_RE = re.compile(
    r"\*{1,2}(" + "|".join(FIELDS) + r"):\*{1,2}\s*", re.I)
# Header keys the parent passes down unchanged (after Difficulty).
INHERITED = ("Autonomy", "Priority")


class SliceError(Exception):
    """A usage problem (no such prompt, no declared slices, ...)."""


# --- parse -------------------------------------------------------------------
def _section(text: str) -> list[str] | None:
    """The lines of the first `## Slices` / `## Phases` section, or None."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = SECTION_RE.match(line)
        if not m:
            continue
        level, out = len(m.group(1)), []
        for nxt in lines[i + 1:]:
            h = HEADING_RE.match(nxt)
            if h and len(h.group(1)) <= level:
                break
            out.append(nxt)
        return out
    return None


def _fields(raw: str) -> tuple[str, dict]:
    """Split an item's text into (prose, {field: value})."""
    parts = FIELD_RE.split(raw)
    prose, found = parts[0], {}
    for key, value in zip(parts[1::2], parts[2::2]):
        found.setdefault(key.lower(), " ".join(value.split()).strip())
    return prose.strip(), found


def _word(value: str) -> str:
    return (value.split() or [""])[0].strip(".,;").lower()


def parse_slices(text: str, *, whole_file: bool = False) -> list[dict]:
    """Numbered items of the declared section -> [{index, title, body, ...}].

    `whole_file`: a `--slices` plan file need not carry the heading; when it
    has none, every numbered item in it is a slice."""
    lines = _section(text)
    if lines is None:
        if not whole_file:
            return []
        lines = text.splitlines()
    items, cur = [], None
    for line in lines:
        m = ITEM_RE.match(line)
        if m:
            cur = {"index": int(m.group(1)), "raw": [m.group(2)]}
            items.append(cur)
        elif cur is not None:
            cur["raw"].append(line.strip())
    out = []
    for it in items:
        raw = " ".join(x for x in it["raw"] if x)
        prose, f = _fields(raw)
        bold = re.match(r"^\*\*(.+?)\*\*\s*", prose)
        if bold:
            title, body = bold.group(1).strip().rstrip("."), prose[bold.end():]
        else:
            title = re.split(r"(?<=[.;:])\s", prose, 1)[0].rstrip(".;:")
            body = prose
        repos = [r.strip(" `.") for r in re.split(r"[,\s]+", f.get("repos", ""))
                 if r.strip(" `.")]
        depends = [int(d) for d in re.findall(r"\d+", f.get("depends", ""))]
        out.append({
            "index": it["index"], "title": title[:120] or f"slice {it['index']}",
            "body": body.strip(), "witness": f.get("witness", "").rstrip(),
            "repos": repos, "consequence": _word(f.get("consequence", "")),
            "difficulty": _word(f.get("difficulty", "")),
            "lane": _word(f.get("lane", "")), "depends": depends,
            "review_minutes": _word(f.get("review-minutes", "")),
        })
    return out


# --- the parent ----------------------------------------------------------------
def _header(text: str, key: str) -> str:
    for line in text.splitlines()[:40]:
        if line.lower().startswith(f"{key.lower()}:"):
            return line.split(":", 1)[1].strip()
    return ""


def _list_header(text: str, key: str) -> list[str]:
    m = re.search(rf"^{key}:\n((?:- .+\n?)+)", text, re.M)
    return [ln[2:].strip() for ln in m.group(1).splitlines()] if m else []


def _title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip().strip("`")
    return fallback


def read_epics(mind: Path) -> list[dict]:
    """`epics.md` -> [{slug, ledger}] (the two fields slicing needs)."""
    f = mind / "epics.md"
    if not f.is_file():
        return []
    out = []
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        h = re.match(r"^## (\S+)\s*$", line)
        if h:
            out.append({"slug": h.group(1), "ledger": ""})
        elif out and line.startswith("- ledger:") and not out[-1]["ledger"]:
            out[-1]["ledger"] = line.split(":", 1)[1].strip().strip("`")
    return out


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _file_slug(text: str, words: int = 5) -> str:
    toks = re.findall(r"[a-z0-9]+", text.lower())
    return "_".join(toks[:words]) or "slice"


def resolve_prompt(mind: Path, prompt: str) -> Path:
    for cand in (Path(prompt), mind / prompt):
        if cand.is_file():
            return cand.resolve()
    raise SliceError(f"batch slice: no such prompt {prompt}")


# --- render --------------------------------------------------------------------
def _repo_spellings(parent_repos: list[str]) -> dict:
    return {normalise_repo(r): r for r in parent_repos}


def _child_repos(s: dict, parent_text: str, parent_repos: list[str]) -> list:
    """Declared `*Repos:*`, else the parent's repos the item names, else the
    parent's one repo when it has exactly one."""
    if s["repos"]:
        return s["repos"]
    spell = _repo_spellings(parent_repos)
    words = {normalise_repo(w) for w in re.findall(r"[A-Za-z0-9_]+",
                                                   s["title"] + " " + s["body"])}
    named = [spell[k] for k in spell if k in words]
    if named:
        return named
    return list(parent_repos) if len(parent_repos) == 1 else []


def _seam(s: dict, slices: list, repos: list) -> str:
    pos = slices.index(s)
    before = slices[pos - 1] if pos else None
    after = slices[pos + 1] if pos + 1 < len(slices) else None
    parts = [f"owns {', '.join(repos) or '(no repo named)'}"]
    parts.append(f"after slice {before['index']} ({before['title']})" if before
                 else "first — nothing before it")
    parts.append(f"before slice {after['index']} ({after['title']})" if after
                 else "last")
    if s["depends"]:
        parts.append("needs slice(s) " + ", ".join(map(str, s["depends"]))
                     + " merged first")
    return "; ".join(parts)


def render_child(s: dict, slices: list, *, parent_rel: str, parent_text: str,
                 epic: str, repos: list, filed: str) -> str:
    lines = [f"# {s['title']}", ""]
    kind = _header(parent_text, "Type")
    if kind:
        lines.append(f"Type: {kind}")
    # The child's target is the parent's when the child still touches it,
    # else the child's first repo — a workspace slice does not target a library.
    target = _header(parent_text, "Target")
    if repos and normalise_repo(target) not in {normalise_repo(r) for r in repos}:
        target = repos[0]
    if target:
        lines.append(f"Target: {target}")
    if repos:
        lines.append("Repos:")
        lines += [f"- {r}" for r in repos]
    themes = _list_header(parent_text, "Themes")
    if themes:
        lines.append("Themes:")
        lines += [f"- {t}" for t in themes]
    if s["difficulty"]:
        lines.append(f"Difficulty: {s['difficulty']}")
    for key in INHERITED:
        v = _header(parent_text, key)
        if v:
            lines.append(f"{key}: {v}")
    lines.append("Status: draft")
    lines.append(f"Epic: {epic}")
    lines.append(f"Phase: {s['index']}")
    if s["consequence"]:
        lines.append(f"Consequence: {s['consequence']}")
    if s["witness"]:
        lines.append(f"Witness: {s['witness']}")
    if s["review_minutes"]:
        lines.append(f"Review-minutes: {s['review_minutes']}")
    lane = s["lane"] or _header(parent_text, "Lane")
    if lane:
        lines.append(f"Lane: {lane}")
    lines.append(f"Filed: {filed}")
    lines += [
        "", s["body"] or s["title"], "",
        "## Seam", "",
        f"Slice {s['index']} of {len(slices)} of `{parent_rel}` (epic "
        f"`{epic}`): {_seam(s, slices, repos)}. One unattended run; reviewed "
        "against its own witness; revertible on its own PR(s).", "",
    ]
    return "\n".join(lines)


# --- propose -----------------------------------------------------------------
def propose(mind: Path, prompt: str, *, slices_file: str = "",
            filed: str = "") -> dict:
    """Read the parent and its declared slices, render + judge the children.

    Writes nothing. The result carries every child's path and text, so
    `apply` is a pure write of what was shown."""
    mind = mind.resolve()
    parent = resolve_prompt(mind, prompt)
    try:
        parent_rel = parent.relative_to(mind).as_posix()
    except ValueError:
        raise SliceError(f"batch slice: {parent} is not inside the Mind at "
                         f"{mind} (pass --mind)")
    text = parent.read_text(encoding="utf-8", errors="replace")
    filed = filed or _dt.date.today().isoformat()
    pp = parse_prompt(parent, mind)
    level, _, factors, derived = effective_difficulty(pp)
    grade, grade_why, _ = effective_unattended(pp, level, factors, derived)

    if slices_file:
        sf = Path(slices_file)
        if not sf.is_file():
            raise SliceError(f"batch slice: no such slices file {slices_file}")
        slices = parse_slices(sf.read_text(encoding="utf-8"), whole_file=True)
        source = f"--slices {slices_file}"
    else:
        slices = parse_slices(text)
        source = f"the parent's `## Slices`/`## Phases` section"

    epics = read_epics(mind)
    existing = next((e for e in epics if e["ledger"] == parent_rel), None)
    epic = existing["slug"] if existing else _slugify(parent.stem)
    epic_clash = (not existing
                  and any(e["slug"] == epic for e in epics))

    parent_repos = _list_header(text, "Repos")
    children = []
    for s in slices:
        repos = _child_repos(s, text, parent_repos)
        body = render_child(s, slices, parent_rel=parent_rel, parent_text=text,
                            epic=epic, repos=repos, filed=filed)
        name = f"{parent.stem}_s{s['index']}_{_file_slug(s['title'])}.md"
        dest = parent.parent / name
        children.append({
            "index": s["index"], "title": s["title"], "witness": s["witness"],
            "repos": repos, "depends": s["depends"],
            "path": dest.relative_to(mind).as_posix(), "text": body,
            "exists": dest.exists(),
            "p": parse_prompt(dest, mind, text=body),
            "seam": _seam(s, slices, repos),
        })

    verdict = judge_slices(children)
    refusals = list(verdict["refusals"])
    if grade != "needs-slicing":
        refusals.insert(0, f"the parent grades Unattended: {grade}, not "
                           "needs-slicing — declare `Unattended: needs-slicing` "
                           "if it is too large for one run")
    if not slices:
        refusals.insert(0, f"no slices declared in {source} — this verb renders "
                           "and judges a decomposition, it does not invent one; "
                           "author a `## Slices` section (or `--slices FILE`)")
    if epic_clash:
        refusals.append(f"epics.md already has an entry `{epic}` for a "
                        "different ledger — rename the parent's slug by hand")
    dupes = sorted({c["index"] for c in children
                    if [x["index"] for x in children].count(c["index"]) > 1})
    if dupes:
        refusals.append(f"slice number(s) {dupes} declared twice")
    for c in children:
        c.update({k: verdict["per"][c["index"]][k] for k in (
            "difficulty", "consequence", "review_minutes", "unattended")})
        c["refusals"] = verdict["per"][c["index"]]["refusals"]
        c["warnings"] = verdict["per"][c["index"]]["warnings"]
        if c["exists"]:
            c["refusals"].append(f"{c['path']} already exists — never "
                                 "overwritten")
        del c["p"]
    ok = not refusals and not any(c["refusals"] for c in children)
    return {
        "ok": ok, "parent": parent_rel, "parent_unattended": grade,
        "parent_why": grade_why[0] if grade_why else "", "source": source,
        "epic": epic, "epic_exists": bool(existing), "children": children,
        "refusals": refusals, "warnings": verdict["warnings"],
        "title": _title(text, parent.stem), "filed": filed,
    }


def epic_entry(d: dict) -> str:
    order = " → ".join(f"{c['index']} {c['title']} ({', '.join(c['repos'])})"
                       for c in d["children"])
    paths = ", ".join(c["path"] for c in d["children"])
    return (f"\n## {d['epic']}\n"
            f"- title: {d['title']}\n"
            f"- ledger: {d['parent']}\n"
            f"- status: SLICED {d['filed']} by `batch slice` into "
            f"{len(d['children'])} children ({paths}); the parent is unchanged "
            "and stays the ledger\n"
            f"- notes: phases in order: {order}\n")


def apply(mind: Path, d: dict) -> list[str]:
    """Write the children and (when the parent is not already an epic) the
    epics.md entry. Refuses unless the proposal was clean. Never touches the
    parent file."""
    if not d["ok"]:
        raise SliceError("batch slice: the proposal is refused — nothing written")
    mind = mind.resolve()
    written = []
    for c in d["children"]:
        dest = mind / c["path"]
        if dest.exists():  # re-checked at write time
            raise SliceError(f"batch slice: {c['path']} appeared — nothing "
                             "more written")
    for c in d["children"]:
        (mind / c["path"]).write_text(c["text"], encoding="utf-8")
        written.append(c["path"])
    if not d["epic_exists"]:
        f = mind / "epics.md"
        before = f.read_text(encoding="utf-8") if f.is_file() else "# Epics\n"
        f.write_text(before.rstrip("\n") + "\n" + epic_entry(d), encoding="utf-8")
        written.append("epics.md")
    return written


# --- report --------------------------------------------------------------------
def report(d: dict, *, applied: list | None = None) -> str:
    head = "PROPOSED" if d["ok"] else "REFUSED"
    out = [f"== Slice proposal: {d['parent']} — {head} ==",
           f"Parent:   Unattended: {d['parent_unattended']} — left untouched "
           "(renaming or retiring it is the human's call)",
           f"Source:   {d['source']}",
           f"Epic:     {d['epic']} ("
           + ("already in epics.md" if d["epic_exists"]
              else "new epics.md entry, the parent as its ledger") + ")", ""]
    for c in d["children"]:
        out.append(f"  {c['index']}. {c['title']}")
        out.append(f"     -> {c['path']}")
        out.append(f"     witness: {c['witness'] or '(none)'}")
        out.append(f"     {c['difficulty']} · {c['consequence']} · "
                   f"~{c['review_minutes']} review-min · unattended "
                   f"{c['unattended']}")
        out.append(f"     seam: {c['seam']}")
        out += [f"     ✗ {r}" for r in c["refusals"]]
        out += [f"     ! {w}" for w in c["warnings"]]
    if d["refusals"]:
        out.append("")
        out += [f"✗ {r}" for r in d["refusals"]]
    out.append("")
    if applied:
        out.append("Wrote: " + ", ".join(applied))
    elif d["ok"]:
        out.append("Nothing written. Re-run with --apply to write the children"
                   + ("" if d["epic_exists"] else " and the epics.md entry")
                   + ".")
    else:
        out.append("Nothing written. Re-cut the refused slices and re-run.")
    return "\n".join(out)
