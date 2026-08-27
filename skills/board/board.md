# /board — read the Brain board (the operational surface)

The morning door in chat form: relay what the published board shows, or
re-render it live. The board is a generated read-only SURFACE — it decides
nothing; every chip on it routes back through the real doors.

1. **Point at the page first.** The live board is
   `https://<org>.github.io/PyAutoBrain/` (refreshed each morning by
   `brain_board.yml`; badge.json beside it is the headline). If the human just
   wants the link or the headline, that is the answer — don't re-collect.
2. **Live digest on request** — run `bin/pyauto-brain board` (add `--json` for
   the raw surface) and relay its markdown digest faithfully, including the
   Degraded section. On a machine with the local workspace, `PYAUTO_ROOT` is
   honoured; without one the resume/community legs degrade honestly and say so.

   **Without `gh` (mobile, web), gather first — you are the only thing that
   can.** The `mcp__github__*` tools are an agent capability; `_board.py` is a
   subprocess and cannot reach them. So fetch the overnight legs yourself,
   write them to a scratch file keyed by endpoint, and hand it over:

   ```
   bin/pyauto-brain board --github-data /tmp/board-github-data.json
   ```

   For each `overnight_jobs` entry in `config/policy.yaml`
   (`<repo>:<workflow>`), one `mcp__github__actions_list`
   (`list_workflow_runs`, `resource_id` = the workflow file, `per_page` 1),
   stored under `repos/<org>/<repo>/actions/workflows/<wf>/runs?per_page=1`.
   Add `.../actions/runs/<id>/jobs` (`list_workflow_jobs`) where you want the
   blocked-at-a-gate refinement. Store each response **verbatim**: the row
   reads `conclusion`, `status`, `created_at` (**not** `updated_at` — that one
   renders the age as `?`) and `html_url`. The file's shape, and the three rules a
   gatherer must not bend — a miss is *could not ask*, an explicit `null` says
   the fetch failed, a broken file is fatal rather than degrading — are the
   contract in [`../../board/AGENTS.md`](../../board/AGENTS.md) → "Reading the
   board in a remote session". Do not invent a second shape for a leg that is
   not covered yet: leave it dark and let it say so.
3. **Never act from the digest.** Community replies stay `/community`'s
   human-gated job; closing issues stays `/issue_cleanup`'s; deletion stays
   `/repo_cleanup`'s. The board only names the door.
4. The local sync/clean leg is not yours to run from chat — it is the
   terminal command `bash PyAutoBrain/bin/morning.sh` on the human's machine.

Publishing (`--apply`) is CI's job (`brain_board.yml`); run it manually only
when asked to debug the render, writing under `_site/` or a scratch dir.
