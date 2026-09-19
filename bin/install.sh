#!/usr/bin/env bash
# Bootstrap Claude Code commands and Claude/Codex skills from every PyAuto
# organism repo that hosts them.
#
# This installer lives in PyAutoBrain (the reasoning/orchestration organ). It
# scans every organ repo's skills/ dir and symlinks skills into both harnesses;
# Claude-only command files remain available as slash commands. Roots that
# aren't checked out are simply skipped.
#
# User-level install roots (scanned in order):
#   - admin_jammy/skills/   — vestigial: admin_jammy hosts no skills and is
#                             slated to leave PyAutoLabs/; kept only so an old
#                             checkout still resolves, auto-skipped once gone
#   - PyAutoMind/skills/    — registry-coupled skills (create_issue, handoff)
#   - PyAutoBrain/skills/   — development-workflow skills (start_*/ship_*/…)
#   - PyAutoHeart/skills/   — status / readiness / diagnostic skills
#   - PyAutoHands/skills/   — release-execution skills ONLY (pre_build)
#   - autolens_profiling/skills/ — science-profiling skills (profile_likelihood)
#
# (PyAutoHands's root is for its own release/packaging-execution skills only — it
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
#   bash PyAutoBrain/bin/install.sh                        # install skills/commands
#   bash PyAutoBrain/bin/install.sh --write-agents-surface # (re)generate the command
#                                                          #   surface block in each organ AGENTS.md
#   bash PyAutoBrain/bin/install.sh --check-agents-surface # drift-check that block (exit 1 on drift)
#   bash PyAutoBrain/bin/install.sh --write-project-discovery # (re)generate committed
#                                                          #   .claude/ + .codex/ discovery per repo
#   bash PyAutoBrain/bin/install.sh --check-project-discovery # drift-check that discovery (exit 1)
#                                                          #   trailing repo names narrow the check
#   bash PyAutoBrain/bin/install.sh --write-workspace-policy # refresh root AGENTS.md delegation block
#   bash PyAutoBrain/bin/install.sh --check-workspace-policy # drift-check that block
#
# The command-surface modes are the agent-agnostic half of command discovery:
# per-tool symlinks (above) are absent in cloud/web sessions, which load only
# committed repo files — so the verb → purpose → `bin/pyauto-brain <verb>` index
# is generated into PyAutoBrain's auto-loaded AGENTS.md (Brain is loaded in every
# session, so one copy reaches everywhere), sourced from the single agent registry
# in `bin/pyauto-brain`. Other organs opt in via the markers but need not — Brain's
# copy already travels with every session.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/_pyauto_root.sh"
. "$SCRIPT_DIR/_repo_paths.sh"
for _repo in PyAutoMind PyAutoBrain PyAutoMemory PyAutoHeart PyAutoHands autolens_profiling PyAutoFit; do
  pyauto_repo_path "$_repo" "$PYAUTO_ROOT" >/dev/null || exit $?
done
ADMIN_SKILLS_DIR="$PYAUTO_ROOT/admin_jammy/skills"
MIND_SKILLS_DIR="$(pyauto_repo_path PyAutoMind "$PYAUTO_ROOT")/skills"
BRAIN_SKILLS_DIR="$(pyauto_repo_path PyAutoBrain "$PYAUTO_ROOT")/skills"
HEART_SKILLS_DIR="$(pyauto_repo_path PyAutoHeart "$PYAUTO_ROOT")/skills"
BUILD_SKILLS_DIR="$(pyauto_repo_path PyAutoHands "$PYAUTO_ROOT")/skills"
PROFILING_SKILLS_DIR="$(pyauto_repo_path autolens_profiling "$PYAUTO_ROOT")/skills"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"

