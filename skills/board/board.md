# /board — read the Brain board (the operational surface)

The morning door in chat form: relay what the published board shows, or
re-render it live. The board is a generated read-only SURFACE — it decides
nothing; every chip on it routes back through the real doors.

1. **Point at the page first.** The live board is
   `https://<org>.github.io/PyAutoBrain/` (refreshed each morning by
   `brain_board.yml`; badge.json beside it is the headline). If the human just
   wants the link or the headline, that is the answer — don't re-collect.
2. **Live digest on request** — run `bin/pyauto-brain board` (needs an
   authenticated `gh`; add `--json` for the raw surface) and relay its
   markdown digest faithfully, including the Degraded section. On a machine
   with the local workspace, `PYAUTO_ROOT` is honoured; without one the
   resume/community legs degrade honestly and say so.
3. **Never act from the digest.** Community replies stay `/community`'s
   human-gated job; closing issues stays `/issue_cleanup`'s; deletion stays
   `/repo_cleanup`'s. The board only names the door.
4. The local sync/clean leg is not yours to run from chat — it is the
   terminal command `bash PyAutoBrain/bin/morning.sh` on the human's machine.

Publishing (`--apply`) is CI's job (`brain_board.yml`); run it manually only
when asked to debug the render, writing under `_site/` or a scratch dir.
