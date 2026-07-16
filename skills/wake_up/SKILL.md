---
name: wake_up
description: Start-of-day wake-up routine for the PyAuto workspace — sync every repo to main and clean generated cruft (local), then a gh-API status glance (overnight scheduled-run conclusions, version-pin drift, resume context) plus /health and /hygiene, ending in one prioritized digest. Runs on the CLI and on mobile Claude Code chat / Codex (auto-skips local-only steps when there is no workspace). Use when starting the day or asked for a morning status/cleanup pass.
---

# Wake Up

Follow [`wake_up.md`](wake_up.md) exactly. Composition skill — drive the existing
doors (`/health`, `/hygiene`) and the `bin/` scripts; auto-run only the
non-destructive steps and surface everything destructive for approval. It is
**environment-aware**: full routine locally, gh-API status glance on mobile/codex.