# ---------- Command surface (agent-agnostic discovery) ----------
#
# The organ repos whose auto-loaded AGENTS.md carries the generated command
# surface. Framework identity (a fork keeps the five organs), so it is fixed
# here — like the skills dirs above — rather than parsed out of repos.yaml. A
# repo opts in by adding the marker pair; absent repos / repos without markers
# are skipped, so this runs in a partial/web checkout.
COMMANDS_BEGIN="<!-- pyauto:commands:begin -->"
COMMANDS_END="<!-- pyauto:commands:end -->"
ORGAN_REPOS=(PyAutoBrain PyAutoMind PyAutoMemory PyAutoHeart PyAutoHands)
WORKSPACE_POLICY="$SCRIPT_DIR/../policy/workspace_model_delegation.md"
WORKSPACE_POLICY_BEGIN="<!-- pyauto:model-delegation:begin -->"
WORKSPACE_POLICY_END="<!-- pyauto:model-delegation:end -->"
WORKSPACE_POINTER="$SCRIPT_DIR/../policy/workspace_model_delegation_pointer.md"
WORKSPACE_POINTER_BEGIN="<!-- pyauto:model-delegation-pointer:begin -->"
WORKSPACE_POINTER_END="<!-- pyauto:model-delegation-pointer:end -->"

# Emit the canonical command-surface block (identical in every organ) to stdout,
# sourced from the agent registry in bin/pyauto-brain — the single source of
# truth for `bin/pyauto-brain <verb>`. Sourcing defines the arrays without
# running the dispatcher (its main is guarded on direct execution).
agents_surface_block() {
  # shellcheck disable=SC1090
  source "$SCRIPT_DIR/pyauto-brain"
  echo "$COMMANDS_BEGIN"
  cat <<'EOF'
<!-- Generated by `PyAutoBrain/bin/install.sh --write-agents-surface` from the
     agent registry in `PyAutoBrain/bin/pyauto-brain`. Do not edit between these
     markers — edit the registry there and re-run. Checked by
     `PyAutoBrain/bin/install.sh --check-agents-surface`. -->

Run from the Brain checkout. Read the selected agent's `AGENTS.md` only when
invoking it; `bin/pyauto-brain help <verb>` exposes its full contract.

**Conductors** — front doors you drive (decide *and* act):

| Verb | Purpose | Entrypoint |
|------|---------|------------|
EOF
  local name desc
  for name in "${CONDUCTOR_ORDER[@]}"; do
    desc="${AGENT_DESC[$name]//|/\\|}"
    printf '| `%s` | %s | `bin/pyauto-brain %s` |\n' "$name" "$desc" "$name"
  done
  cat <<'EOF'

**Faculties** — read-only opinions the conductors consult (also runnable):

| Verb | Purpose | Entrypoint |
|------|---------|------------|
EOF
  for name in "${FACULTY_ORDER[@]}"; do
    desc="${AGENT_DESC[$name]//|/\\|}"
    printf '| `%s` | %s | `bin/pyauto-brain %s` |\n' "$name" "$desc" "$name"
  done
  echo "$COMMANDS_END"
}

# Splice the block (read from a file, so no awk -v escape processing) between the
# markers in one AGENTS.md, replacing whatever is there.
_splice_surface() {
  local file="$1" blockfile="$2" tmp
  tmp="$(mktemp)"
  awk -v begin="$COMMANDS_BEGIN" -v end="$COMMANDS_END" -v bf="$blockfile" '
    $0 == begin { while ((getline line < bf) > 0) print line; close(bf); skip=1; next }
    $0 == end   { skip=0; next }
    !skip       { print }
  ' "$file" > "$tmp"
  if cmp -s "$file" "$tmp"; then
    echo "unchanged: $file"; rm -f "$tmp"
  else
    mv "$tmp" "$file"; echo "updated: $file"
  fi
}

