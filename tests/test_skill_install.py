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


def test_installer_keeps_commands_and_installs_both_skill_homes(tmp_path):
    claude_home = tmp_path / "claude"
    codex_home = tmp_path / "codex"
    env = os.environ | {
        "HOME": str(tmp_path / "home"),
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
