#!/usr/bin/env python3
"""agents/conductors/docs/_docs.py — core for the Documentation Agent.

DECISION + READ-ONLY AUDIT. It reads intent (raw text or a PyAutoMind prompt
file) and emits a DocsDecision, or reads one page and scores it against
skills/WRITING_STYLE.md. It never edits a page and never writes a file:
authoring runs through start_dev, like every other docs task.

Five surfaces, two families:

  people-facing  readme · setup · rtd   -> skills/WRITING_STYLE.md applies
  tutorial       tutorial               -> deferred to the Workspace conductor
                                           (its workspace/howto registers own
                                           the science prose)
  agent-facing   agent                  -> WRITING_STYLE.md does not apply

The style guide is the single source: the README/setup templates, the jargon
list, the journey order and the checklist are parsed out of WRITING_STYLE.md
at run time, never restated here.

Stdlib-only. Exit codes: 0 decision/audit · 4 inputs unresolvable · 5 bad usage.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import _pyauto_root  # noqa: E402
from _repo_paths import repo_path  # noqa: E402

PYAUTO_ROOT = _pyauto_root.pyauto_root()
BRAIN_HOME = Path(__file__).resolve().parents[3]
STYLE_GUIDE = BRAIN_HOME / "skills" / "WRITING_STYLE.md"
TUTORIAL_GUIDE = BRAIN_HOME / "skills" / "TUTORIAL_WRITING_STYLE.md"
STYLE_REL = "PyAutoBrain/skills/WRITING_STYLE.md"
TUTORIAL_REL = "PyAutoBrain/skills/TUTORIAL_WRITING_STYLE.md"

PEOPLE_FACING = ("readme", "setup", "rtd")
SURFACE_LABELS = {
    "readme": "GitHub README",
    "setup": "setup / how-to page",
    "rtd": "Read the Docs page",
    "tutorial": "tutorial narrative",
    "agent": "agent-facing file",
}

# Surface signals, checked in this precedence order: an explicit agent file or
# README beats a generic "tutorial" word ("rewrite the <howto repo> README" is
# a README job; "a <howto repo> chapter" is a tutorial).
SURFACE_SIGNALS = (
    ("agent", ("agents.md", "claude.md", "skill.md", "skills/", "wiki/core",
               "agent-facing", "agent facing", "agent instructions",
               "agent-only", "command body")),
    ("readme", ("readme", "front page", "landing page", "repo homepage")),
    ("setup", ("setup page", "set-up page", "docs/setup", "install page",
               "installation page", "how-to page", "howto page",
               "getting started page", "setup guide", "install guide")),
    ("rtd", ("read the docs", "readthedocs", "rtd", "sphinx", ".rst",
             "docs site", "documentation site", "api docs", "api reference",
             "docs page")),
    ("tutorial", ("tutorial", "notebook", "chapter", "worked example",
                  "example script", "guided tour", "lesson", "docstring",
                  "howto", "how to lens", "walkthrough")),
)

HOWTO_HINT_WORDS = ("howto", "chapter", "beginner", "undergrad", "first-time",
                    "first time", "lesson", "course", "learner")

# Categories whose people-facing pages are kept in step: a structural change
# to one README (sections, order, template) is mirrored across the category.
# Membership is read from the body map (PyAutoMind/repos.yaml), never listed
# here — naming instance repos in organ code is what the tenant firewall
# catches.
STEP_CATEGORIES = ("assistant", "workspace", "howto", "library")


def fail(code, msg):
    print(f"docs: {msg}", file=sys.stderr)
    sys.exit(code)


# ------------------------------------------------------------ the guide ----


def guide_text():
    try:
        return STYLE_GUIDE.read_text(encoding="utf-8")
    except OSError:
        return ""


def guide_section(text, heading):
    m = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else ""


def _unwrap(s):
    return re.sub(r"\s+", " ", s).strip()


def guide_templates(text):
    """{"readme": [...], "setup": [...]} parsed from '## Page templates'."""
    sec = guide_section(text, "Page templates")
    out = {}
    m = re.search(r"\*\*A README\*\* should have:(.*?)(?:\n\n|\Z)", sec, re.S)
    if m:
        body = _unwrap(m.group(1))
        parts = re.split(r",\s*(?:then\s+)?|\.\s+|\bthen\b", body)
        out["readme"] = [re.sub(r"^and\s+", "", p.strip(" .")) for p in parts
                         if p.strip(" .")]
    m = re.search(r"\*\*A setup page\*\*.*?:\s*\n(.*?)(?:\n\n[^-]|\Z)", sec, re.S)
    if m:
        out["setup"] = [_unwrap(b).rstrip(";.").replace("**", "") for b in
                        re.findall(r"^- (.+?)(?=^- |\Z)", m.group(1), re.M | re.S)]
    return out


def guide_rules(text):
    """{number: (bold lead, full text)} from '## The rules'."""
    sec = guide_section(text, "The rules")
    rules = {}
    for m in re.finditer(r"^(\d+)\. \*\*(.+?)\*\*(.*?)(?=^\d+\. |\Z)", sec, re.M | re.S):
        rules[int(m.group(1))] = (m.group(2).strip(), _unwrap(m.group(2) + m.group(3)))
    return rules


def guide_journey(text):
    rule = guide_rules(text).get(9)
    if not rule:
        return []
    m = re.search(r"journey\.\*?\*?\s*(.+)$", rule[1])
    tail = m.group(1) if m else ""
    return [p.strip(" .") for p in tail.split(",") if p.strip(" .")]


def guide_jargon(text):
    rule = guide_rules(text).get(3)
    m = re.search(r"jargon such as (.+?) in people-facing", rule[1]) if rule else None
    if not m:
        return ["harness", "adapter", "leg", "gate", "card", "organ", "conductor"]
    return [w.strip() for w in re.split(r",| or ", m.group(1)) if w.strip()]


def guide_checklist(text):
    sec = guide_section(text, "Checklist before you finish")
    return [_unwrap(b) for b in re.findall(r"^- (.+?)(?=^- |\Z)", sec, re.M | re.S)]


# ------------------------------------------------------------- decision ----


def read_intent(arg):
    for base in (Path(arg), repo_path(PYAUTO_ROOT, "PyAutoMind") / arg):
        if base.is_file():
            return base.read_text(encoding="utf-8"), str(base)
    return arg, None


def known_repos():
    """name -> category from the body map; empty when it is not on disk."""
    repos = {}
    manifest = repo_path(PYAUTO_ROOT, "PyAutoMind") / "repos.yaml"
    try:
        text = manifest.read_text(encoding="utf-8")
    except OSError:
        return repos
    for m in re.finditer(r"^  ([A-Za-z][\w.-]*):\s*\n(?:    .*\n)*?    category:\s*(\w+)",
                         text, re.M):
        repos[m.group(1)] = m.group(2)
    return repos


def step_groups(repos):
    return {c: [r for r, cat in repos.items() if cat == c] for c in STEP_CATEGORIES}


def family_libraries(repos):
    """Bare family word -> library repo ('PyAutoThing' -> 'autothing'), derived
    from the body map's library entries."""
    out = {}
    for r, cat in repos.items():
        if cat == "library":
            m = re.match(r"(?i)py(auto\w+)$", r)
            if m:
                out[m.group(1).lower()] = r
    return out