write_agents_surface() {
  local blockfile repo agents
  blockfile="$(mktemp)"; agents_surface_block > "$blockfile"
  for repo in "${ORGAN_REPOS[@]}"; do
    agents="$(pyauto_repo_path "$repo" "$PYAUTO_ROOT")/AGENTS.md"
    if [ ! -f "$agents" ]; then
      echo "skipped (absent): $agents"; continue
    fi
    if ! grep -qF -- "$COMMANDS_BEGIN" "$agents" || ! grep -qF -- "$COMMANDS_END" "$agents"; then
      echo "skipped (no command markers): $agents"; continue
    fi
    _splice_surface "$agents" "$blockfile"
  done
  rm -f "$blockfile"
}

check_agents_surface() {
  local blockfile repo agents cur drift=0
  blockfile="$(mktemp)"; agents_surface_block > "$blockfile"
  for repo in "${ORGAN_REPOS[@]}"; do
    agents="$(pyauto_repo_path "$repo" "$PYAUTO_ROOT")/AGENTS.md"
    if [ ! -f "$agents" ]; then
      echo "skipped (absent): $agents"; continue
    fi
    if ! grep -qF -- "$COMMANDS_BEGIN" "$agents"; then
      echo "skipped (no command markers): $agents"; continue
    fi
    cur="$(mktemp)"
    awk -v begin="$COMMANDS_BEGIN" -v end="$COMMANDS_END" '
      $0 == begin { grab=1 } grab { print } $0 == end { grab=0 }' "$agents" > "$cur"
    if cmp -s "$cur" "$blockfile"; then
      echo "OK: $agents"
    else
      echo "DRIFT: $agents — run: bash PyAutoBrain/bin/install.sh --write-agents-surface"
      drift=1
    fi
    rm -f "$cur"
  done
  rm -f "$blockfile"
  return "$drift"
}

