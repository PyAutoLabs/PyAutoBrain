"""PyAutoBrain#630: the shift watcher posts as its own minimal GitHub App.

The App (`PYAUTO_SHIFT_APP_ID` / `_INSTALLATION_ID` / `_KEY`) signs an RS256
JWT, mints an installation token on a tick's first watcher GitHub call, holds
it in memory for that tick only (never on disk), and gives it to the watcher's
own `gh` calls only. A mint that fails holds every watcher call — never the
human's `gh` auth in its place — and backs off 10 min. A
generated RSA key and a fake API stand in for GitHub: nothing here reaches
the network.
"""

from __future__ import annotations

import base64
import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "tests"))
import test_orchestrator_dispatch as d  # noqa: E402 — the 3b fixtures
from test_orchestrator_dispatch import _digest, orch  # noqa: E402
import test_orchestrator_steering as st  # noqa: E402 — the fake GitHub
import _app_token  # noqa: E402

NOW = d.NOW
T0 = NOW.timestamp()
APP_ID, INSTALLATION = "123456", "98765"
SLUG = "pyautolabs-watcher"


def _b64decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def _claims(jwt_token: str) -> dict:
    return json.loads(_b64decode(jwt_token.split(".")[1]))


@pytest.fixture(scope="module")
def rsa_key(tmp_path_factory):
    """A throwaway 2048-bit key: (pem path, public key)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path_factory.mktemp("app") / "watcher.pem"
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                       serialization.PrivateFormat.TraditionalOpenSSL,
                                       serialization.NoEncryption()))
    return path, key.public_key()


def _verify(jwt_token: str, public_key) -> None:
    head, body, sig = jwt_token.split(".")
    public_key.verify(_b64decode(sig), f"{head}.{body}".encode(), padding.PKCS1v15(),
                      hashes.SHA256())   # raises when the signature is wrong


class FakeAPI:
    """`POST /app/installations/<id>/access_tokens` and `GET /app`. A token
    lives `ttl` s from the JWT's own clock (its `iat` + 60); `fail` refuses."""

    def __init__(self, fail=False, ttl=3600):
        self.calls, self.fail, self.ttl, self.minted = [], fail, ttl, 0

    def __call__(self, method, url, headers, body=None):
        self.calls.append((method, url, headers))
        assert headers["Authorization"].startswith("Bearer ")
        if self.fail:
            raise _app_token.AppTokenError(f"{method} {url} returned HTTP 401")
        now = _claims(headers["Authorization"][7:])["iat"] + 60
        if method == "POST" and url.endswith("/access_tokens"):
            self.minted += 1
            exp = _dt.datetime.fromtimestamp(now + self.ttl, _dt.timezone.utc)
            return {"token": f"ghs_fake{self.minted}",
                    "expires_at": exp.strftime("%Y-%m-%dT%H:%M:%SZ")}
        if (method, url) == ("GET", f"{_app_token.API}/app"):
            return {"slug": SLUG}
        raise AssertionError(f"unexpected API call {method} {url}")


def _app_env(key_path, **extra) -> dict:
    return {**os.environ, _app_token.APP_ID_ENV: APP_ID,
            _app_token.APP_INSTALLATION_ENV: INSTALLATION,
            _app_token.APP_KEY_ENV: str(key_path), **extra}


def _settings(key_path) -> dict:
    return _app_token.app_settings(_app_env(key_path))


# --- the JWT ------------------------------------------------------------------------

def test_the_jwt_claims_are_iss_iat_minus_60_and_exp_plus_9_minutes(rsa_key):
    path, public = rsa_key
    token = _app_token.make_jwt(APP_ID, str(path), now=1_000_000)
    assert json.loads(_b64decode(token.split(".")[0]))["alg"] == "RS256"
    assert _claims(token) == {"iss": APP_ID, "iat": 1_000_000 - 60, "exp": 1_000_000 + 540}
    _verify(token, public)


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")
def test_without_pyjwt_openssl_signs_the_same_claims_with_no_shell(rsa_key, monkeypatch):
    path, public = rsa_key
    monkeypatch.setitem(sys.modules, "jwt", None)          # `import jwt` now fails
    calls = []

    def run(argv, **kw):
        calls.append((argv, kw))
        return subprocess.run(argv, **kw)
    token = _app_token.make_jwt(APP_ID, str(path), now=2_000_000, run=run)
    assert calls and calls[0][0] == ["openssl", "dgst", "-sha256", "-sign", str(path)]
    assert "shell" not in calls[0][1]
    assert _claims(token) == {"iss": APP_ID, "iat": 2_000_000 - 60, "exp": 2_000_000 + 540}
    _verify(token, public)


def test_a_key_that_cannot_be_read_is_an_error_naming_no_secret(tmp_path):
    with pytest.raises(_app_token.AppTokenError, match="PYAUTO_SHIFT_APP_KEY"):
        _app_token.make_jwt(APP_ID, str(tmp_path / "absent.pem"), now=1)


# --- mint in memory, once a tick; a failure backs off ---------------------------------

