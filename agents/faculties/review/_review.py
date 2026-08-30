#!/usr/bin/env python3
"""agents/faculties/review/_review.py — the review-surface substrate.

The **review faculty** is a read-only opinion sink: given a task worktree or
explicit repo checkouts, it prepares the **ReviewSurface** — everything the
reviewing agent needs to run the review procedure in this faculty's AGENTS.md
(code review at high effort + a verify pass) and map the outcome to a
CLEAN / FINDINGS / BLOCKED verdict.

This script produces the *surface*, never the *verdict*: findings are the
reviewing agent's judgment. It is stdlib-only, never writes anything, and
never exits non-zero because of what the diff contains.

Exit codes: 0 surface produced · 4 no reviewable diff / could not resolve ·
5 bad usage.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# The one workspace-root resolver, shared with bin/_pyauto_root.sh, so a
# remote session (checkouts under /home/user, $HOME=/root) resolves the same
# tree a developer box does.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import _pyauto_root  # noqa: E402

WT_BASE = _pyauto_root.pyauto_wt_root()

# Paths that smell like public API / behaviour when changed — flags only,
# the reviewing agent judges.
RISK_MARKERS = {
    "config-or-schema": (".yaml", ".yml", ".json", ".toml", ".ini", ".cfg"),
    "packaging": ("setup.py", "setup.cfg", "pyproject.toml", "requirements"),
}


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=False,
    )
    return out.stdout.strip() if out.returncode == 0 else ""


# Load-bearing empirical claims: assertions about the change's *effect* that are
# dangerous if wrong (a "no-op" that isn't; a "byte-identical" that differs).
# The whole point of surfacing them is to ROUTE the reviewing agent to each one
# so the adversarial "what would make this false, and what was run?" pass fires
# by construction — not because the author remembered to run it. See
# docs/agent_failure_modes.md item 6 (and A5/F3: real, confident, wrong claims).
_CLAIM_RE = re.compile(
    r"\b("
    r"no[- ]?ops?|byte[- ]?identical|identical|unchanged|no change|"
    r"does ?n['o]t (?:change|affect|touch|break)|"
    r"proven|verified|no effect|equivalent|"
    r"zero (?:diff|leak|regression|change)|0 diff|"
    r"safe to (?:delete|merge|remove)|cannot (?:leak|break|affect)|"
    r"guaranteed|behaviou?r[- ]preserving"
    r")\b",
    re.IGNORECASE,
)


def load_bearing_claims(text: str, limit: int = 12) -> list[str]:
    """Extract lines from commit-message bodies that assert a load-bearing
    empirical claim. Returned for the reviewing agent to adversarially check;
    the agent makes the final load-bearing/idle judgement."""
    seen: set[str] = set()
    claims: list[str] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("#*-> ").strip()
        if len(line) < 8 or not _CLAIM_RE.search(line):
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        claims.append(line if len(line) <= 200 else line[:197] + "...")
        if len(claims) >= limit:
            break
    return claims


def repo_surface(repo: Path) -> dict | None:
    """One repo's slice of the ReviewSurface, or None if there is no diff."""
    if not (repo / ".git").exists():
        return None
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    base = _git(repo, "merge-base", "HEAD", "origin/main")
    if not base:
        return None
    commits = _git(repo, "log", "--oneline", f"{base}..HEAD")
    if not commits:
        return None
    claims = load_bearing_claims(_git(repo, "log", "--format=%B", f"{base}..HEAD"))
    files = _git(repo, "diff", "--name-status", f"{base}..HEAD").splitlines()
    stat = _git(repo, "diff", "--shortstat", f"{base}..HEAD")
    changed = [line.split("\t")[-1] for line in files if line.strip()]
    flags = []
    if not any("test" in f.lower() for f in changed):
        flags.append("no-test-changes")
    for name, exts in RISK_MARKERS.items():
        if any(f.endswith(exts) or any(m in f for m in exts) for f in changed):
            flags.append(name)
    if any(f.endswith(".py") and "test" not in f.lower() for f in changed):
        flags.append("python-source")
    return {
        "repo": repo.name,
        "path": str(repo),
        "branch": branch,
        "base": base[:12],
        "commits_ahead": len(commits.splitlines()),
        "commits": commits.splitlines(),
        "shortstat": stat,
        "files": files,
        "risk_flags": flags,
        "claims_to_falsify": claims,
    }


def in_place_repos(task: str) -> list[Path]:
    """Checkouts claimed by an in-place task (worktree: none) in active.md.

    Parses only the named task's `- repos:` block (`  - <Repo>: <branch>`
    lines), never the bare 2-space claims other tooling reads — an in-place
    entry lists its repos there and the checkouts live at the workspace root.
    """
    pyauto_root = _pyauto_root.pyauto_root()
    active = pyauto_root / "PyAutoMind" / "active.md"
    if not active.exists():
        return []
    repos: list[Path] = []
    in_entry = in_block = False
    for line in active.read_text(errors="replace").splitlines():
        if line.startswith("## "):
            in_entry = line[3:].strip() == task
            in_block = False
            continue
        if not in_entry:
            continue
        if line.strip() == "- repos:":
            in_block = True
            continue
        if in_block:
            m = re.match(r"^  - ([A-Za-z0-9_-]+):", line)
            if m:
                repos.append(pyauto_root / m.group(1))
            else:
                in_block = False
    return [r for r in repos if (r / ".git").exists()]


