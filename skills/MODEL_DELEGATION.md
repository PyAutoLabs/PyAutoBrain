# Model delegation policy

Brain roles and faculties are architectural roles; invoking one does not itself
require an LLM subagent.

## Anthropic: preserve the execution-tier split

| Session model | Judgment tier | Execution tier |
|---|---|---|
| Fable | Fable plans, decomposes, judges, and talks to the user | Opus performs all remaining implementation, edits, tests, diagnostics, and prose |
| Opus | Opus | Opus, except the mechanical floor below may use Sonnet |
| Sonnet | Sonnet | Run inline; there is no lower tier |

Fable and Opus delegate execution even when the target worker is also Opus.
Answering from already-loaded context, reading a handful of files, editing a
few lines in files already read, and conversations with the user (plans,
decisions, reviews, and judgment calls) remain in-session.
Sonnet is used from Opus only for fixed shell/git recipes whose errors surface
immediately: test/commit/push/open-PR in `ship_library`; commit/push/smoke/
open-PR/cross-reference in `ship_workspace`; and format/generate/version-bump/
commit/push/dispatch in `pre_build`. If it is unclear whether work is
mechanical enough, it goes to Opus.
Narrative science tutorials always go to Opus; code-heavy notes may use Sonnet
only for a mechanical adaptation of an existing sibling.

For Anthropic, planning, worktree/environment setup, release triage, commit and
PR wording, downstream-impact and merge decisions, registry/completion updates,
final issue comments, and all user-facing judgment remain in the main session.

## OpenAI: direct by default

Astra and Sol normally execute routine sequential work in the current session,
including edits, targeted tests, and git steps. Use a Sol worker selectively
when independent work can run usefully in parallel, a separate context is
justified by substantial noisy execution or independent progress, or a
genuinely independent review is required. Wall-clock duration alone is not a
reason to spawn, and delegation is not presumed to save tokens.

Keep planning, user decisions, approval gates, registry updates, and final
judgment in the main session. Do not spawn a worker merely because a Brain
conductor consults a faculty or a workflow reaches a shell/git phase. The
review faculty remains independent for both provider families.

No default is defined for other model families. If a requested worker is not
available, execute in-session without changing safety or approval gates.

## Cross-environment capability handoff

A missing execution capability does not make the execution environment the new
orchestrator. The current scientist-facing session keeps planning, Mind state,
approval gates and final judgment; hand off only the smallest coherent phase
whose required evidence cannot be produced here.

A cross-environment packet carries:

- the existing Mind task / issue;
- repository, branch and exact starting commit;
- one coherent objective and permitted files/scope;
- required commands, runtime/scientific checks or review question;
- explicit "do not broaden/redesign unrelated work";
- requested return: resulting commit/diff (if any), pass/fail counts and only
  decision-relevant failure/environment evidence.

The receiving environment resumes the existing branch; it does not create a
second task or lifecycle. The orchestrator consumes the returned evidence and
continues the same Brain → review/vitals → Heart → PR flow.

**Independent review is a separate capability.** A conversation that authored
the branch cannot satisfy the independent-review leg by rereading its own diff.
If no independent worker/reviewer is available in the current surface, hand off
only the review phase or require human review.

**No OpenAI API fallback.** An ordinary ChatGPT orchestration route must never
turn a missing worker/runtime into an OpenAI SDK, Responses API,
`OPENAI_API_KEY`, browser/session automation or other separately billed API
call. Use an explicitly chosen supported execution surface or stop at the
missing phase.

## Bounded worker contract

- Pass only the worktree, affected files, accepted plan, required commands,
  and the smallest relevant evidence.
- Give one coherent phase to a worker and reuse it for related fixes.
- Request concise results: changed files, pass/fail counts, and only the
  decision-relevant tail of a failure.
- Keep full logs in a file or harness transcript, not chat.
- Do not rerun an unchanged successful check unless inputs or its gate changed.
- Prefer native completion events. Do not repeatedly poll unchanged pending
  state or agent lists; use bounded waits only when needed, and never arm a
  timer or monitor that outlives the turn.

Long Anthropic delegations retain the existing milestone heartbeat: one short
line per phase/test/commit milestone in a progress file, roughly every 10–20
minutes of healthy work, monitored by the main session and stopped on return.
Long OpenAI delegations may use the same bounded heartbeat; inline work does not.

## Bundles, Cortex, and teaching prose

Bundles parallelize only independent members. Anthropic members use their
execution tier; OpenAI members use workers only for the selective reasons above.
Within one repo, members remain sequential.

Cortex work still enters through the declared assistant and returns scientific
results plus assistant drift. The provider policy decides whether that work
uses a subagent; the assistant boundary does not force a spawn.

Narrative science scripts use Opus in the Anthropic family. OpenAI authors them
inline by default, or with Sol when a selective delegation reason applies. The
content heuristic is unchanged: science instruction gets teaching prose; code
exercise scripts get concise usage notes.
