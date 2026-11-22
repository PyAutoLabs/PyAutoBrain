#!/usr/bin/env python3
"""Check local Codex shift prerequisites; --smoke explicitly runs one no-op worker."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / 'agents' / 'conductors' / 'batch'))
import _codex  # noqa: E402
import _login  # noqa: E402


def check() -> dict:
    errors = []
    if not Path('/proc/self/stat').exists():
        errors.append('Linux/WSL with /proc process identity is required')
    try:
        help_result = subprocess.run(['codex', 'exec', '--help'], capture_output=True,
                                     text=True, timeout=30)
        for flag in ('--json', '--sandbox', '--add-dir', '--approve-for-me'):
            if help_result.returncode or flag not in help_result.stdout:
                errors.append(f'installed codex exec does not advertise {flag}')
    except (OSError, subprocess.SubprocessError):
        errors.append('codex exec is unavailable')
    login = _codex.probe()
    if login['state'] != 'ok':
        errors.append(login['detail'])
    reviewer = _login.probe()
    if reviewer['state'] != 'ok':
        errors.append('Claude login must be verified for independent Opus reviews')
    return {'ok': not errors, 'errors': errors,
            'manual_check': 'Review and trust the current project hook hash with /hooks; '
                            'verify gh auth and Heart before a shift. This check starts no model.'}


def smoke(model: str) -> dict:
    # Disposable workspace: no repositories, shift grants or publication.
    import shutil

    root = Path(tempfile.mkdtemp(prefix="pyauto-codex-smoke-"))
    home = root / 'state'
    marker = root / 'smoke-ok.txt'
    prompt = (f'This is a bounded CLI integration smoke test, not a development task. '
              f'Write exactly PYAUTO_CODEX_OK to {marker}, then stop. '
              'Do not read other projects, call another model, use the network, '
              'create a task, commit, push or launch any background work.')
    lease = _codex.launch(prompt, home=home, cwd=root, write_root=root, model=model,
                          effort='medium', mode='dontAsk', env=dict(os.environ))
    sid = lease['agent_id']
    try:
        end = time.monotonic() + 300
        while time.monotonic() < end:
            state = _codex.state(sid, home)
            if state in {'done', 'error', 'killed'}:
                usage = _codex.usage(sid, home)
                passed = state == 'done' and marker.exists() and marker.read_text().strip() == 'PYAUTO_CODEX_OK'
                return {'ok': passed and usage is not None, 'state': state, 'usage': usage,
                        'marker': passed, 'scope': 'no-op only; no development/merge readiness claim'}
            time.sleep(.2)
        return {'ok': False, 'error': 'smoke timed out after 300 seconds'}
    finally:
        _codex.stop(sid, home)
        # Never remove a live supervisor's state directory.
        end = time.monotonic() + 10
        while _codex.state(sid, home) not in {'done', 'error', 'killed'}:
            if time.monotonic() >= end:
                # Preserve evidence if the supervisor cannot be observed.
                print(f'Smoke state retained at {root}; inspect before another attempt.', file=sys.stderr)
                break
            time.sleep(.1)
        else:
            shutil.rmtree(root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke', action='store_true', help='explicitly run one no-op model session')
    parser.add_argument('--model', help='installed Codex model id; required with --smoke')
    args = parser.parse_args()
    if args.smoke and not args.model:
        parser.error('--smoke requires --model')
    result = check()
    if args.smoke and result['ok']:
        result = smoke(args.model)
    print(json.dumps(result, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
