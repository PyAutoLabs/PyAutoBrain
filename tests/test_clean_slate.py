"""Safety and behavior tests for the generated-cruft cleanup executor."""

import os
import subprocess
from pathlib import Path


BRAIN_HOME = Path(__file__).resolve().parents[1]
CLEAN_SLATE = BRAIN_HOME / "bin" / "clean_slate.sh"


def _init_repo(root, name, ignore="*.egg-info/\nbuild/\n"):
    repo = root / name
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    if ignore:
        (repo / ".gitignore").write_text(ignore)
    return repo


def _run(root, dry_run=False, packaging_only=True):
    env = {**os.environ, "PYAUTO_ROOT": str(root)}
    if dry_run:
        env["DRY_RUN"] = "1"
    args = ["bash", str(CLEAN_SLATE)]
    if packaging_only:
        args.append("--packaging")
    return subprocess.run(args, capture_output=True, text=True, env=env)


def _write(directory, name="generated.txt"):
    directory.mkdir(parents=True)
    (directory / name).write_text("generated")


def test_dry_run_reports_packaging_without_removing_it(tmp_path):
    repo = _init_repo(tmp_path, "PyAutoGalaxy")
    egg_info = repo / "autogalaxy.egg-info"
    build = repo / "build"
    _write(egg_info)
    _write(build)

    result = _run(tmp_path, dry_run=True)

    assert result.returncode == 0, result.stderr
    assert "[dry-run] remove packaging directory autogalaxy.egg-info/" in result.stdout
    assert "[dry-run] remove packaging directory build/" in result.stdout
    assert egg_info.exists() and build.exists()


def test_cleanup_is_root_scoped_ignored_and_tracked_safe(tmp_path):
    repo = _init_repo(tmp_path, "PyAutoGalaxy")
    egg_info = repo / "autogalaxy.egg-info"
    build = repo / "build"
    nested_build = repo / "src" / "build"
    output = repo / "output"
    _write(egg_info)
    _write(build)
    _write(nested_build)
    _write(output)
    (repo / "test_report.md").write_text("keep in packaging-only mode")

    protected = _init_repo(tmp_path, "PyAutoFit")
    _write(protected / "build", "tracked.txt")
    subprocess.run(
        ["git", "-C", str(protected), "add", "-f", "build/tracked.txt"],
        check=True,
    )

    unignored = _init_repo(tmp_path, "PyAutoArray", ignore="")
    _write(unignored / "local.egg-info")

    assistant = _init_repo(tmp_path, "euclid_assistant")
    _write(assistant / "build")

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert not egg_info.exists() and not build.exists()
    assert nested_build.exists()
    assert output.exists() and (repo / "test_report.md").exists()
    assert (protected / "build" / "tracked.txt").exists()
    assert (unignored / "local.egg-info").exists()
    assert (assistant / "build").exists()
