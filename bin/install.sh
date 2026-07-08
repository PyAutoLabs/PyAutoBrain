#!/usr/bin/env bash
# Bootstrap Claude Code skills/commands into ~/.claude/ from every PyAuto
# organism repo that hosts skills.
#
# This installer lives in PyAutoBrain (the reasoning/orchestration organ). It
# scans every organ repo's skills/ dir and symlinks their skills+commands into
# ~/.claude/. Roots that aren't checked out are simply skipped.
#
# Discovery roots (scanned in order):
#   - admin_jammy/skills/   — vestigial: admin_jammy hosts no skills and is
#                             slated to leave PyAutoLabs/; kept only so an old
#                             checkout still resolves, auto-skipped once gone
#   - PyAutoMind/skills/    — registry-coupled skills (create_issue, handoff)
#   - PyAutoBrain/skills/   — development-workflow skills (start_*/ship_*/…)
#   - PyAutoHeart/skills/   — status / readiness / diagnostic skills
#   - PyAutoBuild/skills/   — release-execution skills ONLY (pre_build)
#   - autolens_profiling/skills/ — science-profiling skills (profile_likelihood)
#
# (PyAutoBuild's root is for its own release/packaging-execution skills only — it
#  owns NO dev-workflow skills; the ship_* skills merely call its release step.)
#
# Auto-discovers skills in each root:
#   - A directory with SKILL.md → installed as ~/.claude/skills/<name>/
#   - A directory with <name>.md (and no SKILL.md) → installed as a flat
#     command at ~/.claude/commands/<name>.md
#
# Safe to re-run — existing symlinks are replaced, non-symlink files are skipped.
#
# Usage:
#   bash PyAutoBrain/bin/install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYAUTO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ADMIN_SKILLS_DIR="$PYAUTO_ROOT/admin_jammy/skills"
MIND_SKILLS_DIR="$PYAUTO_ROOT/PyAutoMind/skills"
BRAIN_SKILLS_DIR="$PYAUTO_ROOT/PyAutoBrain/skills"
HEART_SKILLS_DIR="$PYAUTO_ROOT/PyAutoHeart/skills"
BUILD_SKILLS_DIR="$PYAUTO_ROOT/PyAutoBuild/skills"
PROFILING_SKILLS_DIR="$PYAUTO_ROOT/autolens_profiling/skills"

# ---------- Execution-environment note ----------
#
# Skill discovery is identical in every execution environment (local-dev,
# web-github, ci-only). When a root repo is not checked out, it is simply
# skipped — the skills from the roots that ARE present still install.

if [ -d "$PYAUTO_ROOT/PyAutoFit" ] || [ -d "$HOME/Code/PyAutoLabs/PyAutoFit" ]; then
  echo "Environment: local-dev (PyAuto repos detected)"
else
  echo "Environment: web-github / ci-only (clone roots on demand)"
fi
echo ""

mkdir -p "$HOME/.claude/skills" "$HOME/.claude/commands"

# ---------- Prune stale symlinks ----------
#
# Self-healing: when a skill is removed or re-homed, its old ~/.claude symlink
# would otherwise dangle. Remove only BROKEN symlinks whose target points into a
# PyAuto root — never touch real files or symlinks that resolve, and never touch
# links pointing outside the managed roots (e.g. user-added skills).

prune_stale_symlinks() {
  local dir="$1"
  [ -d "$dir" ] || return 0
  for link in "$dir"/*; do
    [ -L "$link" ] || continue
    [ -e "$link" ] && continue                      # resolves fine — keep
    local tgt; tgt="$(readlink "$link")"
    case "$tgt" in
      "$PYAUTO_ROOT"/*|"$HOME/Code/PyAutoLabs"/*)
        echo "  PRUNE $(basename "$link") (stale → $tgt)"; rm -f "$link" ;;
    esac
  done
}

prune_stale_symlinks "$HOME/.claude/skills"
prune_stale_symlinks "$HOME/.claude/commands"

# ---------- Install one source dir's skills/commands ----------

install_from_dir() {
  local source_dir="$1"
  local label="$2"

  if [ ! -d "$source_dir" ]; then
    echo "${label}: (source dir not present, skipping)"
    return
  fi

  echo "$label"
  local installed_count=0

  for entry in "$source_dir"/*/; do
    [ -d "$entry" ] || continue
    local name
    name=$(basename "$entry")

    # Skip the install.sh dir itself, or any non-skill dirs
    [ "$name" = "skills" ] && continue

    if [ -f "$entry/SKILL.md" ]; then
      # Skill — symlink the directory
      local dst="$HOME/.claude/skills/$name"
      _link_symlink "$entry" "$dst" "skill"
      installed_count=$((installed_count + 1))
    elif [ -f "$entry/$name.md" ]; then
      # Command — symlink the flat .md file
      local dst="$HOME/.claude/commands/$name.md"
      _link_symlink "$entry/$name.md" "$dst" "command"
      installed_count=$((installed_count + 1))
    else
      echo "  SKIP $name (no SKILL.md or $name.md found)"
    fi
  done

  echo "  ($installed_count installed from $label)"
  echo ""
}

_link_symlink() {
  local src="$1"
  local dst="$2"
  local kind="$3"
  local name
  name=$(basename "$dst")

  if [ -L "$dst" ]; then
    rm "$dst"
  elif [ -e "$dst" ]; then
    echo "  SKIP $name ($kind — non-symlink exists at $dst)"
    return
  fi

  ln -s "$src" "$dst"
  echo "  LINK $name ($kind)"
}

# ---------- Run installs ----------

install_from_dir "$ADMIN_SKILLS_DIR" "admin_jammy/skills/ — vestigial (hosts no skills)"
install_from_dir "$MIND_SKILLS_DIR"  "PyAutoMind/skills/ — registry-coupled skills (Mind)"
install_from_dir "$BRAIN_SKILLS_DIR" "PyAutoBrain/skills/ — development-workflow skills (Brain)"
install_from_dir "$HEART_SKILLS_DIR" "PyAutoHeart/skills/ — status / readiness skills (Heart)"
install_from_dir "$BUILD_SKILLS_DIR" "PyAutoBuild/skills/ — release-execution skills (Hands)"
install_from_dir "$PROFILING_SKILLS_DIR" "autolens_profiling/skills/ — science-profiling skills"

# ---------- Summary ----------

echo "Done. Restart Claude Code to pick up changes."
