"""Cross-harness discovery and installer coverage."""

import os
import re
import subprocess
from pathlib import Path


BRAIN_HOME = Path(__file__).resolve().parents[1]
DISPATCHER = BRAIN_HOME / "bin" / "pyauto-brain"
INSTALLER = BRAIN_HOME / "bin" / "install.sh"
MARKDOWN_LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")


def public_agents() -> set[str]:
    result = subprocess.run(
        [str(DISPATCHER), "help"],
        check=True,
        capture_output=True,
        text=True,
    )
    return set(re.findall(r"^    ([a-z][a-z0-9_-]+)\s+", result.stdout, re.MULTILINE))


def test_every_public_agent_has_a_skill_wrapper():
    agents = public_agents()
    assert agents
    missing = [
        name
        for name in sorted(agents)
        if not (BRAIN_HOME / "skills" / name / "SKILL.md").is_file()
    ]
    assert missing == []


def test_local_skill_links_resolve():
    broken = []
    for skill in sorted((BRAIN_HOME / "skills").glob("*/SKILL.md")):
        for target in MARKDOWN_LINK.findall(skill.read_text()):
            path = target.split("#", 1)[0]
            if not path or "://" in path:
                continue
            if not (skill.parent / path).resolve().exists():
                broken.append(f"{skill.relative_to(BRAIN_HOME)} -> {target}")
    assert broken == []


def _pyauto_root(tmp_path):
    """A fixture PYAUTO_ROOT whose `PyAutoBrain/` is this checkout.

    Without this the installer falls back to `DEFAULT_PYAUTO_ROOT`
    (`bin/../..`, i.e. this repo's grandparent) and looks for
    `<grandparent>/PyAutoBrain/skills`. That resolves only when the checkout
    happens to be *named* `PyAutoBrain` and sits one level under the root —
    true on a laptop, false for a clone at any other path (a cloud session
    cloning to `pyautobrain` finds nothing, so the Brain skills are never
    scanned and the assertions below have nothing to assert on).

    Pinning the root makes these tests depend on the installer's behaviour
    rather than on where the repo happens to be checked out. Same pattern as
    `test_invalid_codex_name_does_not_suppress_claude_surfaces` below.
    """
    root = tmp_path / "PyAutoLabs"
    root.mkdir(parents=True, exist_ok=True)
    (root / "PyAutoBrain").symlink_to(BRAIN_HOME, target_is_directory=True)
    return root


