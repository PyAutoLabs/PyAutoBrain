#!/usr/bin/env bash
# agents/conductors/health/health.sh — the health conductor (the iterate-until-
# green LOOP).
#
# The health conductor is the organism's clinician: the brain's vagus-nerve link
# to the Heart. It runs the health loop *with a human* —
#
#     assess -> triage -> recommend + checkpoint -> (on go-ahead) dispatch a
#     validation leg (DELEGATED) -> re-assess -> repeat
#
# — until PyAutoHeart goes GREEN (or the human stops). It is a CONDUCTOR: it
# decides and drives, delegating every ACTION to the agent that owns it, and
# reimplements no check of its own.
#
# What each loop stage means for THIS script (the deterministic footing; the
# conversational mediation is the Brain session's, layered on top):
#
#   assess     render the unified card (the vitals faculty draws Heart's board)
#              and ADOPT Heart's verdict verbatim — never re-derive a gate here.
#   triage     map every readiness reason to its Heart capability (via the
#              manifest — reason over CATEGORIES of signal, not hard-coded check
#              names), and split *expected first-run gaps* (no validation report,
#              install-verify never run) from *real problems* (failing CI, dirty
#              tree, off-main, behind, version skew). Rank by what blocks green.
#   recommend  surface the SINGLE best next action + a checkpoint. Cite
#              `pyauto-heart fix <topic>` only when Heart's verdict names that
#              failure class (topics: ci / dirty / drift / timing).
#   dispatch   (NOT done here) on the human's go-ahead the Brain session drives
#              the leg via the RELEASE conductor (`pyauto-brain release
#              validate`), which owns the MCP GitHub boundary. This conductor
#              never dispatches or mutates a repo itself.
#   re-assess  re-run this script; the loop repeats until GREEN or the human stops.
#
# Boundaries (this cut):
#   * CONSULTS the vitals faculty for every verdict (read-only). Only vitals /
#     Heart measures; this conductor never re-derives a verdict.
#   * DELEGATES all GitHub dispatch to the release conductor
#     (`pyauto-brain release validate ...`); it never dispatches itself.
#   * Scope = validation + recommend. It RECOMMENDS the next dispatch; it does NOT
#     auto-run it. Every dispatch is a human checkpoint. Repo-editing fixes are a
#     deliberate FOLLOW-UP, not in this cut.
#
# Usage:
#   health.sh                 # assess: card + adopt verdict + triage + recommend
#   health.sh assess          # same as the no-arg assess
#   health.sh triage          # triage + recommend only (no card re-render)
#   health.sh recommend       # the single recommended next checkpoint only
#   health.sh --json [sub]     # machine footing for the Brain session
#   health.sh -h|--help       # this header
#
# Exit codes mirror the ADOPTED verdict so a caller (and the loop) can branch:
#   0 green · 2 yellow · 3 red · 4 unknown. A CLI usage error (unknown
# subcommand) exits 5 — kept distinct from the verdict codes so misuse is never
# read as a real YELLOW.

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

# ---------------------------------------------------------------------------
# Argument parsing: one optional subcommand + a --json flag (order-independent).
# ---------------------------------------------------------------------------
sub="assess"
json_only=0
for arg in "$@"; do
  case "$arg" in
    --json) json_only=1 ;;
    -h|--help)
      sed -n '2,60p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    assess|triage|recommend)
      sub="$arg"
      ;;
    *)
      echo "health: unknown subcommand '$arg' (supported: assess | triage | recommend [--json])" >&2
      exit 5   # usage error — distinct from the verdict codes (2=YELLOW)
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Locate the vitals faculty (the single component that talks to Heart) and the
# Heart capability manifest (Heart self-describing its surface — never vendored).
# The manifest is OPTIONAL context: triage reasons about categories of signal and
# degrades gracefully if it is absent.
# ---------------------------------------------------------------------------
vitals="$(_agents_dir)/faculties/vitals/vitals.sh"
manifest=""
if heart_dir="$(_resolve_dir PYAUTO_HEART PyAutoHeart 2>/dev/null)"; then
  cand="$heart_dir/health_agent/capabilities.yaml"
  [[ -f "$cand" ]] && manifest="$cand"
fi

