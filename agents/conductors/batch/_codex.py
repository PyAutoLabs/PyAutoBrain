"""Codex CLI backend. Local Linux/WSL process records, never an API client.

Opaque codex:<uuid> identities route observations independently of a brief
which may subsequently change. Each runner owns one private session directory.
Unknown/corrupt state holds a lease; it is never evidence that a worker died.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

PREFIX = "codex:"
ID_RE = re.compile(r"codex:([0-9a-f]{32})\Z")


def session_dir(agent_id: str, home: Path) -> Path:
    match = ID_RE.fullmatch(agent_id)
    if not match:
        raise ValueError("invalid Codex worker identity")
    return Path(home) / "codex-sessions" / match[1]


def write_json(path: Path, value: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value), encoding="utf-8")
    tmp.replace(path)


def read_record(agent_id: str, home: Path) -> dict | None:
    try:
        obj = json.loads((session_dir(agent_id, home) / "state.json").read_text())
        if not isinstance(obj, dict) or obj.get("agent_id") != agent_id:
            return None
        if obj.get("state") not in {"starting", "working", "done", "error", "killed"}:
            return None
        for key in ("pid", "child_pid"):
            if key in obj and (type(obj[key]) is not int or obj[key] <= 0):
                return None
        for key in ("identity", "child_identity"):
            if key in obj and (not isinstance(obj[key], str) or not obj[key]):
                return None
        return obj
    except (OSError, ValueError, TypeError):
        return None


def process_identity(pid: int) -> str | None:
    """Linux start ticks + boot id prevent PID reuse across ticks/reboots."""
    try:
        stat = Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()
        if stat[0] == "Z":
            return None
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        return f"{boot}:{stat[19]}"
    except (OSError, ValueError, IndexError, TypeError):
        return None


def state(agent_id: str, home: Path) -> str | None:
    rec = read_record(agent_id, home)
    if rec is None:
        return None
    if rec["state"] in {"done", "error", "killed"}:
        return rec["state"]
    if rec.get("pid") and rec.get("identity"):
        if process_identity(rec["pid"]) == rec["identity"]:
            return "working"
        # A supervisor crash is not a worker crash while its child survives.
        if not rec.get("child_pid") or not rec.get("child_identity"):
            # Death between Popen and the child's identity write is ambiguous.
            # Holding the lease is safer than starting a duplicate worker.
            return None
        if process_identity(rec["child_pid"]) == rec["child_identity"]:
            return "working"
        return "error"
    # A launcher crash before the supervisor starts cannot silently free a slot.
    return None


def usage(agent_id: str, home: Path) -> dict | None:
    """Completed-turn usage. Missing/partial events retain the reservation.

    Codex input includes cached input: subtract it for the existing shift
    budget's uncached-input + output convention; report cache reads separately.
    """
    try:
        totals = dict(input=0, output=0, cache_creation=0, cache_read=0, subagents=0)
        found = False
        for line in (session_dir(agent_id, home) / "events.jsonl").read_text().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue  # an in-flight final line is normal
            if not isinstance(event, dict) or event.get("type") != "turn.completed":
                continue
            u = event.get("usage")
            if not isinstance(u, dict):
                return None
            fields = [u.get(k) for k in ("input_tokens", "output_tokens", "cached_input_tokens")]
            if any(type(n) is not int or n < 0 for n in fields) or fields[2] > fields[0]:
                return None
            found = True
            totals["input"] += fields[0] - fields[2]
            totals["output"] += fields[1]
            totals["cache_read"] += fields[2]
        if not found:
            return None
        for request in session_dir(agent_id, home).glob("review-*.request.json"):
            result = request.with_name(request.name.replace(".request.json", ".result.json"))
            try:
                raw = json.loads(result.read_text())["usage"]
                fields = [raw.get(k) for k in ("input_tokens", "output_tokens",
                          "cache_creation_input_tokens", "cache_read_input_tokens")]
                if any(type(n) is not int or n < 0 for n in fields):
                    return None
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                return None
            totals["input"] += fields[0]
            totals["output"] += fields[1]
            totals["cache_creation"] += fields[2]
            totals["cache_read"] += fields[3]
            totals["subagents"] += sum(fields[:3])
        totals["total"] = totals["input"] + totals["output"] + totals["cache_creation"]
        return totals
    except (OSError, ValueError):
        return None


def probe(run=None) -> dict:
    """Require ChatGPT CLI auth, never accept an API-key billing fallback."""
    run = run or subprocess.run
    try:
        res = run(["codex", "login", "status"], capture_output=True, text=True, timeout=30)
        output = (res.stdout or "") + (res.stderr or "")
        if res.returncode == 0 and "logged in using chatgpt" in output.lower():
            return {"state": "ok", "detail": "Codex ChatGPT login", "backend": "codex", "expires_at": ""}
        # Do not echo CLI output: some versions show a masked API key.
        return {"state": "expired", "detail": "Codex ChatGPT login required; run codex login", "backend": "codex",
                "expires_at": ""}
    except (OSError, subprocess.SubprocessError):
        return {"state": "expired", "detail": "Codex login could not be verified; run codex login status", "backend": "codex",
                "expires_at": ""}


def command(model: str, effort: str, mode: str, cwd: Path, write_root: Path) -> list[str]:
    if mode not in {"auto", "dontAsk"}:
        raise ValueError("Codex worker-mode must be auto or dontAsk (acceptEdits has no equivalent)")
    argv = ["codex", "exec", "--json", "--color", "never", "--model", model,
            "-c", f"model_reasoning_effort={json.dumps(effort)}",
            "-c", 'model_provider="openai"', "-c", 'forced_login_method="chatgpt"',
            "-c", "features.multi_agent=false", "-c", "features.goals=false",  # usage is for this worker only
            "--cd", str(cwd),
            "--add-dir", str(write_root), "--skip-git-repo-check"]
    if mode == "auto":
        argv.append("--approve-for-me")
    else:
        argv += ["--sandbox", "workspace-write", "-c", 'approval_policy="never"']
    return argv + ["-"]


def launch(prompt: str, *, home: Path, cwd: Path, write_root: Path, model: str,
           effort: str, mode: str, env: dict, scope=None, lease_path: Path | None = None) -> dict:
    if not Path("/proc/self/stat").exists():
        raise ValueError("Codex shift workers currently require Linux/WSL process identity")
    agent_id = PREFIX + uuid.uuid4().hex
    directory = session_dir(agent_id, home)
    directory.mkdir(parents=True, mode=0o700)
    argv = command(model, effort, mode, cwd, write_root)
    argv[-1:-1] = ["--add-dir", str(home)]
    (directory / "prompt.txt").write_text(prompt, encoding="utf-8")
    write_json(directory / "request.json", {"argv": argv, "cwd": str(cwd)})
    write_json(directory / "state.json", {"agent_id": agent_id, "state": "starting"})
    identity = {"pid": 0, "agent_id": agent_id, "session_id": agent_id,
                "backend": "codex", "model": model, "effort": effort, "mode": mode}
    if lease_path is not None:
        lease = json.loads(lease_path.read_text())
        # Reserve identity before starting any process. A watcher killed after
        # spawn can adopt this attempt instead of treating it as a dead stub.
        write_json(lease_path, {**lease, **identity})
    clean_env = dict(env)
    clean_env["PYAUTO_CODEX_SESSION_DIR"] = str(directory)
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL"):
        clean_env.pop(key, None)
    # The runner and child retain the existing Mind commit guard environment.
    runner = [sys.executable, str(Path(__file__).with_name("_codex_runner.py")), str(directory)]
    if scope:
        runner = scope(runner)
    with (directory / "runner.log").open("ab") as log:
        proc = subprocess.Popen(runner, cwd=cwd, env=clean_env, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=log, start_new_session=True)
    # Only the runner writes state; a late parent cannot overwrite completion.
    # No retry after an ambiguous start: that would duplicate the worker.
    try:
        for _ in range(100):
            rec = read_record(agent_id, home)
            if rec and rec["state"] != "starting":
                break
            if proc.poll() is not None:
                write_json(directory / "state.json", {"agent_id": agent_id, "state": "error",
                                                       "reason": "runner exited before handshake"})
                break
            time.sleep(0.02)
    except OSError:
        pass  # Process exists: return the reserved identity, never permit a retry.
    return identity


def stop(agent_id: str, home: Path) -> tuple[bool, str]:
    rec = read_record(agent_id, home)
    if not rec:
        return False, "Codex session state unreadable; refusing to target an unverified process"
    if rec["state"] in {"done", "error", "killed"}:
        return True, ""
    if not rec.get("pid") or process_identity(rec["pid"]) != rec.get("identity"):
        return False, "Codex supervisor identity unavailable; inspect its local session record"
    # Supervisor handles termination and escalation of its own child group.
    (session_dir(agent_id, home) / "STOP").touch()
    return True, ""
