# The Brain Board — the operational surface (the morning door)

> Tier: **surface** — a generated page, not an agent. It decides nothing and
> opines on nothing; it reads what the organs already publish and renders it.
> (Contrast conductors, which act, and faculties, which judge — this only
> shows. The precedent is the Mind dashboard, which lives with the intake
> conductor; the Heart and Hands boards are the sibling shapes.)

The sixth one-tap board, live at the Brain's GitHub Pages URL
(`https://<org>.github.io/PyAutoBrain/`): the organism's **morning and
general starting point**. It replaces the interactive `/wake_up` composition —
everything that skill assembled by driving doors in sequence is collected on a
schedule and rendered as one page, each actionable row carrying a one-tap 📋
copy-for-Claude payload:

| Section | Signal owner | One-tap payload |
|---------|--------------|-----------------|
| ⌨ Morning sync | `bin/morning.sh` (local) | the terminal command itself |
| 🌙 Overnight | scheduled workflows (`config/policy.yaml board: overnight_jobs`); a ⏸ blocked gate's ::warning annotation is rendered inline | `/bug … — <run url>` on failures |
| ❤️ Readiness & release | the Heart board's `badge.json` + `board.json` (structured blockers, each carrying its OWN `/bug` prompt — or, for an evidence gap, the `command` that re-runs its check — plus `stale_plan`, the one payload that closes every gap; all rendered verbatim, never re-derived) and the Hands badge | `/health`, the plan's prompt or command chain, the blockers' own prompts |
| ⏱ Test performance | the Heart board's published `performance` block — rendered verbatim, never re-derived | each row's own prompt |
| 🏷️ Version consistency | the coupled-set stamps (`board: version_stamps`) | `/bug version drift: …` |
| 💬 Community | the Ears (`community scan`, reused wholesale) — every open conversation gets a row | `/community`, `/community triage <ref>` |
| 🔄 Resume | the Mind's registry + generated counts; pending-release PRs | `/start_dev …`, `/prm <url>` |
| 🧹 Upkeep | open-issue count; the cleanup doors | `/issue_cleanup`, `/hygiene`, `/repo_cleanup` |
| 🧼 Hygiene | the hygiene conductor's own `--json` pre-scan, run IN this render (BOARD_HYGIENE_SCAN=1; brain_board.yml checks out the body-map scan set blobless+sparse first) — no machine involved | each row's own delegate door |
| 🖥️ Dev box | `state/devbox_board.json` — worktree state (unpushed/dirty/stashes — the one thing only the dev box can see; its hygiene rows render only when no cloud scan ran), pushed by `board publish` (morning.sh's last step); age-stamped, stale at 48h, dropped after 7d | — |
| 🤖 Autonomous runs | the tail of the Mind's `autonomy_log.md`, verbatim | — |
| 🚪 All doors | `bin/pyauto-brain`'s own registry (never a second copy) | `/<verb>` |

The header also carries a **trend sparkline** — the "N need you" count per
day, handed forward through the published `board.json` itself (no commits, no
extra state: each render reads yesterday's page, appends today, caps at 30).

**Compose, don't recompute** — the board re-derives nothing. The community
section imports the community conductor's `build_scan()`; the resume counts
are parsed from the Mind's own generated `dashboard.md`; readiness comes from
the Heart board's published badge. Every unreachable source degrades into an
honest "Degraded" row, never fabricated content.

**Read-only** — the collect half touches only read-only `gh` endpoints and
public Pages URLs. It never posts, labels, or edits anything on GitHub, and
never writes files outside `--apply`'s output directory.

## Running

```bash
bin/pyauto-brain board                # markdown digest in the terminal
bin/pyauto-brain board --html         # the one-tap page
bin/pyauto-brain board --badge        # the cross-board headline contract
bin/pyauto-brain board --apply        # write _site/ (what brain_board.yml serves)
bin/pyauto-brain board publish        # dev-box leg: distill hygiene + worktree
                                      #   state into state/devbox_board.json and
                                      #   push (morning.sh runs this for you;
                                      #   --dry-run prints, --no-hygiene is fast)
```

Publishing is `.github/workflows/brain_board.yml`: a morning cron plus manual
dispatch renders `--apply` output and deploys it to GitHub Pages (page +
`badge.json` + `board.json` + `board.md`). Nothing is committed to the repo —
the board is served, not stored, so a daily refresh makes no commit noise.

## Look (`_theme.py`)

`board/_theme.py` is the one place that answers *what does a one-tap board
look like* — the stylesheet, the hero, the facet pills, the family footer.
Presentation only: no state, no collection, no policy. It is shared, not
copied: this board and the Mind dashboard (rendered by the intake conductor)
both import it, so a change to the look lands on the whole family at once
rather than drifting page by page.

Each organ has an accent sampled from its own logo, and every board opens
with a dark hero reproducing that logo's wordmark — white `PyAuto`, the organ
name in its accent, the logo's tagline underneath. Below the hero the page
goes back to being a plain readable document, because these are lists people
scan on a phone before breakfast.

*A phone before breakfast* is a size, not a mood: the sheet makes wrapping the
page **default** (`overflow-wrap` on `body`, inherited), so a run URL or a
dotted test id in markup the theme has never seen — an organ's own reasons
list, details block or footer — cannot push the page sideways. A board that
needs a column on one line (`white-space:nowrap`) still may; what it must not
do is re-declare the wrap per component, which is how the family drifted into
one page that scrolled and one that did not.

Colour is information, never decoration: the accent is organ identity; pills
are row facets, toned so that only the *exception* is coloured (`supervised`
is 9 of 10 prompts in the Mind, so it stays neutral — tinting it would paint
the backlog and say nothing); `ok`/`warn`/`bad` stay reserved for verdict
semantics. `ORGANS` holds the palette — five of the six are sampled from the
real logo files; the umbrella board has no logo to sample, so its accent and
tagline are designed to sit in the family instead.

**This board's own facets.** Every row here says what it is in the same
vocabulary the Mind dashboard uses. The accent is what the row *is* — the
repo a workflow belongs to, the kind of a community conversation, the target
of an in-flight task, a door that acts (a conductor) rather than one that only
opines. A tone is what the row *says*: a conclusion, a Heart verdict, a
version stamp off consensus, how long someone has waited on a reply. An
in-flight task is the one row that composes rather than invents — it reads
the `Type:`/`Target:`/`Difficulty:`/`Autonomy:`/`Priority:` header the Mind
already wrote, so a task looks like itself on both pages. Above the sections,
a header strip carries one number per section that can ask something of a
human; a source that could not be read counts `–`, never a zero.

## Configuration

Instance vocabulary lives in `config/policy.yaml` under `board:` (the declared
config surface an adopting fork replaces): `overnight_jobs` (repo:workflow
pairs for the sweep), `version_stamps` (repo:path pairs for the consistency
check), `reference_release_repo`, `heart_board`, and `boards` (the sibling
board links). The org/owner is derived from the Mind's body map
(`PyAutoMind/repos.yaml`) at runtime — never hardcoded here.

Env: `PYAUTO_ROOT` (workspace root holding `PyAutoMind/`), `BOARD_GH`
(the gh binary; hermetic tests point it at a stub), `BOARD_PAGES_BASE`
(sibling-board base URL; tests point it at `file://` fixtures).

## Reading the board in a remote session

A Claude Code remote session (web/mobile) cannot reach either of the board's
data sources by default:

- **`gh` is not installed.** The overnight sweep, the version stamps, the
  community scan and the pending-release search all run through it. Without it
  they cannot ask — which is not the same as asking and getting nothing, and
  the render now says so (`could not read`, never `no runs`).
- **The sibling Pages boards are refused by the egress policy.** The proxy
  answers `403` to `CONNECT` for `<org>.github.io`, so `board.json` and
  `badge.json` — the Heart's readiness surface among them — are unreadable.
  Retrying never helps; the reason is named in the Degraded section rather than
  reported as a flake. Where the sibling repo is checked out, the board falls
  back to its local `board/board.json`.

So a remote render is expected to be partial. It carries a **⚠️ Degraded
render** banner above the sections, a per-leg reason at the foot, a headline
qualified with `partial view (N legs unread)`, and a grey badge rather than a
green one — a green badge is only ever emitted by a render that read
everything and found nothing wrong.

To get a complete board in a remote session, the environment needs outbound
access to the Pages host. That is environment configuration on claude.ai
(**Settings → the environment's network policy**), not something this repo can
set: add `<org>.github.io`, and `objects.githubusercontent.com` if you also
want CI artifacts to be downloadable rather than rebuilt locally. `gh` itself
is not installable in that image — drive GitHub through the MCP tools instead
(`skills/GITHUB_ACCESS.md`).
