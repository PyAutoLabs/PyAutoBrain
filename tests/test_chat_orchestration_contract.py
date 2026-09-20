"""Contracts for ordinary-Chat orchestration without a parallel workflow."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"


def _read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_workflow_separates_orchestration_capabilities_from_execution_evidence():
    text = _read("skills/WORKFLOW.md")
    for token in (
        "orchestration environment",
        "execution environment",
        "repository-read",
        "repository-write",
        "github-control",
        "test-execution",
        "independent-review",
        "remote-compute",
        "required evidence",
    ):
        assert token in text
    assert "Lane:" in text
    assert "must not grow a `chatgpt`" in text.lower()


def test_chat_route_has_no_openai_api_fallback():
    texts = "\n".join(
        _read(path)
        for path in (
            "skills/WORKFLOW.md",
            "skills/GITHUB_ACCESS.md",
            "skills/MODEL_DELEGATION.md",
        )
    )
    assert "No OpenAI API fallback" in texts or "no API fallback" in texts
    for executable_pattern in (
        "api.openai.com",
        "from openai import",
        "import openai",
        "client.responses.create",
        "responses.create(",
        "OPENAI_API_KEY=",
    ):
        assert executable_pattern not in texts


def test_github_only_development_records_no_fake_worktree():
    for path in (
        "skills/start_dev/start_dev.md",
        "skills/start_dev/reference.md",
        "skills/start_library/start_library.md",
        "skills/start_workspace/start_workspace.md",
    ):
        text = _read(path)
        assert "GitHub-control-only" in text
        assert "worktree" in text
    assert "no fake `worktree:`" in _read("skills/start_dev/start_dev.md")


def test_remote_conflicts_still_use_mind_repo_claims():
    reference = _read("skills/start_dev/reference.md")
    assert "Do not\n  skip task-claim checks" in reference
    assert "repos:" in reference
    assert "fail closed" in reference


def test_ci_evidence_never_becomes_heart_or_independent_review():
    workflow = _read("skills/WORKFLOW.md")
    library = _read("skills/ship_library/ship_library.md")
    workspace = _read("skills/ship_workspace/ship_workspace.md")
    for text in (workflow, library, workspace):
        assert "Heart" in text
        assert "exact-head" in text.lower() or "exact branch head" in text.lower()
        assert "CI" in text or "Actions" in text
    assert "never substitutes for the authoritative Heart verdict" in workflow
    assert "cannot self-certify" in workflow
    assert "same-conversation reread is not an independent review" in library
    assert "same-conversation reread is not an independent review" in workspace


def test_no_runtime_provider_switch_was_added():
    """Harness names belong in adapters/docs, not execution routing code."""
    offenders = []
    for root in (ROOT / "agents", ROOT / "bin"):
        for path in root.rglob("*"):
            if path.suffix not in {".py", ".sh"} or not path.is_file():
                continue
            if "chatgpt" in path.read_text(encoding="utf-8", errors="replace").lower():
                offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, offenders
