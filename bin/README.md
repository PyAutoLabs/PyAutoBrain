# PyAutoBrain/bin/

Executable tooling for the PyAuto organism.

- **`pyauto-brain`** — the PyAutoBrain CLI (reasoning-layer entry point).
- **`install.sh`** — the cross-organ Claude skill/command **installer**.
- **`check_skill_line_counts.sh`** — the skill line-count **guard** (primary
  skill `.md` files must stay < 200 lines).

The installer and guard used to live in `admin_jammy/skills/`. They moved here
because they are organism-wide infrastructure, not admin_jammy's own tooling —
admin_jammy hosts no skills and is slated to leave `PyAutoLabs/`.

## install.sh

Auto-discovers (no hardcoded skill list) by scanning each organ repo's
`skills/` dir for `*/` subdirs, then symlinks each into `~/.claude/`:

- **`PyAutoMind/skills/`** — registry-coupled skills (`create_issue`).
- **`PyAutoBrain/skills/`** — development-workflow skills (`start_dev`,
  `start_dev_for_user`, `plan_branches`, `start_library`, `start_workspace`,
  `ship_library`, `ship_workspace`, `register_and_iterate`, `repo_cleanup`,
  `update_issue`).
- **`PyAutoHeart/skills/`** — status / readiness / validation skills
  (`worktree_status`, `smoke_test`, `dep_audit`, `verify_install`,
  `review_release`, `audit_docs`, `cli_noise_clean`), plus the reference-only
  `/health` legs `health_sweep/`, `pyauto-status/`, `pyauto-status-full/` (driven
  by the Brain's `/health` door, not installed as standalone commands).
- **`PyAutoBuild/skills/`** — release-execution skills **only** (`pre_build`).
  Build owns no dev-workflow skills; `ship_*` (Brain) only *call* its release step.
- **`autolens_profiling/skills/`** — science-profiling skills (`profile_likelihood`).
- **`admin_jammy/skills/`** — vestigial: hosts no skills; scanned only so an old
  checkout still resolves, auto-skipped once admin_jammy leaves.

Discovery rule per root:

- A directory with `SKILL.md` → **skill**, symlinked to `~/.claude/skills/<name>/`.
- A directory with `<dirname>.md` (and no `SKILL.md`) → **command**, symlinked to
  `~/.claude/commands/<name>.md`.

Roots that aren't checked out are skipped. It is idempotent — existing symlinks
are replaced, non-symlink files are left alone, and broken symlinks pointing into
a PyAuto root are pruned. Re-run it after pulling updates.

## Bootstrap on a new machine

```bash
cd ~/Code/PyAutoLabs
git clone git@github.com:PyAutoLabs/PyAutoBrain.git
git clone git@github.com:PyAutoLabs/PyAutoMind.git
git clone git@github.com:PyAutoLabs/PyAutoHeart.git
bash PyAutoBrain/bin/install.sh
```

## Execution environments

There is **no special "mobile" or "phone" mode**. Skills run the same logic in
any environment and only differ in where they read state from: a `local-dev`
checkout uses local git + task worktrees; a `web-github` / `ci-only` session uses
the clones present in the working directory (and the GitHub API for branch
state). The full environment model is in `PyAutoBrain/skills/WORKFLOW.md`.