# _read_readiness — echo the authoritative readiness JSON *through the vitals
# faculty* (never Heart directly). Adopt-not-re-derive: we only read the verdict
# and reasons Heart already computed. Emits "{}" if the read fails.
_read_readiness() {
  local out
  out="$(bash "$vitals" readiness --json 2>/dev/null)"
  if [[ -z "$out" ]]; then printf '{}'; else printf '%s' "$out"; fi
}

# _triage — the deterministic triage + recommendation engine. Reads readiness
# JSON on stdin, emits a triage object on stdout. MANIFEST (optional) lets the
# engine confirm which capability ids Heart actually exposes; the reason->
# capability mapping is by signal CATEGORY (keyword class), so a renamed check
# still lands in the right category.
_triage() {
  MANIFEST="$manifest" python3 -c '
import json, os, re, sys

try:
    r = json.load(sys.stdin)
except Exception:
    r = {}

verdict = (r.get("verdict") or "unknown").lower()
score = r.get("score")
ts = r.get("ts")
red = list(r.get("red_reasons") or [])
yellow = list(r.get("yellow_reasons") or [])

# Optional: the set of capability ids Heart advertises, so triage stays honest
# about the surface it maps to (reason over categories present in the manifest,
# not invented names). Absent manifest -> empty set -> mapping still works.
known_caps = set()
mpath = os.environ.get("MANIFEST", "")
if mpath and os.path.isfile(mpath):
    try:
        import yaml  # PyYAML ships with Heart; optional here
        m = yaml.safe_load(open(mpath)) or {}
        for grp in ("continuous_checks", "deep_checks", "release_validation",
                    "dashboard"):
            for item in (m.get(grp) or []):
                cid = item.get("id")
                if cid:
                    known_caps.add(cid)
    except Exception:
        known_caps = set()

# Reason -> (capability, kind) by CATEGORY of signal. kind is one of:
#   real-problem  a genuine health signal to act on now (gates green)
#   baseline-gap  an expected first-run unknown you accept (standing YELLOW)
#   advisory      monitoring only; does not gate readiness
# fix_topic is the `pyauto-heart fix <topic>` class IFF Heart offers one for that
# failure class (ci / dirty / drift / timing); otherwise None (never invented).
# Order matters: first match wins, so put specific patterns before generic ones.
RULES = [
    (re.compile(r"uncommitted|\bdirty\b",            re.I), "repo_state",     "real-problem", "dirty"),
    (re.compile(r"not main|on branch",               re.I), "repo_state",     "real-problem", None),
    (re.compile(r"behind origin|\bbehind\b",         re.I), "repo_state",     "real-problem", None),
    (re.compile(r"AHEAD|MISMATCH|version.?skew|pinned|version\.txt|general\.yaml", re.I),
                                                             "version_skew",   "real-problem", None),
    (re.compile(r"timing|slow|regression",           re.I), "script_timing",  "real-problem", "timing"),
    (re.compile(r"worktree|drift",                   re.I), "worktree_drift", "advisory",     "drift"),
    (re.compile(r"\bCI\b",                           re.I), "ci_status",      "real-problem", "ci"),
    (re.compile(r"open PR",                          re.I), "open_prs",       "advisory",     None),
    (re.compile(r"test run|report\.json|test_run",   re.I), "test_run",       "baseline-gap", None),
    (re.compile(r"install verif|verify_install",     re.I), "verify_install", "baseline-gap", None),
    (re.compile(r"release validation|validation report", re.I),
                                                             "validate",       "baseline-gap", None),
    (re.compile(r"\burl\b",                          re.I), "url_check",      "advisory",     None),
]

# Rank buckets: lower sorts first (most blocking first).
KIND_RANK = {"real-problem": 0, "advisory": 2, "baseline-gap": 3}
SEV_RANK = {"red": 0, "yellow": 1}

def repo_of(reason):
    # "PyAutoConf: on branch ..." -> "PyAutoConf"; else None.
    m = re.match(r"\s*([A-Za-z0-9_\-]+)\s*:", reason)
    return m.group(1) if m else None

def classify(reason, severity):
    for rx, cap, kind, fix in RULES:
        if rx.search(reason):
            return cap, kind, fix
    # Unmatched: an unknown. A red unknown is a real problem; a yellow one is a
    # baseline gap (never silently green, never escalated).
    return "unknown", ("real-problem" if severity == "red" else "baseline-gap"), None

items = []
for severity, reasons in (("red", red), ("yellow", yellow)):
    for reason in reasons:
        cap, kind, fix_topic = classify(reason, severity)
        # Severity wins over the keyword class: anything Heart put in red_reasons
        # is a release blocker to act on now, never a "baseline gap" you accept.
        # (E.g. absent validation -> "no release validation" is a yellow
        # baseline-gap; a FAILED validation -> "release validation FAILED" is red
        # and a real problem, even though both map to the `validate` capability.)
        if severity == "red" and kind != "real-problem":
            kind = "real-problem"
        repo = repo_of(reason)
        fix_cmd = None
        if fix_topic:
            # Cite a fix ONLY for a named failure class (Heart offers ci/dirty/
            # drift/timing). Append the repo/project where the topic takes one.
            suffix = (" " + repo) if repo else ""
            if fix_topic in ("ci", "dirty", "timing"):
                fix_cmd = "pyauto-heart fix " + fix_topic + suffix
            elif fix_topic == "drift":
                fix_cmd = "pyauto-heart fix drift"
        items.append({
            "reason": reason,
            "severity": severity,
            "capability": cap,
            "capability_known": (cap in known_caps) if known_caps else None,
            "kind": kind,
            "blocks_green": severity == "red" or kind == "real-problem",
            "fix": fix_cmd,
        })

items.sort(key=lambda it: (KIND_RANK.get(it["kind"], 4),
                           SEV_RANK.get(it["severity"], 2),
                           it["capability"]))

blockers = [it for it in items if it["severity"] == "red"]
warn_real = [it for it in items if it["severity"] == "yellow" and it["kind"] == "real-problem"]
gaps = [it for it in items if it["kind"] == "baseline-gap"]
advisory = [it for it in items if it["kind"] == "advisory"]

# ---- the SINGLE recommended next checkpoint -------------------------------
CHECKPOINT = ("This is a checkpoint: the health conductor RECOMMENDS but will "
              "NOT run it. Confirm to proceed; the Brain session then drives the "
              "leg and Heart re-judges.")

def top(lst):
    return lst[0] if lst else None

if verdict == "green":
    rec = {"action": "none", "command": None,
           "headline": "GREEN — the organism is release-healthy. No action needed.",
           "detail": "A release conductor (pyauto-brain release) may now proceed.",
           "checkpoint": None}
elif blockers:
    t = top(blockers)
    cap = t["capability"]
    reason = t["reason"]
    if t["fix"]:
        cmd = t["fix"]
        detail = ("Top blocker maps to the " + cap + " capability; Heart offers a "
                  "remediation entry point. Resolving blockers is outside this "
                  "validation+recommend cut, so this is handed to you / a "
                  "feature-agent session.")
    else:
        cmd = None
        detail = ("Top blocker maps to the " + cap + " capability, which has no "
                  "`pyauto-heart fix` shortcut — it is human / Release-Agent work "
                  "(e.g. land the dev branch back to main). NOT a health-conductor "
                  "dispatch. Do NOT dispatch a release rehearsal while RED: the "
                  "release preflight (Stage 0/1) will abort on this signal anyway.")
    rec = {"action": "resolve-blockers", "command": cmd,
           "headline": "RED — resolve the top blocker first: " + reason,
           "detail": detail, "checkpoint": CHECKPOINT}
elif warn_real:
    t = top(warn_real)
    cap = t["capability"]
    reason = t["reason"]
    rec = {"action": "resolve-warning", "command": t["fix"],
           "headline": "YELLOW — a genuine warning to act on: " + reason,
           "detail": "Maps to the " + cap + " capability. Clear it, then re-assess.",
           "checkpoint": CHECKPOINT}
elif gaps or verdict == "yellow":
    # Pure baseline gaps: the classic first-run YELLOW. The one leg that closes
    # the release-validation gap and makes GREEN reachable is release validate.
    rec = {"action": "release-validate",
           "command": "pyauto-brain release validate",
           "headline": ("YELLOW — only expected first-run gaps remain (no fresh "
                        "release validation for the current source)."),
           "detail": ("Run the full Stages 0-3 orchestrator: TestPyPI rehearsal + "
                      "wheel integration at release fidelity -> Heart ingests -> "
                      "re-judge. This is the leg that flips the no-release-"
                      "validation gap and makes GREEN reachable. DELEGATED to the "
                      "release "
                      "conductor (it owns the MCP GitHub boundary)."),
           "checkpoint": CHECKPOINT}
else:
    rec = {"action": "refresh", "command": "pyauto-brain vitals",
           "headline": "UNKNOWN — could not obtain a verdict from the vitals faculty.",
           "detail": "Refresh Heart, then re-run the health conductor.",
           "checkpoint": None}

print(json.dumps({
    "verdict": verdict,
    "score": score,
    "ts": ts,
    "counts": {
        "blockers": len(blockers),
        "warnings_real": len(warn_real),
        "expected_gaps": len(gaps),
        "advisory": len(advisory),
    },
    "items": items,
    "recommendation": rec,
}, indent=2))
'
}

