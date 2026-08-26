# issue_cleanup — reference detail

Factored out of `issue_cleanup.md`. The body is authoritative for the flow; this
holds the collection commands, the record header taxonomy, the evidence rules,
the dashboard layout, the per-bucket execution recipes, the recap, and the
execution-environment fallback.

> **GitHub surface.** The `gh` commands below name the *operation*, not
> necessarily the command: a Claude Code remote session has no `gh` and
> reaches GitHub through the `mcp__github__*` tools instead. Probe once
> (`command -v gh`) and translate via
> [`../GITHUB_ACCESS.md`](../GITHUB_ACCESS.md).

## Collect open issues

Resolve the repo list and owners from `PyAutoMind/repos.yaml`. For each repo:

```bash
gh api "repos/<owner>/<repo>/issues?state=open&per_page=100" --paginate \
  --jq '[.[] | select(.pull_request == null) | {num:.number, title:.title,
         author:.user.login, created:.created_at, updated:.updated_at,
         labels:[.labels[].name], comments:.comments}]'
```

`select(.pull_request == null)` is **required** — the issues endpoint returns
pull requests too, and counting them inflates every total.

Note: this `gh` build rejects several documented `--json` fields on
`gh issue list` / `gh run view` (`displayTitle`, `jobs`, …). Use `gh api` for
anything structured; it is the reliable path here.

## Parse the records

Evidence comes from `PyAutoMind/complete/**/*.md`. Two rules govern it.

### Rule 1 — only *known* header lines count

Match `^\s*-?\s*<key>:\s*<rest-of-line>` and read the issue URL out of
`<rest-of-line>`. A URL appearing anywhere else in the file is **prose**, not a
claim: `complete/2026/05/many-vis-prep-dft.md` discusses `PyAutoArray#326` in
its notes while its own `- issue:` header says `(CI-triage cluster G, no GitHub
issue)`.

**`<key>` must be in the known set below — an arbitrary `- <word>:` is not a
header.** Records use `- notes:` for long prose paragraphs that routinely cite
issue URLs, so a bare "any `- key:` line" regex re-admits exactly the prose
Rule 1 exists to exclude. `PyAutoGalaxy#417` is the worked example: it appears
only inside another record's `- notes:` field, so nothing claims it and it
belongs in the unreconciled backlog.

### Rule 2 — the header key decides the meaning

| Key | Uses¹ | Meaning | Closable? |
|-----|------:|---------|-----------|
| `issue:` | 630 | This record **completes** that issue | **yes** |
| `issues:` | 6 | Same, several issues on one line | **yes** |
| `followup-issue:` | 2 | Record **spawned** it; still open | **no** |
| `follow-up-issue:` | 1 | Record **spawned** it; still open | **no** |
| `library-followup-issue:` | 1 | Record **spawned** it; still open | **no** |
| `parent-issue:` | 1 | Umbrella this record is one part of | **no** |
| `upstream-issues-filed:` | 1 | Filed upstream, not ours to close | **no** |
| `issued:` | 1 | Filed only — see Rule 3 | **no** |
| `plan:` | — | Implementation backlog, deliberately open | **no** |

¹ counts from the 2026-07-28 census of 800 records; re-derive rather than trust
these, but the **ratio** is the point — the completing key dominates, so a loose
`*issue*:` match looks right on a spot-check and silently closes live
follow-ups.

Treat the completing set as an **allowlist** (`issue:`, `issues:`), never the
spawn set as a denylist — a new spawn-style key added later must fail closed.

The table above is also the **known-key set** for Rule 1: a `- <word>:` line
whose key is not in it (`notes:`, `summary:`, `repos:`, …) is prose, and its
URLs are not claims of any kind.

### Rule 3 — annotations and status override

- Any `open` token (case-insensitive) in the text **after** the URL means hands
  off: `(open)`, `(open — findings census stays as reference)`, `(STAYS OPEN —
  real finding + resumable fit)`, `(both stay OPEN for parked design work
  only)`. Scan `plan:` lines for these too.
