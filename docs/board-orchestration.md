# Dashboard orchestration panel

The Ears panel is the reference: one chat for the board's work, a prominent copy
action, optional direction, an exact selectable preview and links to where the
work happens. The common order is logo/banner, section navigation, then the
orchestration panel and content. These are single-user operational boards: omit
paragraphs explaining what the dashboard does or how to use it. Keep concise
headings, controls, work links and actual status/evidence. Legacy hero ledes and
panel descriptions remain accepted by the API but are not displayed.

## Component contract

Use `board/_theme.py::orchestration_panel(key, title, description, prompt,
work_links=(), copy_label='Copy check-in prompt', organ=None, refreshed_at=None,
refresh_url=None)` and the shared stylesheet and
`JS`. Each panel needs a unique simple key. Headings, descriptions, labels,
prompts and user direction are plain text, never interpreted as HTML.

Supply the lowercase `organ` key for the approved action heading. The shared
`prompt_heading(organ, heading_id=None)` helper also serves existing owner-specific
controls without changing their prompts. It selects fixed text and emphasizes only
the organ name with `strong`; it never accepts arbitrary heading HTML. Titles for
legacy callers remain escaped plain text. All thirteen organ headings live in
`board/_theme.py`; reuse that mapping rather than copying sentences into renderers.
Keep each heading on one line with responsive typography; do not hide overflow or
truncate words. Omit explanatory subtitles and preserve work links/copy controls.

`work_links` is an ordered list of mappings with `label` and `href`. Destinations
must be HTTPS GitHub links. These owner-supplied links appear beside the controls
and are appended under **Work on GitHub** in the portable prompt. Repository
buttons display the repository name from the destination URL, without the owner
prefix or “Open”/“repository” filler. Non-repository companion destinations keep
their supplied labels; portable prompt metadata retains its original labels.
Every primary panel copy button uses **Copy check-in prompt**. They are fixed
metadata; typing a focus does not rewrite them. Avoid putting the same URL list
in the base prompt as well. Missing metadata displays an explicit unavailable
message, never an invented destination.

Link the actual work repository, which may differ from the board's source or
hosting repository. Derive identity from Mind's body map or the domain's project
registry. For several projects, use clearly named links; never pick an arbitrary
project for a whole-board check-in. A domain may explicitly select a project and
supply its associated destinations, while preserving a useful whole-board default.
Ears keeps **Open Community Hub** as a companion work surface; the hub must not
be mislabelled as a repository. Public boards must not expose private-only
metadata that their owner has not authorized for publication.

## Prompt and interaction behavior

The owner supplies the default prompt and preserves its domain workflow. Copying
only writes to the clipboard. It never runs commands, files issues, posts replies,
merges PRs, releases packages or submits compute. Optional direction is appended
as user context, leaving the general remit and trusted repository context intact.

The preview is the exact complete copy payload, including repository links and
optional direction. Empty direction restores the general prompt. Unicode is
preserved; browser line endings are normalized to LF. The shared 50,000-character
budget applies to the composed prompt. Over-budget requests offer the complete
text as a download, never a truncated copy.

Copy feedback uses a live status region. If clipboard access fails, open and
select the complete preview for manual copying. Without JavaScript, default
prompt text and work links remain accessible through native HTML controls.
Different panels must not overwrite one another's input, preview or feedback.

## Last updated footer

Omit redundant **GitHub Page** links and the legacy standalone Cortex
last-check-in/stale widget. Keep underlying check-in records and feed semantics.

Every panel has the same small footer beneath the copy controls: **Read the
prompt** on the left, **Last updated …** and **↻ Update** on the right. It wraps
below the preview control on narrow screens. Brain owns the markup, typography,
wording and browser clock; owners supply the refresh timestamp and destination.

`refreshed_at` is the last successful collection of the information displayed
in the panel. Supply a precise timezone-aware ISO-8601 timestamp (seconds
required) or an aware Python datetime. It is not a scientific evidence date,
last content-change date, check-in, verdict time or the time a browser opens the
page. A rerender of cached inputs must preserve the successful-refresh receipt;
a new successful collection may update the receipt even when content is unchanged.
Keep existing evidence-age and health indicators and feed semantics intact.

The browser shows `Last updated 23 minutes ago` (or `just now`, hours, days),
with one common policy: green below one hour, yellow from one hour to below
24 hours, red at 24 hours and above. These colours describe snapshot freshness,
never health or scientific qualification. Missing, malformed, date-only,
timezone-less or future timestamps show grey `Last updated unavailable`.
Future stamps remain available for inspection but cannot look fresh. A native
keyboard-accessible disclosure reveals the exact UTC date and time. Without
JavaScript, valid timestamps remain readable in UTC; no freshness colour is
guessed. Age advances every 30 seconds and when the tab becomes visible, without
network requests or changing the source timestamp.

