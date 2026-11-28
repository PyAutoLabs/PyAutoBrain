# Brain board — agents and workflows

Read-only directory and task-routing surface. Brain clarifies intent, plans,
consults faculties and coordinates workflows. Mind owns task state; Heart owns
health and test/CI timing evidence; Hands owns release execution; Ears owns
community collection. The board does not duplicate their dashboards.

## Visible surface

1. Agents & workflows, generated from the dispatcher registry and installed
   skill sources. Conductors coordinate, faculties advise, workflows execute
   procedures. Keep this the first content section.
2. A shared orchestration panel for an unspecified task (shared layout places
   it beside the banner controls). Focus on the user's request and route it.
3. Maintenance: issue/repo cleanup, Hygiene findings and local observations,
   plus an actionable CI-speedup entry linked to Heart's timing evidence.
4. Homeostasis (maintenance orchestrator): every maintenance finding and
   where it stands (below).

No morning sync, community section/shortcut, readiness/release, versions,
resume, autonomous history (the hygiene ledger's trend is the one history kept), need-you/trend banner or global Degraded section.
Explain unavailable retained evidence locally; never present a failed read as
an empty successful check. Do not remove conductors merely because their
operational evidence lives in another organ.

## Collection and compatibility

`board/_board.py` collects Heart's performance evidence, open issue counts,
Hygiene and explicit dev-box publishes. It does not poll overnight workflows.
Scientist reviews dated owner records and workflow runs on demand for the
requested period; no scheduled digest or duplicate activity ledger is created.
Retired source collectors are not called. Deprecated board.json keys remain
empty for existing readers. state.json retains the shared v1 schema; badge and
state describe availability of Brain's directory and maintenance evidence,
never overnight outcomes or release readiness.
The internal `degraded` list remains diagnostic metadata and keeps freshness
unknown when a required read fails, but is not a global page section.

## Hygiene ledger (PyAutoBrain#735)

`board/_hygiene_ledger.py` keeps one JSONL line per UTC day of the hygiene
pre-scan: `{date, sha, rows, status, not_scanned, absent_repos, unkeyed,
findings, evidence}`.
`sha` is the Brain commit that rendered, not the scanned repos' commits.
Keyed modes (`KEYED_MODES`): `refs`, `docstrings`, `escapes`, `optdeps`,
`extras`; keys are `<mode>:<repo>:<file>:<ref>` without line numbers (rules in
`finding_key`; `docstrings`/`escapes` are per file, `extras` is
`extras:::<dependency>` with the declaring repos in `evidence`). Any other
non-clean mode is listed in `unkeyed`. A same-day re-run replaces that day's
line, except that a partial, unscanned, errored or unkeyed mode (or one with
`absent_repos`) never replaces
the complete keys and status an earlier run that day recorded for that mode.
With `BOARD_HYGIENE_LEDGER` set, the render upserts today's line, fills
board.json `history` (last 30 days, counts only), draws a sparkline per hygiene
row plus a collapsed trend list, and `--apply` publishes `hygiene_ledger.jsonl`
beside board.json. Unset, there is no history.

Write path: a **published sidecar**, not a commit. `brain_board.yml` fetches the
live ledger from its own Pages site (cache bypassed with `?ts=<run id>` and a
no-cache header) and keeps `contents: read`; committing would need a token that
can push to the ruleset-protected `main`. The sidecar's cost is durability, so
it fails closed: a non-404 error, a malformed body (an HTML page, a truncated
file), a ledger with fewer days than the live board.json's `history` (a
truncation on a line boundary), or a 404 ledger beside a board.json that has
history (a LOST ledger) stops the job before deploy. `--apply` with
`BOARD_HYGIENE_LEDGER` set requires the ledger AND fetch's `.fetched.json`
marker (exit 5 otherwise, before writing anything) and refuses fewer days
than were fetched. **A fetch failure therefore blocks that day's board refresh —
intended.** Only a true first publish (board.json 404 or history empty), or
`fetch --reset` added on purpose, starts an empty ledger. The cloud job is the
only writer; a dev-box `board publish` never touches it.

Known follow-up, not fixed here: the `tokens` row still differs between laptop
and cloud, because it reads the workspace-root `AGENTS.md`, which only a laptop
has.

## Homeostasis (maintenance orchestrator) (PyAutoBrain#747)

