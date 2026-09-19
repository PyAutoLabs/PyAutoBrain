# Library merge freeze gate

Read before merging any library PR; organs/workspaces skip this page.
All other [merge gates](prm.md) still apply.

1. **The Heart freeze window — library PRs only.** A release validation is a
   window in which the library `main`s must not move: a merge landing inside it
   invalidates the evidence and restales the rehearsal (~75 minutes, measured
   2026-08-29). Heart's flag says whether one is open:

   ```bash
   pyauto-heart freeze --show      # exit 3 = frozen; 0 = clear or expired
   ```

   Active **and** a target PR is in a **library** repo (the `category: library`
   entries of `PyAutoMind/repos.yaml`) → stop, report the `FROZEN: …` line
   verbatim, and say when it expires. Organ and workspace repos are not gated;
   a workspace PR whose library half is held waits on the library-first gate
   below anyway. Where Heart is not installed (mobile, web, CI) there is
   nothing to read — say so in one line; an absent flag is not a freeze.

   **`--thaw "<why>"` is the only way past**, and it is loggable by
   construction: merge, then append one row to `PyAutoMind/autonomy_log.md`
   under a `## Freeze overrides` heading (create the section, with this header,
   on first use) —

   ```
   | date | task / PR | freeze reason | until | thawed by | why |
   ```

   — in the same Mind push the close-out already makes (step 5.4). The override
   exists because a freeze is advice about evidence, not a protected branch,
   and an unloggable override is one people route around instead of recording.
   Never thaw silently, and never thaw to get past a red check: this gate is
   about *when*, and step 2 is about *whether*.
