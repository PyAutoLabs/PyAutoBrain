"""Read Heart's monitoring inventory and forward its findings unchanged."""

import argparse
import json
import sys
from pathlib import Path


def assess(board):
    monitoring = board.get("monitoring") if isinstance(board, dict) else None
    error = None
    if not isinstance(monitoring, dict):
        error = "Heart monitoring inventory is missing."
    elif not (
        type(monitoring.get("schema_version")) is int
        and monitoring.get("schema_version") == 1
        and monitoring.get("status") in {"green", "red", "yellow", "stale", "grey"}
        and type(monitoring.get("score")) is int
        and type(monitoring.get("complete")) is bool
        and isinstance(monitoring.get("counts"), dict)
        and isinstance(monitoring.get("checks"), list)
        and isinstance(monitoring.get("findings"), list)
        and isinstance(monitoring.get("penalties"), list)
        and all(isinstance(c, dict) for c in monitoring["checks"] + monitoring["findings"])
    ):
        error = "Heart monitoring inventory is malformed or unsupported."
    if error:
        return {
            "scope": "dashboard", "verdict": "unknown", "score": None,
            "complete": False, "status": "unknown", "counts": {},
            "checks": [], "findings": [], "items": [], "penalties": [],
            "blocked_reason": error,
            "recommendation": {"action": "blocked", "command": None,
                               "headline": error},
        }
    result = dict(monitoring)
    # Status and completion are Heart-owned. Preserve all inventory fields,
    # including applicability, evidence, blocked reasons and action payloads.
    result.update(scope="dashboard", verdict=monitoring["status"],
                  items=monitoring["findings"],
                  release_verdict=board.get("verdict"),
                  release_score=board.get("score"))
    findings = monitoring["findings"]
    done = monitoring["complete"] and monitoring["status"] == "green" and not findings
    first = findings[0] if findings else {}
    action = first.get("action")
    result["recommendation"] = {
        "action": "none" if done else "review-findings" if findings else "blocked",
        "command": action.get("payload") if isinstance(action, dict) and action.get("kind") == "command" else None,
        "heart_action": action,
        "headline": "Monitoring complete — no unresolved findings." if done else
                    first.get("summary") or "Monitoring incomplete — review Heart inventory coverage.",
        "blocked_reason": first.get("blocked_reason"),
    }
    return result


def _read_local(text):
    """The local Heart's board, or None when it printed no JSON object."""
    try:
        board = json.loads(text)
    except ValueError:
        return None
    return board if isinstance(board, dict) else None


def _read_published():
    faculty = Path(__file__).resolve().parents[2] / "faculties" / "vitals"
    sys.path.insert(0, str(faculty))
    import _vitals
    base, repo = _vitals.pages_source()
    return _vitals.read_published(base, repo)[1] if base else {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--published", action="store_true")
    parser.add_argument("--published-fallback", action="store_true",
                        help="read stdin, but fall back to the published board "
                             "when the local Heart printed no JSON board "
                             "(e.g. a checkout that has never ticked)")
    parser.add_argument("--mode", choices=("assess", "triage", "recommend"), default="assess")
    args = parser.parse_args()
    source = "published" if args.published else "local"
    board = {}
    try:
        if args.published:
            board = _read_published()
        else:
            board = _read_local(sys.stdin.read())
            if board is None and args.published_fallback:
                # The local Heart answered with no board at all (it prints
                # "No cache yet" before its first tick). That is an absent
                # local vantage, not an inventory verdict: read the published
                # board instead. A local board that parses but lacks or
                # mangles its inventory is NOT replaced — that stays explicit.
                source = "published"
                board = _read_published()
    except Exception:
        board = {}
    result = assess(board if isinstance(board, dict) else {})
    result["source"] = source
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("== health: dashboard monitoring = " + result["status"].upper() + " ==")
        print("Monitoring score: " + str(result["score"]) + " · complete: " + str(result["complete"])
              + " · source: " + result["source"])
        if args.mode != "recommend":
            for finding in result["findings"]:
                print("  [" + str(finding.get("status", "unknown")) + "] " + str(finding.get("summary", "")))
                action = finding.get("action")
                if isinstance(action, dict):
                    print("    " + str(action.get("payload", "")))
                if finding.get("blocked_reason"):
                    print("    Blocked: " + str(finding["blocked_reason"]))
        print(result["recommendation"]["headline"])
        if args.mode == "recommend" and result["recommendation"].get("heart_action"):
            print(json.dumps(result["recommendation"]["heart_action"]))
        print("Re-read with pyauto-brain health --scope dashboard; completion requires Heart's complete inventory and no unresolved findings.")
    status = result["status"]
    done = result["complete"] and status == "green" and not result["findings"]
    return 0 if done else {"red": 3, "yellow": 2, "stale": 6}.get(status, 4)


if __name__ == "__main__":
    sys.exit(main())
