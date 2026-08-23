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
| 🌙 Overnight | scheduled workflows (`config/policy.yaml board: overnight_jobs`) | `/bug … — <run url>` on failures |
| ❤️ Readiness | the Heart board's `badge.json` (cross-board contract) | `/health` |
| 🏷️ Version consistency | the coupled-set stamps (`board: version_stamps`) | `/bug version drift: …` |
| 💬 Community | the Ears (`community scan`, reused wholesale) | `/community`, `/community triage <ref>` |
| 🔄 Resume | the Mind's registry + generated counts; pending-release PRs | `/start_dev …`, `/prm <url>` |
| 🧹 Upkeep | open-issue count; the cleanup doors | `/issue_cleanup`, `/hygiene`, `/repo_cleanup` |
| 🚪 All doors | `bin/pyauto-brain`'s own registry (never a second copy) | `/<verb>` |

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
```

Publishing is `.github/workflows/brain_board.yml`: a morning cron plus manual
dispatch renders `--apply` output and deploys it to GitHub Pages (page +
`badge.json` + `board.json` + `board.md`). Nothing is committed to the repo —
the board is served, not stored, so a daily refresh makes no commit noise.

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
