"""tests/test_repo_settings_workflow.py — the settings sweep's shell block.

**Why this file exists.** The sweep was control-tested across seven scenarios
before it shipped, and still failed on its first real dispatch. The harness ran
`bash <script>`; GitHub runs `bash -e {0}`. Under `-e` the per-repo read

    before=$(gh api "repos/$slug" ... 2>/dev/null)

aborts the whole script the moment one repo is unreadable — silently, since its
stderr is discarded — so the unreadable branch and the in-org/out-of-org failure
split were dead code in production while passing every local test. A control
test that does not reproduce the caller's invocation proves nothing about the
caller, so every test here runs the block **exactly as GitHub does**.

Fixtures use invented repo names: this is a `.py` file under a framework organ,
so the tenant firewall scans it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

BRAIN_HOME = Path(__file__).resolve().parents[1]
WORKFLOW = BRAIN_HOME / ".github" / "workflows" / "repo_settings.yml"

# GitHub's default for a `run:` block with no `shell:` key. Hardcoded rather
# than read from the workflow because it is a property of the *runner*, and the
# point of these tests is to pin the runner's behaviour, not to echo the file.
GITHUB_SHELL = ["bash", "-e"]


def _step() -> dict:
    doc = yaml.safe_load(WORKFLOW.read_text())
    for st in doc["jobs"]["settings"]["steps"]:
        if "Read or set" in str(st.get("name", "")):
            return st
    raise AssertionError("the per-repo step is gone — this test needs repointing")


def test_the_step_does_not_override_the_shell():
    """If it ever sets `shell:`, GITHUB_SHELL above stops being the truth."""
    assert "shell" not in _step(), "step now sets shell: — update GITHUB_SHELL"


def _harness(tmp_path: Path, gh_body: str) -> Path:
    """A cwd the block can run in: stub `gh`, a body map, the real derivation."""
    binv = tmp_path / "stubbin"
    binv.mkdir()
    gh = binv / "gh"
    gh.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(gh_body))
    gh.chmod(0o755)

    (tmp_path / "bin").mkdir()
    shutil.copy(BRAIN_HOME / "bin" / "branch_sweep_targets.py", tmp_path / "bin")

    (tmp_path / ".mind").mkdir()
    (tmp_path / ".mind" / "repos.yaml").write_text(
        yaml.safe_dump(
            {
                "repos": {
                    "Lib": {"github": "Org/Lib", "category": "library"},
                    "Mine": {"github": "Person/Mine", "category": "admin"},
                }
            },
            sort_keys=False,
        )
    )
    (tmp_path / "script.sh").write_text(_step()["run"])
    return binv


def _run(tmp_path: Path, gh_body: str, mode: str = "audit"):
    binv = _harness(tmp_path, gh_body)
    env = {
        **os.environ,
        "PATH": f"{binv}{os.pathsep}{os.environ['PATH']}",
        "GH_TOKEN": "stub",
        "ORG": "Org",
        "MODE": mode,
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
    }
    (tmp_path / "summary.md").write_text("")
    proc = subprocess.run(
        [*GITHUB_SHELL, "script.sh"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    return proc, (tmp_path / "summary.md").read_text()


# The org listing every scenario shares; `$1 $2 …` is the gh argv.
_LIST = '''
    case "$*" in
      *"orgs/Org/repos"*) printf 'Org/Alpha\\nOrg/Beta\\n'; exit 0 ;;
'''


def test_an_unreadable_in_org_repo_is_reported_not_silently_fatal(tmp_path):
    """The regression: under -e this aborted with no output at all."""
    proc, summary = _run(
        tmp_path,
        _LIST
        + '''
      *"repos/Org/Beta"*) exit 1 ;;
      *) echo true; exit 0 ;;
    esac
    ''',
    )
    assert "::warning::" in proc.stdout, f"silent abort regressed:\n{proc.stdout!r}"
    assert "Org/Beta" in proc.stdout
    assert "unreadable" in summary
    assert "Org/Alpha" in summary, "aborted before finishing the sweep"
    assert proc.returncode == 1, "an in-org failure must still fail the job"


def test_an_unreadable_out_of_org_repo_warns_but_keeps_the_job_green(tmp_path):
    """A personal-account repo the org PAT cannot admin must not redden the schedule."""
    proc, summary = _run(
        tmp_path,
        _LIST
        + '''
      *"repos/Person/Mine"*) exit 1 ;;
      *) echo true; exit 0 ;;
    esac
    ''',
    )
    assert "::warning::" in proc.stdout
    assert "Person/Mine" in proc.stdout
    assert proc.returncode == 0, "an out-of-org failure must not fail the job"


def test_a_refused_patch_out_of_org_keeps_the_job_green(tmp_path):
    """`hard=0` on the PATCH branch — the other trailing-compound instance."""
    proc, summary = _run(
        tmp_path,
        _LIST
        + '''
      *"-X PATCH"*) case "$*" in *Person/Mine*) exit 1 ;; esac; exit 0 ;;
      *) echo false; exit 0 ;;
    esac
    ''',
        mode="apply",
    )
    assert "refused (needs admin)" in summary
    assert proc.returncode == 0


def test_all_already_on_is_green_and_sweeps_every_repo(tmp_path):
    proc, summary = _run(tmp_path, _LIST + '''
      *) echo true; exit 0 ;;
    esac
    ''')
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for slug in ("Org/Alpha", "Org/Beta", "Person/Mine"):
        assert slug in summary, f"{slug} missing — the sweep stopped early"


def test_an_empty_org_listing_refuses_rather_than_reporting_a_clean_sweep(tmp_path):
    """Losing org read must not look like 'nothing to do'."""
    proc, _ = _run(tmp_path, '''
    case "$*" in
      *"orgs/Org/repos"*) exit 0 ;;
      *) echo true; exit 0 ;;
    esac
    ''')
    assert proc.returncode == 1
    assert "listed no repos" in proc.stdout
