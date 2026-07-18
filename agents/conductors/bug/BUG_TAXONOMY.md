# Bug taxonomy & surfaces known to the Bug Agent

This audit records how the Bug Agent **classifies** a defect, decides **where the fix
belongs**, and which **health inputs** it reads. It mirrors the Feature Agent's
[`../feature/MIND_TAXONOMY.md`](../feature/MIND_TAXONOMY.md) and reuses that agent's
deterministic core by import (repo/target parsing, the difficulty heuristic, PyAutoMemory
routing, in-flight down-ranking all live in `_feature.py`). The Bug Agent adds only the
bug-specific reasoning in `_bug.py`. Sources of truth: `PyAutoMind/ROUTING.md`,
`PyAutoBrain/AGENTS.md`, `agents/faculties/vitals/`, `PyAutoMind/bug/health_fixes/`.

## Classification (typing the threat)

A first-pass heuristic (`classify()` in `_bug.py`), deliberately transparent so the
reasoning layer can override it — exactly as the difficulty heuristic is.

| Axis | Values | How it is derived |
|------|--------|-------------------|
| **severity** | critical · high · medium · low | keyword signals (crash/release-block → critical; regression/wrong-result → high; typo/cosmetic → low); a ≥3-repo blast radius nudges up. |
| **scope** | single-file · single-repo · multi-repo · ecosystem | repo blast radius: ≤1 → single-repo, 2 → multi-repo, ≥3 → ecosystem. |
| **type** | test-failure · runtime-error · wrong-result · docs-error · workflow-error · config-error · release-error · flaky · unknown | first matching signal group in `TYPE_ORDER`; genuine-defect types rank above administrative ones. |
| **confidence** | high · medium · low | high when the type is clear and no ambiguity keywords fire; low when the type is `unknown` or the report is exploratory. |

**Signal discipline.** Type signals are specific on purpose: generic words ("workflow",
"pipeline") appear in ordinary science prompts and would mis-type a real defect, so they
are omitted; a specific marker like `docstring` for `docs-error` is kept because it is
not generic. When the lists drift, edit `TYPE_SIGNALS` / `TYPE_ORDER` in `_bug.py` and
this table together — never encode them where the agent re-derives at runtime.

## Fix locus — the targeted response (no autoimmunity)

The immune system's core decision: *where does the fix belong?* The strong prior is a
**general fix in library source**; a user-facing workspace script is documentation and
must not be degraded to squash a symptom. `fix_locus()` returns a locus + a caution:

| Situation | Locus | Rule |
|-----------|-------|------|
| target is an organ (PyAutoBrain/Heart/Build/Mind/Memory) | **infrastructure** | fix the organ; keep the health/exec/reasoning boundaries intact. |
| any **library** repo resolves | **library source (general fix)** | fix the class of failure at the source. If a workspace also appears, do **not** touch its scripts to mask it. |
| **workspace** only, `config-error` | **workspace config** | use `config/build/env_vars.yaml` / `no_run.yaml` — never inline edits to the script body. |
| **workspace** only, other type | **workspace source-first** | first ask whether the real defect is upstream in library source; edit the script only if the defect truly lives there, and never in a way that reduces clarity. |
| nothing resolves | **unresolved** | locate the owning repo before deciding. |

**The autoimmune failure mode** (what agents do *without* this context, and must not):
injecting test env-vars into a script, hard-coding an output path, mutating
`os.environ`, adding a silent guard that swallows bad data, or rebaselining a tutorial
to conceal a library regression. Each trades the script's didactic clarity for a local
symptom fix — damaging the tissue the fix exists to protect. Prefer the general source
fix; when a workspace knob is genuinely needed, it goes through the sanctioned config
files, not the script.

## Reproduction (identify, never run)

`reproduction()` returns *known / unknown / a PyAutoHeart check* — the Bug Agent
**names** the reproduction; it never executes it (that is the vitals faculty / Heart /
smoke tests). A Heart-derived finding carries its check name; a test-failure names the
failing test to run; a traceback in the prompt is a known repro; an exploratory report
is `unknown` and forces `investigate-first`.

## Fix strategy & workflow

`fix_strategy()` → `direct · investigate-first · split-into-phases · defer/re-home`:
low confidence or human-judgement → investigate first; large/too-large → phase it
(prefer several small shippable fix PRs); a mis-filed prompt → defer/re-home. The
`recommended_workflow` is always a development path — `library | workspace | combined |
infrastructure` — because a bug still ships through `start_library` / `start_workspace`;
a bug is never re-homed to `research/` just because no repo resolved.

## The two health inputs (health mode)

PyAutoHeart measures health; the Bug Agent reasons about failures and must **not**
re-implement a Heart check. `bug.sh health` reads two complementary signals:

1. **Live vitals verdict** — `consult_vitals_verdict` (the vitals faculty; only it talks
   to Heart). "What is RED/YELLOW right now."
2. **Filed PyAutoHeart issues** — `gh issue list --repo PyAutoLabs/PyAutoHeart --state
   open` (`$PYAUTO_HEART_REPO` overridable). The durable, detailed findings Heart
   authored (e.g. #27 release-fidelity, #19/#7 degraded-health, #10 url-check).

For each finding `_bug.py` emits a first-pass **category hint** (real-bug / config /
flaky / expected, from the issue title + labels); the reasoning layer confirms it and
decides where the fix belongs (affected repo, PyAutoHeart, PyAutoHands, PyAutoBrain).
Confirmed real defects become `PyAutoMind/bug/health_fixes/<name>.md` prompts and enter
the normal workflow; flaky / expected findings are left to the Health conductor's loop.
Validation after patching is always the vitals faculty (`pyauto-heart readiness` GREEN,
or acknowledged YELLOW), never a check re-run here.

## Difficulty & selection (reused, severity-weighted)

Difficulty is the Feature Agent's heuristic verbatim (`F.estimate_difficulty` — repos
affected, prompt size, scientific complexity, architectural risk, test burden, memory
context; thresholds `≤2 small · ≤5 medium · ≤9 large · >9 too-large`). Selection scans
`bug/**` (excluding `README.md`), down-ranks paths referenced in `active.md` /
`planned.md`, and ranks **severity-first** by default and under `--impact` (a bug list is
a triage queue); `--difficulty easy` / `--budget` / `--model weak` flip to smallest-first
for limited-token runs; `--ambitious` / `--model strong` prefer the largest.

## The diagnosis-faculty seam

The pure, side-effect-free reasoning here — `classify()` + `likely_owner()` +
`fix_locus()` — is the shape of a future read-only **`diagnosis` faculty** under
`agents/faculties/diagnosis/`, reusable by the Feature Agent's re-homing and the Health
conductor's triage. It is kept inline in the Bug conductor for v1 (keep the conductor set
small; don't multiply faculties prematurely), with this as the documented seam.

## Boundary audit — reasoning vs. health vs. execution

```
intent      → PyAutoMind   (bug/* prompts, bug/health_fixes/, active/planned state)
reasoning   → PyAutoBrain  (Bug Agent — this; reuses the Feature core)
knowledge   → PyAutoMemory (recurring failures / prior fixes / flaky tests; cited, not invented)
health      → PyAutoHeart  (via the vitals faculty + filed Heart issues; never re-implemented)
execution   → PyAutoHands  (via start_dev / ship_* — never run by this agent)
```

No execution, health-checking, or knowledge-authoring logic lives in the Bug Agent. It
detects, classifies, locates, and plans — then hands a `BugDecision` to the workflow.