def _files_holding(root: Path, secret: str) -> list[Path]:
    return [f for f in Path(root).rglob("*") if f.is_file()
            and secret.encode() in f.read_bytes()]


def test_the_token_is_minted_once_a_tick_in_memory_and_never_written(rsa_key, tmp_path):
    path, public = rsa_key
    api, state = FakeAPI(), tmp_path / "state"
    auth = _app_token.WatcherAuth(state, now=T0, environ=_app_env(path), request=api)
    assert api.calls == []                                  # nothing until a call needs it
    assert auth.env()["GH_TOKEN"] == "ghs_fake1"
    method, url, headers = api.calls[0]
    assert (method, url) == ("POST", f"{_app_token.API}/app/installations/{INSTALLATION}"
                                     "/access_tokens")
    jwt_token = headers["Authorization"][7:]
    _verify(jwt_token, public)
    assert _claims(jwt_token)["iss"] == APP_ID
    # Reused for the rest of the tick: no second mint.
    assert auth.env()["GH_TOKEN"] == auth.env()["GH_TOKEN"] == "ghs_fake1"
    assert api.minted == 1
    # Nothing on disk holds it (a worker runs as the same user).
    assert _files_holding(tmp_path, "ghs_fake") == []
    # The next tick mints its own.
    nxt = _app_token.WatcherAuth(state, now=T0 + 180, environ=_app_env(path), request=api)
    assert nxt.env()["GH_TOKEN"] == "ghs_fake2" and api.minted == 2


def test_a_failed_mint_records_only_a_time_and_reason_and_backs_off(rsa_key, tmp_path):
    path, _ = rsa_key
    api, state = FakeAPI(fail=True), tmp_path / "state"

    def auth(at):
        return _app_token.WatcherAuth(state, now=at, environ=_app_env(path), request=api)
    a = auth(T0)
    with pytest.raises(_app_token.AppTokenError, match="HTTP 401"):
        a.env()
    assert a.failed() and a.secrets() == set()
    rec = json.loads((state / _app_token.MINT_FAILURE_FILE).read_text())
    assert set(rec) == {"at", "error"} and rec["at"] == T0 and rec["error"].endswith("HTTP 401")
    assert sorted(f.name for f in state.iterdir()) == [_app_token.MINT_FAILURE_FILE]
    # Inside the back-off: no call at all, an error.
    n = len(api.calls)
    with pytest.raises(_app_token.AppTokenError, match="no new mint"):
        auth(T0 + 599).env()
    assert len(api.calls) == n
    # After it: tried again; a success removes the record and writes nothing.
    api.fail = False
    assert auth(T0 + 601).env()["GH_TOKEN"] == "ghs_fake1"
    assert list(state.iterdir()) == [] and _files_holding(tmp_path, "ghs_fake") == []


def test_in_app_mode_a_missing_token_raises_never_falls_back(rsa_key, tmp_path):
    path, _ = rsa_key
    a = _app_token.WatcherAuth(tmp_path, now=T0, environ=_app_env(path), request=FakeAPI())
    a._resolved = True                                      # resolved, yet no token
    with pytest.raises(_app_token.AppTokenError, match="no App installation token"):
        a.env()
    assert a.failed()


def test_the_app_login_is_its_slug_as_a_bot_never_gh_api_user(rsa_key, tmp_path,
                                                               monkeypatch):
    path, _ = rsa_key
    api = FakeAPI()
    monkeypatch.setattr(orch, "_AUTH", _app_token.WatcherAuth(
        tmp_path, now=T0, environ=_app_env(path), request=api))

    def no_gh(argv, **kw):
        raise AssertionError(f"gh called: {argv}")
    assert orch.gh_login(run=no_gh) == f"{SLUG}[bot]"
    assert [c[:2] for c in api.calls] == [("GET", f"{_app_token.API}/app")]
    # An App can never be the mentioned human: no self-mention warning.
    lines = _digest.worker_lines({"poster_login": f"{SLUG}[bot]",
                                  "mention_login": st.LOGIN})
    assert not any("will not notify" in ln for ln in lines)


# --- the watcher's calls: the App token, else nothing ---------------------------------

def _gh(gh: st.FakeGitHub, envs: list):
    def run(argv, **kw):
        envs.append(kw.get("env"))
        return gh(argv, **kw)
    return run


def _tick(brief, mind, home, minutes, claude, run, auth):
    return orch.tick(brief, mind, home=home, now=st._at(minutes), grace_s=0, auth=auth,
                     spawner=orch.RealSpawner(brief, "auto", run=claude),
                     agents=orch.AgentsView([]), tokens=lambda s: 0,
                     health=lambda u: "RUNNING", github=run, pr_state=lambda u: None,
                     poster=lambda i, b: orch.gh_comment(i, b, run=run))