def _norm(s):
    return re.sub(r"[\s\-]+", "_", s.lower())


def detect_surface(text):
    low = text.lower()
    hits = [s for s, words in SURFACE_SIGNALS
            if any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", low) for w in words)]
    return hits


def detect_repo(text, repos):
    """Longest explicit repo mention wins (spaces/hyphens treated as _)."""
    low = _norm(text)
    found = [r for r in repos
             if re.search(rf"(?<![a-z0-9]){re.escape(r.lower())}(?![a-z0-9])", low)]
    if found:
        return max(found, key=len), "explicit"
    for fam, lib in family_libraries(repos).items():
        if re.search(rf"\b{fam}\b", low):
            return lib, f"family word '{fam}'"
    return None, None


def page_for(surface, target, text):
    m = re.search(r"([\w./-]+\.(?:md|rst|py|ipynb))\b", text)
    if m:
        return m.group(1)
    return {
        "readme": "README.md",
        "setup": "docs/setup/<tool>.md",
        "rtd": "docs/<page>.rst (or .md)",
        "agent": "AGENTS.md / skills/<name>/... (as named)",
        "tutorial": "scripts/<package>/<example>.py",
    }[surface]


def move_targets(surface, category):
    if surface == "readme":
        out = ["advanced examples, benchmarks and history -> their own pages "
               "under docs/, linked by one-line bullets (rule 7)",
               "install mechanics -> a setup page per tool, docs/setup/<tool>.md "
               "(rule 1)"]
        if category == "assistant":
            out.append("prices, free tiers and supported agents -> link "
                       "the one shared AI-options page WRITING_STYLE.md rule 5 "
                       "names, never restate (rule 5)")
        out.append("agent-only instructions -> a short collapsed <details> "
                   "block at the bottom (rule 10)")
        return out
    if surface == "setup":
        return ["anything that changes (prices, tiers, support status) -> the "
                "one shared page it lives on (rule 5)",
                "deep troubleshooting -> its own page, linked from Next steps"]
    if surface == "rtd":
        return ["long reference material -> its own page in the toctree, "
                "linked by a short bullet that says what it shows (rule 7)",
                "agent-only notes -> AGENTS.md or a collapsed block (rule 10)"]
    return []


def build_decision(args):
    text, prompt_path = read_intent(args.intent)
    repos = known_repos()
    surfaces = detect_surface(text)
    target, how = detect_repo(text, repos)
    category = repos.get(target) if target else None
    notes = []

    if surfaces:
        surface = surfaces[0]
    elif category in ("workspace", "howto"):
        surface = "tutorial"
        notes.append("no surface named — inferred 'tutorial' from the target "
                     f"repo's category ({category})")
    elif target:
        surface = "readme"
        notes.append("no surface named — defaulted to the repo README; say "
                     "'setup page' or 'Read the Docs' if that is the page")
    else:
        fail(4, "cannot resolve a surface or a target repo from the intent — "
                "name the page (README, setup page, Read the Docs, tutorial, "
                "AGENTS.md) and the repo")
    if target is None:
        fail(4, f"surface '{surface}' resolved but no target repo — name the "
                "repo by its name in PyAutoMind/repos.yaml")
    if how and how.startswith("family word") and surface in ("readme", "setup"):
        notes.append(f"resolved {how} to the library {target}; name the "
                     "*_assistant or *_workspace repo explicitly if you meant "
                     "that page")
    mixed = surface in PEOPLE_FACING and "tutorial" in surfaces[1:]
    if mixed:
        notes.append("mixed document: WRITING_STYLE.md for the project "
                     "sections, TUTORIAL_WRITING_STYLE.md for the walkthrough "
                     "(skills/docs/docs.md)")

    gtext = guide_text()
    templates = guide_templates(gtext)
    applies = surface in PEOPLE_FACING
    if surface == "readme":
        template = templates.get("readme", [])
    elif surface == "setup":
        template = templates.get("setup", [])
    elif surface == "rtd":
        template = guide_journey(gtext)
        notes.append("the guide has no Read the Docs template — the rule 9 "
                     "journey order is the page skeleton")
    else:
        template = []

    siblings = []
    group = step_groups(repos).get(category or "")
    if group and target in group and surface in ("readme", "setup"):
        siblings = [r for r in group if r != target]
        if category == "assistant" and surface == "readme":
            notes.append("README.md is domain content in the clone partition — "
                         "`clone sync` will not carry it; mirror structural "
                         "changes to the sibling READMEs by hand")

    deferred = None
    if surface == "tutorial":
        low = text.lower()
        register = ("howto" if category == "howto"
                    or any(w in low for w in HOWTO_HINT_WORDS) else "workspace")
        deferred = {
            "conductor": "workspace",
            "register_hint": register,
            "command": f'bin/pyauto-brain workspace "{text.strip().splitlines()[0][:80]}"',
            "why": "tutorial science prose belongs to the Workspace conductor's "
                   "workspace/howto registers; its WorkspaceDecision is "
                   "authoritative for repo, register, placement and sibling",
        }

    if applies:
        style = STYLE_REL + (f" + {TUTORIAL_REL}" if mixed else "")
        checklist = guide_checklist(gtext)
        nxt = ("route into start_dev (work type docs/) → author against the "
               "template → `pyauto-brain docs audit <page>` before review; "
               "this decision writes nothing")
    elif surface == "tutorial":
        style = TUTORIAL_REL
        checklist = []
        nxt = ("run the Workspace conductor (command above) → start_dev → "
               "start_workspace → ship_workspace; this decision writes nothing")
    else:
        style = None
        checklist = [
            "WRITING_STYLE.md does not apply — agent-facing files follow their "
            "own conventions (see the guide's preamble)",
            "keep primary skill files within budget: "
            "bin/check_skill_line_counts.sh",
            "registry-generated blocks (AGENTS.md command surface) are "
            "regenerated with bin/install.sh --write-agents-surface, never "
            "hand-edited",
        ]
        nxt = ("route into start_dev (work type docs/); this decision writes "
               "nothing")

    title = text.strip().splitlines()[0].lstrip("# ").strip()[:88]
    return {
        "title": title,
        "prompt_path": prompt_path,
        "surface": surface,
        "surface_label": SURFACE_LABELS[surface],
        "target_repo": target,
        "repo_category": category,
        "page": page_for(surface, target, text),
        "writing_style_applies": applies,
        "style_guide": style,
        "page_template": template,
        "move_long_material_to": move_targets(surface, category),
        "siblings_in_step": siblings,
        "deferred_to": deferred,
        "checklist": checklist,
        "audit_command": (f"bin/pyauto-brain docs audit {target}/<page>"
                          if applies else None),
        "notes": notes,
        "next_action": nxt,
    }


def print_decision(d):
    print("== DocsDecision (decision only, writes nothing) ==")
    print(f"Intent:               {d['title']}")
    if d["prompt_path"]:
        print(f"Prompt file:          {d['prompt_path']}")
    print(f"Surface:              {d['surface']} ({d['surface_label']})")
    print(f"Target repo:          {d['target_repo']}"
          + (f" [{d['repo_category']}]" if d["repo_category"] else ""))
    print(f"Page:                 {d['page']}")
    print(f"WRITING_STYLE.md:     {'applies' if d['writing_style_applies'] else 'does not apply'}")
    print(f"Style guide:          {d['style_guide'] or '(agent conventions)'}")
    if d["page_template"]:
        print("Page template (from the style guide):")
        for i, s in enumerate(d["page_template"], 1):
            print(f"  {i}. {s}")
    if d["move_long_material_to"]:
        print("Move long material to:")
        for s in d["move_long_material_to"]:
            print(f"  - {s}")
    if d["siblings_in_step"]:
        print(f"Siblings in step:     {', '.join(d['siblings_in_step'])}")
    if d["deferred_to"]:
        df = d["deferred_to"]
        print(f"Deferred to:          {df['conductor']} conductor "
              f"(register hint: {df['register_hint']})")
        print(f"  run: {df['command']}")
        print(f"  why: {df['why']}")
    if d["checklist"]:
        print("Checklist:")
        for s in d["checklist"]:
            print(f"  - {s}")
    if d["audit_command"]:
        print(f"Audit:                {d['audit_command']}")
    for n in d["notes"]:
        print(f"Note:                 {n}")
    print(f"Next action:          {d['next_action']}")


# ---------------------------------------------------------------- audit ----

SCREEN_LINES = 60          # "within a screen of scrolling"
DENSE_WORDS = 110          # a paragraph this long wants a list (rule 8)
LONG_SENTENCE_WORDS = 35   # rule 11 "keep sentences short"
HEADING_WORDS = 6          # rule 12 "plain headings"
HEDGES = ("rather than assuming", "treat it as", "rather than tested",
          "check the provider", "it is worth noting", "please note",
          "note that", "be aware", "may or may not", "as far as we know",
          "should generally", "in most cases")
# Phrases that address an AI agent directly (a link to AGENTS.md, or "agents"
# as a topic word, is not agent-only text).
AGENT_MARKERS = re.compile(r"\b(notes? (for|to) (ai )?agents|for ai agents|"
                           r"agent instructions|instructions for (ai )?agents|"
                           r"if you are an? (ai|agent|llm)|ai agents?:|agents:)", re.I)
PRICE = re.compile(r"(?:[$£€]\s?\d|\b\d+\s?(?:usd|gbp)\b|\bper month\b|/month\b|"
                   r"\bfree tier\b)", re.I)
AGENT_FILES = ("AGENTS.md", "CLAUDE.md", "SKILL.md")


def strip_regions(lines):
    """Per line: (kind, text) — kind in code/comment/details/prose, with
    inline code and link targets removed from prose so jargon checks only see
    words a reader reads."""
    out, fence, comment, details = [], False, False, 0
    for raw in lines:
        s = raw.strip()
        if s.startswith(("```", "~~~")):
            fence = not fence
            out.append(("code", ""))
            continue
        if fence:
            out.append(("code", ""))
            continue
        if comment or s.startswith("<!--"):
            comment = "-->" not in s
            out.append(("comment", ""))
            continue
        if re.search(r"<details\b", s, re.I):
            details += 1
        kind = "details" if details else "prose"
        if re.search(r"</details>", s, re.I):
            details = max(0, details - 1)
        clean = re.sub(r"`[^`]*`", " ", raw)
        clean = re.sub(r"\]\([^)]*\)", "]", clean)
        clean = re.sub(r"<[^>]+>", " ", clean)
        clean = re.sub(r"https?://\S+", " ", clean)
        out.append((kind, clean))
    return out


def headings(lines, regions):
    hs = []
    for i, (raw, (kind, _)) in enumerate(zip(lines, regions)):
        if kind != "prose":
            continue
        m = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", raw)
        if m:
            hs.append({"line": i + 1, "level": len(m.group(1)), "text": m.group(2)})
        m = re.search(r"<h([1-6])[^>]*>(.*?)</h\1>", raw, re.I)
        if m:
            hs.append({"line": i + 1, "level": int(m.group(1)),
                       "text": re.sub(r"<[^>]+>", "", m.group(2))})
    return hs


def slug(text):
    t = re.sub(r"[^\w\- ]", "", text.lower()).strip()
    return re.sub(r" ", "-", t)


def paragraphs(regions):
    """Prose paragraphs as (first line no, text), lists and headings excluded."""
    paras, buf, start = [], [], None
    for i, (kind, text) in enumerate(regions):
        s = text.strip()
        is_block = (kind != "prose" or not s or s.startswith(("#", "-", "*", "|", ">"))
                    or re.match(r"^\d+\.", s))
        if is_block:
            if buf:
                paras.append((start, " ".join(buf)))
            buf, start = [], None
            continue
        if start is None:
            start = i + 1
        buf.append(s)
    if buf:
        paras.append((start, " ".join(buf)))
    return paras


def sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(*])", text) if s.strip()]


