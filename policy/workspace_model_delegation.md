<!-- pyauto:model-delegation:begin -->
- **Choose delegation by provider.** Anthropic preserves its execution-tier
  policy: Fable → Opus, Opus → Opus, with Sonnet only for the documented
  mechanical floor. OpenAI executes routine sequential work directly and uses
  Sol workers selectively for independent parallel work, substantial noisy work
  needing separate context, or independent review. Duration alone is not a
  reason to spawn. Brain roles are not automatic LLM spawns. State the
  session model before the first delegation decision. Full policy:
  `skills/MODEL_DELEGATION.md` in the resolved Brain checkout.
<!-- pyauto:model-delegation:end -->
