# Heart — PyAutoHeart

**What it owns:** the health verdict. Heart continuously watches every repo
— branch state, CI conclusions, open PRs, version skew, script timing,
workspace-validation results — and rolls them into one authoritative
answer: `pyauto-heart readiness` → **GREEN / YELLOW / RED**, a score, and
the reasons. GREEN means it is safe to release.

**Repo:** [PyAutoLabs/PyAutoHeart](https://github.com/PyAutoLabs/PyAutoHeart)
· live board: <https://pyautolabs.github.io/PyAutoHeart/>

## The boundary that matters

Heart is an **observer**. It never writes into other repos and never
triggers a build; the Brain reads the verdict (through its vitals faculty —
the only component allowed to talk to Heart) and decides what to do. RED is
a hard stop at every autonomy level. YELLOW requires an explicit human
acknowledgement to ship past. This split — the gate cannot execute, the
executor cannot gate — is the organism's central safety property.

## The pieces

- **Continuous checks** run in a <30s tick (daemon or scheduled): repo
  state, CI status, open PRs, worktree drift, script timing, version skew.
- **Deep checks** run on demand or on cloud cron: install verification, the
  URL-hygiene sweep, release validation.
- **One renderer, many surfaces:** the same cached snapshot projects to the
  terminal board, a one-line shell prompt, GitHub Pages, markdown summaries
  and JSON — the surfaces cannot disagree.
- **`config/repos.yaml`** — the polling/gating policy: which repos, which
  required workflows, what thresholds, which dirty-file patterns are noise.

## For an adopter

Fork it. The check framework, tick budget, dashboard and readiness logic
are the framework; **`config/repos.yaml` is yours** — it is the single
biggest config surface in the organism, and it is checked against your
Mind's body map by `repos_sync.py --check`. A handful of remaining
constant tables (the library tuple in `readiness.py`, the
workspace→library map in `version_skew.py`) are declared surfaces listed in
{doc}`../adoption/config_surfaces`.
