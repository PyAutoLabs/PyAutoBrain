# /board — read the Brain board (the operational surface)

The agents/workflows directory in chat form: relay what the published board shows, or
re-render it live. The board is a generated read-only SURFACE — it decides
nothing; every chip on it routes back through the real doors.

1. **Point at the page first.** The live board is
   `https://<org>.github.io/PyAutoBrain/` (refreshed each morning by
   `brain_board.yml`; badge.json beside it is the headline). If the human just
   wants the link or the headline, that is the answer — don't re-collect.
2. **Live digest on request** — run `bin/pyauto-brain board` (add `--json` for
   the raw surface) and relay its markdown digest faithfully, including local unavailable-evidence notices. `PYAUTO_ROOT` selects the local workspace.

   **Without `gh` (mobile, web), gather first — you are the only thing that
   can.** The `mcp__github__*` tools are an agent capability; `_board.py` is a
   subprocess and cannot reach them. So fetch the GitHub legs yourself,
   write them to a scratch file keyed by endpoint, and hand it over:

   ```
   bin/pyauto-brain board --github-data /tmp/board-github-data.json
   ```

   Today that is one key — upkeep's open-issue count, stored under
   `search/issues?q=org:<org>+is:issue+is:open&per_page=1` as GitHub's search
   response verbatim (the leg reads `total_count`). If your tools cannot run
   that search, store `null`: the leg then says it is unread rather than
   reporting zero. Overnight, versions, community and resume are retired and
   need nothing. Store each response **verbatim**: field names are part of the
   contract (the retired overnight row, for instance, read `created_at`, never
   `updated_at`). The file's shape, and the three rules a
   gatherer must not bend — a miss is *could not ask*, an explicit `null` says
   the fetch failed, a broken file is fatal rather than degrading — are the
   contract in [`../../board/AGENTS.md`](../../board/AGENTS.md) → "Reading the
   board in a remote session". Do not invent a second shape for a leg that is
   not covered yet: leave it dark and let it say so.
3. **Never act from the digest.** Community replies stay `/community`'s
   human-gated job; closing issues stays `/issue_cleanup`'s; deletion stays
   `/repo_cleanup`'s. The board only names the door.
Publishing (`--apply`) is CI's job (`brain_board.yml`); run it manually only
when asked to debug the render, writing under `_site/` or a scratch dir.
