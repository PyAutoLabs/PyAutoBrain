"""Contract tests for the Documentation conductor's CLI footing.

Hermetic: PYAUTO_ROOT points at a temp root holding only a fixture body map
(invented repo names — the tenant firewall keeps instance facts out of organ
code, tests included), so no real checkout is read, and audits run on fabricated pages. The
conductor is read-only — test_never_writes asserts it explicitly.
"""

import json
import os
import subprocess
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
BRAIN = BRAIN_HOME / "bin" / "pyauto-brain"

DECISION_KEYS = {
    "title", "prompt_path", "surface", "surface_label", "target_repo",
    "repo_category", "page", "writing_style_applies", "style_guide",
    "page_template", "move_long_material_to", "siblings_in_step",
    "deferred_to", "checklist", "audit_command", "notes", "next_action",
}

GOOD_README = """\
<p align="center"><img src="logo.png" alt="Logo"></p>

# PyAutoThing

PyAutoThing fits models to your data. You can use it from a notebook or a script.

## Getting Started

Install it and run your first fit:

```bash
pip install autothing
```

## Your first fit

See [Getting Started](#getting-started) and [the guide](docs/guide.md).

## License

MIT.
"""

BAD_README = """\
# Example Prompt 1 (Teacher Mode): Simulate, inspect and model a strong lens

The conductor routes each request through the harness — then the gate checks
it — and finally the organ (the Heart) (or the Hands) acts. Check the provider's
current plans rather than assuming anything. It costs $20 per month. Wow! Great!
Also more text here. And more. And even more sentences in the intro.

## Agents

If you are an AI agent, read AGENTS.md first.

[broken](missing.md) and [bad anchor](#nowhere)
"""


FIXTURE_REPOS = {
    "PyAutoHeart": "organ",
    "PyAutoAlpha": "library", "PyAutoBeta": "library",
    "autoalpha_workspace": "workspace", "autobeta_workspace": "workspace",
    "HowToAlpha": "howto", "HowToBeta": "howto", "HowToGamma": "howto",
    "autoalpha_assistant": "assistant", "autobeta_assistant": "assistant",
    "autogamma_assistant": "assistant", "autodelta_assistant": "assistant",
}


def _body_map(root):
    manifest = root / "PyAutoMind" / "repos.yaml"
    if not manifest.exists():
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("repos:\n" + "".join(
            f"  {name}:\n    github: Org/{name}\n    category: {cat}\n"
            for name, cat in FIXTURE_REPOS.items()))


def _run(args, root):
    _body_map(root)
    env = {**os.environ, "PYAUTO_ROOT": str(root)}
    return subprocess.run(
        [str(BRAIN), "docs", *args], capture_output=True, text=True, env=env,
    )


def _decide(text, root):
    r = _run(["--json", text], root)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_assistant_readme_decision_is_complete(tmp_path):
    d = _decide("rewrite the autoalpha assistant README in the new style", tmp_path)
    assert set(d) == DECISION_KEYS
    assert d["surface"] == "readme"
    assert d["target_repo"] == "autoalpha_assistant"
    assert d["writing_style_applies"] is True
    assert d["style_guide"].endswith("skills/WRITING_STYLE.md")
    # The template is parsed from the guide, not restated.
    assert d["page_template"][:2] == ["a title", "an image"]
    assert "License" in d["page_template"]
    assert set(d["siblings_in_step"]) == {
        "autobeta_assistant", "autogamma_assistant", "autodelta_assistant"}
    assert any("rule 5" in m for m in d["move_long_material_to"])
    assert d["checklist"]
    assert d["deferred_to"] is None


def test_setup_page_uses_setup_template(tmp_path):
    d = _decide("new setup page for Codex in autobeta_assistant", tmp_path)
    assert d["surface"] == "setup"
    assert "What it costs" in d["page_template"]
    assert any(s.startswith("Next steps") for s in d["page_template"])


def test_rtd_page_uses_journey_order(tmp_path):
    d = _decide("Read the Docs page on PyAutoBeta samplers", tmp_path)
    assert d["surface"] == "rtd"
    assert d["target_repo"] == "PyAutoBeta"
    assert d["page_template"][0] == "What it is"
    assert any("no Read the Docs template" in n for n in d["notes"])


def test_tutorial_is_deferred_to_workspace_conductor(tmp_path):
    d = _decide("a HowToAlpha chapter tutorial on mass profiles", tmp_path)
    assert d["surface"] == "tutorial"
    assert d["writing_style_applies"] is False
    assert d["style_guide"].endswith("TUTORIAL_WRITING_STYLE.md")
    assert d["deferred_to"]["conductor"] == "workspace"
    assert d["deferred_to"]["register_hint"] == "howto"
    assert d["deferred_to"]["command"].startswith("bin/pyauto-brain workspace ")
    assert d["page_template"] == [] and d["siblings_in_step"] == []


def test_workspace_register_hint_for_reference_examples(tmp_path):
    d = _decide("an example script notebook for autoalpha_workspace", tmp_path)
    assert d["deferred_to"]["register_hint"] == "workspace"


