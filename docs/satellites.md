# The category contract

The organism works *on* satellites — the repositories being developed. The
body map (`PyAutoMind/repos.yaml`) assigns every repo a **category**, and
the category is a contract: it says what the repo is for and what the
organism expects of it. You don't need the live instance's repos; you need
repos that honour the contracts your body map declares.

| Category | What it is for | What the organism expects of it |
|----------|----------------|--------------------------------|
| `organ` | The five organism repos themselves. | Framework identity — names survive a fork; excluded from the tenant firewall's instance-fact tokens. |
| `library` | A source package you release. | A test suite and CI workflow Heart gates on; a row in the Brain release conductor's library set; a PyPI package the Hands release; a version floor workspaces pin against. |
| `workspace` | Runnable, user-facing examples for one library. | A `run_workspace` row in `pre_build.sh` (repo, package, flags, parent library); a version pin Heart's `version_skew` compares to the installed library; required CI (smoke tests) on `main`; notebook generation from its scripts. |
| `workspace_test` | Regression / smoke / parity scripts — code-heavy, doc-light. | Same `run_workspace` mechanics; scripts runnable headless in the validation pipeline; the home for cross-package and integration checks that don't belong in a library's unit tests. |
| `workspace_developer` | Profiling and experiment scripts. | Not release-gated; polled for repo state only. |
| `howto` | Narrative teaching tutorials. | Version-pinned like a workspace; notebook generation; prose held to a higher bar (judgment-tier writing). |
| `assistant` | A curated knowledge pack that makes any AI assistant an expert on one domain/stack. | Self-contained and public; its own currency checks; never a dumping ground for personal material. |
| `pipeline` | Glue for one external project or survey. | Workspace-like validation where runnable; otherwise polled only. |
| `project` | Analysis/results repos (profiling campaigns, the docs hub). | Polled for state; no release mechanics. |
| `admin` | Personal tooling. | Outside the organism proper; hosts helpers the workflow sources (e.g. the worktree script). |

Two properties make the contract workable:

- **Declared, not discovered.** Everything the organism knows about a repo
  is in the body map plus the per-organ config surfaces — never inferred
  from the repo's contents at runtime. Adding a repo is: add the `repos.yaml`
  row, add the config-surface rows its category requires, run
  `repos_sync.py --write`, and the drift checks confirm the mirrors agree.
- **Checked, not trusted.** `repos_sync.py --check` verifies the body map
  against Heart's polling policy, the Hands' `run_workspace` table, the
  label tooling, and every local checkout's actual git remote — so the
  contract can't silently rot.

An adopter's minimal viable body: one `library` + one `workspace`. Every
other category is opt-in as your project grows into it. The contract has a
working embodiment you can copy — the **PyAutoProject template family**
([PyAutoProject](https://github.com/PyAutoLabs/PyAutoProject) +
[autoproject_workspace](https://github.com/PyAutoLabs/autoproject_workspace) +
[autoproject_workspace_test](https://github.com/PyAutoLabs/autoproject_workspace_test)),
a complete 1D-Gaussian project satisfying every expectation in the table;
the {doc}`adoption guide <adoption/guide>` walks through it.
