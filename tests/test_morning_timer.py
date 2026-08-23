"""Contract tests for bin/morning_timer.sh — the overnight scheduler for the
morning routine. Hermetic: only the `print` mode runs (it renders exactly what
`install` would write, without touching systemd or crontab), forced onto each
backend via MORNING_TIMER_MODE."""

import os
import subprocess
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
SCRIPT = BRAIN_HOME / "bin" / "morning_timer.sh"
MORNING = BRAIN_HOME / "bin" / "morning.sh"


def _run(mode, *args):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True, text=True,
        env={**os.environ, "MORNING_TIMER_MODE": mode},
    )


def test_systemd_print_renders_persistent_timer_at_the_given_time():
    r = _run("systemd", "print", "04:45")
    assert r.returncode == 0, r.stderr
    assert f"ExecStart=/bin/bash {MORNING}" in r.stdout
    assert "OnCalendar=*-*-* 04:45:00" in r.stdout
    # A night the machine slept through is caught up, not skipped.
    assert "Persistent=true" in r.stdout


def test_cron_print_renders_marked_line_without_octal_fields():
    r = _run("cron", "print", "05:05")
    assert r.returncode == 0, r.stderr
    # Leading zeros stripped (05 would read as octal-ish cron noise) and the
    # marker present so uninstall can find its own line.
    assert f"5 5 * * * /bin/bash {MORNING}" in r.stdout
    assert "# pyauto-morning" in r.stdout


def test_bad_times_are_rejected():
    assert _run("cron", "print", "4x:45").returncode == 2
    assert _run("cron", "print", "25:00").returncode == 2
    # Default time is valid.
    assert _run("cron", "print").returncode == 0
