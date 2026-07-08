#!/usr/bin/env python3
"""agents/faculties/memory/_memory.py — the recall substrate.

The **memory faculty** is a read-only opinion sink: given a topic/question, it
greps the organism's knowledge surfaces — PyAutoMemory's sub-wikis,
autolens_assistant's skills/wiki pages, and Mind's complete.md history — and
returns a **cited digest**: ranked pages with matching snippets. The consulting
agent reads only the listed pages and synthesises; this script never dumps
content, never writes, and builds no index.

Exit codes: 0 digest · 4 no hits or no surface · 5 usage.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MAX_FILE_BYTES = 300_000
SNIPPETS_PER_PAGE = 2
STOPWORDS = {"the", "a", "an", "of", "in", "on", "for", "and", "or", "to",
             "with", "how", "what", "prior", "work", "about", "is", "are"}


def terms_of(query: str) -> list[str]:
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9_]+", query)]
    return [w for w in words if len(w) > 2 and w not in STOPWORDS] or words


def surfaces(memory: Path | None, assistant: Path | None, mind: Path | None):
    """Yield (surface-name, root, md-file) triples, discovered at query time."""
    if memory and memory.is_dir():
        for wiki in sorted(memory.glob("*_wiki")):
            for f in wiki.rglob("*.md"):
                yield f"PyAutoMemory/{wiki.name}", memory, f
    if assistant and assistant.is_dir():
        for sub in ("skills", "wiki"):
            root = assistant / sub
            if root.is_dir():
                for f in root.rglob("*.md"):
                    yield f"autolens_assistant/{sub}", assistant.parent, f
    if mind and (mind / "complete.md").is_file():
        yield "PyAutoMind/complete.md", mind.parent, mind / "complete.md"


def score_file(f: Path, terms: list[str]):
    try:
        if f.stat().st_size > MAX_FILE_BYTES:
            return 0, []
        text = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0, []
    low = text.lower()
    hits = sum(low.count(t) for t in terms)
    if not hits:
        return 0, []
    snippets = []
    for line in text.splitlines():
        ll = line.lower()
        if any(t in ll for t in terms) and line.strip():
            snippets.append(line.strip()[:160])
            if len(snippets) >= SNIPPETS_PER_PAGE:
                break
    return hits, snippets


def digest(query: str, memory, assistant, mind, limit: int) -> dict:
    terms = terms_of(query)
    ranked = []
    seen_surfaces = set()
    for name, base, f in surfaces(memory, assistant, mind):
        seen_surfaces.add(name.split("/")[0])
        hits, snippets = score_file(f, terms)
        if hits and snippets:
            try:
                rel = str(f.relative_to(base))
            except ValueError:
                rel = str(f)
            ranked.append({"surface": name, "page": rel, "hits": hits,
                           "snippets": snippets})
    ranked.sort(key=lambda r: -r["hits"])
    return {
        "query": query,
        "terms": terms,
        "surfaces_present": sorted(seen_surfaces),
        "pages": ranked[:limit],
        "instruction": "read only the listed pages, then synthesise; "
                       "PyAutoMemory citations never reach public output",
    }


def emit_human(d: dict) -> None:
    print(f"== Memory digest (read-only) — query: {d['query']!r} ==")
    print(f"surfaces present: {', '.join(d['surfaces_present']) or 'NONE'}")
    if not d["pages"]:
        print("no matching pages — proceed without memory context "
              "(never invent it)")
        return
    for p in d["pages"]:
        print(f"\n-- {p['page']}  [{p['surface']}]  ({p['hits']} hits)")
        for s in p["snippets"]:
            print(f"   | {s}")
    print(f"\n{d['instruction']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="memory")
    ap.add_argument("--memory", default="", help="PyAutoMemory checkout")
    ap.add_argument("--assistant", default="", help="autolens_assistant checkout")
    ap.add_argument("--mind", default="", help="PyAutoMind checkout")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("query", nargs="*")
    a = ap.parse_args(argv)
    query = " ".join(a.query).strip()
    if not query:
        print("memory: pass a topic/question to recall", file=sys.stderr)
        return 5
    mem = Path(a.memory) if a.memory else None
    ast = Path(a.assistant) if a.assistant else None
    mind = Path(a.mind) if a.mind else None
    d = digest(query, mem, ast, mind, a.limit)
    if not d["surfaces_present"]:
        print("memory: no knowledge surface found (PyAutoMemory / "
              "autolens_assistant / PyAutoMind absent)", file=sys.stderr)
        return 4
    print(json.dumps(d, indent=2)) if a.as_json else emit_human(d)
    return 0 if d["pages"] else 4


if __name__ == "__main__":
    sys.exit(main())
