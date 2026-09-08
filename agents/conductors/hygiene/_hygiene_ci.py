#!/usr/bin/env python3
"""
Hygiene ``ci`` mode: rank the slowest parts of CI from the Heart board.

The Heart already measures CI cost and publishes it, machine-readable, as the
``performance`` block of its board (``board.json``, schema v3):

* ``scripts.rows`` — one row per smoke-listed workspace script per python leg
  (the per-script timings the smoke gate uploads as an artifact);
* ``unit.tests``  — the slowest unit tests per library, from the test gates;
* ``gates``       — every workflow's wall-clock distribution (median / max).

Until now the only consumer was a human reading the ⏱ section. This helper is
the conductor's read of the same surface: it fetches the board once, ranks the
three lanes, folds the python legs of a script into ONE candidate (the slowest
leg is the cost the gate pays; both legs run in parallel so the gate waits for
the slower), and emits a ranked worklist — each item carrying the evidence a
fix needs (seconds, share of its leg, cache state, run URL) plus, when the
script is checked out locally, a *lever* read from the file itself.

Measurement lives in Heart; hygiene acts. Nothing here re-times anything and
nothing here edits a script: the ``/ci_speedup`` skill takes this worklist and
drives each fix through the ordinary dev flow.

Where the board comes from (first hit wins):

1. ``--board <path-or-url>`` / ``HYGIENE_HEART_BOARD``;
2. the published copy on the organism's Pages —
   ``https://<org>.github.io/<heart>/board.json`` where ``<org>`` is the most
   common GitHub owner in the body map (never hardcoded — tenant firewall) and
   ``<heart>`` is the ``heart_board`` policy key (default ``PyAutoHeart``);
3. a local Heart checkout's ``board/board.json`` under ``$PYAUTO_ROOT`` — the
   same fallback the Brain board uses when Pages is unreachable.

Levers (the ``lever`` field) are heuristics READ from the script text, each a
plain fact about the file rather than a diagnosis:

* ``env_knob``      — the script reads an ``os.environ.get("NAME", "<int>")``
                      sizing knob: a ``set:`` override in the smoke profile can
                      shrink the run without touching the file;
* ``simulates``     — it calls ``should_simulate`` and spawns the simulator
                      when the dataset is absent: with the dataset cache cold
                      the simulation is paid inside the script's own timing;
* ``jax_jit``       — it JITs (``jax.jit`` / ``ENV: jax``): compile cost, paid
                      in full on a ``cache_jax: miss`` leg;
* ``full_datasets`` — its ``ENV:`` releases ``PYAUTO_SMALL_DATASETS``;
* ``real_search``   — its ``ENV:`` releases ``PYAUTO_TEST_MODE`` (the search
                      really runs);
* ``subprocess``    — it spawns a child interpreter (a second import of the
                      science stack inside the timing);
* ``plots``         — it draws (``aplt.`` / ``plt.``) — cheap per call, not
                      cheap in a loop.

Usage
-----
    _hygiene_ci.py [--board PATH|URL] [--top N] [--lane scripts|tests|gates|all]
                   [--scripts-root DIR] [--json]

Exit codes: 0 ranked; 3 no board reachable (prints where it looked).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _hygiene_repos import resolve_map  # noqa: E402

DEFAULT_HEART = "PyAuto" + "Heart"   # an organ: framework identity, not an instance fact
BOARD_FILENAME = "board.json"
FETCH_TIMEOUT_S = 20

# --- Source resolution -------------------------------------------------------


def derive_org() -> str | None:
    """The organism's GitHub owner = the most common owner in the body map."""
    path = resolve_map()
    if path is None:
        return None
    homes = re.findall(r"^\s+github:\s*(\S+)\s*$", path.read_text(encoding="utf-8"), re.M)
    owners = [h.split("/")[0] for h in homes if "/" in h]
    return max(set(owners), key=owners.count) if owners else None


def pyauto_root() -> Path:
    root = os.environ.get("PYAUTO_ROOT")
    if root:
        return Path(root)
    # .../<checkout>/agents/conductors/hygiene/_hygiene_ci.py -> the repos' parent
    return HERE.parents[3]


def candidate_sources(explicit: str | None, heart_repo: str) -> list[str]:
    out: list[str] = []
    if explicit:
        out.append(explicit)
    env = os.environ.get("HYGIENE_HEART_BOARD")
    if env:
        out.append(env)
    org = derive_org()
    if org:
        out.append(f"https://{org.lower()}.github.io/{heart_repo}/{BOARD_FILENAME}")
    for rel in (Path("board") / BOARD_FILENAME, Path("docs") / BOARD_FILENAME, Path(BOARD_FILENAME)):
        out.append(str(pyauto_root() / heart_repo / rel))
    return out


