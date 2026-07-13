# PyAutoScientist

PyAutoScientist is a working, opinionated reference implementation of an
**AI-agent development organism** for human-led, natural-language software
development: a set of six git repositories — Mind, Brain, Heart, Hands,
Memory, Gut — through which you lead a multi-repo project in plain English. You
describe what you want; AI agents plan, implement, test, gate and release
it; you make every judgment call.

It is not a framework you install. It is the live system that develops the
[PyAuto astronomy stack](https://pyautolabs.github.io) every day — tens of
repositories, nightly releases, hundreds of tasks — documented so that you
can **fork it and lead your own**, driving projects that have nothing to do
with astronomy.

## The idea in five lines

- Every piece of work starts as a plain-English markdown file you write in
  the **Mind**.
- The **Brain** classifies it, plans it, and routes it through specialist agents.
- Work happens on task worktrees and ships as pull requests, gated by the
  **Heart**'s health verdict.
- The **Hands** package and release what merges.
- The **Memory** holds the long-term domain knowledge the agents consult.

## What adopting it means

You fork the three framework organs (Brain, Heart, Hands), replace a small
set of declared config surfaces with your own repositories, write your own
Mind and Memory from the documented shapes, and `git pull` upstream
improvements cleanly from then on. One upstream, N private organisms — never
a shared deployment. The {doc}`adoption guide <adoption/guide>` is the
walkthrough; {doc}`adoption/config_surfaces` is the exact contract.

Be aware of what this *is* before investing: PyAutoScientist assumes
**Claude Code** (skills and commands installed under `~/.claude`), the
**GitHub CLI**, a trunk-based single-maintainer flow with task worktrees,
and GitHub Actions + PyPI for releases. Those assumptions are the product,
not incidental debt — they are stated plainly in the adoption guide.

## Reading order

```{toctree}
:maxdepth: 2

concepts/organism
concepts/agents
concepts/workflow
```

```{toctree}
:caption: The organs
:maxdepth: 1

organs/mind
organs/brain
organs/heart
organs/build
organs/memory
organs/gut
```

```{toctree}
:caption: Adopting it
:maxdepth: 1

satellites
adoption/guide
adoption/config_surfaces
example
```
