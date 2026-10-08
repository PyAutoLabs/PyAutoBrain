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
3. Review overnight work: only failures, blocked gates, pending/missing runs
   and unavailable evidence. Successful routine runs remain in machine data.
4. Maintenance: issue/repo cleanup, Hygiene findings and local observations,
   plus an actionable CI-speedup entry linked to Heart's timing evidence.

No morning sync, community section/shortcut, readiness/release, versions,
resume, autonomous history, need-you/trend banner or global Degraded section.
Explain unavailable retained evidence locally; never present a failed read as
an empty successful check. Do not remove conductors merely because their
operational evidence lives in another organ.

## Collection and compatibility

`board/_board.py` collects overnight jobs from `config/policy.yaml`, Heart's
performance evidence, open issue counts, Hygiene and explicit dev-box publishes.
Retired source collectors are not called. Deprecated board.json keys remain
empty for existing readers. state.json retains the shared v1 schema; badge and
state describe Brain's overnight coordination only, never release readiness.
The internal `degraded` list remains diagnostic metadata and keeps freshness
unknown when a required read fails, but is not a global page section.

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
verbatim. Each configured overnight workflow reads
`repos/<org>/<repo>/actions/workflows/<workflow>/runs?per_page=1`, with optional
`repos/<org>/<repo>/actions/runs/<id>/jobs` for blocked-gate evidence.

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
