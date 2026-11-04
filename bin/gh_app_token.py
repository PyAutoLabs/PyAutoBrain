#!/usr/bin/env python3
"""bin/gh_app_token.py — mint a fresh pyautolabs-bot App installation token.

WHY. An App installation token lives 60 minutes, but the nightly release job
runs for hours. The workflow mints one token at the start; the nightly driver
calls this helper to mint a new one before the old one runs out, so a long
watch on a passing run never ends in "HTTP 401: Bad credentials".

WHAT IT DOES. Signs a short-lived JWT with the App's private key (via the
`openssl` command, so there are no Python dependencies), finds the App's
installation on the owner, and asks for an installation token with exactly
the permission set the workflow's mint step uses. Prints the token, nothing
else.

Environment:
  APP_CLIENT_ID    the App's client id (the JWT issuer)
  APP_PRIVATE_KEY  the App's private key, PEM text
  APP_OWNER        the installation owner (default PyAutoLabs)

Exit 0 with the token on stdout; exit 1 with a one-line reason on stderr. The
key, the JWT and the token never appear in an error message.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

API = "https://api.github.com"

# Must match the `permission-*` inputs of the `app_token` step in
# .github/workflows/nightly-release.yml (a test pins this). `actions_variables`
# is the installation's name for the App's "Variables" permission.
INSTALLATION_PERMISSIONS = {
    "actions": "write",
    "contents": "read",
    "issues": "read",
    "actions_variables": "write",
}


class MintError(Exception):
    """A failure whose message is safe to print (no secrets in it)."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign(message: bytes, private_key: str) -> bytes:
    """RS256-sign `message` with `openssl dgst`; the key file is 0600 and always removed."""
    fd, key_path = tempfile.mkstemp(prefix="gh-app-key-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(private_key)
        proc = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_path],
            input=message,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise MintError(f"could not run openssl ({exc.strerror})") from None
    finally:
        try:
            os.unlink(key_path)
        except OSError:
            pass
    if proc.returncode != 0:
        raise MintError(
            "openssl could not sign the JWT (is APP_PRIVATE_KEY a valid PEM key?)"
        )
    return proc.stdout


def make_jwt(client_id: str, private_key: str, now: int | None = None) -> str:
    """A 10-minute App JWT; `iat` is back-dated 60 s for clock drift."""
    now = int(time.time()) if now is None else int(now)
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {"iat": now - 60, "exp": now + 540, "iss": client_id}
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(claims, separators=(",", ":")).encode())
    )
    signature = _sign(signing_input.encode("ascii"), private_key)
    return signing_input + "." + _b64url(signature)


def _request(method: str, url: str, headers: dict, body: dict | None = None):
    """One GitHub API call; returns the decoded JSON. All HTTP goes through here."""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        raise MintError(f"{method} {url} returned HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise MintError(f"{method} {url} failed ({type(exc).__name__})") from None


def mint(
    client_id: str, private_key: str, owner: str = "PyAutoLabs", request=_request
) -> str:
    """Mint an installation token for `owner` with INSTALLATION_PERMISSIONS."""
    headers = {
        "Authorization": f"Bearer {make_jwt(client_id, private_key)}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    installations = request("GET", f"{API}/app/installations", headers, None)
    match = [
        i
        for i in installations or []
        if str((i.get("account") or {}).get("login", "")).lower() == owner.lower()
    ]
    if not match:
        raise MintError(f"the App has no installation on '{owner}'")
    result = request(
        "POST",
        f"{API}/app/installations/{match[0]['id']}/access_tokens",
        headers,
        {"permissions": INSTALLATION_PERMISSIONS},
    )
    token = (result or {}).get("token")
    if not token:
        raise MintError("GitHub returned no token")
    return token


def main() -> int:
    client_id = os.environ.get("APP_CLIENT_ID", "")
    private_key = os.environ.get("APP_PRIVATE_KEY", "")
    owner = os.environ.get("APP_OWNER") or "PyAutoLabs"
    if not client_id or not private_key:
        print(
            "gh_app_token: APP_CLIENT_ID and APP_PRIVATE_KEY must both be set",
            file=sys.stderr,
        )
        return 1
    try:
        token = mint(client_id, private_key, owner)
    except MintError as exc:
        print(f"gh_app_token: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — never dump a traceback that could carry secrets
        print(f"gh_app_token: unexpected {type(exc).__name__}", file=sys.stderr)
        return 1
    print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
