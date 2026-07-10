#!/usr/bin/env bash
# Bootstrap Claude Code commands and Claude/Codex skills from every PyAuto
# organism repo that hosts them.
#
# This installer lives in PyAutoBrain (the reasoning/orchestration organ). It
# scans every organ repo's skills/ dir and symlinks skills into both harnesses;
# Claude-only command files remain available as slash commands. Roots that
# aren't checked out are simply skipped.
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
# Auto-discovers surfaces in each root independently:
#   - SKILL.md → installed in both the Claude and Codex skill roots
#   - <name>.md → installed as a flat Claude command
# A directory may contain both; neither surface suppresses the other.
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
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"

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

mkdir -p "$CLAUDE_HOME/skills" "$CLAUDE_HOME/commands" "$CODEX_HOME/skills"

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

prune_stale_symlinks "$CLAUDE_HOME/skills"
prune_stale_symlinks "$CLAUDE_HOME/commands"
prune_stale_symlinks "$CODEX_HOME/skills"

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

    local found=0
    if [ -f "$entry/SKILL.md" ]; then
      local skill_name
      skill_name="$(sed -n 's/^name:[[:space:]]*//p' "$entry/SKILL.md" | head -1)"
      if [ -z "$skill_name" ] || [[ "$skill_name" == *[!a-z0-9-]* ]]; then
        echo "  SKIP $name (invalid or missing SKILL.md name: ${skill_name:-<empty>})"
        found=1
      else
        _link_symlink "$entry" "$CLAUDE_HOME/skills/$name" "Claude skill"
        _link_symlink "$entry" "$CODEX_HOME/skills/$skill_name" "Codex skill"
        installed_count=$((installed_count + 2))
        found=1
      fi
    fi
    if [ -f "$entry/$name.md" ]; then
      _link_symlink "$entry/$name.md" "$CLAUDE_HOME/commands/$name.md" "Claude command"
      installed_count=$((installed_count + 1))
      found=1
    fi
    if [ "$found" -eq 0 ]; then
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

echo "Done. Restart Claude Code and Codex to pick up changes."
