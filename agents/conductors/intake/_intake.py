#!/usr/bin/env python3
"""agents/conductors/intake/_intake.py — analysis core for the Intake Agent.

The Intake Agent (organism-facing: the **Conception Agent**) is where a task is
*conceived*: it turns raw input — a text-vomit idea, a bug report, an ideas.md
bullet — into a **formal, grouped, headed PyAutoMind prompt** that the Feature /
Bug / … agents can then reason over. It sits strictly *before* create_issue /
start_dev: it FILES a prompt, it does not start development.

    raw input  ->  Intake Agent  ->  PyAutoMind <work-type>/<target>/<name>.md
                                      (with a light Type/Target/Difficulty/…
                                       header — no YAML)

Boundary (see AGENTS.md): `/route` infers a work-type and *dispatches* (starts
dev now); intake infers a work-type and *files a prompt* (defers). Low-confidence
classification lands in `triage/` — the existing unclassified bucket, reused not
reinvented. Difficulty is OWNED here (scope is decided during the intake
back-and-forth) and persisted into the header via the shared sizing faculty, so
the Feature Agent later trusts the same number.

Stdlib only. Writes ONLY under --apply; every other path is read-only.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path

# The shared sizing faculty: prompt parsing, the PyAutoMind taxonomy/vocabulary,
# repo resolution (incl. the organism repos), and the difficulty heuristic. Both
# the Feature Agent and this agent consult it — one source of truth for sizing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "faculties" / "sizing"))
from _sizing import (  # noqa: E402
    WORK_TYPES, LIBRARY_REPOS, WORKSPACE_REPOS, ORGANISM_REPOS, KNOWN_REPOS,
    RISK_KEYWORDS, AMBIGUITY_KEYWORDS, normalise_repo, estimate_difficulty, _hits,
)

# --- work-type classification -------------------------------------------------
# Keyword signals per work-type. The classifier scores each type by keyword hits
# (word-boundary prefix match via _sizing._hits) and picks the strongest; ties /
# zero-signal fall to `triage`. `feature` verbs are the natural default for "I
# want X", so they are broad — but bug/test/docs/etc. win when their signals fire.
WORK_TYPE_SIGNALS = {
    "bug": ["bug", "crash", "regression", "fails", "failing", "broken", "error",
            "traceback", "incorrect", "wrong", "nan", "exception", "does not work",
            "doesn't work", "raises", "stack trace", "segfault"],
    "test": ["test", "smoke test", "coverage", "parity", "unit test",
             "regression test", "pytest", "assert"],
    "docs": ["document", "docs", "tutorial", "notebook", "example script",
             "guide", "readme", "docstring", "walkthrough", "how-to", "howto"],
    "refactor": ["refactor", "restructure", "reorganise", "reorganize", "rename",
                 "tidy", "decouple", "clean up", "cleanup the", "extract into",
                 "split out", "no behaviour change", "no behavior change"],
    "release": ["release", "pypi", "changelog", "version bump", "tag a",
                "packaging", "deploy", "wheel"],
    "maintenance": ["dependency", "dependencies", "bump", "upgrade", "pin ",
                    "version cap", "tech debt", "hygiene", "housekeeping"],
    "research": ["research", "investigate", "explore", "study", "figure out",
                 "open question", "not sure", "design note", "scoping",
                 "literature", "compare approaches"],
    "experiment": ["experiment", "spike", "proof of concept", "proof-of-concept",
                   "poc", "prototype", "try out", "sandbox"],
    # `_hits` is word-boundary *prefix* matching, so keep bare stems that would
    # over-fire out: "add " (with the space) matches "add X" but not "address"/
    # "additional"; "new " not "renew".
    "feature": ["add ", "implement", "support", "introduce", "enable", "new ",
                "extend", "build a", "create a", "capability", "feature"],
}
# Order used to break exact-score ties (more specific intent wins over feature).
TYPE_PRECEDENCE = ["bug", "test", "docs", "refactor", "release", "maintenance",
                   "research", "experiment", "feature"]

# --- target inference ---------------------------------------------------------
# When no @RepoName resolves a target, guess the domain from keywords. Maps a
# domain keyword -> the target folder (second-folder slug) it belongs under.
TARGET_SIGNALS = {
    "autolens": ["lens", "lensing", "deflection", "einstein", "caustic",
                 "source reconstruction", "subhalo", "substructure", "point source"],
    "autogalaxy": ["galaxy", "light profile", "mass profile", "sersic", "bulge",
                   "disk", "mge", "morphology"],
    "autofit": ["sampler", "nautilus", "dynesty", "emcee", "prior", "non-linear",
                "search", "aggregator", "graphical model", "model fitting"],
    "autoarray": ["grid", "mask", "array", "inversion", "pixelization",
                  "interferometer", "convolver", "over sample", "oversampl"],
    "pyautobrain": ["brain", "conductor", "faculty", "feature agent", "route",
                    "reasoning layer", "intake", "agent"],
    "pyautomind": ["pyautomind", "the mind", "prompt registry", "active.md",
                   "planned.md", "ideas.md", "dashboard"],
    "pyautoheart": ["heart", "readiness", "health check", "vitals", "green verdict"],
    "pyautobuild": ["autobuild", "release.yml", "notebook generation", "the hands"],
    "pyautomemory": ["pyautomemory", "wiki", "bibliography", "literature summary"],
    "workspaces": ["workspace", "tutorial", "example notebook", "howto"],
}
# Human-readable display name for the header's `Target:` line.
REPO_DISPLAY = {
    "autoconf": "PyAutoConf", "autofit": "PyAutoFit", "autoarray": "PyAutoArray",
    "autogalaxy": "PyAutoGalaxy", "autolens": "PyAutoLens",
    "pyautomind": "PyAutoMind", "pyautobrain": "PyAutoBrain",
    "pyautoheart": "PyAutoHeart", "pyautobuild": "PyAutoBuild",
    "pyautomemory": "PyAutoMemory", "autobuild": "PyAutoBuild",
    "workspaces": "workspaces",
}
PRIORITY_HIGH = ["urgent", "asap", "blocker", "blocking", "critical", "important",
                 "high priority", "must fix", "regression"]
PRIORITY_LOW = ["someday", "nice to have", "eventually", "low priority", "minor",
                "when there is time", "backlog"]


def _slug(text: str, maxwords: int = 7) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    slug = "_".join(words[:maxwords])
    return slug[:48].strip("_") or "untitled"


def _title(text: str) -> str:
    """First markdown heading, else first non-empty line, trimmed to a title."""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        s = s.lstrip("#").strip().rstrip(":").rstrip(".")
        # Keep it title-length: first sentence / ~10 words.
        s = re.split(r"(?<=[a-z])[.?!]\s", s)[0]
        return " ".join(s.split()[:10]) or "Untitled"
    return "Untitled"


def _repos_in(text: str) -> list:
    # Resolve both @RepoName mentions and bare repo names — a raw text dump often
    # writes "autolens" / "pyautobrain", not "@PyAutoLens". The known-repo names
    # all carry an auto/pyauto/howto stem, so a word-boundary match is safe (it
    # will not fire on generic words, and \b keeps "autolens" out of
    # "autolens_workspace").
    found = {normalise_repo(m) for m in re.findall(r"@[A-Za-z0-9._/-]+", text)}
    low = text.lower()
    for token in KNOWN_REPOS:
        if re.search(r"\b" + re.escape(token) + r"\b", low):
            found.add(normalise_repo(token))
    return sorted(m for m in found if m in KNOWN_REPOS)


def classify_work_type(text: str):
    """Return (work_type, confidence, per_type_hits)."""
    scores = {}
    for wt, sigs in WORK_TYPE_SIGNALS.items():
        # Word-boundary prefix match (shared _hits) — not plain substring, so
        # "add" does not fire on "address" and "test" not on "latest".
        hits = _hits(text, sigs)
        if hits:
            scores[wt] = hits
    if not scores:
        return "triage", "low", {}
    best = max(scores, key=lambda k: (len(scores[k]), -TYPE_PRECEDENCE.index(k)))
    top = len(scores[best])
    contenders = [k for k in scores if len(scores[k]) == top]
    # A confident call needs a clear winner; a tie across dissimilar types (e.g.
    # bug vs feature both at 1) is genuinely ambiguous -> triage.
    if len(contenders) > 1 and best != "feature" and "feature" not in contenders:
        # Distinct non-feature types tied: unclear which kind of work this is.
        if len({c for c in contenders}) > 1:
            return "triage", "low", scores
    conf = "high" if top >= 2 else "medium"
    return best, conf, scores


def infer_target(text: str, repos: list):
    """Return (target_folder, primary_repo_display, resolved_repos)."""
    lib = [r for r in repos if r in LIBRARY_REPOS]
    wsp = [r for r in repos if r in WORKSPACE_REPOS]
    org = [r for r in repos if r in ORGANISM_REPOS]
    # Primary target folder preference: library repo, then organism, then
    # workspace bucket. (A library+workspace task still targets its library.)
    if lib:
        return lib[0], REPO_DISPLAY.get(lib[0], lib[0]), repos
    if org:
        return org[0], REPO_DISPLAY.get(org[0], org[0]), repos
    if wsp:
        return "workspaces", "workspaces", repos
    # No @mention resolved — guess the domain from keywords.
    low = text.lower()
    for tgt, sigs in TARGET_SIGNALS.items():
        if any(re.search(r"\b" + re.escape(s), low) for s in sigs):
            return tgt, REPO_DISPLAY.get(tgt, tgt), repos
    return "?", "?", repos


def infer_workflow(target: str, repos: list):
    lib = [r for r in repos if r in LIBRARY_REPOS]
    wsp = [r for r in repos if r in WORKSPACE_REPOS]
    org = [r for r in repos if r in ORGANISM_REPOS]
    if lib and wsp:
        return "combined"
    if lib or target in LIBRARY_REPOS:
        return "library"
    if org or target in ORGANISM_REPOS:
        return "infrastructure"
    if wsp or target == "workspaces":
        return "workspace"
    return "unknown"


def infer_priority(text: str) -> str:
    low = text.lower()
    if any(k in low for k in PRIORITY_HIGH):
        return "high"
    if any(k in low for k in PRIORITY_LOW):
        return "low"
    return "normal"


def infer_autonomy(level: str, factors: dict) -> str:
    """safe | supervised | human-required."""
    repo_count = factors["repos_affected"]
    if factors["human_judgement"] and repo_count == 0:
        return "human-required"          # unscoped / needs a design decision
    if (factors["architectural_risk"] or level in ("large", "too-large")
            or repo_count > 1):
        return "supervised"
    return "safe"


def analyse(text: str, source: str):
    """Classify raw text into a full IntakeDecision (never writes)."""
    repos = _repos_in(text)
    work_type, confidence, type_hits = classify_work_type(text)
    target, target_display, repos = infer_target(text, repos)

    # Build a prompt-shaped dict the shared sizing faculty understands.
    p = {"text": text, "repos": repos, "words": len(text.split()),
         "target": target, "work_type": work_type}
    level, score, factors = estimate_difficulty(p)

    autonomy = infer_autonomy(level, factors)
    priority = infer_priority(text)
    workflow = infer_workflow(target, repos)

    title = _title(text)
    slug = _slug(title)
    folder = work_type if confidence != "low" else "triage"
    if folder == "triage":
        proposed = f"triage/{slug}.md"
    elif target != "?":
        proposed = f"{folder}/{target}/{slug}.md"
    else:
        proposed = f"triage/{slug}.md"
        folder = "triage"

    # `Type:` matches the destination folder (PyAutoMind convention). For a
    # low-confidence triage filing that means `Type: triage`, not the provisional
    # guess — the guess still rides in the IntakeDecision's `work_type` field.
    header = _render_header(title, folder, target_display, repos, level,
                            autonomy, priority)
    return {
        "source": source,
        "title": title,
        "work_type": work_type,
        "classification_confidence": confidence,
        "type_signals": type_hits,
        "target": target,
        "target_display": target_display,
        "repos_affected": repos,
        "difficulty": level,
        "difficulty_score": score,
        "difficulty_factors": factors,
        "autonomy": autonomy,
        "priority": priority,
        "workflow": workflow,
        "proposed_path": proposed,
        "header": header,
        "risks": _risks(level, factors, confidence, target),
        "next_action": _next_action(proposed, confidence),
    }


def _render_header(title, work_type, target_display, repos, level, autonomy, priority):
    lines = [f"# {title}", "", f"Type: {work_type}", f"Target: {target_display}"]
    if repos:
        lines.append("Repos:")
        lines += [f"- {REPO_DISPLAY.get(r, r)}" for r in repos]
    lines += [f"Difficulty: {level}", f"Autonomy: {autonomy}",
              f"Priority: {priority}", "Status: formalised"]
    return "\n".join(lines)


def _risks(level, factors, confidence, target):
    out = []
    if confidence == "low":
        out.append("Low classification confidence — filed to triage/ for a human "
                   "to re-home once the work type is clear.")
    if target == "?":
        out.append("No target repo resolved — add an @RepoName reference or set "
                   "Target: before start_dev.")
    if factors["architectural_risk"]:
        out.append("Architectural / API risk keywords present — review scope before build.")
    if level in ("large", "too-large"):
        out.append("Large: expect to split into phased PRs at start_dev time.")
    if not out:
        out.append("Low risk; ready to formalise.")
    return out


def _next_action(proposed, confidence):
    if confidence == "low":
        return (f"Re-run with a clearer description or --apply to file {proposed} "
                "in triage/ for manual re-homing.")
    return (f"Review the header, then `--apply` to write {proposed}; "
            "afterwards `/start_dev {}` routes it.".format(proposed))


# --- apply (the only writing path) -------------------------------------------
def write_prompt(mind: Path, decision: dict, body_text: str, source_note: str):
    """Write the formal prompt file. Returns the path written (relative to mind)."""
    rel = Path(decision["proposed_path"])
    dest = mind / rel
    if dest.exists():
        stamp = _dt.date.today().isoformat().replace("-", "")
        dest = dest.with_name(f"{dest.stem}_{stamp}{dest.suffix}")
        rel = dest.relative_to(mind)
    dest.parent.mkdir(parents=True, exist_ok=True)
    date = _dt.date.today().isoformat()
    note = (f"\n\n<!-- formalised by the Intake (Conception) Agent on {date} "
            f"from {source_note} -->\n")
    dest.write_text(decision["header"] + "\n\n" + body_text.strip() + note,
                    encoding="utf-8")
    return str(rel)


# --- census + dashboard ---------------------------------------------------------
# The header convention this agent writes (see _render_header); census parses the
# same fields back out of every filed prompt. Legacy prompts pre-date the header,
# so every field is optional — absence is reported, never fatal.
HEADER_FIELDS = ("type", "target", "difficulty", "autonomy", "priority", "status")


def parse_header(text: str) -> dict:
    """Extract the light metadata header (`Field: value` lines) from a prompt.

    Only scans the top of the file so a stray "Status:" deep in prose does not
    fire; first occurrence of each field wins. No YAML — the blessed convention.
    """
    fields = {}
    for line in text.splitlines()[:30]:
        m = re.match(r"(Type|Target|Difficulty|Autonomy|Priority|Status):\s*(\S.*)",
                     line.strip())
        if m:
            fields.setdefault(m.group(1).lower(), m.group(2).strip())
    return fields


def census(mind: Path) -> dict:
    """Inventory every filed prompt — one record per `<work-type>/**/*.md`.

    Read-only, always. Walks the WORK_TYPES folders (incl. `triage/`); `issued/`
    prompts are already dispatched, so they are counted but not itemised. This is
    the Mind *backlog* view — health belongs to the Heart, never here.
    """
    records, hygiene = [], []
    for wt in WORK_TYPES:
        folder = mind / wt
        if not folder.is_dir():
            continue
        for f in sorted(folder.rglob("*.md")):
            if f.name == "README.md":
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            rel = f.relative_to(mind)
            header = parse_header(text)
            missing = [h for h in HEADER_FIELDS if h not in header]
            records.append({
                "path": str(rel),
                "work_type": wt,
                # Second folder = target repo/domain (authoritative — a header
                # Target: is free prose and must not override the taxonomy).
                "target": rel.parts[1] if len(rel.parts) > 2 else "-",
                "title": _title(text),
                "difficulty": header.get("difficulty", "-"),
                "autonomy": header.get("autonomy", "-"),
                "priority": header.get("priority", "-"),
                "status": header.get("status", "-"),
                "header": header,
                "missing": missing,
            })
            if len(missing) == len(HEADER_FIELDS):
                hygiene.append(f"{rel} — no metadata header (pre-dates intake)")

    def _count(key):
        out = {}
        for r in records:
            out[r[key]] = out.get(r[key], 0) + 1
        return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))

    issued = mind / "issued"
    return {
        "generated": _dt.date.today().isoformat(),
        "total": len(records),
        "issued_count": sum(1 for _ in issued.glob("*.md")) if issued.is_dir() else 0,
        "by_work_type": _count("work_type"),
        "by_target": _count("target"),
        "by_difficulty": _count("difficulty"),
        "by_priority": _count("priority"),
        "records": records,
        "hygiene": hygiene,
    }


def _cell(value: str) -> str:
    return str(value).replace("|", "\\|")


def render_dashboard(c: dict) -> str:
    """Render the census as the Mind backlog page (`dashboard.md`).

    Backlog only, by design: no readiness verdicts, no test state — that is the
    Heart's dashboard (`/health`). Links are repo-root-relative so the page
    renders cleanly on GitHub.
    """
    L = [
        "# PyAutoMind backlog dashboard",
        "",
        f"<!-- generated by `pyauto-brain intake dashboard --apply` on "
        f"{c['generated']} — regenerate, do not hand-edit -->",
        "",
        f"**{c['total']}** filed prompts in the backlog · **{c['issued_count']}** "
        "already dispatched to issues (`issued/`). Backlog view only — organism "
        "health lives with the Heart (`/health`), not here.",
        "",
        "| Work-type | Prompts |",
        "|-----------|--------:|",
    ]
    L += [f"| {wt} | {n} |" for wt, n in c["by_work_type"].items()]
    for wt in c["by_work_type"]:
        rows = [r for r in c["records"] if r["work_type"] == wt]
        rows.sort(key=lambda r: (r["target"], r["path"]))
        L += ["", f"## {wt} ({len(rows)})", "",
              "| Prompt | Target | Difficulty | Autonomy | Priority |",
              "|--------|--------|------------|----------|----------|"]
        L += [f"| [{_cell(r['title'])}]({r['path']}) | {r['target']} "
              f"| {r['difficulty']} | {r['autonomy']} | {r['priority']} |"
              for r in rows]
    if c["hygiene"]:
        L += ["", "## Hygiene", "",
              f"{len(c['hygiene'])} prompt(s) without a metadata header — they "
              "show `-` above. Re-home or re-run intake on them when touched.", "",
              "<details>", "<summary>Headerless prompts</summary>", ""]
        L += [f"- `{h.split(' — ')[0]}`" for h in c["hygiene"]]
        L += ["", "</details>"]
    return "\n".join(L) + "\n"


def emit_census(c: dict):
    def _fmt(counts, top=None):
        items = list(counts.items())[:top]
        s = " · ".join(f"{k} {n}" for k, n in items)
        return s + (" · …" if top and len(counts) > top else "")

    print("== Mind census ==")
    print(f"Filed prompts:   {c['total']}   (already issued: {c['issued_count']})")
    print(f"By work-type:    {_fmt(c['by_work_type'])}")
    print(f"By target:       {_fmt(c['by_target'], top=8)}")
    print(f"By difficulty:   {_fmt(c['by_difficulty'])}")
    print(f"By priority:     {_fmt(c['by_priority'])}")
    print(f"Hygiene:         {len(c['hygiene'])} prompt(s) without a metadata "
          "header (--json lists them)")


# --- ideas.md scanning --------------------------------------------------------
def scan_ideas(mind: Path):
    """Yield (bullet_text, context_header) for substantive ideas.md lines."""
    f = mind / "ideas.md"
    if not f.is_file():
        return []
    out, ctx = [], ""
    for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
        s = raw.strip()
        if not s or set(s) <= set("-# "):
            continue
        if s.endswith(":") and not s.startswith("-"):
            ctx = s.rstrip(":")
            continue
        text = s.lstrip("-*").strip()
        if text.startswith("[formalised"):   # already reconciled — skip
            continue
        if len(text) < 4:
            continue
        out.append((text, ctx))
    return out


def mark_ideas(mind: Path, formalised: dict):
    """Conservatively annotate formalised ideas.md bullets in place.

    Rewrites each formalised bullet line as `- [formalised -> <path>] <text>` —
    it never deletes the original text, so nothing is lost until a human (or a
    later, trusted pass) prunes it.
    """
    f = mind / "ideas.md"
    if not f.is_file():
        return
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    out = []
    for raw in lines:
        content = raw.strip().lstrip("-*").strip()
        if content in formalised and not content.startswith("[formalised"):
            indent = raw[:len(raw) - len(raw.lstrip())]
            out.append(f"{indent}- [formalised -> {formalised[content]}] {content}")
        else:
            out.append(raw)
    f.write_text("\n".join(out) + "\n", encoding="utf-8")


# --- emit ---------------------------------------------------------------------
def emit_human(d: dict):
    print("== IntakeDecision ==")
    print(f"Source:               {d['source']}")
    print(f"Title:                {d['title']}")
    print(f"Work-type:            {d['work_type']}  (confidence: {d['classification_confidence']})")
    print(f"Target:               {d['target_display']}")
    print(f"Repos resolved:       {', '.join(d['repos_affected']) or '(none)'}")
    print(f"Difficulty:           {d['difficulty']} (score {d['difficulty_score']})")
    print(f"Autonomy:             {d['autonomy']}")
    print(f"Priority:             {d['priority']}")
    print(f"Workflow:             {d['workflow']}")
    print(f"Proposed path:        {d['proposed_path']}")
    print("Header to be written:")
    for ln in d["header"].splitlines():
        print(f"  {ln}")
    print("Risks / notes:")
    for r in d["risks"]:
        print(f"  - {r}")
    print(f"Next action:          {d['next_action']}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="intake", add_help=True)
    ap.add_argument("--mind", required=True)
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--apply", action="store_true",
                    help="write the formal prompt file(s); default is dry-run")
    sub = ap.add_subparsers(dest="cmd", required=True)

    cl = sub.add_parser("classify", help="classify raw text or a file")
    cl.add_argument("text", nargs="*", help="raw idea text")
    cl.add_argument("--file", default="", help="read raw text from a file")

    sub.add_parser("ideas", help="scan ideas.md and propose one prompt per bullet")

    sub.add_parser("census", help="inventory all filed prompts (always read-only)")

    sub.add_parser("dashboard", help="render the census as the Mind backlog page; "
                                     "--apply writes dashboard.md")

    a = ap.parse_args(argv)
    mind = Path(a.mind)

    if a.cmd == "census":
        c = census(mind)
        print(json.dumps(c, indent=2)) if a.as_json else emit_census(c)
        return 0

    if a.cmd == "dashboard":
        c = census(mind)
        page = render_dashboard(c)
        written = None
        if a.apply:
            (mind / "dashboard.md").write_text(page, encoding="utf-8")
            written = "dashboard.md"
        if a.as_json:
            summary = {k: v for k, v in c.items() if k != "records"}
            print(json.dumps({"census": summary, "page": page, "written": written},
                             indent=2))
        elif written:
            print(f"Wrote: {written} ({c['total']} prompts, "
                  f"{len(c['hygiene'])} hygiene flag(s))")
        else:
            print(page, end="")
        return 0

    if a.cmd == "classify":
        if a.file:
            src_path = Path(a.file)
            if not src_path.is_file():
                print(f"intake: file not found: {src_path}", file=sys.stderr)
                return 4
            text = src_path.read_text(encoding="utf-8", errors="replace")
            source = f"file:{a.file}"
        elif a.text:
            text = " ".join(a.text)
            source = "user-intake"
        else:
            text = sys.stdin.read()
            source = "stdin"
        if not text.strip():
            print("intake: no input text to classify.", file=sys.stderr)
            return 4
        decision = analyse(text, source)
        if a.apply:
            written = write_prompt(mind, decision, text, source)
            decision["written"] = written
        if a.as_json:
            print(json.dumps(decision, indent=2))
        else:
            emit_human(decision)
            if a.apply:
                print(f"\nWrote: {decision['written']}")
        return 0

    if a.cmd == "ideas":
        bullets = scan_ideas(mind)
        if not bullets:
            print("intake: no un-formalised ideas found in ideas.md.", file=sys.stderr)
            return 4
        results = []
        formalised = {}
        for text, ctx in bullets:
            ctx_text = f"{ctx}: {text}" if ctx else text
            d = analyse(ctx_text, f"ideas.md ({ctx or 'top'})")
            if a.apply:
                d["written"] = write_prompt(mind, d, ctx_text, d["source"])
                formalised[text] = d["written"]
            results.append(d)
        if a.apply and formalised:
            mark_ideas(mind, formalised)
        if a.as_json:
            print(json.dumps(results, indent=2))
        else:
            print(f"== Intake: {len(results)} idea(s) from ideas.md ==")
            for d in results:
                mark = f" -> WROTE {d['written']}" if a.apply else ""
                print(f"  [{d['work_type']}/{d['target']}, {d['difficulty']}, "
                      f"conf {d['classification_confidence']}] {d['title']}"
                      f"  =>  {d['proposed_path']}{mark}")
            if not a.apply:
                print("\n(dry-run — re-run `intake ideas --apply` to write these + "
                      "mark the bullets in ideas.md)")
        return 0

    return 5


if __name__ == "__main__":
    sys.exit(main())
