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
work_links=(), copy_label='Copy check-in prompt', organ=None)` and the shared stylesheet and
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
and are appended under **Work on GitHub** in the portable prompt. They are fixed
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

## Adoption matrix

| Board | Renderer owner | Prompt and work destination | Phase |
|---|---|---|---|
| Brain | Brain `board/_board.py` | Operational review; configured Brain repository | Core |
| Mind | Brain intake conductor | Task planning; resolved Mind repository | Core |
| Cortex | Brain Cortex conductor | Existing check-in; Cortex and active registered project remotes | Core |
| Ears | Ears | Existing community check-in; Community Hub and relevant work repos | Pilot |
| Heart | Heart | Existing systematic repair instructions; Heart work repository | Pilot |
| Hands | Hands | Release coordination with existing approval gates | Consumers |
| Memory | Memory | Knowledge/reading workflow with existing approval gates | Consumers |
| Pulse | Pulse | Profiling check-in and registered project repositories | Consumers |
| Insight | Insight | Inference check-in and registered project repositories | Consumers |
| Nerves | Nerves | Configuration work and relevant repositories | Consumers |
| Gut | Gut | Retention/recovery workflow, preserving destructive-action approval | Consumers |
| Eyes | Eyes | Figure review and registered project repositories | Consumers |
| Scientist | Scientist | Organism routing and the relevant organ repositories | Consumers |

The later phases must audit destinations and preserve existing payloads before
adoption; this table is not a claim of completed rollout. Heart moves its
recognizable systematic-fix action into the top panel without competing duplicate
primary controls. The standards-discovery rollout is tracked alongside these
migrations in Mind.

## Verification

Check text/URL escaping, visible destinations, exact preview/copy agreement,
empty and multiline direction, Unicode, multiple panels, clipboard denial,
keyboard navigation, prompt budgets, mobile/tablet/desktop and light/dark.
Preserve existing freshness indicators, data feeds and action-specific controls.
After authorized merges, regenerate and inspect published HTML; source adoption
alone does not make a board live.