- A record carrying `Status: issued` **filed** its issue rather than completing
  it (`ep-hierarchical-scale-collapse.md` → `PyAutoFit#1405`, a live bug).
  Read the status field; `complete/` is the directory, not the verdict.

### Rule 4 — a phase-scoped claim does not complete an umbrella

If the annotation scopes the claim to part of the work — `(Phase 5 F5 item)`,
`(Phase 5 item 4)`, `(WP 2)`, `(stage b)` — the record completed *that piece*,
not the issue. Several records may each claim a different phase of the same
umbrella without any of them finishing it.

Route these to **bucket B** (weak evidence), never A. `PyAutoBrain#130` is the
worked example: four separate records claim Phase-5 items of it, and no
combination of them establishes that Phase 5 as a whole is done. Deciding that
needs a human reading the issue, which is exactly what bucket B is for.

## Evidence legs

An issue reaches bucket A only with **both**:

1. **Record leg** — a completing header key claims it, with no `open`
   annotation and no `Status: issued`.
2. **PR leg** — a merged PR. Check **both** paths; the timeline alone
   under-reports (12 of 29 in the first sweep had only the second):

```bash
# path 1 — GitHub's own cross-reference
gh api "repos/<owner>/<repo>/issues/<n>/timeline?per_page=100" \
  --jq '[.[] | select(.event=="cross-referenced" and .source.issue.pull_request != null)
        | {pr:.source.issue.number, merged:(.source.issue.pull_request.merged_at != null)}]'

# path 2 — a PR number named in the record body, verified merged
gh api "repos/<owner>/<repo>/pulls/<pr>" --jq 'if .merged_at then "MERGED" else .state end'
```

## Buckets

| Bucket | Definition | Action |
|---|---|---|
| **A** shipped | both evidence legs pass | closable, on confirmation |
| **B** weak evidence | a record exists but a leg fails | report only |
| **C** deliberately open | annotation or `Status: issued` says so | never touch |
| **D** in flight | claimed in `active.md` / `parked.md` | never touch |
| **E** external | author not in the maintainer set | route to `$community` |
| **F** unreconciled | no record at all | the real backlog; sub-split by age |

The maintainer set comes from `repos.yaml` ownership; everyone else is external.
Bot authors (`github-actions[bot]`) are their own sub-group: self-refreshing
issues like `[url-check]` and `[heart-health]` re-open themselves by design and
must be excluded from staleness ranking.

## Dashboard layout

```
Issue Cleanup — Audit
=====================
Summary
  18 repos scanned · 82 open issues
  A 29 closable · B 7 weak · C 5 held · D 6 in flight · E 8 external · F 27 unreconciled

Bucket A — Shipped, closable (record header + merged PR)
Bucket B — Record exists, evidence incomplete (report only)
Bucket C — Deliberately open (annotated in the record)
Bucket D — In flight (active.md / parked.md)
Bucket E — External, awaiting our reply  → $community
Bucket F — Unreconciled backlog (no record) — split: ancient / live / bot
```

One section per bucket, issues grouped by repo, each line carrying the evidence
that classified it (record path, PR number, or the annotation text). Omit empty
buckets; always print the Summary counts even if zero.

## Per-bucket execution (fixed order)

Print the exact list and get approval before each destructive step.

1. **Bucket A** — batch confirm, then per issue: comment the evidence, then
   close as completed.

   ```bash
   gh api repos/<owner>/<repo>/issues/<n>/comments -f body="$(cat <<'EOF'
   Closing as complete — swept by an issue-tracker reconciliation pass.

   This work shipped and is recorded in PyAutoMind:
   - `PyAutoMind/complete/<year>/<month>/<slug>.md`

   Verified via two independent legs: the record claims this issue in its
   `- issue:` header, and its pull request is confirmed merged. Reopen if
   anything here is still outstanding.
   EOF
   )"
   gh api -X PATCH repos/<owner>/<repo>/issues/<n> \
     -f state=closed -f state_reason=completed
   ```

   `gh issue close` is broken in this environment — it must be the comment +
   `PATCH` pair. `--jq .state` on the PATCH gives a one-word confirmation per
   issue; a run that prints anything other than `closed` needs investigating,
   not retrying.

