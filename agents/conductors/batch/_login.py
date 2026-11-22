"""The CLI login probe.

A worker that dies on an expired `claude` login must not be read as "blocked
on a person". This asks the CLI itself, with `claude auth status --json` — a
local read of the stored login, no model call — and says one of:

- `ok`      — logged in, and the login has not expired;
- `expired` — `loggedIn: false`, a `loginExpiresAt` already passed, or the CLI
  saying "Login reached its time limit" / "not logged in";
- `unknown` — the CLI could not be run or printed nothing it could read;
- `skipped` — `PYAUTO_LOGIN_PROBE=off` (the test suite; a machine without
  the CLI on purpose).

`batch brief --check` refuses a launch on `expired` (or a login that lapses
before `review-at:`); the watcher holds spawning on it (AUTONOMY.md "The
watcher's network surface", Login probe).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess

PROBE_ENV = "PYAUTO_LOGIN_PROBE"
#: What the human reads, in the brief check, the event and its comment.
EXPIRED_LINE = "CLI login expired: run `claude /login`"
#: Phrases the CLI prints for a login it cannot use (lower-cased match).
EXPIRED_PHRASES = ("login reached its time limit", "not logged in")
ARGV = ["claude", "auth", "status", "--json"]


def _parse(value: str):
    try:
        t = _dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)


def expires(result: dict):
    """The probe's `expires_at` as a datetime, or None."""
    return _parse(result.get("expires_at") or "")


def probe(run=None, now: _dt.datetime | None = None) -> dict:
    """{"state": ok|expired|unknown|skipped, "detail", "expires_at"}."""
    if os.environ.get(PROBE_ENV, "").strip().lower() in ("off", "0", "no"):
        return {"state": "skipped", "detail": f"{PROBE_ENV}=off", "expires_at": ""}
    run = run or subprocess.run
    now = now or _dt.datetime.now(_dt.timezone.utc)
    try:
        res = run(ARGV, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return {"state": "unknown", "detail": "no `claude` on PATH", "expires_at": ""}
    except (OSError, subprocess.SubprocessError) as e:
        return {"state": "unknown", "detail": f"`claude auth status` failed ({e})"[:200],
                "expires_at": ""}
    text = f"{res.stdout or ''}\n{res.stderr or ''}"
    low = text.lower()
    for phrase in EXPIRED_PHRASES:
        if phrase in low:
            line = next((ln.strip() for ln in text.splitlines() if phrase in ln.lower()),
                        phrase)
            return {"state": "expired", "detail": line[:200], "expires_at": ""}
    try:
        d = json.loads(res.stdout or "")
    except ValueError:
        d = None
    if not isinstance(d, dict):
        return {"state": "unknown", "detail": f"`claude auth status --json` exit "
                f"{res.returncode}: " + (text.strip()[:160] or "no output"), "expires_at": ""}
    at = str(d.get("loginExpiresAt") or "")
    if d.get("loggedIn") is False:
        return {"state": "expired", "detail": "loggedIn: false", "expires_at": at}
    when = _parse(at) if at else None
    if when is not None and when <= now:
        return {"state": "expired", "detail": f"login expired at {at}", "expires_at": at}
    if d.get("loggedIn") is True:
        return {"state": "ok", "detail": "logged in", "expires_at": at}
    return {"state": "unknown", "detail": "no loggedIn field in `claude auth status --json`",
            "expires_at": at}