def test_readme_beats_tutorial_and_flags_mixed(tmp_path):
    d = _decide("rewrite the HowToAlpha README with a tutorial walkthrough", tmp_path)
    assert d["surface"] == "readme"
    assert d["siblings_in_step"] == ["HowToBeta", "HowToGamma"]
    assert "TUTORIAL_WRITING_STYLE.md" in d["style_guide"]
    assert any("mixed document" in n for n in d["notes"])


def test_agent_facing_file_does_not_apply_style(tmp_path):
    d = _decide("tighten the AGENTS.md of PyAutoHeart", tmp_path)
    assert d["surface"] == "agent"
    assert d["writing_style_applies"] is False
    assert d["style_guide"] is None
    assert d["page"] == "AGENTS.md"
    assert any("does not apply" in c for c in d["checklist"])


def test_plan_reads_a_mind_prompt_path(tmp_path):
    prompt = tmp_path / "PyAutoMind" / "draft" / "docs" / "assistants" / "x.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("# Assistant README\n\nRewrite the autogamma_assistant README.\n")
    d = _decide("draft/docs/assistants/x.md", tmp_path)
    assert d["prompt_path"] == str(prompt)
    assert d["target_repo"] == "autogamma_assistant"


def test_unresolvable_exits_4_and_no_intent_exits_5(tmp_path):
    r = _run(["--json", "write some documentation please"], tmp_path)
    assert r.returncode == 4 and "cannot resolve" in r.stderr
    r = _run(["README for something"], tmp_path)
    assert r.returncode == 4 and "no target repo" in r.stderr
    assert _run([], tmp_path).returncode == 5


def test_text_output_names_the_decision(tmp_path):
    r = _run(["rewrite the autoalpha assistant README"], tmp_path)
    assert r.returncode == 0
    assert "DocsDecision" in r.stdout
    assert "Siblings in step:" in r.stdout


def _audit(page, root, *extra):
    r = _run(["audit", str(page), "--json", *extra], root)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_audit_good_readme_passes(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n")
    (tmp_path / "logo.png").write_bytes(b"")
    page = tmp_path / "README.md"
    page.write_text(GOOD_README)
    a = _audit(page, tmp_path)
    failing = {c["id"]: c["finding"] for c in a["checks"] if c["status"] != "pass"}
    assert failing == {}
    assert a["score"] == 100
    assert all(c["kind"] in ("mechanical", "heuristic") for c in a["checks"])
    assert a["not_checked"]


def test_audit_bad_readme_lists_concrete_fixes(tmp_path):
    page = tmp_path / "README.md"
    page.write_text(BAD_README)
    a = _audit(page, tmp_path)
    status = {c["id"]: c for c in a["checks"]}
    for cid in ("image", "getting_started", "license_last", "jargon", "hedging",
                "changeable_facts", "exclamations", "plain_headings",
                "agent_text", "links", "dash_chains", "intro_length"):
        assert status[cid]["status"] == "fix", cid
        assert status[cid]["fixes"], cid
    assert any("'conductor'" in f for f in status["jargon"]["fixes"])
    assert any("missing.md" in f for f in status["links"]["fixes"])
    assert any("#nowhere" in f for f in status["links"]["fixes"])
    assert a["score"] < 50


def test_audit_ignores_jargon_in_code_and_details(tmp_path):
    page = tmp_path / "README.md"
    page.write_text(GOOD_README + "\n```\nconductor gate organ\n```\n"
                    "<details><summary>For agents</summary>\n\nthe conductor\n\n</details>\n"
                    "Use `the_gate` here.\n")
    a = _audit(page, tmp_path)
    jargon = next(c for c in a["checks"] if c["id"] == "jargon")
    assert jargon["status"] == "pass", jargon


def test_audit_setup_page_template(tmp_path):
    page = tmp_path / "docs" / "setup" / "codex.md"
    page.parent.mkdir(parents=True)
    page.write_text("# Codex\n\nCodex is an agent you run.\n\n## What it costs\n\nSee the page.\n")
    a = _audit(page, tmp_path)
    assert a["page_kind"] == "setup"
    setup = next(c for c in a["checks"] if c["id"] == "setup_sections")
    assert setup["status"] == "fix"
    assert "Install and start" in setup["finding"]


def test_audit_agent_file_is_not_scored(tmp_path):
    page = tmp_path / "AGENTS.md"
    page.write_text("# Agents\n\nThe conductor gate.\n")
    a = _audit(page, tmp_path)
    assert a["score"] is None and "does not apply" in a["note"]


def test_audit_missing_page_exits_4(tmp_path):
    assert _run(["audit", str(tmp_path / "nope.md")], tmp_path).returncode == 4


def test_never_writes(tmp_path):
    page = tmp_path / "README.md"
    page.write_text(BAD_README)
    _body_map(tmp_path)
    before = sorted((str(p), p.stat().st_mtime_ns) for p in tmp_path.rglob("*"))
    _run(["rewrite the autoalpha assistant README"], tmp_path)
    _run(["audit", str(page)], tmp_path)
    after = sorted((str(p), p.stat().st_mtime_ns) for p in tmp_path.rglob("*"))
    assert before == after


def test_docs_entry_routes_through_the_conductor():
    entry = (BRAIN_HOME / "skills" / "docs" / "docs.md").read_text()
    assert "bin/pyauto-brain docs" in entry
    assert "docs audit" in entry
    assert "No dedicated Documentation" not in entry
