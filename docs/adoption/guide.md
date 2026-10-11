# Adopting PyAutoScientist

The adoption model is a **config-diff fork**: one upstream (the live
organs), N private organisms downstream. You fork the framework organs,
confine your diff to the declared config surfaces, and `git pull` upstream
improvements cleanly forever after. There is deliberately no shared
deployment, no "generic edition", and no stability promise on `main` — see
{ref}`the disclaimer <stability>` below.

## Independent starter preview

The Scientist adoption pilot now offers an opt-in, independently named empty
[local dashboard preview](https://github.com/PyAutoLabs/PyAutoScientist/blob/main/STARTER.md).
It separates instance identity and selected organ connections from the renderer,
and does not require the full organ family. It does not yet bootstrap a working
Mind or harness, activate organs or deploy an independent site. The existing
full-stack walkthrough below remains separate from this smaller pilot path.

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

## Minimal local pilot: Claude skill discovery

This opt-in path connects the starter pieces without running the user-wide
installer. It prepares local skill discovery; it does not install or authenticate
Claude Code, publish anything, or certify the full development/release workflow.
Use an already installed Claude Code and Python with PyYAML. Heart remains
required before shipping; discovering a skill never bypasses its own gates.

Use one workspace directory with flat `PyAutoBrain`, `PyAutoScientist` and
`PyAutoMind` directories. Keep compatible framework checkouts pinned to revisions
you have validated. The local directory names are framework lookup slots; the
Scientist display name and GitHub repository names remain your choices.

1. From the workspace root, generate a new empty Mind using a trusted existing
   Mind source checkout (the destination must not already exist):

   ```sh
   python3 /path/to/Mind-source/scripts/spawn.py --minimal-mind --write PyAutoMind
   ```

2. Populate **your** `PyAutoMind/repos.yaml`. Replace these fictitious GitHub
   identities with your own or the explicit framework sources you use. Registration
   does not create repositories, verify access or activate an organ:

   ```yaml
   categories:
     organ: {}
   repos:
     PyAutoBrain:
       github: ExampleResearch/PyAutoBrain
       category: organ
     PyAutoMind:
       github: ExampleResearch/ResearchPlans
       category: organ
     PyAutoScientist:
       github: ExampleResearch/MiraScientist
       category: organ
   ```

3. Create user-owned Scientist configuration in a new directory:

   ```sh
   python3 PyAutoScientist/scripts/starter.py instance --repos PyAutoMind/repos.yaml \
     --name "Mira Scientist" --repo PyAutoScientist \
     --pages-url https://example.invalid/mira/ --apply
   ```

4. Preview missing workspace-local links, write them, then check them:

   ```sh
   python3 PyAutoBrain/bin/project_discovery.py starter-check --root .
   python3 PyAutoBrain/bin/project_discovery.py starter-write --root .
   python3 PyAutoBrain/bin/project_discovery.py starter-check --root .
   ```

   The first check exits 1 while links are missing. Write creates relative links
   in **this workspace's** `.claude/skills` to the registered Brain and Mind
   skills. It never writes user-wide settings, either source repository, or a
   Codex discovery directory. Existing unrelated skills are preserved. Any
   conflicting destination or symlinked discovery parent rejects the whole plan
   before writing. Repeating write is a no-op when links match. Stale or custom
   links are not deleted; inspect conflicts yourself after moving checkouts.

5. Start a fresh Claude session **at the workspace root**, scoped to this Mind:

   ```sh
   PYAUTO_ROOT="$PWD" claude
   ```

   Give it this first request:

   > Read instance/SETUP.md, PyAutoMind/AGENTS.md, PyAutoMind/repos.yaml and
   > PyAutoBrain/AGENTS.md. Inspect existing task state before changing anything.
   > Help me connect one existing project using PyAutoScientist/PROJECTS.md.
   > Ask for missing identity, purpose and visibility; don't assume an assistant.
   > Keep source material in its owning project. Validate and show a local preview.
   > Don't publish, install optional organs, run science or change access.

6. Validate the profile and render locally, using the same explicit Brain source:

   ```sh
   PYAUTO_BRAIN="$PWD/PyAutoBrain" python3 PyAutoScientist/scripts/organism_board.py \
     --instance instance/instance.json --repos PyAutoMind/repos.yaml --check-instance
   PYAUTO_BRAIN="$PWD/PyAutoBrain" python3 PyAutoScientist/scripts/organism_board.py \
     --instance instance/instance.json --repos PyAutoMind/repos.yaml --html
   ```

   Save the HTML output to a scratch file. Project entries are private by default;
   only explicitly public projects/resources appear in the dashboard projection.
   Memory, assistants and other organs remain optional. Keep canonical identities
   in Mind, project relationships in the instance, and project content at source.

The acceptance checkpoint is a real fresh session discovering the local skills,
reading the correct Mind and preserving records while connecting a project. CLI
and filesystem tests alone do not prove that conversational behavior; record it
before calling an adopter's harness validated. If Claude does not discover the
local skills, stop and diagnose its configuration rather than running the global
installer or silently falling back to another Scientist's state.
