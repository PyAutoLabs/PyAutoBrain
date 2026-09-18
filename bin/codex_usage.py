#!/usr/bin/env python3
"""Report metadata-only usage from explicitly selected Codex JSONL rollouts."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


COUNTERS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)
COORDINATION = {
    "spawn_agent": "spawn",
    "send_message": "message",
    "followup_task": "followup",
    "wait_agent": "wait",
    "list_agents": "list",
    "interrupt_agent": "interrupt",
    "collaboration.spawn_agent": "spawn",
    "collaboration.send_message": "message",
    "collaboration.followup_task": "followup",
    "collaboration.wait_agent": "wait",
    "collaboration.list_agents": "list",
    "collaboration.interrupt_agent": "interrupt",
}


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.replace(tzinfo=result.tzinfo or timezone.utc)
    except ValueError:
        return None


def parse_rollout(path: Path) -> dict[str, Any]:
    session_id = None
    snapshots: list[dict[str, int]] = []
    models: set[str] = set()
    efforts: set[str] = set()
    times: list[datetime] = []
    coordination: dict[str, int] = {}
    limitations: list[str] = []

    try:
        handle = path.open(encoding="utf-8")
    except OSError as exc:
        return {
            "path": str(path),
            "session_id": None,
            "complete": False,
            "usage": None,
            "models": [],
            "reasoning_efforts": [],
            "duration_seconds": None,
            "coordination": {},
            "limitations": [f"unreadable: {exc}"],
        }

    latest_snapshot_invalid = False
    try:
        for number, line in enumerate(handle, 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                limitations.append(f"line {number}: malformed JSON ignored")
                continue
            if not isinstance(event, dict):
                continue
            payload = (
                event.get("payload")
                if isinstance(event.get("payload"), dict)
                else event
            )
            event_type = event.get("type")
            if event_type == "session_meta":
                candidate_id = payload.get("id") or payload.get("session_id")
                if isinstance(candidate_id, str):
                    session_id = candidate_id
                elif candidate_id is not None:
                    limitations.append(f"line {number}: non-string session id ignored")
            for candidate in (event.get("timestamp"), payload.get("timestamp")):
                parsed = _timestamp(candidate)
                if parsed:
                    times.append(parsed)
            model = payload.get("model")
            effort = payload.get("reasoning_effort") or payload.get("effort")
            if isinstance(model, str):
                models.add(model)
            if isinstance(effort, str):
                efforts.add(effort)
            usage = payload.get("total_token_usage")
            if not isinstance(usage, dict):
                info = payload.get("info")
                usage = (
                    info.get("total_token_usage") if isinstance(info, dict) else None
                )
            if isinstance(usage, dict):
                values = {key: usage.get(key) for key in COUNTERS}
                if not all(
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                    for value in values.values()
                ):
                    limitations.append(
                        f"line {number}: incomplete or invalid cumulative counters ignored"
                    )
                    latest_snapshot_invalid = True
                elif (
                    values["cached_input_tokens"] > values["input_tokens"]
                    or values["reasoning_output_tokens"] > values["output_tokens"]
                ):
                    limitations.append(
                        f"line {number}: subset counter exceeds inclusive total; snapshot ignored"
                    )
                    latest_snapshot_invalid = True
                else:
                    snapshots.append(values)
                    latest_snapshot_invalid = False
            if event_type == "response_item" and payload.get("type") in {
                "function_call",
                "custom_tool_call",
            }:
                name = str(payload.get("name", ""))
                operation = COORDINATION.get(name)
                if operation:
                    coordination[operation] = coordination.get(operation, 0) + 1
    except (OSError, UnicodeError) as exc:
        limitations.append(f"read error: {exc}")
        latest_snapshot_invalid = True
    finally:
        handle.close()
    usage = snapshots[-1] if snapshots and not latest_snapshot_invalid else None
    if usage:
        usage = usage | {
            "uncached_input_tokens": usage["input_tokens"]
            - usage["cached_input_tokens"],
            "total_tokens": usage["input_tokens"] + usage["output_tokens"],
        }
    if usage is None:
        limitations.append("no cumulative usage snapshot; token totals are unknown")
    duration = (max(times) - min(times)).total_seconds() if len(times) > 1 else None
    return {
        "path": str(path),
        "session_id": session_id,
        "complete": usage is not None,
        "usage": usage,
        "models": sorted(models),
        "reasoning_efforts": sorted(efforts),
        "duration_seconds": duration,
        "coordination": coordination,
        "limitations": limitations,
    }


def aggregate(paths: list[Path], child_paths: set[Path]) -> dict[str, Any]:
    sessions: list[dict[str, Any]] = []
    seen_files: set[Path] = set()
    seen_ids: set[str] = set()
    limitations: list[str] = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen_files:
            limitations.append(f"duplicate file ignored: {path}")
            continue
        seen_files.add(resolved)
        result = parse_rollout(path)
        identity = result.get("session_id")
        if identity and identity in seen_ids:
            prior = next(
                item for item in sessions if item.get("session_id") == identity
            )
            if prior.get("usage") != result.get("usage"):
                prior["complete"] = False
                prior["usage"] = None
                prior["limitations"].append(
                    "conflicting duplicate session counters; total is unknown"
                )
                limitations.append(f"conflicting duplicate session id: {identity}")
            else:
                limitations.append(f"duplicate session id ignored: {identity}")
            continue
        if identity:
            seen_ids.add(identity)
        result["role"] = "child" if resolved in child_paths else "parent"
        sessions.append(result)

    complete = all(item.get("complete") for item in sessions) and bool(sessions)
    totals = {key: 0 for key in COUNTERS} if complete else None
    if totals is not None:
        for item in sessions:
            for key in (*COUNTERS, "uncached_input_tokens", "total_tokens"):
                totals.setdefault(key, 0)
                totals[key] += item["usage"][key]
    if child_paths:
        limitations.append(
            "child rollouts may inherit parent events after full-history forks; "
            "aggregation cannot prove exclusivity and may over-count"
        )
    return {
        "complete": complete,
        "totals": totals,
        "sessions": sessions,
        "limitations": limitations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "rollouts", nargs="+", type=Path, help="explicit JSONL rollout files"
    )
    parser.add_argument(
        "--child", action="append", default=[], type=Path, help="explicit child rollout"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    paths = args.rollouts + args.child
    report = aggregate(paths, {path.resolve() for path in args.child})
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("Codex usage report (metadata extracted; conversations are never output)")
        for item in report["sessions"]:
            usage = item.get("usage") or "unknown"
            print(
                f"- {item['role']} {item['path']}: usage={usage}; models={item['models']}; efforts={item['reasoning_efforts']}; duration_s={item['duration_seconds']}; coordination={item['coordination']}"
            )
            for limitation in item["limitations"]:
                print(f"  limitation: {limitation}")
        print(
            f"totals: {report['totals'] if report['complete'] else 'unknown/incomplete'}"
        )
        for limitation in report["limitations"]:
            print(f"limitation: {limitation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