2. **Bucket F, ancient sub-group** — never batch. Per issue: read the body,
   grep the current source for the API/module/infrastructure it names, and
   decide.
   - Named surface is **gone** → close with `state_reason=not_planned` and a
     comment saying what was greped and that it returned zero.
   - Named surface is **absent but still wanted** (the ask was never
     implemented) → **keep open**, and say so in the recap.

3. **Buckets B, C, D, E** — no action. Report them so the next sweep does not
   re-derive the same conclusions, and point bucket E at `$community`.

## Recap

```
Issue Cleanup — Recap
  Closed N as completed (bucket A)
  Closed N as not_planned (obsolete, bucket F)
  Held N deliberately-open · N in-flight · N external
  Left N unreconciled — the real backlog
  Kept open despite age: <issue> — <why it is still valid>
```

List everything kept and why, so the next sweep resumes from there rather than
re-litigating it.

## Regression bar

The audit is deterministic given the same trackers and records, so it can be
checked rather than eyeballed. Against the post-sweep state of 2026-07-28 it
must reproduce exactly:

| Bucket | Count | Notes |
|---|---:|---|
| open issues | 47 | across the 18 repos with trackers |
| **A** closable | **0** | all 29 were closed that day |
| **B** partial/umbrella | 1 | `PyAutoBrain#130` — Rule 4 |
| **C** deliberately open | 7 | see below |
| spawn-key held | 3 | Rule 2 |
| **D** in flight | 6 | `active.md` / `parked.md` |
| **E** external | 8 | community backlog |
| **F** unreconciled | 22 | the real backlog |

Bucket C must contain exactly `PyAutoArray#377`, `PyAutoFit#1330`,
`PyAutoFit#1332`, `PyAutoFit#1338`, `PyAutoFit#1405`, `PyAutoReduce#13`,
`PyAutoReduce#17` — note `#1338` arrives via an annotated `plan:` line and
`#1405` via `Status: issued`, so this count also exercises Rule 3.

The three spawn-key holds are `PyAutoArray#326` (`library-followup-issue`),
`autolens_workspace_test#106` (`follow-up-issue`) and `autolens_workspace_test#77`
(`followup-issue`) — the check that catches a regression to loose `*issue*:`
matching.

Two traps this bar exists to catch, both of which a first implementation got
wrong:

- **`PyAutoGalaxy#417` must land in F, not in a held bucket.** It is cited only
  inside another record's `- notes:` prose. If it shows up as "held", the
  header-key allowlist (Rule 1) has regressed to matching any `- word:` line —
  right answer, wrong reason.
- **`PyAutoBrain#130` must land in B, not A.** If it appears as closable, Rule 4
  has regressed and umbrella issues are being closed on partial evidence.
- `PyAutoHands#16` and `#17` stay in F despite being ~1337 days old — match them
  exactly, not by a `PyAutoHands#1*` prefix, which also catches `#127`/`#156`/`#161`.

## Execution environments

The audit is pure `gh` + reading `PyAutoMind/`, so it runs anywhere `gh` is
authenticated — including mobile Claude Code chat and Codex, where
`$repo-cleanup` cannot run at all. No local library checkout is needed.

This is the harness-portable half of the pair, so keep it that way: no step may
depend on a local library checkout, a Claude-only tool, or a `~/.claude` path.
Commands in this file are plain `gh` + POSIX shell for exactly that reason.
`bin/install.sh` installs the skill into `~/.claude/skills/issue_cleanup`,
`~/.claude/commands/issue_cleanup.md` and `~/.codex/skills/issue-cleanup` (Codex
takes the hyphenated `name:` from `SKILL.md`, which is why that frontmatter must
stay hyphenated).

The one degraded piece is the obsolescence probe in bucket F, which greps repo
source: without a local checkout, use
`gh api repos/<owner>/<repo>/contents/<path>` or the code-search API, and if
neither is available report the ancient issues as **candidates only** rather
than closing them.