def test_installer_keeps_commands_and_installs_both_skill_homes(tmp_path):
    claude_home = tmp_path / "claude"
    codex_home = tmp_path / "codex"
    env = os.environ | {
        "HOME": str(tmp_path / "home"),
        "PYAUTO_ROOT": str(_pyauto_root(tmp_path)),
        "CLAUDE_HOME": str(claude_home),
        "CODEX_HOME": str(codex_home),
    }

    subprocess.run(
        ["bash", str(INSTALLER)],
        cwd=BRAIN_HOME,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    for name in ("intake", "start_dev"):
        assert (claude_home / "skills" / name).is_symlink()
        assert (claude_home / "commands" / f"{name}.md").is_symlink()

    assert (codex_home / "skills" / "intake").is_symlink()
    assert (codex_home / "skills" / "start-dev").is_symlink()
    assert not (codex_home / "skills" / "start_dev").exists()

    assert (claude_home / "skills" / "release").is_symlink()
    assert (codex_home / "skills" / "release").is_symlink()
    assert not (claude_home / "commands" / "release.md").exists()


def test_installer_preserves_non_symlink_destinations(tmp_path):
    claude_home = tmp_path / "claude"
    codex_home = tmp_path / "codex"
    protected = codex_home / "skills" / "intake"
    protected.mkdir(parents=True)
    marker = protected / "user-owned.txt"
    marker.write_text("keep\n")
    env = os.environ | {
        "HOME": str(tmp_path / "home"),
        "PYAUTO_ROOT": str(_pyauto_root(tmp_path)),
        "CLAUDE_HOME": str(claude_home),
        "CODEX_HOME": str(codex_home),
    }

    result = subprocess.run(
        ["bash", str(INSTALLER)],
        cwd=BRAIN_HOME,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert marker.read_text() == "keep\n"
    assert "SKIP intake (Codex skill" in result.stdout


def test_invalid_codex_name_does_not_suppress_claude_surfaces(tmp_path):
    pyauto_root = tmp_path / "PyAutoLabs"
    skill = pyauto_root / "PyAutoBrain" / "skills" / "legacy_skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: legacy_skill\ndescription: Legacy test skill.\n---\n"
    )
    (skill / "legacy_skill.md").write_text("# Legacy command\n")
    claude_home = tmp_path / "claude"
    codex_home = tmp_path / "codex"
    env = os.environ | {
        "HOME": str(tmp_path / "home"),
        "PYAUTO_ROOT": str(pyauto_root),
        "CLAUDE_HOME": str(claude_home),
        "CODEX_HOME": str(codex_home),
    }

    result = subprocess.run(
        ["bash", str(INSTALLER)],
        cwd=BRAIN_HOME,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert (claude_home / "skills" / "legacy_skill").is_symlink()
    assert (claude_home / "commands" / "legacy_skill.md").is_symlink()
    assert not (codex_home / "skills" / "legacy_skill").exists()
    assert "Codex skill name invalid" in result.stdout


def test_command_surface_block_is_current():
    """This repo's committed command-surface block matches the agent registry.
    Guards against editing bin/pyauto-brain without regenerating the block
    (bash PyAutoBrain/bin/install.sh --write-agents-surface)."""
    result = subprocess.run(
        ["bash", str(INSTALLER), "--check-agents-surface"],
        cwd=BRAIN_HOME,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DRIFT" not in result.stdout


def test_project_discovery_tree_is_current():
    """This repo's committed .claude/ + .codex/ discovery symlinks match skills/.
    Guards against adding or deleting a skill without regenerating the trees
    (bash PyAutoBrain/bin/install.sh --write-project-discovery). Scoped to
    PyAutoBrain so a sibling organ's drift never reddens a local Brain run."""
    result = subprocess.run(
        ["bash", str(INSTALLER), "--check-project-discovery", "PyAutoBrain"],
        cwd=BRAIN_HOME,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DRIFT" not in result.stdout


def test_workspace_policy_write_is_idempotent_and_preserves_symlink(tmp_path):
    root = _pyauto_root(tmp_path)
    target = tmp_path / "root-agents.md"
    target.write_text(
        "before\n<!-- pyauto:model-delegation:begin -->\nold\n<!-- pyauto:model-delegation:end -->\n<!-- pyauto:model-delegation-pointer:begin -->\nold pointer\n<!-- pyauto:model-delegation-pointer:end -->\nafter\n"
    )
    (root / "AGENTS.md").symlink_to(target)
    env = os.environ | {"PYAUTO_ROOT": str(root)}
    for _ in range(2):
        subprocess.run(
            ["bash", str(INSTALLER), "--write-workspace-policy"], env=env, check=True
        )
    assert (root / "AGENTS.md").is_symlink()
    assert target.read_text().count("<!-- pyauto:model-delegation:begin -->") == 1
    subprocess.run(
        ["bash", str(INSTALLER), "--check-workspace-policy"], env=env, check=True
    )


def test_workspace_policy_migrates_legacy_block(tmp_path):
    root = _pyauto_root(tmp_path)
    agents = root / "AGENTS.md"
    agents.write_text(
        "# Rules\n- **Delegate execution to a subagent — for every task.**\n"
        "  old provider policy\n- **Never rewrite pushed history.** Keep this.\n"
        "- **Model delegation** (provider-aware defaults: old)\n"
        "  → `PyAutoBrain/skills/WORKFLOW.md`.\n"
    )
    env = os.environ | {"PYAUTO_ROOT": str(root)}
    subprocess.run(
        ["bash", str(INSTALLER), "--write-workspace-policy"], env=env, check=True
    )
    text = agents.read_text()
    assert "old provider policy" not in text
    assert "pyauto:model-delegation:begin" in text
    assert "Never rewrite pushed history" in text


def test_workspace_policy_rejects_malformed_target_without_writing(tmp_path):
    root = _pyauto_root(tmp_path)
    agents = root / "AGENTS.md"
    original = "before\n<!-- pyauto:model-delegation:begin -->\nunterminated\n"
    agents.write_text(original)
    result = subprocess.run(
        ["bash", str(INSTALLER), "--write-workspace-policy"],
        env=os.environ | {"PYAUTO_ROOT": str(root)},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert agents.read_text() == original


def test_workspace_policy_rejects_reversed_legacy_block_without_writing(tmp_path):
    root = _pyauto_root(tmp_path)
    agents = root / "AGENTS.md"
    original = (
        "- **Never rewrite pushed history.** Keep this.\n"
        "- **Delegate execution to a subagent — for every task.**\n"
        "- **Model delegation** (provider-aware defaults: old)\n"
        "  → `PyAutoBrain/skills/WORKFLOW.md`.\n"
    )
    agents.write_text(original)
    result = subprocess.run(
        ["bash", str(INSTALLER), "--write-workspace-policy"],
        env=os.environ | {"PYAUTO_ROOT": str(root)},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert agents.read_text() == original


def test_workspace_policy_rejects_reversed_pointer_markers(tmp_path):
    root = _pyauto_root(tmp_path)
    agents = root / "AGENTS.md"
    original = (
        "<!-- pyauto:model-delegation:begin -->\npolicy\n<!-- pyauto:model-delegation:end -->\n"
        "<!-- pyauto:model-delegation-pointer:end -->\npointer\n"
        "<!-- pyauto:model-delegation-pointer:begin -->\n"
    )
    agents.write_text(original)
    result = subprocess.run(
        ["bash", str(INSTALLER), "--write-workspace-policy"],
        env=os.environ | {"PYAUTO_ROOT": str(root)},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert agents.read_text() == original


def test_command_surface_covers_every_public_agent():
    agents = public_agents()
    assert agents
    text = (BRAIN_HOME / "AGENTS.md").read_text()
    begin = text.index("<!-- pyauto:commands:begin -->")
    end = text.index("<!-- pyauto:commands:end -->")
    surface = text[begin:end]
    missing = [
        name for name in sorted(agents) if f"`bin/pyauto-brain {name}`" not in surface
    ]
    assert missing == []


def test_registered_discovery_adapters_and_scoped_write(tmp_path):
    root = tmp_path / 'PyAutoLabs'
    mind = root / 'PyAutoMind'
    mind.mkdir(parents=True)
    (mind / 'repos.yaml').write_text(
        'repos:\n  PyAutoBrain:\n    path: PyAutoBrain\n'
        '  autolens_assistant:\n    path: lens/autolens_assistant\n'
        '  autolens_workspace:\n    path: lens/autolens_workspace\n')
    (root / 'PyAutoBrain').symlink_to(BRAIN_HOME, target_is_directory=True)
    assistant = root / 'lens' / 'autolens_assistant'
    assistant.mkdir(parents=True)
    skills = assistant / 'skills'
    skills.mkdir()
    (skills / 'al_plot.md').write_text('---\nname: al_plot\ndescription: ' + 'Plot a <lens> with A > B. ' * 80 + '\n---\n\nBody.\n')
    (skills / '_helper.md').write_text('# Helper\n')
    (skills / 'README.md').write_text('# Readme\n')
    workspace = root / 'lens' / 'autolens_workspace'
    neutral = workspace / 'skills' / 'open_result'
    neutral.mkdir(parents=True)
    (neutral / 'SKILL.md').write_text('---\nname: open_result\ndescription: Open a result.\n---\n')
    env = os.environ | {'PYAUTO_ROOT': str(root)}
    def call(mode, *repos):
        return subprocess.run(['bash', str(INSTALLER), mode, *repos], env=env,
                              capture_output=True, text=True)
    assert call('--check-project-discovery', 'autolens_assistant').returncode == 1
    assert call('--write-project-discovery', 'autolens_assistant').returncode == 0
    assert not (workspace / '.codex').exists()
    assert (assistant / '.claude/commands/al_plot.md').is_symlink()
    adapter = assistant / '.codex/skills/autolens-assistant-al-plot/SKILL.md'
    assert adapter.is_file()
    assert 'name: autolens-assistant-al-plot' in adapter.read_text()
    desc_line = next(line for line in adapter.read_text().splitlines() if line.startswith('description: '))
    assert len(desc_line) < 1050
    assert '<' not in desc_line and '>' not in desc_line
    assert (adapter.parent / '../../../skills/al_plot.md').resolve() == skills / 'al_plot.md'
    assert not (assistant / '.claude/commands/_helper.md').exists()
    assert (assistant / '.claude/skills/_helper.md').is_symlink()
    assert call('--write-project-discovery', 'autolens_workspace').returncode == 0
    assert (workspace / '.claude/skills/open_result').is_symlink()
    assert (workspace / '.codex/skills/autolens-workspace-open-result/SKILL.md').is_file()
    assert call('--check-project-discovery', 'autolens_assistant', 'autolens_workspace').returncode == 0
    assert call('--write-project-discovery', 'autolens_assistant', 'autolens_workspace').returncode == 0


def test_discovery_detects_drift_and_preserves_user_file(tmp_path):
    root = tmp_path / 'PyAutoLabs'
    mind = root / 'PyAutoMind'
    mind.mkdir(parents=True)
    (mind / 'repos.yaml').write_text('repos:\n  sample_assistant:\n    path: sample_assistant\n')
    repo = root / 'sample_assistant'
    skills = repo / 'skills'
    skills.mkdir(parents=True)
    (skills / 'run.md').write_text('---\nname: run\ndescription: Run.\n---\n')
    protected = repo / '.claude/commands/run.md'
    protected.parent.mkdir(parents=True)
    protected.write_text('user\n')
    env = os.environ | {'PYAUTO_ROOT': str(root)}
    write = subprocess.run(['bash', str(INSTALLER), '--write-project-discovery', 'sample_assistant'],
                           env=env, capture_output=True, text=True)
    assert protected.read_text() == 'user\n'
    assert write.returncode == 2
    assert 'CONFLICT' in write.stdout
    assert not (repo / '.codex').exists()
    assert subprocess.run(['bash', str(INSTALLER), '--check-project-discovery', 'sample_assistant'],
                          env=env, capture_output=True).returncode == 1
    protected.unlink()
    subprocess.run(['bash', str(INSTALLER), '--write-project-discovery', 'sample_assistant'], env=env, check=True)
    (skills / 'run.md').unlink()
    assert subprocess.run(['bash', str(INSTALLER), '--check-project-discovery', 'sample_assistant'],
                          env=env, capture_output=True).returncode == 1
    subprocess.run(['bash', str(INSTALLER), '--write-project-discovery', 'sample_assistant'], env=env, check=True)
    assert not (repo / '.codex/skills/sample-assistant-run').exists()


def test_scoped_discovery_rejects_cross_repo_codex_collision(tmp_path):
    root = tmp_path / 'PyAutoLabs'
    mind = root / 'PyAutoMind'
    mind.mkdir(parents=True)
    (mind / 'repos.yaml').write_text(
        'repos:\n  foo_bar:\n    path: foo_bar\n  foo-bar:\n    path: foo-bar\n')
    for name in ('foo_bar', 'foo-bar'):
        skill = root / name / 'skills' / 'run.md'
        skill.parent.mkdir(parents=True)
        skill.write_text('---\nname: run\ndescription: Run.\n---\n')
    result = subprocess.run(
        ['bash', str(INSTALLER), '--write-project-discovery', 'foo_bar'],
        env=os.environ | {'PYAUTO_ROOT': str(root)}, capture_output=True, text=True)
    assert result.returncode == 2
    assert 'Codex skill collision foo-bar-run' in result.stderr
    assert not (root / 'foo_bar' / '.codex').exists()


def test_discovery_preserves_unrelated_user_symlinks_and_rejects_target_conflict(tmp_path):
    root = tmp_path / 'PyAutoLabs'
    mind = root / 'PyAutoMind'
    mind.mkdir(parents=True)
    (mind / 'repos.yaml').write_text('repos:\n  sample_assistant:\n    path: sample_assistant\n')
    repo = root / 'sample_assistant'
    skills = repo / 'skills'
    skills.mkdir(parents=True)
    (skills / 'run.md').write_text('---\nname: run\ndescription: Run.\n---\n')
    user = repo / '.claude/skills/custom.md'
    user.parent.mkdir(parents=True)
    user.symlink_to('../../notes/custom.md')
    env = os.environ | {'PYAUTO_ROOT': str(root)}
    def call(mode):
        return subprocess.run(['bash', str(INSTALLER), mode, 'sample_assistant'],
                              env=env, capture_output=True, text=True)
    assert call('--write-project-discovery').returncode == 0
    assert user.is_symlink() and os.readlink(user) == '../../notes/custom.md'
    assert call('--check-project-discovery').returncode == 0
    expected_link = repo / '.claude/skills/run.md'
    expected_link.unlink()
    expected_link.symlink_to('../../notes/run.md')
    original_adapter = (repo / '.codex/skills/sample-assistant-run/SKILL.md').read_text()
    assert call('--write-project-discovery').returncode == 2
    assert os.readlink(expected_link) == '../../notes/run.md'
    assert (repo / '.codex/skills/sample-assistant-run/SKILL.md').read_text() == original_adapter


def test_discovery_detects_same_repo_normalized_name_collision(tmp_path):
    root = tmp_path / 'PyAutoLabs'
    mind = root / 'PyAutoMind'
    mind.mkdir(parents=True)
    (mind / 'repos.yaml').write_text('repos:\n  sample_assistant:\n    path: sample_assistant\n')
    skills = root / 'sample_assistant' / 'skills'
    skills.mkdir(parents=True)
    (skills / 'first.md').write_text('---\nname: same_name\ndescription: First.\n---\n')
    (skills / 'second.md').write_text('---\nname: same-name\ndescription: Second.\n---\n')
    result = subprocess.run(['bash', str(INSTALLER), '--write-project-discovery', 'sample_assistant'],
                            env=os.environ | {'PYAUTO_ROOT': str(root)}, capture_output=True, text=True)
    assert result.returncode == 2
    assert 'duplicate discovery path' in result.stderr
    assert not (root / 'sample_assistant' / '.codex').exists()


def test_discovery_repairs_broken_managed_link(tmp_path):
    root = tmp_path / 'PyAutoLabs'
    mind = root / 'PyAutoMind'
    mind.mkdir(parents=True)
    (mind / 'repos.yaml').write_text('repos:\n  sample_assistant:\n    path: sample_assistant\n')
    skills = root / 'sample_assistant' / 'skills'
    skills.mkdir(parents=True)
    (skills / 'run.md').write_text('---\nname: run\ndescription: Run.\n---\n')
    env = os.environ | {'PYAUTO_ROOT': str(root)}
    def call(mode):
        return subprocess.run(['bash', str(INSTALLER), mode, 'sample_assistant'],
                              env=env, capture_output=True, text=True)
    assert call('--write-project-discovery').returncode == 0
    link = root / 'sample_assistant' / '.claude/skills/run.md'
    (skills / 'run.md').unlink()
    assert link.is_symlink() and not link.exists()
    assert call('--check-project-discovery').returncode == 1
    assert call('--write-project-discovery').returncode == 0
    assert not link.is_symlink()


def test_removed_organ_skill_reports_dangling_codex_link_without_deleting(tmp_path):
    root = tmp_path / 'PyAutoLabs'
    mind = root / 'PyAutoMind'
    mind.mkdir(parents=True)
    (mind / 'repos.yaml').write_text('repos:\n  PyAutoHeart:\n    path: PyAutoHeart\n')
    repo = root / 'PyAutoHeart'
    skill = repo / 'skills' / 'pulse'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('---\nname: pulse\ndescription: Read pulse.\n---\n')
    env = os.environ | {'PYAUTO_ROOT': str(root)}
    def call(mode):
        return subprocess.run(['bash', str(INSTALLER), mode, 'PyAutoHeart'],
                              env=env, capture_output=True, text=True)
    assert call('--write-project-discovery').returncode == 0
    codex_link = repo / '.codex/skills/pulse'
    (skill / 'SKILL.md').unlink()
    skill.rmdir()
    assert codex_link.is_symlink() and not codex_link.exists()
    assert call('--check-project-discovery').returncode == 1
    write = call('--write-project-discovery')
    assert write.returncode == 2
    assert 'pulse' in write.stdout
    assert codex_link.is_symlink()


def test_discovery_refuses_symlinked_surface_even_with_no_expected_links(tmp_path):
    root = tmp_path / 'PyAutoLabs'
    mind = root / 'PyAutoMind'
    mind.mkdir(parents=True)
    (mind / 'repos.yaml').write_text('repos:\n  sample_assistant:\n    path: sample_assistant\n')
    repo = root / 'sample_assistant'
    (repo / 'skills').mkdir(parents=True)
    outside = tmp_path / 'outside'
    outside.mkdir()
    user_link = outside / 'custom.md'
    user_link.symlink_to('../../skills/custom.md')
    (repo / '.claude').mkdir()
    (repo / '.claude/commands').symlink_to(outside, target_is_directory=True)
    env = os.environ | {'PYAUTO_ROOT': str(root)}
    for mode in ('--check-project-discovery', '--write-project-discovery'):
        result = subprocess.run(['bash', str(INSTALLER), mode, 'sample_assistant'],
                                env=env, capture_output=True, text=True)
        assert result.returncode == 0
        assert user_link.is_symlink()
    (repo / 'skills/run.md').write_text('---\nname: run\ndescription: Run.\n---\n')
    result = subprocess.run(['bash', str(INSTALLER), '--write-project-discovery', 'sample_assistant'],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 2
    assert '.claude/commands' in result.stdout
    assert user_link.is_symlink()
