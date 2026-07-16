# Adopting PyAutoScientist

The adoption model is a **config-diff fork**: one upstream (the live
organs), N private organisms downstream. You fork the framework organs,
confine your diff to the declared config surfaces, and `git pull` upstream
improvements cleanly forever after. There is deliberately no shared
deployment, no "generic edition", and no stability promise on `main` — see
{ref}`the disclaimer <stability>` below.

## Prerequisites — what PyAutoScientist *is*

These are the product, not incidental choices. If they don't fit how you
work, this system is not for you (and that's fine):

- **Claude Code** as the agent harness — the Brain's skills and verb
  commands install into `~/.claude` and are written for it.
- **The GitHub CLI (`gh`)** and GitHub-hosted repos — issues, PRs and CI
  state are read and written through it.
- **A trunk-based, single-maintainer flow** with task worktrees under a
  common workspace root (`~/Code/<YourLabs>/` + `<YourLabs>-wt/`).
- **GitHub Actions + PyPI** for the release pipeline, if you release
  packages.

## The walkthrough

Every "create" step below is a GitHub **Use this template** click — the
template repos are generated from the live organism and satisfy every
contract on day one.

1. **Fork Brain, Heart, Hands** (keep the repo names — they are framework
   identity).
2. **Create your Mind from
   [PyAutoMind-template](https://github.com/PyAutoLabs/PyAutoMind-template)**:
   the registry files, work-type prompt folders and generic `scripts/` come
   ready, and its `repos.yaml` body map is pre-filled with the template
   satellite family below. The schemas it follows are documented in
   [REFERENCE.md](https://github.com/PyAutoLabs/PyAutoMind/blob/main/REFERENCE.md).
3. **Create your science repos from the PyAutoProject family** —
   [PyAutoProject](https://github.com/PyAutoLabs/PyAutoProject) (the
   library: a working 1D-Gaussian model + `Analysis` + packaged prior
   config on the PyAutoFit engine),
   [autoproject_workspace](https://github.com/PyAutoLabs/autoproject_workspace)
   (end-to-end scripts that build to notebooks; `start_here.py` teaches the
   convention), and
   [autoproject_workspace_test](https://github.com/PyAutoLabs/autoproject_workspace_test)
   (smoke/regression scripts). Rename `autoproject` to your science and
   replace the Gaussian with your model — the {doc}`category contract
   <../satellites>` is what each repo must keep honouring.
4. **Replace the config surfaces** in your forks with rows for your repos —
   the complete inventory with file paths is {doc}`config_surfaces`. The
   big three: Heart's `config/repos.yaml` (what to poll and gate), the
   Hands' `run_workspace` table in `pre_build.sh` (what the pipeline runs),
   and the Brain's constant tables (sizing sets, routing keywords, the
   release library tuple).
5. **Regenerate and check.** `python3 <YourMind>/scripts/repos_sync.py
   --write` stamps the generated doc blocks from your body map; `--check`
   verifies every mirror agrees — including the tenant firewall, which
   fails if an upstream instance fact survives anywhere outside the
   declared surfaces you just replaced.
6. **Install the command surface**: `bash <YourBrain>/bin/install.sh`
   symlinks every organ's skills into `~/.claude`.
7. **Create your Memory from
   [PyAutoMemory-template](https://github.com/PyAutoLabs/PyAutoMemory-template)
   when you need it** — the wiki schema, bibliography tooling and citation
   validation come wired, plus a structure lint in CI, with one empty `wiki/example/` to copy per
   domain; the organism runs fine without it until your knowledge
   accumulates. Your assistant repo comes later still — grown by the clone
   agent once your project matures, never hand-built.
8. **Go.** Write your first prompt in your Mind and run `/start_dev` on it.

The Mind and Memory templates are **generated views** of the live organism
(stamped by `spawn`, drift-checked in CI) — they track the live structure
without ever containing its content.

## Staying current

Because your diff is confined to config surfaces, `git pull upstream main`
in each framework organ stays clean: you take every improvement the
upstream ships, and your instance facts never collide with it. The tenant
firewall is what keeps this true over time — upstream runs it in `--check`,
so new upstream code cannot silently hardcode an instance fact that would
land in your fork.

(stability)=
## The stability disclaimer

The upstream organs are a **living reference implementation** — the
maintainer's daily working system, moving fast (hundreds of commits a
quarter), with no compatibility promises on `main`. Fork-and-pull at your
own pace; pin what you depend on; expect churn. Issues and PRs are welcome,
but the pace is set by the live instance's needs. Each organ carries this
disclaimer in its `CONTRIBUTING.md`.