def load_board(source: str) -> dict | None:
    try:
        if source.startswith(("http://", "https://")):
            req = urllib.request.Request(source, headers={"User-Agent": "pyauto-brain-hygiene"})
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8"))
        path = Path(source)
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None
    return None


# --- Ranking -----------------------------------------------------------------


def _num(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def rank_scripts(perf: dict) -> list[dict]:
    """One candidate per (repo, entry): the slowest python leg, with every leg's
    seconds kept for the record and the share of that leg's total."""
    scripts = perf.get("scripts") or {}
    leg_totals: dict[tuple, float | None] = {}
    for leg in scripts.get("repos") or []:
        if isinstance(leg, dict):
            leg_totals[(leg.get("repo"), str(leg.get("python")))] = _num(leg.get("total_s"))
    folded: dict[tuple, dict] = {}
    for row in scripts.get("rows") or []:
        if not isinstance(row, dict):
            continue
        seconds = _num(row.get("seconds"))
        if seconds is None:
            continue  # a null row never ran — never a candidate
        key = (row.get("repo"), row.get("entry"))
        item = folded.setdefault(key, {
            "lane": "scripts", "repo": row.get("repo"), "entry": row.get("entry"),
            "seconds": 0.0, "legs": {}, "python": None, "run_url": None,
            "cache_jax": None, "cap_s": None, "status": None, "prev_s": None, "prompt": None,
        })
        item["legs"][str(row.get("python"))] = seconds
        if seconds > item["seconds"]:
            item.update({
                "seconds": seconds, "python": str(row.get("python")),
                "run_url": row.get("run_url"), "cache_jax": row.get("cache_jax"),
                "cap_s": _num(row.get("cap_s")), "status": row.get("status"),
                "prev_s": _num(row.get("prev_s")), "prompt": row.get("prompt"),
            })
    for item in folded.values():
        total = leg_totals.get((item["repo"], item["python"]))
        item["share_of_leg"] = round(item["seconds"] / total, 3) if total else None
        cap = item.get("cap_s")
        item["share_of_cap"] = round(item["seconds"] / cap, 3) if cap else None
    return sorted(folded.values(), key=lambda i: -i["seconds"])


def rank_tests(perf: dict) -> list[dict]:
    unit = perf.get("unit") or {}
    folded: dict[tuple, dict] = {}
    for row in unit.get("tests") or []:
        if not isinstance(row, dict):
            continue
        seconds = _num(row.get("seconds"))
        if seconds is None:
            continue
        key = (row.get("repo"), row.get("nodeid"))
        item = folded.setdefault(key, {
            "lane": "tests", "repo": row.get("repo"), "entry": row.get("nodeid"),
            "seconds": 0.0, "legs": {}, "python": None, "run_url": None,
            "ratio": None, "prev_s": None, "prompt": None,
        })
        item["legs"][str(row.get("python"))] = seconds
        if seconds > item["seconds"]:
            item.update({
                "seconds": seconds, "python": str(row.get("python")),
                "run_url": row.get("run_url"), "ratio": _num(row.get("ratio")),
                "prev_s": _num(row.get("prev_s")), "prompt": row.get("prompt"),
            })
    return sorted(folded.values(), key=lambda i: -i["seconds"])


def rank_gates(perf: dict) -> list[dict]:
    out = []
    for gate in perf.get("gates") or []:
        if not isinstance(gate, dict):
            continue
        median = _num(gate.get("median_s"))
        if median is None:
            continue
        out.append({
            "lane": "gates", "repo": gate.get("repo"), "entry": gate.get("workflow"),
            "seconds": median, "max_s": _num(gate.get("max_s")),
            "pr_median_s": _num(gate.get("pr_median_s")), "runs": gate.get("runs_counted"),
            "state": gate.get("state"), "run_url": gate.get("actions_url"),
            "prompt": gate.get("prompt"),
        })
    return sorted(out, key=lambda i: -i["seconds"])


# --- Levers read from the script text ---------------------------------------

_ENV_KNOB = re.compile(r"""os\.environ\.get\(\s*["']([A-Z0-9_]+)["']\s*,\s*["']?(\d+)["']?\s*\)""")
_ENV_LINE = re.compile(r"^ENV:\s*(.+)$", re.M)


def levers_from_text(text: str) -> list[dict]:
    """Plain facts about the file, each with the lever it implies."""
    out: list[dict] = []
    for name, default in _ENV_KNOB.findall(text):
        out.append({"lever": "env_knob", "detail": f"{name} (default {default})",
                    "action": f"set {name} lower for smoke via a profile_smoke.yaml `set:` override"})
    if "should_simulate(" in text:
        out.append({"lever": "simulates", "detail": "runs the simulator when the dataset is absent",
                    "action": "cold dataset cache → simulation is inside this timing; check cache_datasets"})
    tokens = set()
    m = _ENV_LINE.search(text)
    if m:
        tokens = set(m.group(1).split())
    if "jax.jit" in text or "@jit" in text or "jax" in tokens or "real_output" in tokens:
        out.append({"lever": "jax_jit", "detail": "JIT-compiles",
                    "action": "compile cost; a cache_jax miss pays it in full — count distinct compiles, reuse shapes"})
    if "full_datasets" in tokens or "real_output" in tokens:
        out.append({"lever": "full_datasets", "detail": "ENV releases PYAUTO_SMALL_DATASETS",
                    "action": "confirm the assertion needs production size; otherwise drop the token"})
    if "real_search" in tokens or "real_output" in tokens:
        out.append({"lever": "real_search", "detail": "ENV releases PYAUTO_TEST_MODE",
                    "action": "the search really runs — cap its iterations or reduce live points"})
    if "subprocess.run(" in text or "subprocess.check_call(" in text:
        out.append({"lever": "subprocess", "detail": "spawns a child interpreter",
                    "action": "a second import of the science stack — move the work in-process or cache its output"})
    plots = len(re.findall(r"\baplt\.\w+\(|\bplt\.\w+\(", text))
    if plots:
        out.append({"lever": "plots", "detail": f"{plots} plot call(s)",
                    "action": "PYAUTO_FAST_PLOTS covers layout only; a plot in a loop is a loop of plots"})
    return out


def attach_levers(items: list[dict], scripts_root: Path) -> None:
    for item in items:
        path = scripts_root / str(item.get("repo") or "") / str(item.get("entry") or "")
        try:
            text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None
        except OSError:
            text = None
        item["script_path"] = str(path) if text is not None else None
        item["levers"] = levers_from_text(text) if text is not None else []


# --- Prompts -----------------------------------------------------------------


def prompt_for(item: dict) -> str:
    if item["lane"] == "scripts":
        bits = [f"{item['seconds']:.1f}s on py{item['python']}"]
        if item.get("share_of_leg"):
            bits.append(f"{item['share_of_leg']:.0%} of that leg")
        if item.get("cache_jax") and item["cache_jax"] != "unknown":
            bits.append(f"jax cache {item['cache_jax']}")
        levers = ", ".join(l["lever"] for l in item.get("levers") or []) or "read the script"
        return (f"/ci_speedup {item['repo']} {item['entry']} — {'; '.join(bits)}; "
                f"levers: {levers}" + (f" — {item['run_url']}" if item.get("run_url") else ""))
    if item["lane"] == "tests":
        ratio = f", {item['ratio']:.2f}x baseline" if item.get("ratio") else ""
        return (f"/ci_speedup {item['repo']} {item['entry']} — {item['seconds']:.1f}s unit test{ratio}"
                + (f" — {item['run_url']}" if item.get("run_url") else ""))
    return (f"/ci_speedup {item['repo']} '{item['entry']}' — median {item['seconds']:.0f}s"
            f"{', max ' + format(item['max_s'], '.0f') + 's' if item.get('max_s') else ''}"
            + (f" — {item['run_url']}" if item.get("run_url") else ""))


# --- Main --------------------------------------------------------------------


def build(board: dict, top: int, lane: str, scripts_root: Path | None) -> dict:
    perf = board.get("performance") or {}
    lanes: dict[str, list[dict]] = {}
    if lane in ("scripts", "all"):
        items = rank_scripts(perf)[:top]
        if scripts_root is not None:
            attach_levers(items, scripts_root)
        lanes["scripts"] = items
    if lane in ("tests", "all"):
        lanes["tests"] = rank_tests(perf)[:top]
    if lane in ("gates", "all"):
        lanes["gates"] = rank_gates(perf)[:top]
    for items in lanes.values():
        for item in items:
            item["prompt"] = prompt_for(item)
    return {
        "decision": "HygieneDecision", "mode": "ci",
        "board_ts": board.get("ts"), "verdict": board.get("verdict"),
        "epoch": (perf.get("epoch") or {}).get("date"),
        "counts": {
            "scripts_timed": sum(1 for r in ((perf.get("scripts") or {}).get("rows") or [])
                                 if isinstance(r, dict) and _num(r.get("seconds")) is not None),
            "tests": len((perf.get("unit") or {}).get("tests") or []),
            "gates": len(perf.get("gates") or []),
            "slowed_scripts": len((perf.get("scripts") or {}).get("slowed") or []),
            "slowed_tests": len((perf.get("unit") or {}).get("slowed_tests") or []),
            "hang_events": len(perf.get("events") or []),
        },
        "lanes": lanes,
        "delegate": "/ci_speedup",
    }


def render(decision: dict, source: str) -> str:
    lines = ["== HygieneDecision (ci: slowest parts of CI, from the Heart board) ==",
             f"board: {source} (ts {decision.get('board_ts')}, epoch {decision.get('epoch')}, "
             f"verdict {decision.get('verdict')})"]
    c = decision["counts"]
    lines.append(f"observed: {c['scripts_timed']} script timings, {c['tests']} unit-test rows, "
                 f"{c['gates']} gates; {c['slowed_scripts']} slowed scripts, {c['slowed_tests']} "
                 f"slowed tests, {c['hang_events']} hang events")
    titles = {"scripts": "Smoke scripts (slowest leg per script; the gate waits for the slower leg)",
              "tests": "Unit tests (slowest per test)",
              "gates": "CI gates (median wall-clock)"}
    for lane, items in decision["lanes"].items():
        lines.append("")
        lines.append(f"-- {titles[lane]}")
        if not items:
            lines.append("   (nothing observed)")
        for n, item in enumerate(items, 1):
            if lane == "scripts":
                legs = " ".join(f"py{p}={s:.1f}s" for p, s in sorted(item["legs"].items()))
                share = f"  {item['share_of_leg']:.0%} of leg" if item.get("share_of_leg") else ""
                cache = f"  jax-cache={item['cache_jax']}" if item.get("cache_jax") else ""
                lines.append(f"{n:2d}. {item['seconds']:6.1f}s  {item['repo']}  {item['entry']}"
                             f"  [{legs}]{share}{cache}")
                for lever in item.get("levers") or []:
                    lines.append(f"       lever {lever['lever']:<13} {lever['detail']} → {lever['action']}")
                if item.get("script_path") is None:
                    lines.append("       (script not checked out under the scan root — levers unread)")
            elif lane == "tests":
                ratio = f"  {item['ratio']:.2f}x" if item.get("ratio") else ""
                lines.append(f"{n:2d}. {item['seconds']:6.1f}s  {item['repo']}  {item['entry']}{ratio}")
            else:
                mx = f"  max {item['max_s']:.0f}s" if item.get("max_s") else ""
                lines.append(f"{n:2d}. {item['seconds']:6.0f}s  {item['repo']} / {item['entry']}{mx}"
                             f"  ({item.get('runs')} runs, {item.get('state')})")
            lines.append(f"       📋 {item['prompt']}")
    lines.append("")
    lines.append("→ hand each 📋 to /ci_speedup: it reads the script, names the cost, and drives the")
    lines.append("  fix through /start_dev (profile override, in-script reduction, cache or CI change).")
    lines.append("  Hygiene ranks and routes; it never edits source and never re-times CI itself.")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--board", help="board.json path or URL (else HYGIENE_HEART_BOARD, Pages, local Heart)")
    ap.add_argument("--heart", default=DEFAULT_HEART, help="Heart repo name (Pages path + local checkout)")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--lane", choices=("scripts", "tests", "gates", "all"), default="all")
    ap.add_argument("--scripts-root", help="where <repo>/<entry> scripts are checked out (default PYAUTO_ROOT)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    tried = candidate_sources(args.board, args.heart)
    board = None
    source = None
    for candidate in tried:
        board = load_board(candidate)
        if board is not None:
            source = candidate
            break
    if board is None:
        msg = "hygiene ci: no Heart board reachable; looked at:\n  " + "\n  ".join(tried)
        if args.json:
            print(json.dumps({"decision": "HygieneDecision", "mode": "ci", "status": "unreachable",
                              "tried": tried}))
        else:
            print(msg, file=sys.stderr)
        return 3

    scripts_root = Path(args.scripts_root) if args.scripts_root else pyauto_root()
    decision = build(board, max(1, args.top), args.lane, scripts_root)
    decision["source"] = source
    if args.json:
        print(json.dumps(decision, indent=2))
    else:
        print(render(decision, source))
    return 0


if __name__ == "__main__":
    sys.exit(main())