def resolve_repos(task: str | None, repos: list[str]) -> list[Path]:
    if task:
        root = WT_BASE / task
        if not root.is_dir():
            # No worktree — an in-place task; fall back to its active.md claims.
            return in_place_repos(task)
        # Claimed repos are real directories (not symlinks) holding a .git
        # file/dir — worktree_create symlinks everything unclaimed.
        return sorted(
            p for p in root.iterdir()
            if p.is_dir() and not p.is_symlink() and (p / ".git").exists()
        )
    return [Path(r).resolve() for r in repos]


ADVERSARY_CONTRACT = """\
INDEPENDENT ADVERSARY MODE (autonomous-ship gate, leg 5)

  Who may run this: NOT the session or model that wrote the branch. The leg's
  entire value is independence — the organism's own audit found the review leg
  on autonomous ships was in practice the branch's own author, that "a healthy
  pass and a rote one write the identical ledger row", and that the one
  confirmed-wrong load-bearing claim of its window lived outside the surface the
  stage reads. The catches that did happen came from a different model reading
  the same diff. A self-run adversary leg is not a weaker version of this leg;
  it is an absent one, and recording it as run is a false ledger row.

  Your job is NOT to review the change. It is to FALSIFY its claims — starting
  with the witness, which is the claim the whole task was scoped around.

  For each claim: what would make this false, and what in the diff, the tests or
  a run actually shows it is not? Then say which. A claim you cannot falsify AND
  cannot find a basis for is a FINDING (unverified-claim), not a pass.
"""


def emit_human(surfaces: list[dict], witness: str = "", adversary: bool = False) -> None:
    print("== ReviewSurface (review faculty — surface only; the verdict is the")
    print("   reviewing agent's, per agents/faculties/review/AGENTS.md) ==")
    for s in surfaces:
        print(f"\n-- {s['repo']}  [{s['branch']}]  base {s['base']}")
        print(f"   {s['commits_ahead']} commit(s) ahead — {s['shortstat']}")
        for c in s["commits"][:10]:
            print(f"   * {c}")
        print(f"   risk flags: {', '.join(s['risk_flags']) or 'none'}")
        for f in s["files"][:40]:
            print(f"     {f}")
        if len(s["files"]) > 40:
            print(f"     ... and {len(s['files']) - 40} more")
        claims = s.get("claims_to_falsify") or []
        if claims:
            print("   claims to falsify (adversarial pass — for EACH: what would")
            print("   make it false, and what in the diff/run proves it isn't?):")
            for c in claims:
                print(f"     ? {c}")
    print("\nVerdict rubric: CLEAN (nothing must change) | FINDINGS (ranked,")
    print("file:line, failure scenario) | BLOCKED (could not review — say why).")
    if witness:
        print()
        print("  THE WITNESS — the claim this task was scoped around, and the")
        print("  one whose failure means the work did not do what it promised:")
        print(f"    * {witness}")
        print("  Falsify it first. If it does not hold, nothing below matters.")
    if adversary:
        print()
        print(ADVERSARY_CONTRACT)
    print("A load-bearing claim above with no falsified-by basis in the branch is")
    print("a FINDING (unverified-claim) — see the faculty AGENTS.md.")
    if any(s.get("claims_to_falsify") for s in surfaces):
        print("Record ONE disposition line per lifted claim in the verdict:")
        print('  claim: "<lifted line>" -> basis-cited: <test/measurement/diff>'
              " | idle | FINDING (unverified-claim)")
        print("A CLEAN over a non-empty claims surface without dispositions is")
        print("malformed evidence, not CLEAN (faculty AGENTS.md step 2a).")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="review")
    ap.add_argument("--task", default="",
                    help="task worktree name under the workspace worktree root "
                         f"({WT_BASE})")
    ap.add_argument("--repo", action="append", default=[], help="explicit repo checkout path")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--witness", default="",
                    help="the task's Witness: header — the claim the work was "
                         "scoped around, falsified first")
    ap.add_argument("--adversary", action="store_true",
                    help="independent-adversary mode (autonomous-ship gate leg "
                         "5): print the independence contract. Must be run by a "
                         "different model from the one that wrote the branch")
    a = ap.parse_args(argv)
    if not a.task and not a.repo:
        print("review: pass --task <name> or --repo <path>", file=sys.stderr)
        return 5
    repos = resolve_repos(a.task or None, a.repo)
    if not repos:
        print("review: could not resolve any repo checkout", file=sys.stderr)
        return 4
    surfaces = [s for s in (repo_surface(r) for r in repos) if s]
    if not surfaces:
        print("review: no reviewable diff against origin/main", file=sys.stderr)
        return 4
    if a.as_json:
        payload = {"review_surface": surfaces}
        if a.witness:
            payload["witness"] = a.witness
        if a.adversary:
            payload["mode"] = "independent-adversary"
            payload["contract"] = ADVERSARY_CONTRACT
        print(json.dumps(payload, indent=2))
    else:
        emit_human(surfaces, witness=a.witness, adversary=a.adversary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