# _exit_code_for <verdict> — map the adopted verdict to the loop exit code.
_exit_code_for() {
  case "$1" in
    green) return 0 ;;
    yellow) return 2 ;;
    red) return 3 ;;
    *) return 4 ;;
  esac
}

# _render_triage_human <triage-json> — pretty-print the triage + recommendation.
_render_triage_human() {
  printf '%s' "$1" | python3 -c '
import json, sys
t = json.load(sys.stdin)
v = t["verdict"].upper()
c = t["counts"]
score = t.get("score")
head = "-- Triage (adopted verdict: " + v
if score is not None:
    head += ", score " + str(score)
head += ") --"
print(head)
print("   " + str(c["blockers"]) + " blocker(s) · "
      + str(c["warnings_real"]) + " real warning(s) · "
      + str(c["expected_gaps"]) + " expected first-run gap(s) · "
      + str(c["advisory"]) + " advisory")
print()

def show(title, kinds):
    rows = [it for it in t["items"] if it["kind"] in kinds]
    if not rows:
        return
    print(title)
    for it in rows:
        mark = "✗" if it["severity"] == "red" else "!"
        line = "  " + mark + " [" + it["capability"] + "] " + it["reason"]
        if it.get("fix"):
            line += "   -> " + it["fix"]
        print(line)
    print()

show("Real problems (act on — these block green):", {"real-problem"})
show("Expected first-run gaps (standing YELLOW — accept, not action items):", {"baseline-gap"})
show("Advisory (monitoring only — does not gate readiness):", {"advisory"})

rec = t["recommendation"]
print("== Recommended next checkpoint ==")
print("  " + rec["headline"])
if rec.get("command"):
    print("    $ " + rec["command"])
if rec.get("detail"):
    print("  " + rec["detail"])
if rec.get("checkpoint"):
    print("  " + rec["checkpoint"])
'
}

