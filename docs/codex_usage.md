# Measuring Codex workflow usage

`bin/codex_usage.py` is a read-only, standard-library report over rollout JSONL
files the user names explicitly. It parses each selected line but extracts and
outputs metadata only; prompts, responses, tool arguments, and secrets are never
reported.

```bash
python bin/codex_usage.py parent.jsonl --child child-a.jsonl --child child-b.jsonl
python bin/codex_usage.py --json parent.jsonl
```

The report uses the last cumulative usage snapshot per session, never sums
snapshots, and de-duplicates repeated files and session IDs. Cached input is
included in input; reasoning is included in output, so those subset counters
are reported separately rather than added again. All observed model and effort
values are listed. Missing counters make the total `unknown/incomplete`, not
zero. Coordination-call counts describe tool calls, not their cause or value.

Explicit children are summed only when every selected session has counters.
Full-history forks may repeat inherited parent events; the current schema does
not always expose a reliable baseline, so child aggregation carries an
over-count warning rather than claiming an exact task total. The report never
converts tokens to billing or subscription cost.

## Activate the workspace policy

After this Brain change merges, update the workspace-root `AGENTS.md` through
the tracked installer:

```bash
bash PyAutoBrain/bin/install.sh --write-workspace-policy
bash PyAutoBrain/bin/install.sh --check-workspace-policy
```

The writer migrates the known legacy delegation text, preserves the root file
and any symlink to it, and fails closed on malformed markers. Do not run it
before `MODEL_DELEGATION.md` exists on the installed branch because the
generated root policy links to that reference.

## Comparison protocol

After 3–5 comparable completed tasks, record for each task:

- selected parent and child rollout paths and whether aggregation is reliable;
- observed models and reasoning-effort values;
- input, cached-input, output, and reasoning-output counters;
- duration and coordination-call count;
- outcome quality and independent-review verdict;
- number of correction loops or user interventions.

Compare medians only across similar task types and report unknown sessions.
Treat the current Astra Medium configuration as the baseline; do not change
local model configuration merely to manufacture a comparison. Do not claim
savings until both usage and outcome/correction evidence support it.

## Static context budgets

Use [context_efficiency.md](context_efficiency.md) for the September follow-up,
Mind’s token-load checker and post-merge root activation. Static byte/line
reductions are not measured task-token savings.
