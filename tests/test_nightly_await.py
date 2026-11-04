"""tests/test_nightly_await.py — the nightly driver keeps its token alive.

An App token lives 60 minutes; a Stage 3 watch once outlived it, `gh` returned
"HTTP 401: Bad credentials", and a passing run was paged as a failure (#577).
await_run must ride out transient read failures, report a red run as red, and
report "could not observe" (4) — never a verdict — when reads keep failing.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

LIB = (
    Path(__file__).resolve().parents[1]
    / "agents"
    / "conductors"
    / "release"
    / "_nightly_lib.sh"
)


def _lean_path(tmp_path: Path) -> str:
    """Only the tools the lib calls, plus a fake `gh` (so no real gh is reachable)."""
    lean = tmp_path / "bin"
    lean.mkdir(exist_ok=True)
    for tool in (
        "bash",
        "python3",
        "date",
        "sleep",
        "mktemp",
        "head",
        "rm",
        "cat",
        "dirname",
        "readlink",
    ):
        found = shutil.which(tool)
        if found and not (lean / tool).exists():
            (lean / tool).symlink_to(found)
    return str(lean)


def _fake_gh(tmp_path: Path, responses: list[str]) -> None:
    """A `gh` that answers call N with responses[N] (the last repeats).

    "FAIL" prints a 401 and exits 1; anything else is printed as the JSON body.
    """
    script_dir = tmp_path / "gh-script"
    script_dir.mkdir()
    for i, r in enumerate(responses):
        (script_dir / str(i)).write_text(r)
    gh = tmp_path / "bin" / "gh"
    gh.write_text(f"""#!/usr/bin/env bash
d="{script_dir}"
n=$(cat "$d/count" 2>/dev/null || echo 0)
echo $((n + 1)) > "$d/count"
i=$n; [[ -f "$d/$i" ]] || i={len(responses) - 1}
r=$(cat "$d/$i")
if [[ "$r" == FAIL ]]; then echo "failed to get run: HTTP 401: Bad credentials" >&2; exit 1; fi
echo "$r"
""")
    gh.chmod(0o755)


def _run(tmp_path: Path, body: str, env_extra: dict | None = None):
    env = {
        "PATH": _lean_path(tmp_path),
        "NIGHTLY_POLL_SECONDS": "0",
        "TMPDIR": str(tmp_path),
        "GH_TOKEN": "oldtoken",
    }
    env.update(env_extra or {})
    return subprocess.run(
        ["bash", "-c", f'set -uo pipefail; source "{LIB}"; {body}'],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def _calls(tmp_path: Path) -> int:
    return int((tmp_path / "gh-script" / "count").read_text())


def test_transient_401s_then_success_returns_0(tmp_path):
    _lean_path(tmp_path)
    _fake_gh(
        tmp_path, ["FAIL", "FAIL", '{"status":"completed","conclusion":"success"}']
    )
    out = _run(tmp_path, 'await_run o/r 7; echo "rc=$?"')
    assert "rc=0" in out.stdout, out.stderr
    assert _calls(tmp_path) == 3


def test_permanent_failure_returns_4_after_five_polls(tmp_path):
    _lean_path(tmp_path)
    _fake_gh(tmp_path, ["FAIL"])
    out = _run(tmp_path, 'await_run o/r 7; echo "rc=$?"')
    assert "rc=4" in out.stdout, out.stderr
    assert _calls(tmp_path) == 5
    assert "Bad credentials" in out.stderr


def test_red_run_returns_2(tmp_path):
    _lean_path(tmp_path)
    _fake_gh(
        tmp_path,
        [
            '{"status":"in_progress","conclusion":null}',
            '{"status":"completed","conclusion":"failure"}',
        ],
    )
    out = _run(tmp_path, 'await_run o/r 7; echo "rc=$?"')
    assert "rc=2" in out.stdout, out.stderr


def test_refresh_is_a_no_op_without_app_credentials(tmp_path):
    out = _run(
        tmp_path,
        'refresh_gh_token --force; echo "rc=$? tok=$GH_TOKEN"',
        {"NIGHTLY_MINT_CMD": "false"},
    )
    assert "rc=0 tok=oldtoken" in out.stdout
    assert "refreshed" not in out.stdout


def test_forced_refresh_exports_the_new_token(tmp_path):
    mint = tmp_path / "mint.sh"
    mint.write_text("#!/usr/bin/env bash\necho newtoken\n")
    mint.chmod(0o755)
    creds = {
        "APP_CLIENT_ID": "id",
        "APP_PRIVATE_KEY": "key",
        "NIGHTLY_MINT_CMD": str(mint),
    }
    out = _run(tmp_path, 'refresh_gh_token --force; echo "rc=$? tok=$GH_TOKEN"', creds)
    assert "rc=0 tok=newtoken" in out.stdout, out.stderr
    assert "GitHub token refreshed" in out.stdout
    # A fresh token is not re-minted until it is old.
    out = _run(tmp_path, 'refresh_gh_token; echo "tok=$GH_TOKEN"', creds)
    assert "tok=oldtoken" in out.stdout


def test_failed_mint_returns_1_and_keeps_the_old_token(tmp_path):
    creds = {
        "APP_CLIENT_ID": "id",
        "APP_PRIVATE_KEY": "key",
        "NIGHTLY_MINT_CMD": str(shutil.which("false")),
    }
    out = _run(tmp_path, 'refresh_gh_token --force; echo "rc=$? tok=$GH_TOKEN"', creds)
    assert "rc=1 tok=oldtoken" in out.stdout
    assert "could not mint" in out.stderr
