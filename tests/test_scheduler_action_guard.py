"""tests/test_scheduler_action_guard.py — no raw scheduler mutations.

hpc-campaign phase 5c (ruling F12): `sbatch`, `scancel` and a mutating
`scontrol` are refused outside a project's `hpc/sync submit|push-submit|act`,
however they are dressed up; reading the queue is free; a mere mention of a
scheduler word (a commit message, a grep) is not a call.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from scheduler_action_guard import check_command  # noqa: E402

HOOK = Path(__file__).resolve().parents[1] / "bin" / "scheduler_action_guard.py"


def run_hook(payload):
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(HOOK)], input=body, capture_output=True, text=True
    )


DENIED = [
    "sbatch job.sh",
    "sbatch --array=0-99 --partition=ral job.sh",
    "/usr/bin/sbatch job.sh",
    "scancel 413011",
    "scancel -u $USER",
    "scontrol hold 413011",
    "scontrol release 413011",
    "scontrol update JobId=413011 ArrayTaskThrottle=4",
    "scontrol -o requeue 413011",
    "scontrol -M ral update JobId=1 Partition=gpu",
    # over ssh, quoted or not, with options
    "ssh ral sbatch job.sh",
    'ssh ral "cd /mnt/ral/x && sbatch job.sh"',
    "ssh -p 22 -o BatchMode=yes ral 'scancel 1'",
    'ssh ral "bash -lc \'scontrol update JobId=1 TimeLimit=2:00:00\'"',
    # chained, piped, substituted
    "hpc/sync jobs; scancel 1",
    "cd x && sbatch job.sh",
    "false || sbatch job.sh",
    "squeue -h -o %i | xargs scancel",
    "squeue -h -o %i | xargs -n 1 scancel",
    "echo $(sbatch --parsable job.sh)",
    "echo `scancel 1`",
    "hpc/sync act hold c 1 && ssh ral scancel 2",
    # env-prefixed and wrapped
    "SLURM_CONF=/x sbatch job.sh",
    "env -u FOO A=1 sbatch job.sh",
    "sudo -u slurm scontrol update JobId=1 Priority=0",
    "timeout 30 sbatch job.sh",
    "nohup nice -n 10 sbatch job.sh",
    "bash -c 'sbatch job.sh'",
    "eval sbatch job.sh",
    "for j in 1 2; do scancel $j; done",
    "if true; then sbatch job.sh; fi",
    # a heredoc that a shell runs
    "ssh ral bash -s <<'EOF'\ncd /mnt/ral/x\nsbatch job.sh\nEOF",
    "cat <<EOF | ssh ral\nscancel 1\nEOF",
    # a campaign's jobs start only through `hpc/sync act submit`
    "ssh ral 'cd /mnt/ral/x && python -m autofit.campaign submit campaign.yaml'",
    "python3 -m autofit.campaign submit campaign.yaml --stage source_lp",
    "/opt/venv/bin/python3.12 -m autofit.campaign submit c.yaml --proposal p.json",
    # srun / salloc start work too (human ruling 2026-10-31)
    "srun -n 4 python fit.py",
    "ssh ral 'salloc -p ral -N 1'",
    # quoting or escaping that the shell reads as the bare word (review 2026-10-31)
    "s\\batch job.sh",
    'eval "sb""atch job.sh"',
    # ssh options after the host
    'ssh ral -t "sbatch job.sh"',
    "ssh ral -p 22 scancel 1",
    # find -exec, parallel
    "find . -name '*.sh' -exec sbatch {} \\;",
    "parallel -j 4 scancel ::: 1 2 3",
    # the escape hatch excuses only the clause it prefixes
    "echo PYAUTO_SKIP_SCHEDULER_GUARD=1; sbatch job.sh",
    'git commit -m "PYAUTO_SKIP_SCHEDULER_GUARD=1" && scancel 1',
]

ALLOWED = [
    # the project's own CLI — the place the queue is changed, with a record
    "hpc/sync submit gpu job.sh --export=ALL,SEED=3",
    "hpc/sync push-submit cpu job.sh",
    "./hpc/sync act hold my_campaign 413011",
    "hpc/sync act update-pending campaign.yaml 413011 TimeLimit=2:00:00",
    "cd /x && hpc/sync act cancel my_campaign 413011",
    "hpc/sync cancel 413011",
    "hpc/sync act submit campaign.yaml --indices 0,7,19",
    "hpc/sync act resubmit campaign.yaml proposal_oom.json",
    "hpc/sync pilot campaign.yaml",
    # campaign verbs that submit nothing
    "ssh ral 'python -m autofit.campaign status campaign.yaml'",
    "python -m autofit.campaign plan campaign.yaml",
    "python -m autofit.campaign submit campaign.yaml --dry-run",
    # reading the queue
    "squeue -u $USER",
    "ssh ral squeue --me",
    "ssh ral 'sacct -j 413011 --format=JobID,State,ExitCode'",
    "scontrol show job 413011",
    "ssh ral 'scontrol show job 413011 | grep -i gres'",
    "scontrol -d show job 413011",
    "scontrol -M ral show partition",
    "scontrol ping",
    "sinfo -p ral",
    # options with which a scheduler word only reads
    "sbatch --help",
    "ssh ral sbatch --test-only job.sh",
    "srun --usage",
    "salloc -V",
    "find . -name '*.sh' -exec grep -l sbatch {} +",
    # mentions, not calls
    'git commit -m "docs: never sbatch or scancel by hand"',
    "grep -rn sbatch hpc/",
    "rg 'scontrol update' wiki/",
    "man sbatch",
    "echo 'use hpc/sync act, not scancel'",
    'gh issue comment 5 --body "ran ssh ral sbatch earlier"',
    # writing a job script that contains a scheduler call is not a call
    "cat <<'EOF' > chain.sh\n#!/bin/bash\nsbatch --dependency=afterok:1 b.sh\nEOF",
    "bash chain_check.sh",
    # nothing to do with the scheduler
    "ls -la && git status",
    "",
]


@pytest.mark.parametrize("command", DENIED)
def test_scheduler_mutations_are_denied(command):
    reason = check_command(command)
    assert reason and "hpc/sync act" in reason and "actions.log" in reason


@pytest.mark.parametrize("command", ALLOWED)
def test_reads_mentions_and_hpc_sync_are_allowed(command):
    assert check_command(command) is None


def test_the_reason_names_the_word_it_caught():
    assert "Raw `scancel`" in check_command("ssh ral scancel 1")
    assert "Raw `scontrol hold`" in check_command("scontrol hold 1")
    assert "Raw `autofit.campaign submit`" in check_command(
        "ssh ral python -m autofit.campaign submit c.yaml")


def test_escape_hatch_allows():
    assert check_command("PYAUTO_SKIP_SCHEDULER_GUARD=1 scancel 1") is None
    assert check_command("cd x && PYAUTO_SKIP_SCHEDULER_GUARD=1 ssh ral scancel 1") is None


def test_unbalanced_quotes_fail_open():
    assert check_command("sbatch 'job.sh") is None


def test_hook_denies_with_the_pretooluse_contract():
    result = run_hook({
        "tool_name": "Bash",
        "hook_event_name": "PreToolUse",
        "tool_input": {"command": "ssh ral scancel 413011"},
    })
    assert result.returncode == 0
    out = json.loads(result.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert out["permissionDecision"] == "deny"
    assert "hpc/sync act" in out["permissionDecisionReason"]


def test_codex_payload_shape_is_judged_the_same():
    result = run_hook({
        "session_id": "codex-session",
        "turn_id": "turn-1",
        "tool_name": "Bash",
        "tool_use_id": "call-1",
        "cwd": "/tmp",
        "hook_event_name": "PreToolUse",
        "tool_input": {"command": "sbatch job.sh"},
    })
    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_hook_allows_silently():
    result = run_hook({"tool_name": "Bash", "tool_input": {"command": "hpc/sync act hold c 1"}})
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_non_bash_tools_are_not_judged():
    result = run_hook({"tool_name": "Write", "tool_input": {"command": "sbatch x"}})
    assert (result.returncode, result.stdout) == (0, "")


@pytest.mark.parametrize("payload", ["not-json", "[]", '{"tool_name":"Bash","tool_input":7}'])
def test_malformed_payload_fails_open_without_crashing(payload):
    result = run_hook(payload)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
