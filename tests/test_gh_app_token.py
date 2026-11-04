"""tests/test_gh_app_token.py — the nightly driver's App token re-mint helper.

The workflow mints one 60-minute token; bin/gh_app_token.py mints the next ones
mid-run. It must sign a valid RS256 JWT and ask for exactly the permission set
the workflow's mint step declares — never more.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "gh_app_token", ROOT / "bin" / "gh_app_token.py"
)
gh_app_token = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gh_app_token)

needs_openssl = pytest.mark.skipif(
    shutil.which("openssl") is None, reason="openssl not installed"
)


def _b64decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


@pytest.fixture
def rsa_key(tmp_path):
    key = tmp_path / "key.pem"
    subprocess.run(
        ["openssl", "genrsa", "-out", str(key), "2048"], check=True, capture_output=True
    )
    return key


@needs_openssl
def test_make_jwt_is_a_verifiable_rs256_jwt(rsa_key, tmp_path):
    jwt = gh_app_token.make_jwt("Iv1.client", rsa_key.read_text(), now=1_000_000)
    parts = jwt.split(".")
    assert len(parts) == 3
    assert all("=" not in p for p in parts)
    assert json.loads(_b64decode(parts[0])) == {"alg": "RS256", "typ": "JWT"}
    claims = json.loads(_b64decode(parts[1]))
    assert claims["iss"] == "Iv1.client"
    assert claims["iat"] == 1_000_000 - 60
    assert claims["exp"] - claims["iat"] == 600

    pub = tmp_path / "pub.pem"
    subprocess.run(
        ["openssl", "rsa", "-in", str(rsa_key), "-pubout", "-out", str(pub)],
        check=True,
        capture_output=True,
    )
    sig = tmp_path / "sig.bin"
    sig.write_bytes(_b64decode(parts[2]))
    verify = subprocess.run(
        ["openssl", "dgst", "-sha256", "-verify", str(pub), "-signature", str(sig)],
        input=f"{parts[0]}.{parts[1]}".encode(),
        capture_output=True,
        check=False,
    )
    assert verify.returncode == 0, verify.stderr


@needs_openssl
def test_mint_picks_the_owner_installation_and_asks_for_exact_permissions(rsa_key):
    calls = []

    def fake_request(method, url, headers, body):
        calls.append((method, url, headers, body))
        if method == "GET":
            return [
                {"id": 1, "account": {"login": "someone-else"}},
                {"id": 42, "account": {"login": "example-org"}},
            ]
        return {"token": "ghs_fresh"}

    token = gh_app_token.mint(
        "Iv1.client", rsa_key.read_text(), "example-org", request=fake_request
    )
    assert token == "ghs_fresh"
    assert calls[0][:2] == ("GET", "https://api.github.com/app/installations")
    method, url, headers, body = calls[1]
    assert (method, url) == (
        "POST",
        "https://api.github.com/app/installations/42/access_tokens",
    )
    assert headers["Authorization"].startswith("Bearer ")
    assert body == {"permissions": gh_app_token.INSTALLATION_PERMISSIONS}


@needs_openssl
def test_mint_fails_cleanly_without_an_owner_installation(rsa_key):
    with pytest.raises(gh_app_token.MintError, match="no installation"):
        gh_app_token.mint(
            "Iv1.client",
            rsa_key.read_text(),
            "example-org",
            request=lambda *a: [{"id": 1, "account": {"login": "x"}}],
        )


def test_permissions_match_the_workflow_mint_step():
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "nightly-release.yml").read_text()
    )
    step = next(
        s for s in workflow["jobs"]["nightly"]["steps"] if s.get("id") == "app_token"
    )
    declared = {
        key[len("permission-") :].replace("-", "_"): value
        for key, value in step["with"].items()
        if key.startswith("permission-")
    }
    assert declared == gh_app_token.INSTALLATION_PERMISSIONS
