# Contributing

The PyAutoScientist organs (PyAutoBrain, PyAutoMind, PyAutoHeart,
PyAutoHands, PyAutoMemory) are a **living reference implementation** — the
maintainer's daily working system, not a stable library.

What that means in practice:

- **`main` moves fast** — hundreds of commits a quarter — and there are
  **no compatibility promises**. Anything may be renamed, rewired or
  removed when the live system needs it.
- **Adopt by fork-and-pull, never by tracking.** Fork the organs, confine
  your changes to the declared config surfaces, and pull upstream at your
  own pace — the model is documented in the
  [adoption guide](https://pyautoscientist.readthedocs.io/en/latest/adoption/guide.html).
  Pin what you depend on.
- **Issues and PRs are welcome**, and read with interest — but triage pace
  is set by the live instance's needs, and PRs that genericise working
  production prompts (`skills/*.md`) or add abstraction for hypothetical
  users will be declined.
- The best contribution while the project is young: **adopt it, and report
  the friction** you hit following the adoption guide.

Docs: <https://pyautoscientist.readthedocs.io> · the organism:
[ORGANISM.md](https://github.com/PyAutoLabs/PyAutoBrain/blob/main/ORGANISM.md)
