# Writing style for user-facing pages

How to write the pages a person reads before they use PyAutoLabs software: GitHub `README.md` files, setup and
how-to pages under `docs/`, and Read the Docs pages. The reference example is the `autolens_assistant` README and its
`docs/setup/` pages after the October 2026 rewrite.

This guide is for people-facing prose. Agent-facing files (`AGENTS.md`, `skills/`, `wiki/core/`), maintainer notes and
the science narrative inside workspace tutorials follow their own conventions.

## Who you are writing for

Picture someone who has just landed on the page: a scientist, a PhD student or a curious member of the public. They
want to know what this is, whether it is for them, and what to do first. They have not read anything else in the
organisation, and they do not care how it is built.

Write for that person first. Detail for experts and maintainers belongs further down the page, or on a page of its own.

## The rules

1. **Say what the reader does, not how it works.** "Open your agent and paste in the starting prompt" beats a
   description of hooks, adapters and sandboxes. Mechanics go on a setup page, or nowhere.
2. **Keep the start short.** "Getting started" is a paragraph or two, not numbered steps wrapped in caveats. If the
   first thing a reader does is copy a prompt or a command, get them to it fast.
3. **Use plain words.** Say "safety checks" rather than "the code-gate hook", and "download this repository" alongside
   `git clone`. Never use internal jargon such as harness, adapter, leg, gate, card, organ or conductor in
   people-facing text.
4. **State a fact once, without hedging.** Do not stack defensive caveats ("check the provider's current plans rather
   than assuming…", "treat it as compatible rather than tested"). Say the useful thing plainly and link to the page
   with the details.
5. **Link to one source for anything that changes.** Prices, free tiers and supported agents live on one shared page
   (for the assistants, `PyAutoScientist/AI_OPTIONS.md`). Other pages link to it rather than repeat it.
6. **Let examples speak for themselves.** A prompt or code block is the content. Introduce it in a sentence; do not
   re-explain what it already says.
7. **Move long material off the front page.** Advanced examples, benchmarks and history go on their own pages, linked
   by short bullets that say what each one shows.
8. **Break dense paragraphs up.** A paragraph listing five benefits reads better as a one-line introduction and a
   bulleted list, each bullet starting with a **bold** word.
9. **Order sections by the reader's journey.** What it is, getting started, first use, ways to customise it, the
   context the reader should add before serious work, projects, how it works, benchmarks, license.
10. **Keep agent-only text out of the reader's way.** Instructions aimed at AI agents go at the bottom of the page,
    short, inside a collapsed `<details>` block. Agents still read them; people only see one small line.
11. **Be warm and direct.** Address the reader as "you", use contractions, keep sentences short, and allow a little
    enthusiasm (one exclamation mark on a page is plenty). Avoid long chains of dashes and brackets.
12. **Use plain headings.** "Teacher Mode", "What it costs", "Install and start", "Next steps". Not "Example Prompt 1
    (Teacher Mode): Simulate, inspect and model a strong lens".

## Page templates

**A README** should have: a title, an image, two or three sentences on what the project is, then Getting Started,
first use, deeper sections in journey order, and License. Any agent note goes last.

**A setup page** for a tool should have these sections:

- a short introduction (two or three sentences on what the tool is and what it lets you do);
- **What it costs**;
- **Install and start** (numbered steps);
- anything needed for the full setup;
- **How well it is tested** (when that differs between tools);
- **Next steps**, linking onward.

## Before and after

> **Before.** The assistant runs inside an **AI coding agent** — a tool that reads this repository, executes Python
> on your computer and inspects the results. That is what lets it install PyAutoLens, plot your `.fits` data, run
> lens models and look at the figures they produce. You do not have to run anything to use it: …
> Three steps: 1. **Choose Claude Code or Codex.** These are the two recommended agents. Codex discovery and safety
> adapters have focused validation; …

> **After.** The assistant runs inside an **AI coding agent**, a tool that can read this repository, run Python on
> your computer and look at the results. Pick your agent: Claude Code or Codex are recommended, and GitHub Copilot
> CLI or OpenCode are free AI options if you want to try it without paying.
>
> Once it is installed, open your AI coding agent and paste in the starting prompt below.

> **Before.** This prompt works for anyone — journalist, student or lensing researcher. The assistant asks your
> background first and pitches everything that follows accordingly:

> **After.** If you've not used the PyAutoLens AI Assistant before, use the prompt below. It'll ask your background
> (e.g. scientist, PhD student, member of the general public) and explain gravitational lensing to you accordingly.

## Checklist before you finish

- Could a newcomer reach the first prompt or command within a screen of scrolling?
- Is every internal term either removed or explained in plain words?
- Is each changeable fact (price, tier, support status) stated once and linked elsewhere?
- Does any example get re-explained in the prose around it?
- Is agent-only text at the bottom and collapsed?
- Do all links and anchors still resolve, including links from other pages to sections you renamed or moved?