def detect_page_kind(path):
    name = path.name
    if name in AGENT_FILES or "skills" in path.parts or (
            "wiki" in path.parts and "core" in path.parts):
        return "agent"
    if name.lower().startswith("readme"):
        return "readme"
    if "setup" in path.parts:
        return "setup"
    if path.suffix in (".py", ".ipynb"):
        return "tutorial"
    return "rtd"


def check(cid, rule, kind, ok, finding, fixes):
    return {"id": cid, "rule": rule, "kind": kind,
            "status": "pass" if ok else "fix", "finding": finding,
            "fixes": [] if ok else fixes}


def audit_page(path, page_kind):
    lines = path.read_text(encoding="utf-8").splitlines()
    regions = strip_regions(lines)
    hs = headings(lines, regions)
    gtext = guide_text()
    paras = paragraphs(regions)
    prose_lines = [(i + 1, t) for i, (k, t) in enumerate(regions) if k == "prose"]
    results = []

    # 1. Title (README template) — mechanical.
    first_h = hs[0] if hs else None
    results.append(check(
        "title", "README template", "mechanical",
        bool(first_h and first_h["level"] == 1),
        f"first heading: {first_h['text']!r} (h{first_h['level']}, line {first_h['line']})"
        if first_h else "no heading at all",
        ["start the page with one `# Title` heading"]))

    h2 = [h for h in hs if h["level"] == 2]
    if page_kind == "readme":
        # 2. Image near the top — mechanical.
        top = "\n".join(lines[:20])
        has_img = bool(re.search(r"!\[|<img\b", top, re.I))
        results.append(check(
            "image", "README template", "mechanical", has_img,
            "image in the first 20 lines" if has_img else "no image in the first 20 lines",
            ["add the project logo or a figure under the title"]))
        # 3. Sections the template names — mechanical (heading text match).
        names = [h["text"].lower() for h in h2]
        gs = any("getting started" in n or "get started" in n or "install and start" in n
                 for n in names)
        lic = [h for h in h2 if "licen" in h["text"].lower()]
        results.append(check(
            "getting_started", "README template / rule 2", "mechanical", gs,
            "a Getting Started section is present" if gs else
            "no 'Getting Started' (or 'Install and start') section",
            ["add a short `## Getting Started` right after the introduction — a "
             "paragraph or two that gets the reader to the first prompt or command"]))
        lic_last = bool(lic) and h2[-1] in lic
        results.append(check(
            "license_last", "README template / rule 9", "mechanical", lic_last,
            "License is the last section" if lic_last else
            ("no License section" if not lic else
             f"License is not last (last section: {h2[-1]['text']!r})"),
            ["end the page with `## License` (only a collapsed agent note may follow)"]))
    if page_kind == "setup":
        want = [t for t in ("What it costs", "Install and start", "Next steps")]
        names = [h["text"].lower() for h in hs]
        missing = [w for w in want if not any(w.lower() in n for n in names)]
        results.append(check(
            "setup_sections", "setup-page template", "mechanical", not missing,
            "all template sections present" if not missing else
            f"missing: {', '.join(missing)}",
            [f"add a `## {w}` section" for w in missing]))

    # 4. Intro: 2-3 sentences before the first H2 — heuristic sentence split.
    first_h2_line = h2[0]["line"] if h2 else len(lines) + 1
    intro = [p for ln, p in paras if ln < first_h2_line]
    n_sent = sum(len(sentences(p)) for p in intro)
    results.append(check(
        "intro_length", "README template / rule 2", "heuristic", 1 <= n_sent <= 4,
        f"{n_sent} sentence(s) before the first section",
        ["cut the opening to two or three sentences on what the project is and "
         "who it is for; move the rest into a later section" if n_sent > 4 else
         "add two or three sentences under the title on what this is"]))

    # 5. First command/prompt within a screen — heuristic (fixed 60-line screen).
    first_code = next((i + 1 for i, (k, _) in enumerate(regions) if k == "code"), None)
    reachable = first_code is not None and first_code <= SCREEN_LINES
    results.append(check(
        "first_command", "checklist 1 / rule 2", "heuristic",
        reachable or page_kind == "rtd",
        f"first code block at line {first_code}" if first_code else
        "no code block or prompt on the page",
        [f"bring the first prompt or command into the first {SCREEN_LINES} lines "
         "— move explanation below it"]))

    # 6. Internal jargon in reader-visible prose — mechanical word match.
    jargon = guide_jargon(gtext)
    jhits = []
    for ln, t in prose_lines:
        for w in jargon:
            if re.search(rf"\b{re.escape(w)}s?\b", t, re.I):
                jhits.append((ln, w))
    results.append(check(
        "jargon", "rule 3 / checklist 2", "mechanical", not jhits,
        f"{len(jhits)} hit(s) of the guide's jargon list ({', '.join(jargon)})",
        [f"line {ln}: replace '{w}' with a plain word, or explain it" for ln, w in jhits[:12]]
        + ([f"... and {len(jhits) - 12} more"] if len(jhits) > 12 else [])))

    # 7. Hedging phrases — heuristic phrase list.
    hhits = [(ln, h) for ln, t in prose_lines for h in HEDGES if h in t.lower()]
    results.append(check(
        "hedging", "rule 4", "heuristic", not hhits,
        f"{len(hhits)} hedging phrase(s)",
        [f"line {ln}: drop the caveat '{h}' — say the useful thing plainly and link "
         "the detail" for ln, h in hhits[:8]]))

    # 8. Changeable facts restated — heuristic price/tier pattern.
    phits = [ln for ln, t in prose_lines if PRICE.search(t)]
    results.append(check(
        "changeable_facts", "rule 5 / checklist 3", "heuristic", not phits,
        f"{len(phits)} line(s) state a price or tier" if phits else "no prices or tiers stated",
        [f"line {ln}: link the one shared page (WRITING_STYLE.md rule 5) "
         "instead of restating the price/tier" for ln in phits[:8]]))

    # 9. Dense paragraphs — heuristic word count.
    dense = [(ln, len(p.split())) for ln, p in paras if len(p.split()) > DENSE_WORDS]
    results.append(check(
        "dense_paragraphs", "rule 8", "heuristic", not dense,
        f"{len(dense)} paragraph(s) over {DENSE_WORDS} words",
        [f"line {ln}: {n} words — break into a one-line intro and a bulleted list "
         "with bold lead words" for ln, n in dense]))

    # 10. Long sentences — heuristic sentence split.
    long_s = [(ln, len(s.split())) for ln, p in paras for s in sentences(p)
              if len(s.split()) > LONG_SENTENCE_WORDS]
    results.append(check(
        "long_sentences", "rule 11", "heuristic", not long_s,
        f"{len(long_s)} sentence(s) over {LONG_SENTENCE_WORDS} words",
        [f"paragraph at line {ln}: a {n}-word sentence — split it" for ln, n in long_s[:8]]))

    # 11. Dash/bracket chains — heuristic: >=2 em dashes or >=2 brackets in one sentence.
    chains = [ln for ln, p in paras for s in sentences(p)
              if s.count("—") + s.count(" -- ") >= 2 or s.count("(") >= 2]
    results.append(check(
        "dash_chains", "rule 11", "heuristic", not chains,
        f"{len(chains)} sentence(s) chain dashes or brackets",
        [f"paragraph at line {ln}: rewrite the dashed/bracketed aside as its own "
         "sentence" for ln in chains[:8]]))

    # 12. Exclamation marks — mechanical count in prose.
    bangs = sum(len(re.findall(r"!(?=\s|$)", t)) for _, t in prose_lines)
    results.append(check(
        "exclamations", "rule 11", "mechanical", bangs <= 1,
        f"{bangs} exclamation mark(s)",
        ["keep at most one exclamation mark on the page"]))

    # 13. Addresses the reader — heuristic.
    you = sum(len(re.findall(r"\byou(r|'re|'ll|'ve)?\b", t, re.I)) for _, t in prose_lines)
    results.append(check(
        "address_reader", "rule 11", "heuristic", you > 0,
        f"'you' appears {you} time(s)",
        ["address the reader as 'you' — say what they do"]))

    # 14. Plain headings — mechanical length/punctuation.
    bad_h = [h for h in hs if len(h["text"].split()) > HEADING_WORDS
             or re.search(r"[():]", h["text"])]
    results.append(check(
        "plain_headings", "rule 12", "mechanical", not bad_h,
        f"{len(bad_h)} heading(s) over {HEADING_WORDS} words or with brackets/colons",
        [f"line {h['line']}: shorten {h['text']!r}" for h in bad_h]))

    # 15. Agent-only text collapsed at the bottom — heuristic detection.
    loose = [ln for ln, t in prose_lines if AGENT_MARKERS.search(t)]
    det = [i + 1 for i, (k, _) in enumerate(regions) if k == "details"]
    last_h2 = h2[-1]["line"] if h2 else 0
    det_high = bool(det) and det[0] < last_h2
    results.append(check(
        "agent_text", "rule 10 / checklist 5", "heuristic", not loose and not det_high,
        (f"{len(loose)} uncollapsed agent-directed line(s)" if loose else
         "no uncollapsed agent-directed text") + ("; a <details> block sits above the last section"
                                       if det_high else ""),
        [f"line {ln}: move agent instructions into a short collapsed <details> block "
         "at the very bottom" for ln in loose[:6]]
        + (["move the <details> agent block below the last section"] if det_high else [])))

    # 16. Local links and anchors resolve — mechanical (offline: external links unchecked).
    anchors = {slug(h["text"]) for h in hs}
    broken, external = [], 0
    for i, raw in enumerate(lines):
        if regions[i][0] in ("code", "comment"):
            continue
        for target in re.findall(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", raw) + \
                re.findall(r"(?:href|src)=\"([^\"]+)\"", raw):
            if re.match(r"^[a-z]+:", target):
                external += 1
                continue
            file_part, _, anchor = target.partition("#")
            if not file_part:
                if anchor and anchor.lower() not in anchors:
                    broken.append((i + 1, target))
                continue
            if not (path.parent / file_part).exists():
                broken.append((i + 1, target))
    results.append(check(
        "links", "checklist 6", "mechanical", not broken,
        f"{len(broken)} broken local link(s); {external} external link(s) not checked (offline)",
        [f"line {ln}: '{t}' does not resolve" for ln, t in broken[:10]]))

    passed = sum(1 for r in results if r["status"] == "pass")
    unchecked = [
        "rule 1 (says what the reader does, not how it works) — judgment",
        "rule 6 (examples re-explained in the surrounding prose) — judgment",
        "rule 9 (full journey order beyond Getting Started/License) — judgment",
        "links from OTHER pages into sections renamed here — needs the repo's "
        "other pages; grep them",
    ]
    return {
        "page": str(path),
        "page_kind": page_kind,
        "style_guide": STYLE_REL,
        "score": round(100 * passed / len(results)),
        "passed": passed,
        "total": len(results),
        "checks": results,
        "not_checked": unchecked,
    }