def test_a_mint_failure_holds_every_write_and_never_uses_the_human_auth(
        rsa_key, tmp_path, monkeypatch):
    path, _ = rsa_key
    mind, brief, home, slot = st._shift(tmp_path, monkeypatch)
    claude, gh, envs = d.FakeClaude(), st.FakeGitHub(), []
    run, api = _gh(gh, envs), FakeAPI(fail=True)
    env = _app_env(path, GH_TOKEN="human-token-not-real")

    def auth(minutes):
        return _app_token.WatcherAuth(home, now=st._at(minutes).timestamp(), environ=env,
                                      request=api)
    r = _tick(brief, mind, home, 0, claude, run, auth(0))
    assert gh.calls == [] and envs == []                    # no read, no status, no gh at all
    assert r["github_auth"]["writes"] == "held" and "HTTP 401" in r["github_auth"]["error"]
    logged = json.loads((slot / orch.LOG_FILE).read_text().splitlines()[-1])
    assert logged["github_auth"]["writes"] == "held"
    assert orch.read_counters(slot)["github_auth"]["ticks"] == 1
    assert r["spawned"] == [{"task": "t1", "pid": 0}]      # the tick itself carried on

    # review-at: the digest is written and names the failure; its post is held
    # and costs no try.
    r = _tick(brief, mind, home, 151, claude, run, auth(151))
    assert r["action"] == "digest" and gh.calls == [] and envs == []
    digest = (slot / orch.DIGEST_FILE).read_text()
    assert "GitHub writes held — the watcher's App token could not be had" in digest
    marker = json.loads((slot / orch.DIGEST_MARKER).read_text())
    assert marker["state"] == "failed" and marker["tries"] == 0 and marker["unsent"]

    # The App recovers: the late sweep posts the digest as the App, and only so.
    api.fail = False
    r = _tick(brief, mind, home, 162, claude, run, auth(162))
    assert r["action"] == "late" and r["posts"]["digest"] == "posted"
    assert set(gh.calls) == {"create"} and len(envs) == len(gh.calls)   # + the correction
    assert all(e["GH_TOKEN"] == "ghs_fake1" and "GITHUB_TOKEN" not in e for e in envs)
    assert api.minted == 1                                  # one mint, reused within the tick
    assert _files_holding(tmp_path, "ghs_fake") == []       # no file holds the token
    assert json.loads((slot / orch.DIGEST_MARKER).read_text())["tries"] == 1


def test_an_app_configured_in_part_makes_no_call_at_all(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "_AUTH", _app_token.WatcherAuth(
        tmp_path, now=T0, environ={_app_token.APP_ID_ENV: APP_ID,
                                   orch.GH_TOKEN_ENV: "static-not-real"}))

    def no_gh(argv, **kw):
        raise AssertionError(f"gh called: {argv}")
    body = tmp_path / "b.md"
    body.write_text("x")
    res = orch.gh_comment(st.ISSUE, body, run=no_gh)
    assert res["posted"] is False and res["unsent"] and "partly configured" in res["error"]
    assert orch.gh_issue_comments(st.ISSUE, "", run=no_gh) is None
    assert orch.gh_comment_edit(f"{st.ISSUE}#issuecomment-1", body, run=no_gh)["edited"] \
        is False
    assert orch.gh_login(run=no_gh) is None


def test_the_static_token_stays_the_fallback_without_the_app(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "_AUTH", _app_token.WatcherAuth(
        tmp_path, now=T0, environ={orch.GH_TOKEN_ENV: "static-not-real"}))
    assert orch._gh_env()["GH_TOKEN"] == "static-not-real"
    monkeypatch.setattr(orch, "_AUTH", _app_token.WatcherAuth(tmp_path, now=T0, environ={}))
    assert orch._gh_env() is None                           # gh's own auth, as before


# --- never in a worker ---------------------------------------------------------------

def test_app_settings_and_minted_token_never_reach_a_worker_or_closeout(
        rsa_key, tmp_path, monkeypatch):
    path, _ = rsa_key
    home = tmp_path / "home"
    api = FakeAPI()
    env = _app_env(path)
    for key in _app_token.APP_ENVS:
        monkeypatch.setenv(key, env[key])
    monkeypatch.setenv(orch.GH_TOKEN_ENV, "static-not-real")
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_fake1")      # a minted token leaked into env
    monkeypatch.setenv("GH_TOKEN", "human-token-not-real")
    auth = _app_token.WatcherAuth(home, now=T0, request=api)
    auth.env()                                            # this tick's token, in memory
    monkeypatch.setattr(orch, "_AUTH", auth)
    mind, brief, _ = d._shift(tmp_path)
    claude = d.FakeClaude()
    sp = orch.RealSpawner(brief, "auto", run=claude)
    sp.spawn("t1", "draft/feature/pyautobrain/t1.md", tmp_path / "leases")
    sp.spawn_closeout("t1", "https://github.com/o/r/pull/1", "x.md", tmp_path / "leases")
    assert len(claude.calls) == 2
    for _argv, kw in claude.calls:
        wenv = kw["env"]
        assert not set(_app_token.APP_ENVS) & set(wenv)
        assert orch.GH_TOKEN_ENV not in wenv and "GITHUB_TOKEN" not in wenv
        assert not {"ghs_fake1", "static-not-real", str(path)} & set(wenv.values())
        assert wenv["GH_TOKEN"] == "human-token-not-real"
    assert api.minted == 1                                # stripping never mints again