# ---------------------------------------------------------------------------
# assess: the full loop-iteration footing — card + verdict + triage + recommend.
# ---------------------------------------------------------------------------
if [[ "$sub" == "assess" && "$json_only" -eq 0 ]]; then
  echo "== health: assessing organism health (consulting the vitals faculty) =="
  if [[ -f "$vitals" ]]; then
    bash "$vitals" || true
  else
    echo "health: vitals faculty not found at $vitals" >&2
  fi
  echo
fi

# Read the authoritative verdict + reasons (through the faculty) and triage them.
readiness_json="$(_read_readiness)"
triage_json="$(printf '%s' "$readiness_json" | _triage)"

verdict="$(printf '%s' "$triage_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("verdict","unknown"))' 2>/dev/null)"
[[ -z "$verdict" ]] && verdict="unknown"

if [[ "$json_only" -eq 1 ]]; then
  # Machine footing for the Brain session: verdict + triage + the single rec.
  printf '%s\n' "$triage_json"
  _exit_code_for "$verdict"; exit $?
fi

case "$sub" in
  assess)
    echo "== health: adopted verdict = ${verdict} =="
    echo
    _render_triage_human "$triage_json"
    echo
    echo "(Re-run \`pyauto-brain health\` after the recommended leg lands to loop."
    echo " The loop ends when Heart reports GREEN — or when you stop.)"
    ;;
  triage)
    _render_triage_human "$triage_json"
    ;;
  recommend)
    printf '%s' "$triage_json" | python3 -c '
import json, sys
rec = json.load(sys.stdin)["recommendation"]
print(rec["headline"])
if rec.get("command"):
    print("  $ " + rec["command"])
if rec.get("checkpoint"):
    print("  " + rec["checkpoint"])
'
    ;;
esac

_exit_code_for "$verdict"; exit $?
