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

1. **Fork Brain, Heart, Hands** (keep the repo names — they are framework
   identity).
2. **Create your Mind** with the documented shape
   ([PyAutoMind/REFERENCE.md](https://github.com/PyAutoLabs/PyAutoMind/blob/main/REFERENCE.md)):
   the registry files, the work-type prompt folders, a copy of `scripts/`,
   and — the load-bearing part — **your own `repos.yaml` body map** listing
   your libraries, workspaces and their categories per the
   {doc}`category contract <../satellites>`.
3. **Replace the config surfaces** in your forks with rows for your repos —
   the complete inventory with file paths is {doc}`config_surfaces`. The
   big three: Heart's `config/repos.yaml` (what to poll and gate), the
   Hands' `run_workspace` table in `pre_build.sh` (what the pipeline runs),
   and the Brain's constant tables (sizing sets, routing keywords, the
   release library tuple).
4. **Regenerate and check.** `python3 <YourMind>/scripts/repos_sync.py
   --write` stamps the generated doc blocks from your body map; `--check`
   verifies every mirror agrees — including the tenant firewall, which
   fails if an upstream instance fact survives anywhere outside the
   declared surfaces you just replaced.
5. **Install the command surface**: `bash <YourBrain>/bin/install.sh`
   symlinks every organ's skills into `~/.claude`.
6. **Create your Memory when you need it** — the shape is documented in
   {doc}`the Memory page <../organs/memory>`; the organism runs fine
   without one until your domain knowledge accumulates.
7. **Go.** Write your first prompt in your Mind and run `/start_dev` on it.

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