`board/_homeostasis.py` is Homeostasis's board, hosted here until Physiology
is cut out of the Brain (not on Heart: Heart holds the readiness verdict, not
a work queue). With `BOARD_HOMEOSTASIS=1` (set by `brain_board.yml`; opt-in
like the hygiene pre-scan, so a terminal render stays instant) the render
reads the findings through `batch maintain`'s own path
(`_maintain.read_sources`: census, monitoring, release, hygiene per mode,
timing). The counts therefore match `batch maintain --dry-run`. The hygiene
source reads `BOARD_HYGIENE_LEDGER` when set (today's line), else the
published ledger. `BOARD_MAINTAIN_{BOARD,CENSUS,HEART,HYGIENE}_JSON` replay
saved inputs.

Status comes from the Mind beside the Brain (`repo_path(PYAUTO_ROOT,
"PyAutoMind")`: in CI the workflow's sibling clone of Mind `main`; locally the
workspace's Mind, read only). It matches the writer's key marks
(`Source-key:`, `<!-- maint-key: -->`, the legacy `<!-- heart-key: -->`) in
`draft/`, `active/` and `complete/`:

| Status | Meaning |
|--------|---------|
| `open` | no prompt carries the key, or only a glance draft does (Homeostasis's own queue) |
| `promoted` | a judge prompt in `draft/` carries it |
| `in-progress` | a prompt in `active/` carries it |
| `done` | only a `complete/` record carries the key mark |
| `cleared` | the Mind carries the key but no source lists it now, and the key's source (from the prompt's "Filed from" line, else every source) read fresh and complete |

**`done` needs the close-out to carry the key.** A `lifecycle.py close`
record today has no `Source-key:`, so a closed maintenance task almost never
reads `done`; making the close-out keep the key is a follow-up in Mind. Until
then, a reported finding that no prompt carries but that a `complete/` record
mentions anywhere in its text reads `open (closed task, awaiting a fresh
read)`, with that record's path. A finding with no mention reads plain `open`.

The section shows counts by source, tier and status, the source reads in
`batch maintain`'s words, the findings (key, source, tier, repo, status,
witness) and the cleared keys. An unread, stale or partial source reads as
such, never as zero findings. The headline names unread and stale/partial
sources as "not all-clear", and the count pill is green only when every
source read fresh and complete and the Mind was read. A key from an unread
source is never cleared. With no Mind, statuses read `unknown`. Any error
(`SystemExit` included) fails this section only, and the board still renders.
The collection runs under an overall time bound (`BOARD_HOMEOSTASIS_TIMEOUT`,
default 180 s); past it the section renders UNREAD. `brain_board.yml` sets
`BOARD_HEART_FEED_ONLY=1`, so the release source reads Heart's published feed
only and never runs a local `pyauto-heart readiness`
(`_maintain.load_release`). `--apply` writes `homeostasis.json` (the whole
section) beside board.json; board.json keeps the counts and reads only. It is a pure
render with no state between runs, so unlike the hygiene ledger there is
nothing to fetch or merge.

`bin/pyauto-brain board` renders Markdown; `--html`, `--json`, `--badge`,
`--state` select other formats. `--apply --out <dir>` writes the published
artifacts. `.github/workflows/brain_board.yml` owns scheduled publication.

## Local evidence and retired morning routine

Morning sync, its timer installer and the wake-up skill are retired. Independent
sync/cleanup utilities remain available for explicit maintenance. They are never
run by opening the dashboard.

Brain local observations remain explicit: `pyauto-brain board publish`.
Heart owns its independent commands: `pyauto-heart tick` followed on success by
`pyauto-heart publish`. These need a local machine; a cloud dashboard refresh
cannot observe its checkouts. Do not imply automatic local publication.

Existing installations should disable the old `pyauto-morning.timer` or remove
the crontab entry marked `# pyauto-morning` before updating. No replacement
background task is installed. Uninstall only the retired routine, not unrelated
Heart publishing or user schedules.

## Shared presentation

Follow [standards](../docs/standards.md), especially navigation and orchestration.
Reuse `_theme.py`; keep Brain-specific changes in this renderer. Other boards
must retain their own controls, content and owning evidence. HTML and Markdown
must agree; escape owner data and preserve exact portable copy payloads.

## Reading the board in a remote session

Without gh, `--github-data <file>` accepts endpoint-keyed JSON supplied by the
agent's GitHub tools. An endpoint absent from that file or explicitly null means
unavailable, never an empty result. Malformed JSON is fatal. Preserve responses
verbatim. This adapter supports retained sources; it does not re-enable
retired overnight collection.

The board's one remaining GitHub leg is upkeep: key
`search/issues?q=org:<org>+is:issue+is:open&per_page=1`
(`open_issues_endpoint()`), value GitHub's search response verbatim (the leg
reads `total_count`). Versions, community and resume are retired and not
collected, so `bin/version_drift.sh` and the community scan need no seam of
their own; a retired leg returns only through this same endpoint-keyed map.

`BOARD_GH` and `BOARD_PAGES_BASE` support hermetic fixtures. A failed Pages
read may use an owning repo's local published artifact; it must not manufacture
freshness. Public artifacts must never leak private local paths or credentials.

## Human-first, machine-readable cockpit evolution

Keep the cockpit a presentation of owner-published state. Extend the shared
`state.json` contract incrementally when it improves the human interface; do
not infer truth from rendered HTML or duplicate an organ's readiness policy.
The optional v1 additions in `state_schema.json` describe attention items with
stable `id`, canonical `state`, `reason`, `actions`, `recommended_action_id`,
and explicit `requires_human_decision` / `decision` when the source knows a
human choice is needed. Legacy producers and colour fields remain supported.

Canonical item states mean: `healthy` (checks satisfied), `active` (work in
progress), `stale` (evidence expired), `blocked` (a prerequisite prevents work),
`failed` (an operation failed), `action_required` (an explicit next intervention
is needed), and `unknown` (insufficient evidence). Severity is a separate fact.
Never map every red colour to failed or every blocked gate to human judgement.
Overnight workflow rows are the first producer: stable repo/workflow identity,
GitHub conclusion or gate annotation as reason, and run URL as evidence. This
is an attention list, not an inventory; successful unblocked runs are omitted.
Cancellation is unknown, not proof of failure or a request to restart.

Actions exist as descriptors independent of buttons: id, label, kind
(`link`, `command`, `prompt`) and target. Commands/prompts are copied for a human
to invoke through existing tools; a prompt is a manual handoff, not executable
shell. Safety is descriptive (`read_only`, `requires_approval`,
`scientific_judgement`, `never_automatic`, `unclassified`), never authorization.
Absent safety means unclassified. Detection, description and recommendation
execute nothing. No generic executor or new permissions infrastructure is added.

`updated` is the feed generation time, not last success or source-check time.
Optional `valid_until` is an owner-declared deadline at or after `updated`;
absence supplies no expiry policy. Preserve evidence URLs and do not invent
source timestamps. Stable identities and structured values can support later
comparisons without a message bus or persistent monitoring service. A future
executor must retain execution evidence; copied prompts do not claim an action
was run or succeeded.
