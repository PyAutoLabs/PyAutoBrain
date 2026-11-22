"""Accounted independent Opus review for one Codex shift worker.

Invoked synchronously by the worker, never a timer or an autonomous close-out.
The reviewer gets the existing faculty contract and repository paths, not the
writer's conversation. All review attempts remain part of that worker's spend.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import uuid

from _codex import write_json

SCHEMA = {"type": "object", "properties": {
    "verdict": {"type": "string", "enum": ["CLEAN", "FINDINGS", "BLOCKED"]},
    "report": {"type": "string"}}, "required": ["verdict", "report"],
    "additionalProperties": False}


def review(task: str, repos: list[Path], *, run=None) -> dict:
    directory = os.environ.get("PYAUTO_CODEX_SESSION_DIR")
    if os.environ.get("PYAUTO_SHIFT_WORKER") != "1" or not directory:
        raise ValueError("review helper is only for a registered Codex shift worker")
    directory = Path(directory)
    state = json.loads((directory / "state.json").read_text())
    if state.get("state") != "working" or state.get("agent_id") != "codex:" + directory.name:
        raise ValueError("Codex worker session is not running")
    repos = [p.resolve(strict=True) for p in repos]
    session = str(uuid.uuid4())
    prefix = directory / f"review-{session}"
    # Create evidence before the call; a killed/incomplete reviewer is unknown
    # spend, never silently zero. Each fresh attempt has a different identity.
    write_json(prefix.with_suffix(".request.json"), {"session_id": session, "task": task,
                                                    "repos": list(map(str, repos))})
    faculty = Path(__file__).resolve().parents[2] / "faculties" / "review" / "AGENTS.md"
    brain = Path(__file__).resolve().parents[3]
    prompt = (f"You are the independent review faculty for task {task}. "
              f"Read {faculty}, then use {brain}/bin/pyauto-brain review --task {task} "
              "to prepare its review surface (use explicit repo paths if needed). "
              "Review both committed and uncommitted changes against origin/main in "
              + ", ".join(map(str, repos)) + ". "
              "Follow the faculty's code-review and verify pass. Read the task's "
              "Mind prompt and its Witness. Never edit source, fix findings, write "
              "Mind state, commit, push, merge or contact anyone. Never delegate or "
              "start another model. If evidence or permissions are insufficient, "
              "return BLOCKED. Return the structured verdict and full findings/evidence; "
              "CLEAN only when the faculty's requirements pass. This is ship leg 3, "
              "not the close-out adversary or merge authority.")
    argv = ["claude", "--print", "--model", "opus", "--effort", "medium",
            "--session-id", session, "--permission-mode", "auto", "--max-turns", "40",
            "--tools", "Read,Glob,Grep,Bash", "--output-format", "json",
            "--json-schema", json.dumps(SCHEMA), "--add-dir", *map(str, repos)]
    run = run or subprocess.run
    try:
        result = run(argv, input=prompt, text=True, capture_output=True, cwd=brain.parent,
                     timeout=1800)
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError("review output is not an object")
        write_json(prefix.with_suffix(".result.json"), payload)
        verdict = payload.get("structured_output") or {}
        if result.returncode or payload.get("is_error") or not isinstance(verdict, dict):
            raise ValueError("review session failed")
        if verdict.get("verdict") not in {"CLEAN", "FINDINGS", "BLOCKED"}:
            raise ValueError("review returned no recognized verdict")
        return {**verdict, "session_id": session, "evidence": str(prefix.with_suffix(".result.json"))}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"verdict": "BLOCKED", "report": str(exc), "session_id": session}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True)
    parser.add_argument("--repo", type=Path, action="append", required=True)
    args = parser.parse_args()
    try:
        result = review(args.task, args.repo)
    except (ValueError, OSError) as exc:
        result = {"verdict": "BLOCKED", "report": str(exc)}
    print(json.dumps(result))
    return 0 if result["verdict"] == "CLEAN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