`refresh_url` opens the owner's existing HTTPS refresh controls. A link to a
GitHub Actions workflow opens its control surface; clicking it does not claim
that a refresh has run. Never substitute a page reload, publication-only action,
scientific compute submission or destructive action. Missing destinations show
`Update unavailable`. Refresh metadata stays out of the copied prompt.

Whole-board aggregation uses the oldest successful refresh across all displayed
sources. If collection failed or a required source has no receipt, show unknown
instead of taking the newest surviving timestamp. Source-specific panels may
use their own narrower scope. No-change content-drift checks may use
`normalize_refresh_stamp(page)` to exclude only the refresh clock; changes to
destinations, prompts and other presentation must still be detected.

### Timestamp and action adoption

| Board | Successful refresh source | Update workflow |
|---|---|---|
| Brain | collected `generated`, unknown when degraded; no clock fallback | `brain_board.yml` |
| Mind | census `refreshed_at`, independent of date-only generation label | `dashboard_refresh.yml` |
| Cortex | census `refreshed_at`, unknown on census problems | `dashboard_refresh.yml` |
| Ears | snapshot `generated` with complete collection receipts | `pages.yml` |
| Heart | collection snapshot `ts`, never verdict fallback | `heart-health.yml` |
| Hands | snapshot `generated`, unknown on collection errors | `release_board.yml` |
| Memory | snapshot `generated` | `knowledge_board.yml` |
| Pulse | oldest successful ingest refresh receipt, preserved offline | `dashboard_refresh.yml` |
| Insight | oldest successful ingest refresh receipt, preserved offline | `dashboard_refresh.yml` |
| Nerves | snapshot `generated`, unknown on collection errors | `nerves_board.yml` |
| Gut | snapshot `generated`, unknown on collection errors/missing ref listing | `gut_board.yml` |
| Eyes | oldest successful manifest collection `captured_at`, not figure age | `dashboard_refresh.yml` |
| Scientist | snapshot `generated`, unknown when any headline is unavailable | `organism_board.yml` |

URLs come from the owning repository identity. This matrix describes source
adoption; live publication is verified after the corresponding owner PRs merge.
The shared component must land before consumers of its new keyword arguments.

## Adoption matrix

| Board | Renderer owner | Prompt and work destination |
|---|---|---|
| Brain | Brain `board/_board.py` | Operational review; configured Brain repository |
| Mind | Brain intake conductor | Task planning; resolved Mind repository |
| Cortex | Brain Cortex conductor | Existing check-in; Cortex and active registered project remotes |
| Ears | Ears `ears/board.py` | Existing community check-in; Community Hub companion, configured Ears repo and publicly verified snapshot work repos |
| Heart | Heart `heart/dashboard.py` | Existing systematic repair instructions; Heart work repository |
| Hands | Hands `autohands/board.py` | Release review with existing approval gates; resolved Hands remote; distinct release/rehearsal/validation actions retained |
| Memory | Memory `scripts/board.py` | Knowledge and reading queue review; resolved Memory remote; paper actions retained |
| Pulse | Pulse `pulse/campaigns.py` and `pulse/board.py` | Existing profiling check-in; Pulse ledger and every registered project repository; separate systematic-fix action retained |
| Insight | Insight `insight/campaigns.py` and `insight/board.py` | Existing inference check-in; Insight ledger and registered inference project repositories |
| Nerves | Nerves `scripts/board.py` index | Configuration review; Nerves and named source repositories from the collected body-map identities; source detail pages retain their specific controls |
| Gut | Gut `scripts/board.py` | Retention/recovery review; Gut and the associated Mind retention ledger; permanent void still requires explicit human authorization |
| Eyes | Eyes `eyes/board.py` | Figure review; Eyes plus every registered visualization project repository; per-figure copy/critique actions retained |
| Scientist | Scientist `scripts/organism_board.py` | Operational routing; each displayed board's work repository; existing door commands retained |

These are the owner implementations and destination rules. Mind's
[consumer phase](https://github.com/PyAutoLabs/PyAutoEars/issues/15) records the
per-repository PRs and post-merge publication evidence. Heart's recognizable
systematic-fix action occupies the top panel without a duplicate primary
action. Optional direction focuses the work without replacing the general
remit or changing trusted repository metadata. A campaign identifier alone is
not a repository identity: do not invent remotes for unregistered projects or
publish private project metadata merely to populate a link.

## Verification

Check text/URL escaping, visible destinations, exact preview/copy agreement,
empty and multiline direction, Unicode, multiple panels, clipboard denial,
keyboard navigation, prompt budgets, mobile/tablet/desktop and light/dark.
Preserve existing freshness indicators, data feeds and action-specific controls.
After authorized merges, regenerate and inspect published HTML; source adoption
alone does not make a board live.