workspace_policy() {
  local mode="$1" agents="$PYAUTO_ROOT/AGENTS.md" target tmp tmp2 begin_count end_count legacy=0 pointer_legacy=0
  [ -f "$agents" ] || { echo "skipped (absent): $agents"; return 0; }
  target="$(readlink -f "$agents")"
  begin_count="$(grep -cFx "$WORKSPACE_POLICY_BEGIN" "$agents" || true)"
  end_count="$(grep -cFx "$WORKSPACE_POLICY_END" "$agents" || true)"
  if [ "$begin_count" = 0 ] && [ "$end_count" = 0 ]; then
    [ "$(grep -cF -- '- **Delegate execution to a subagent' "$target" || true)" = 1 ] &&
      [ "$(grep -cF -- '- **Never rewrite pushed history.' "$target" || true)" = 1 ] || {
        echo "cannot locate unique legacy delegation block: $agents"; return 1;
      }
    legacy=1
  elif [ "$begin_count" != 1 ] || [ "$end_count" != 1 ]; then
    echo "malformed workspace-policy markers: $agents"; return 1
  fi
  [ "$(grep -cFx "$WORKSPACE_POLICY_BEGIN" "$WORKSPACE_POLICY" || true)" = 1 ] &&
    [ "$(grep -cFx "$WORKSPACE_POLICY_END" "$WORKSPACE_POLICY" || true)" = 1 ] || {
      echo "malformed policy source: $WORKSPACE_POLICY"; return 1;
    }
  awk -v begin="$WORKSPACE_POLICY_BEGIN" -v end="$WORKSPACE_POLICY_END" '
    $0 == begin { if (seen_end) exit 2; seen_begin=1 }
    $0 == end { if (!seen_begin) exit 2; seen_end=1 }
    END { if (!seen_begin || !seen_end) exit 2 }
  ' "$WORKSPACE_POLICY" || { echo "unordered policy source: $WORKSPACE_POLICY"; return 1; }
  [ "$(grep -cFx "$WORKSPACE_POINTER_BEGIN" "$WORKSPACE_POINTER" || true)" = 1 ] &&
    [ "$(grep -cFx "$WORKSPACE_POINTER_END" "$WORKSPACE_POINTER" || true)" = 1 ] || {
      echo "malformed pointer source: $WORKSPACE_POINTER"; return 1;
    }
  awk -v begin="$WORKSPACE_POINTER_BEGIN" -v end="$WORKSPACE_POINTER_END" '
    $0 == begin { if (seen_end) exit 2; seen_begin=1 }
    $0 == end { if (!seen_begin) exit 2; seen_end=1 }
    END { if (!seen_begin || !seen_end) exit 2 }
  ' "$WORKSPACE_POINTER" || { echo "unordered pointer source: $WORKSPACE_POINTER"; return 1; }
  if [ "$(grep -cFx "$WORKSPACE_POINTER_BEGIN" "$target" || true)" = 0 ] &&
     [ "$(grep -cFx "$WORKSPACE_POINTER_END" "$target" || true)" = 0 ]; then
    [ "$(grep -cF -- '- **Model delegation** (provider-aware defaults:' "$target" || true)" = 1 ] || {
      echo "cannot locate unique legacy delegation pointer: $agents"; return 1;
    }
    awk '
      /- \*\*Model delegation\*\* \(provider-aware defaults:/ { if (seen_end) exit 2; seen_begin=1 }
      /PyAutoBrain\/skills\/WORKFLOW\.md/ { if (seen_begin) seen_end=1 }
      END { if (!seen_begin || !seen_end) exit 2 }
    ' "$target" || { echo "unordered legacy delegation pointer: $agents"; return 1; }
    pointer_legacy=1
  elif [ "$(grep -cFx "$WORKSPACE_POINTER_BEGIN" "$target" || true)" != 1 ] ||
       [ "$(grep -cFx "$WORKSPACE_POINTER_END" "$target" || true)" != 1 ]; then
    echo "malformed workspace-pointer markers: $agents"; return 1
  else
    awk -v begin="$WORKSPACE_POINTER_BEGIN" -v end="$WORKSPACE_POINTER_END" '
      $0 == begin { if (seen_end) exit 2; seen_begin=1 }
      $0 == end { if (!seen_begin) exit 2; seen_end=1 }
      END { if (!seen_begin || !seen_end) exit 2 }
    ' "$target" || { echo "unordered workspace-pointer markers: $agents"; return 1; }
  fi
  if [ "$legacy" = 1 ]; then awk '
    /- \*\*Delegate execution to a subagent/ { if (seen_end) exit 2; seen_begin=1 }
    /- \*\*Never rewrite pushed history\./ { if (!seen_begin) exit 2; seen_end=1 }
    END { if (!seen_begin || !seen_end) exit 2 }
  ' "$target" || { echo "unordered legacy delegation block: $agents"; return 1; }; fi
  if [ "$legacy" = 0 ]; then awk -v begin="$WORKSPACE_POLICY_BEGIN" -v end="$WORKSPACE_POLICY_END" '
    $0 == begin { if (seen_end) exit 2; seen_begin=1 }
    $0 == end { if (!seen_begin) exit 2; seen_end=1 }
    END { if (!seen_begin || !seen_end) exit 2 }
  ' "$target" || { echo "unordered workspace-policy markers: $agents"; return 1; }; fi
  tmp="$(mktemp "$(dirname "$target")/.agents-policy.XXXXXX")"
  awk -v begin="$WORKSPACE_POLICY_BEGIN" -v end="$WORKSPACE_POLICY_END" -v policy="$WORKSPACE_POLICY" -v legacy="$legacy" '
    legacy && /^- \*\*Delegate execution to a subagent/ { while ((getline line < policy) > 0) print line; close(policy); skip=1; next }
    legacy && skip && /^- \*\*Never rewrite pushed history\./ { skip=0; print; next }
    $0 == begin { while ((getline line < policy) > 0) print line; close(policy); skip=1; next }
    $0 == end { skip=0; next }
    !skip { print }
  ' "$target" > "$tmp"
  tmp2="$(mktemp "$(dirname "$target")/.agents-pointer.XXXXXX")"
  awk -v begin="$WORKSPACE_POINTER_BEGIN" -v end="$WORKSPACE_POINTER_END" -v policy="$WORKSPACE_POINTER" -v legacy="$pointer_legacy" '
    legacy && /^- \*\*Model delegation\*\* \(provider-aware defaults:/ { while ((getline line < policy) > 0) print line; close(policy); skip=1; next }
    legacy && skip && /PyAutoBrain\/skills\/WORKFLOW\.md/ { skip=0; next }
    $0 == begin { while ((getline line < policy) > 0) print line; close(policy); skip=1; next }
    $0 == end { skip=0; next }
    !skip { print }
  ' "$tmp" > "$tmp2"
  rm -f "$tmp"; tmp="$tmp2"
  chmod --reference="$target" "$tmp"
  if cmp -s "$target" "$tmp"; then
    echo "OK: $agents"; rm -f "$tmp"; return 0
  fi
  if [ "$mode" = write ]; then mv "$tmp" "$target"; echo "updated: $agents"; return 0; fi
  rm -f "$tmp"; echo "DRIFT: $agents — run: bash PyAutoBrain/bin/install.sh --write-workspace-policy"; return 1
}

# ---------- Committed per-tool discovery (web/cloud) ----------
#
# Project discovery is generated from every registered repository in the Mind
# body map. Claude links remain relative to canonical skills/; Codex adapters
# expose flat assistant and workspace skills under stable namespaced names.
# This committed tree is available in cloud/web sessions without user-level setup.
# The Python generator uses the registered body map and preserves user-owned files.
write_project_discovery() {
  python3 "$SCRIPT_DIR/project_discovery.py" write --root "$PYAUTO_ROOT" "$@"
}
check_project_discovery() {
  python3 "$SCRIPT_DIR/project_discovery.py" check --root "$PYAUTO_ROOT" "$@"
}

case "${1:-}" in
  --write-agents-surface) write_agents_surface; exit 0 ;;
  --check-agents-surface) check_agents_surface; exit $? ;;
  --write-project-discovery) shift; write_project_discovery "$@"; exit $? ;;
  --check-project-discovery) shift; check_project_discovery "$@"; exit $? ;;
  --write-workspace-policy) workspace_policy write; exit $? ;;
  --check-workspace-policy) workspace_policy check; exit $? ;;
  --help|-h)
    sed -n '2,24p' "$0"; exit 0 ;;