def build_audit(args):
    path = Path(args.page)
    if not path.is_file():
        alt = Path(PYAUTO_ROOT) / args.page
        if not alt.is_file():
            fail(4, f"no such page: {args.page}")
        path = alt
    kind = args.kind or detect_page_kind(path)
    if kind in ("agent", "tutorial"):
        return {
            "page": str(path), "page_kind": kind, "style_guide": None,
            "score": None, "passed": 0, "total": 0, "checks": [],
            "not_checked": [],
            "note": ("WRITING_STYLE.md does not apply to agent-facing files"
                     if kind == "agent" else
                     "tutorial prose follows TUTORIAL_WRITING_STYLE.md and the "
                     "Workspace conductor's format checklist; this audit scores "
                     "people-facing pages only"),
        }
    return audit_page(path, kind)


def print_audit(a):
    print(f"== DocsAudit — {a['page']} ({a['page_kind']}) — read-only ==")
    if a.get("note"):
        print(f"Not scored:           {a['note']}")
        return
    print(f"Against:              {a['style_guide']}")
    print(f"Score:                {a['score']}/100 ({a['passed']}/{a['total']} checks pass)")
    for r in a["checks"]:
        mark = "ok " if r["status"] == "pass" else "FIX"
        print(f"  [{mark}] {r['id']:17s} {r['rule']:28s} ({r['kind']}) {r['finding']}")
    fixes = [(r["id"], f) for r in a["checks"] for f in r["fixes"]]
    if fixes:
        print("Fixes:")
        for cid, f in fixes:
            print(f"  - [{cid}] {f}")
    print("Not checked (judgment — read the page):")
    for s in a["not_checked"]:
        print(f"  - {s}")


# ----------------------------------------------------------------- main ----


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "audit":
        parser = argparse.ArgumentParser(prog="docs audit")
        parser.add_argument("page", help="the page to score (README.md, docs/...)")
        parser.add_argument("--kind", choices=["readme", "setup", "rtd", "agent", "tutorial"],
                            default=None, help="override the page kind")
        parser.add_argument("--json", action="store_true")
        args = parser.parse_args(argv[1:])
        audit = build_audit(args)
        print(json.dumps(audit, indent=2)) if args.json else print_audit(audit)
        sys.exit(0)

    parser = argparse.ArgumentParser(prog="docs", description=__doc__)
    parser.add_argument("intent", nargs="?", default=None,
                        help="raw intent text, or a PyAutoMind prompt path")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not args.intent or not args.intent.strip():
        fail(5, "no intent given — pass raw text, a PyAutoMind prompt path, or "
                "`audit <page>`")
    decision = build_decision(args)
    print(json.dumps(decision, indent=2)) if args.json else print_decision(decision)
    sys.exit(0)


if __name__ == "__main__":
    main()
