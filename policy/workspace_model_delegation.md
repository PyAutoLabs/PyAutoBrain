<!-- pyauto:model-delegation:begin -->
- **Choose delegation by provider — every task, not only start_dev.** State
  the session model in the opening line. Anthropic sessions keep judgment
  in-session and delegate execution: Fable is the architect and sends all
  edits, tests, prose and ship phases to Opus; Opus → Opus; Sonnet only for
  the fixed ship_* step 4 / pre_build step 2 recipes (unsure → Opus).
  Delegate beyond a few lines of edits or a couple of file reads; stay
  in-session for loaded-context answers, few-line edits in files already read
  and user conversations. Long delegations write a progress file the main
  session monitors. OpenAI executes routine sequential work directly; Sol
  workers only for independent parallel work, substantial noisy work or
  independent review. Duration alone is not a reason to spawn; Brain roles
  are not automatic LLM spawns. Workflow steps are installed skills
  (`/start_dev`, `/ship_library`…, via `bin/install.sh`). Full policy and
  heartbeat: "Bounded worker contract" in `skills/MODEL_DELEGATION.md` of the
  resolved Brain checkout.
<!-- pyauto:model-delegation:end -->