esac

# ---------- Execution-environment note ----------
#
# Skill discovery is identical in every execution environment (local-dev,
# web-github, ci-only). When a root repo is not checked out, it is simply
# skipped — the skills from the roots that ARE present still install.

if [ -d "$(pyauto_repo_path PyAutoFit "$PYAUTO_ROOT")" ] || [ -d "$HOME/Code/PyAutoLabs/PyAutoFit" ]; then
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
      _link_symlink "$entry" "$CLAUDE_HOME/skills/$name" "Claude skill"
      installed_count=$((installed_count + 1))
      found=1

      local skill_name
      skill_name="$(sed -n 's/^name:[[:space:]]*//p' "$entry/SKILL.md" | head -1)"
      if [ -z "$skill_name" ] || [[ "$skill_name" == *[!a-z0-9-]* ]]; then
        echo "  SKIP $name (Codex skill name invalid or missing: ${skill_name:-<empty>})"
      else
        _link_symlink "$entry" "$CODEX_HOME/skills/$skill_name" "Codex skill"
        installed_count=$((installed_count + 1))
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
install_from_dir "$BUILD_SKILLS_DIR" "PyAutoHands/skills/ — release-execution skills (Hands)"
install_from_dir "$PROFILING_SKILLS_DIR" "autolens_profiling/skills/ — science-profiling skills"

# ---------- Summary ----------

echo "Done. Restart Claude Code and Codex to pick up changes."
