"""The unattended-ssh probe for a brief that grants the `ral` lane.

A worker reaches RAL by key auth through the jump host with nobody to answer
a prompt, so a lane that is unusable must be said at launch, not found by a
worker that spends its session on it. For a brief whose `lanes:` include
`ral`, `batch brief --check` asks once:
`ssh -o BatchMode=yes -o ConnectTimeout=10 <host> true`. BatchMode never
prompts, so the answer is what a worker will get. The result is one of:

- `ok`      — the host answered;
- `failed`  — ssh ran and exited non-zero (its last line is the detail);
- `unknown` — no `ssh` on PATH, the call timed out, or no host is named;
- `skipped` — `PYAUTO_RAL_PROBE=off` (the test suite; a machine with no RAL).

Anything but `ok` and `skipped` is a **warning, never a refusal**: the human
may be about to fix it, and a brief with no RAL task loses nothing. It runs in
the launch chat only, never in the watcher (AUTONOMY.md "The watcher's network
surface", RAL probe).

The host is the tenant's, so it is never written here. `PYAUTO_RAL_SSH_HOST`
names it; otherwise it is read from the Mind's own access note,
`policy/hpc_ral.md` ("SSH alias `<name>`").
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

PROBE_ENV = "PYAUTO_RAL_PROBE"
HOST_ENV = "PYAUTO_RAL_SSH_HOST"
#: Where a Mind records how its cluster is reached.
POLICY_FILE = "policy/hpc_ral.md"
_ALIAS_RE = re.compile(r"SSH alias `([A-Za-z0-9][\w.-]*)`")
_HOST_RE = re.compile(r"^[A-Za-z0-9][\w.@-]*$")
CONNECT_TIMEOUT_S = 10
TIMEOUT_S = 30


def host_of(mind) -> str:
    """The ssh host to probe: `PYAUTO_RAL_SSH_HOST`, else the first "SSH alias
    `<name>`" in the Mind's `policy/hpc_ral.md`; "" when neither names one. A
    value that is not a plain host name (it would be read as an ssh option)
    is not a host."""
    name = os.environ.get(HOST_ENV, "").strip()
    if not name:
        try:
            text = (Path(mind) / POLICY_FILE).read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        m = _ALIAS_RE.search(text)
        name = m.group(1) if m else ""
    return name if _HOST_RE.match(name) else ""


def argv_for(host: str) -> list[str]:
    return ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={CONNECT_TIMEOUT_S}",
            host, "true"]


def probe(mind, run=None) -> dict:
    """{"state": ok|failed|unknown|skipped, "host", "detail"}."""
    if os.environ.get(PROBE_ENV, "").strip().lower() in ("off", "0", "no"):
        return {"state": "skipped", "host": "", "detail": f"{PROBE_ENV}=off"}
    host = host_of(mind)
    if not host:
        return {"state": "unknown", "host": "",
                "detail": f"no host named ({HOST_ENV}, or \"SSH alias `<name>`\" in the "
                          f"Mind's {POLICY_FILE})"}
    run = run or subprocess.run
    try:
        res = run(argv_for(host), capture_output=True, text=True, timeout=TIMEOUT_S,
                  stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return {"state": "unknown", "host": host, "detail": "no `ssh` on PATH"}
    except subprocess.TimeoutExpired:
        return {"state": "unknown", "host": host,
                "detail": f"no answer in {TIMEOUT_S} s"}
    except (OSError, subprocess.SubprocessError) as e:
        return {"state": "unknown", "host": host, "detail": f"ssh failed to run ({e})"[:200]}
    if res.returncode == 0:
        return {"state": "ok", "host": host, "detail": "answered"}
    lines = [ln.strip() for ln in f"{res.stderr or ''}\n{res.stdout or ''}".splitlines()
             if ln.strip()]
    return {"state": "failed", "host": host,
            "detail": (lines[-1] if lines else f"exit {res.returncode}")[:200]}


def findings(lanes, mind, run=None) -> tuple[dict | None, list[str]]:
    """(probe result, warnings) for a brief's `lanes:`. No `ral`, no probe and
    no ssh call: (None, [])."""
    if "ral" not in (lanes or []):
        return None, []
    res = probe(mind, run)
    if res["state"] in ("ok", "skipped"):
        return res, []
    if res["state"] == "failed":
        return res, [f"brief.lanes: ral is granted, but unattended ssh to `{res['host']}` "
                     f"fails ({res['detail']}) — a worker that needs RAL will park; fix the "
                     "key setup or drop `ral` from `lanes:`"]
    return res, [f"brief.lanes: ral is granted, but unattended ssh could not be checked "
                 f"({res['detail']})"]
