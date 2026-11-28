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
  legacy `<!-- heart-key: -->`; `_maintain_write.marked_keys`):

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
            keys = W.marked_keys(text)
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
    rows = []
    for f in findings:
        status, prompt = status_of((marks or {}).get(f.key)) if marks is not None \
            else ("unknown", "")
        rows.append({"key": f.key, "source": f.source, "tier": f.tier_floor,
                     "repo": f.repo, "status": status, "mind_path": prompt,
                     "stale": bool(f.stale), "witness": f.witness,
                     "summary": f.summary})
    cleared = cleared_keys(marks, listed, reads) if marks is not None else []
    unread = [s for s, r in reads.items() if not r.get("ok")]
    status_counts = {s: sum(1 for r in rows if r["status"] == s)
                     for s in STATUSES + (("unknown",) if marks is None else ())}
    status_counts[CLEARED] = len(cleared)
    return {
        "title": TITLE,
        "count": len(rows),
        "unread": unread,
        "mind": "read" if marks is not None else (mind_why or "unread"),
        "reads": [_read_row(n, r) for n, r in reads.items()],
        "counts": {"source": _count(rows, "source"), "tier": _count(rows, "tier"),
                   "status": status_counts},
        "findings": rows,
        "cleared": cleared,
    }


def collect(mind: Path | None, *, reader=None) -> dict:
    """The section for one board render. `reader` returns `read_sources`'s
    (reads, raw, findings) — default: `batch maintain --dry-run`'s read of
    every source, with the saved inputs `INPUT_ENV` names. Never raises: a
    failure is `{"title", "error"}`, rendered as this section unread."""
    try:
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
    except Exception as exc:  # noqa: BLE001 — this section fails soft, the board never
        return {"title": TITLE, "error": f"{exc.__class__.__name__}: {str(exc)[:160]}"}


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

def _counts_line(counts: dict) -> str:
    return " · ".join(f"{k} {n}" for k, n in counts.items()) or "none"


def read_line(r: dict) -> str:
    """One source read, in `batch maintain`'s words."""
    if not r["ok"]:
        return (f"{r['source']}: UNREAD — {r['why'] or r.get('verdict') or 'no data'} "
                "(findings from it are not all-clear)")
    age = "age unknown" if r.get("age_hours") is None else f"{r['age_hours']:.1f} h old"
    verdict = f", verdict {r['verdict']}" if r.get("verdict") else ""
    flag = " — STALE: listed, never filed or cleared" if r["stale"] else ""
    if r.get("partial"):
        flag += f" — PARTIAL ({r['why']}): never clear keys from it"
    return f"{r['source']}: {r['from']} ({age}{verdict}){flag}"


def headline(section: dict | None) -> str:
    if section is None:
        return (f"{TITLE}: not collected this render — `BOARD_HOMEOSTASIS=1` collects "
                "it; `batch maintain --dry-run` lists the findings")
    if section.get("error"):
        return f"{TITLE}: UNREAD this render ({section['error']}) — not all-clear"
    head = f"{section['count']} finding(s)"
    if section["unread"]:
        head += (f" — {len(section['unread'])} source(s) UNREAD "
                 f"({', '.join(section['unread'])}): incomplete, not all-clear")
    if section["mind"] != "read":
        head += f" — statuses unknown ({section['mind']})"
    return head


def render_md(section: dict | None) -> list:
    L = ["", f"## {TITLE}"]
    if section is None or section.get("error"):
        return L + [headline(section)]
    c = section["counts"]
    L += [headline(section),
          f"By source: {_counts_line(c['source'])}",
          f"By tier: {_counts_line(c['tier'])}",
          f"By status: {_counts_line(c['status'])}", "", "Sources read:"]
    L += [f"- {read_line(r)}" for r in section["reads"]]
    if section["findings"]:
        L += ["", "| Key | Source | Tier | Repo | Status | Witness |",
              "|-----|--------|------|------|--------|---------|"]
        for r in section["findings"]:
            cells = (r["key"], r["source"], r["tier"] + ("*" if r["stale"] else ""),
                     r["repo"] or "-", r["status"] + (f" ({r['mind_path']})" if r["mind_path"] else ""),
                     r["witness"])
            L.append("| " + " | ".join(str(x).replace("|", "\\|") for x in cells) + " |")
    if section["cleared"]:
        L += ["", f"Cleared ({len(section['cleared'])}): "
              + ", ".join(f"{r['key']} ({r['path']})" for r in section["cleared"])]
    return L


def render_html(section: dict | None, esc, pills, plain) -> list:
    """The section's HTML: a heading, the count lines, the source reads and the
    findings table, each long list in the board's collapsed `<details>`."""
    H = [f'<a id="{ANCHOR}"></a><h2>{esc(TITLE)}</h2>']
    if section is None or section.get("error"):
        return H + [plain(esc(headline(section)) + pills(("unread", "y")))]
    c = section["counts"]
    tone = "y" if section["unread"] or section["mind"] != "read" else "g"
    H.append(plain(esc(headline(section)) + pills((f"{section['count']} findings", tone))))
    for label, key in (("By source", "source"), ("By tier", "tier"), ("By status", "status")):
        H.append(plain(f"<b>{label}</b> " + esc(_counts_line(c[key]))))
    H.append("<details><summary>Sources read</summary>")
    for r in section["reads"]:
        H.append(plain(esc(read_line(r))
                       + pills(("ok", "g") if r["ok"] and not r["stale"]
                               else ("unread", "y") if not r["ok"] else ("stale", "y"))))
    H.append("</details>")
    if section["findings"]:
        H.append(f"<details><summary>Findings ({section['count']})</summary>")
        # The page's one table style (`table.recent`): rows on a phone.
        H.append('<table class="recent homeostasis">')
        for r in section["findings"]:
            status = esc(r["status"]) + (f' <span class="facets">{esc(r["mind_path"])}</span>'
                                         if r["mind_path"] else "")
            H.append(f'<tr><td class="what">{status}</td>'
                     f"<td><code>{esc(r['key'])}</code>"
                     + pills((r["source"], ""), (r["tier"] + ("*" if r["stale"] else ""),
                                                 "g" if r["tier"] == "glance" else "y"),
                             (r["repo"] or "-", "n"))
                     + f'<br><span class="facets">witness: {esc(r["witness"])}</span></td></tr>')
        H.append("</table>")
        if any(r["stale"] for r in section["findings"]):
            H.append('<p class="muted">* stale: listed, never filed</p>')
        H.append("</details>")
    if section["cleared"]:
        H.append(f"<details><summary>Cleared ({len(section['cleared'])})</summary>")
        for r in section["cleared"]:
            H.append(plain(f"<code>{esc(r['key'])}</code> "
                           f'<span class="facets">{esc(r["path"])}</span>'))
        H.append("</details>")
    H.append(f'<p class="muted"><a href="{SIDECAR}">{SIDECAR}</a></p>')
    return H
