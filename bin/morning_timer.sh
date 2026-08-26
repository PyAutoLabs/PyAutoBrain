#!/usr/bin/env bash
#
# morning_timer.sh — schedule bin/morning.sh to run overnight on THIS machine,
# so the sync/clean/publish leg is already done when the human wakes up and
# the board reads "observed this morning" from the first glance.
#
# Every leg of morning.sh is local (it syncs and cleans YOUR checkouts and
# publishes YOUR dev-box observation), so the schedule must live on the dev
# box — the board's own cloud refresh (brain_board.yml, 05:30 UTC) is separate
# and unaffected. The publish push re-triggers a board render anyway, so the
# board updates minutes after the local run regardless of ordering.
#
#   bash PyAutoBrain/bin/morning_timer.sh install [HH:MM]   # default 05:30 local
#   bash PyAutoBrain/bin/morning_timer.sh uninstall
#   bash PyAutoBrain/bin/morning_timer.sh status
#   bash PyAutoBrain/bin/morning_timer.sh print [HH:MM]     # show what install
#                                                           #   would write
#
# Backend: systemd user units (pyauto-morning.service/.timer, Persistent=true
# so a night the machine slept through is caught up at next wake/boot) when
# `systemctl --user` works; otherwise a marked crontab line. Override with
# MORNING_TIMER_MODE=systemd|cron.
#
# Prerequisites on the dev box: non-interactive git credentials (the publish
# leg pushes to the Brain's main), and for the systemd path a user session at
# the fire time — enable lingering once (`loginctl enable-linger $USER`) so
# the timer fires before first login; install says so if it is off.
#
# Caveat: clean_slate deletes untracked REGENERABLE datasets. If something
# else runs on this machine overnight and writes datasets it still needs,
# schedule after it finishes, or point the timer at
# `morning.sh --no-publish`-style variants by editing the unit.

set -u

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
MORNING="$HERE/morning.sh"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
LOG_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/pyauto"
MARKER="# pyauto-morning (installed by morning_timer.sh)"

when="${2:-05:30}"
case "$when" in
  [0-2][0-9]:[0-5][0-9]) ;;
  *) echo "morning_timer: time must be HH:MM (got '$when')" >&2; exit 2 ;;
esac
hh="${when%%:*}"; mm="${when##*:}"
if [ "$((10#$hh))" -gt 23 ]; then
  echo "morning_timer: hour must be 00-23 (got '$hh')" >&2; exit 2
fi

mode="${MORNING_TIMER_MODE:-}"
if [ -z "$mode" ]; then
  if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
    mode=systemd
  elif command -v crontab >/dev/null 2>&1; then
    mode=cron
  else
    echo "morning_timer: neither a systemd user session nor crontab is available" >&2
    exit 1
  fi
fi

service_unit() {
  cat <<EOF
[Unit]
Description=PyAuto morning routine (sync + clean + dev-box publish)

[Service]
Type=oneshot
ExecStart=/bin/bash $MORNING
EOF
}

timer_unit() {
  cat <<EOF
[Unit]
Description=Run the PyAuto morning routine overnight

[Timer]
OnCalendar=*-*-* $hh:$mm:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
}

cron_line() {
  # Strip a leading zero so cron never sees an octal-looking field.
  printf '%d %d * * * /bin/bash %s >> %s/morning.log 2>&1 %s\n' \
    "$((10#$mm))" "$((10#$hh))" "$MORNING" "$LOG_DIR" "$MARKER"
}

case "${1:-status}" in
  print)
    if [ "$mode" = systemd ]; then
      echo "# $UNIT_DIR/pyauto-morning.service"; service_unit
      echo; echo "# $UNIT_DIR/pyauto-morning.timer"; timer_unit
    else
      echo "# crontab line"; cron_line
    fi
    ;;
  install)
    if [ "$mode" = systemd ]; then
      mkdir -p "$UNIT_DIR"
      service_unit > "$UNIT_DIR/pyauto-morning.service"
      timer_unit   > "$UNIT_DIR/pyauto-morning.timer"
      systemctl --user daemon-reload
      systemctl --user enable --now pyauto-morning.timer
      echo "installed: pyauto-morning.timer fires daily at $when local (Persistent=true"
      echo "catches up a night the machine slept through). Logs: journalctl --user -u pyauto-morning"
      if command -v loginctl >/dev/null 2>&1 \
         && [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
        echo "note: lingering is OFF — before first login the timer cannot fire."
        echo "      enable once with: loginctl enable-linger $USER"
      fi
    else
      mkdir -p "$LOG_DIR"
      { crontab -l 2>/dev/null | grep -vF "$MARKER"; cron_line; } | crontab -
      echo "installed: crontab entry fires daily at $when local. Log: $LOG_DIR/morning.log"
      echo "note: plain cron does not catch up runs the machine slept through."
    fi
    ;;
  uninstall)
    if [ "$mode" = systemd ]; then
      systemctl --user disable --now pyauto-morning.timer 2>/dev/null
      rm -f "$UNIT_DIR/pyauto-morning.service" "$UNIT_DIR/pyauto-morning.timer"
      systemctl --user daemon-reload
      echo "uninstalled pyauto-morning.timer"
    else
      crontab -l 2>/dev/null | grep -vF "$MARKER" | crontab -
      echo "removed the pyauto-morning crontab entry"
    fi
    ;;
  status)
    if [ "$mode" = systemd ]; then
      systemctl --user list-timers pyauto-morning.timer --no-pager 2>/dev/null \
        || echo "pyauto-morning.timer is not installed"
    else
      crontab -l 2>/dev/null | grep -F "$MARKER" \
        || echo "no pyauto-morning crontab entry"
    fi
    ;;
  *)
    echo "usage: morning_timer.sh install [HH:MM] | uninstall | status | print [HH:MM]" >&2
    exit 2
    ;;
esac
