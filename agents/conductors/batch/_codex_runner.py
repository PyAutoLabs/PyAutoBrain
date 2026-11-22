"""One detached Codex CLI worker. Only spawned by the explicitly selected backend."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from _codex import process_identity, write_json


def run(directory: Path) -> int:
    rec = json.loads((directory / "state.json").read_text())
    request = json.loads((directory / "request.json").read_text())
    rec.update(state="working", pid=os.getpid(), identity=process_identity(os.getpid()))
    write_json(directory / "state.json", rec)
    child = None
    try:
        with (directory / "prompt.txt").open("rb") as prompt, \
                (directory / "events.jsonl").open("wb") as output, \
                (directory / "stderr.log").open("wb") as errors:
            child = subprocess.Popen(request["argv"], cwd=request["cwd"], stdin=prompt,
                                     stdout=output, stderr=errors, start_new_session=True)
            rec["child_pid"] = child.pid
            identity = process_identity(child.pid)
            if identity is not None:
                rec["child_identity"] = identity
            write_json(directory / "state.json", rec)
            killed = False
            while child.poll() is None:
                if (directory / "STOP").exists():
                    killed = True
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait(timeout=3)
                    break
                time.sleep(0.1)
            # The leader can exit before its children. End the whole owned
            # process group before publishing terminal state (also on success).
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            rec.update(state="killed" if killed else "done" if child.returncode == 0 else "error",
                       returncode=child.returncode)
    except Exception as exc:
        # A failed supervisor must not leave a live unaccounted worker.
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=3)
        rec.update(state="error", reason=f"{type(exc).__name__}: {exc}")
    write_json(directory / "state.json", rec)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(Path(sys.argv[1])))
