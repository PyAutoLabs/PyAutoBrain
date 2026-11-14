"""The shift watcher's own GitHub identity: a minimal GitHub App (PyAutoBrain#630).

The watcher posts its comments (status, mentions, digest, correction) and reads
the shift issue's comments as its own App, `pyautolabs-watcher` — Issues
read/write on PyAutoMind only — so an @mention of the human notifies the human,
and nothing on the laptop holds bypass powers (it is NOT `pyautolabs-bot`, a
ruleset bypass actor with org-wide push). See `AGENTS.md` "The watcher's
GitHub identity".

Three settings, all or none:

- `PYAUTO_SHIFT_APP_ID` — the App id (the JWT issuer);
- `PYAUTO_SHIFT_APP_INSTALLATION_ID` — its installation on PyAutoMind's owner;
- `PYAUTO_SHIFT_APP_KEY` — the path of the App's private key (`.pem`).

With all three set, the watcher signs an RS256 JWT (PyJWT, else `openssl dgst`,
no shell), mints an installation token (`POST /app/installations/<id>/access_tokens`),
caches it with its `expires_at` in the watcher's state directory (mode 600) and
mints again when it is under `REFRESH_MARGIN_S` from expiry — about one mint an
hour. With none set, `PYAUTO_SHIFT_GH_TOKEN` (a static token) is the fallback,
and with neither, `gh`'s own auth, as before. When the App is configured but no
token can be had, the watcher's GitHub calls are not made at all: never the
human's `gh` auth in its place. No error message carries the key, a JWT or a token.

Runs under the systemd unit's `/usr/bin/python3` (3.10): standard library plus
an optional PyJWT.
"""

from __future__ import annotations

import base64
import datetime as _dt
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

APP_ID_ENV = "PYAUTO_SHIFT_APP_ID"
APP_INSTALLATION_ENV = "PYAUTO_SHIFT_APP_INSTALLATION_ID"
APP_KEY_ENV = "PYAUTO_SHIFT_APP_KEY"
APP_ENVS = (APP_ID_ENV, APP_INSTALLATION_ENV, APP_KEY_ENV)
#: The static fallback: a token given to the watcher's `gh` calls as `GH_TOKEN`.
GH_TOKEN_ENV = "PYAUTO_SHIFT_GH_TOKEN"

API = "https://api.github.com"
#: The cached installation token, in the watcher's state directory, mode 600.
CACHE_FILE = "app_token.json"
#: A cached token this close to its expiry is minted again.
REFRESH_MARGIN_S = 600
#: A token this close to expiry is not used even when a refresh fails.
MIN_USABLE_S = 60
#: After a failed mint, no new attempt for this long (a tick is ~3 min).
MINT_BACKOFF_S = 600
#: The JWT: back-dated for clock drift, and inside GitHub's 10-minute cap.
JWT_BACKDATE_S = 60
JWT_LIFETIME_S = 540


class AppTokenError(Exception):
    """No App token could be had; the message is safe to log (no secrets)."""


def app_settings(environ=None) -> dict | None:
    """The App's three settings; None when none is set. Some but not all set
    is a misconfiguration — an error, never a quiet fallback to another identity."""
    env = os.environ if environ is None else environ
    vals = {k: str(env.get(k, "") or "").strip() for k in APP_ENVS}
    if not any(vals.values()):
        return None
    missing = [k for k, v in vals.items() if not v]
    if missing:
        raise AppTokenError("the App is partly configured: " + ", ".join(missing)
                            + " unset")
    return {"app_id": vals[APP_ID_ENV], "installation_id": vals[APP_INSTALLATION_ENV],
            "key_path": vals[APP_KEY_ENV]}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def jwt_claims(app_id: str, now: float) -> dict:
    now = int(now)
    return {"iat": now - JWT_BACKDATE_S, "exp": now + JWT_LIFETIME_S, "iss": str(app_id)}


def _sign_openssl(message: bytes, key_path: str, run=None) -> bytes:
    """RS256 through `openssl dgst -sha256 -sign <key>` — an argv, no shell."""
    run = run or subprocess.run
    try:
        res = run(["openssl", "dgst", "-sha256", "-sign", str(key_path)], input=message,
                  capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        raise AppTokenError(f"openssl could not run ({type(e).__name__})") from None
    if res.returncode != 0 or not res.stdout:
        raise AppTokenError(f"openssl could not sign the JWT (is {APP_KEY_ENV} a PEM key?)")
    return res.stdout


def make_jwt(app_id: str, key_path: str, now: float | None = None, *,
             use_pyjwt: bool = True, run=None) -> str:
    """The App's JWT: `iat` = now − 60 s, `exp` = now + 9 min, `iss` = the App id.
    PyJWT when it imports, else `openssl`."""
    claims = jwt_claims(app_id, time.time() if now is None else now)
    if use_pyjwt:
        try:
            import jwt as _pyjwt
        except ImportError:
            _pyjwt = None
        if _pyjwt is not None:
            try:
                key = Path(key_path).read_text(encoding="utf-8")
            except OSError as e:
                raise AppTokenError(f"cannot read {APP_KEY_ENV} ({e.strerror})") from None
            try:
                token = _pyjwt.encode(claims, key, algorithm="RS256")
            except Exception as e:  # noqa: BLE001 — a bad key; never echo it
                raise AppTokenError(f"PyJWT could not sign the JWT ({type(e).__name__}; "
                                    f"is {APP_KEY_ENV} a PEM key?)") from None
            return token.decode("ascii") if isinstance(token, bytes) else token
    if not Path(key_path).is_file():
        raise AppTokenError(f"cannot read {APP_KEY_ENV} (no such file)")
    header = {"alg": "RS256", "typ": "JWT"}
    signing_input = (_b64url(json.dumps(header, separators=(",", ":")).encode()) + "."
                     + _b64url(json.dumps(claims, separators=(",", ":")).encode()))
    return signing_input + "." + _b64url(_sign_openssl(signing_input.encode("ascii"),
                                                       key_path, run=run))


def request(method: str, url: str, headers: dict, body: dict | None = None):
    """One GitHub API call (urllib); the decoded JSON. The fake-API seam."""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise AppTokenError(f"{method} {url} returned HTTP {e.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise AppTokenError(f"{method} {url} failed ({type(e).__name__})") from None


def _headers(jwt_token: str) -> dict:
    return {"Authorization": f"Bearer {jwt_token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "pyauto-shift-watcher"}


def _parse_ts(value: str) -> float:
    s = str(value or "").strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    t = _dt.datetime.fromisoformat(s)   # raises ValueError on anything else
    if t.tzinfo is None:
        t = t.replace(tzinfo=_dt.timezone.utc)
    return t.timestamp()


def mint(settings: dict, now: float, request=request, **jwt_kw) -> dict:
    """One installation token: `{"token", "expires_at"}` (GitHub's own expiry)."""
    jwt_token = make_jwt(settings["app_id"], settings["key_path"], now, **jwt_kw)
    res = request("POST", f"{API}/app/installations/{settings['installation_id']}"
                          "/access_tokens", _headers(jwt_token), None)
    token = (res or {}).get("token") if isinstance(res, dict) else None
    expires = (res or {}).get("expires_at") if isinstance(res, dict) else None
    if not token or not expires:
        raise AppTokenError("GitHub returned no installation token")
    try:
        _parse_ts(expires)
    except ValueError:
        raise AppTokenError("GitHub returned an unreadable expires_at") from None
    return {"token": token, "expires_at": expires}


def app_login(settings: dict, now: float, request=request, **jwt_kw) -> str:
    """The login the App's comments carry: `<slug>[bot]` (`GET /app`, with the JWT —
    `gh api user` does not answer for an installation token)."""
    jwt_token = make_jwt(settings["app_id"], settings["key_path"], now, **jwt_kw)
    res = request("GET", f"{API}/app", _headers(jwt_token), None)
    slug = (res or {}).get("slug") if isinstance(res, dict) else None
    if not slug:
        raise AppTokenError("GET /app returned no slug")
    return f"{slug}[bot]"


def _read_cache(path: Path) -> dict:
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return rec if isinstance(rec, dict) else {}


def _write_cache(path: Path, rec: dict) -> None:
    """Written mode 600 from creation, then renamed into place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, sort_keys=True)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def installation_token(settings: dict, cache_path: Path, now: float, request=request,
                       **jwt_kw) -> str:
    """The cached token while it has more than `REFRESH_MARGIN_S` left; else a
    fresh mint, cached. A failed refresh still uses a cached token with more
    than `MIN_USABLE_S` left; a failed mint backs off `MINT_BACKOFF_S`."""
    cache_path = Path(cache_path)
    rec = _read_cache(cache_path)
    same = (str(rec.get("app_id")) == settings["app_id"]
            and str(rec.get("installation_id")) == settings["installation_id"])
    left = None
    if same and rec.get("token"):
        try:
            left = _parse_ts(rec.get("expires_at", "")) - now
        except ValueError:
            left = None
    if left is not None and left > REFRESH_MARGIN_S:
        return rec["token"]
    failure = rec.get("failure") if same else None
    if isinstance(failure, dict) and now - float(failure.get("at", 0)) < MINT_BACKOFF_S:
        if left is not None and left > MIN_USABLE_S:
            return rec["token"]
        raise AppTokenError(f"{failure.get('error', 'mint failed')} (no new mint for "
                            f"{MINT_BACKOFF_S // 60} min after a failure)")
    try:
        minted = mint(settings, now, request=request, **jwt_kw)
    except AppTokenError as e:
        keep = {k: rec[k] for k in ("token", "expires_at") if same and k in rec}
        _write_cache(cache_path, {"app_id": settings["app_id"],
                                  "installation_id": settings["installation_id"],
                                  **keep, "failure": {"at": now, "error": str(e)}})
        if left is not None and left > MIN_USABLE_S:
            return rec["token"]
        raise
    _write_cache(cache_path, {"app_id": settings["app_id"],
                              "installation_id": settings["installation_id"],
                              "minted_at": now, **minted})
    return minted["token"]


class WatcherAuth:
    """Who the watcher's own `gh` calls run as, resolved lazily and at most once
    per tick: the App (`mode` "app"), the static token ("token"), or — with
    neither configured — `gh`'s own auth ("gh"). `error` is why an App
    configured could not be used this tick; then `env()` raises and no
    GitHub call is made."""

    def __init__(self, state_dir: Path, now: float | None = None, environ=None,
                 request=request, **jwt_kw):
        self.state_dir = Path(state_dir)
        self.now = time.time() if now is None else float(now)
        self.environ = os.environ if environ is None else environ
        self.request, self.jwt_kw = request, jwt_kw
        self.error: str | None = None
        self.token: str | None = None
        #: Whether a GitHub call wanted this identity (a failure is reported only then).
        self.used = False
        self._resolved = False
        try:
            self.settings = app_settings(self.environ)
        except AppTokenError as e:
            self.settings, self.error, self._resolved = {}, str(e), True
        static = str(self.environ.get(GH_TOKEN_ENV, "") or "").strip()
        self.mode = "app"   # configured, or partly configured (then `error` is set)
        if self.settings is None:
            self.mode = "token" if static else "gh"
            self.token, self._resolved = static or None, True

    @property
    def cache_path(self) -> Path:
        return self.state_dir / CACHE_FILE

    def _resolve(self) -> None:
        self.used = True
        if self._resolved:
            return
        self._resolved = True
        try:
            self.token = installation_token(self.settings, self.cache_path, self.now,
                                            request=self.request, **self.jwt_kw)
        except AppTokenError as e:
            self.error = str(e)
        except Exception as e:  # noqa: BLE001 — never a traceback that could carry a secret
            self.error = f"unexpected {type(e).__name__} minting the App token"

    def env(self) -> dict | None:
        """The environment for one watcher `gh` call; None means `gh`'s own auth
        (only when no identity is configured at all). Raises `AppTokenError`
        when the App is configured and no token can be had."""
        self._resolve()
        if self.error:
            raise AppTokenError(self.error)
        if self.token is None:
            return None
        env = {k: v for k, v in self.environ.items() if k != "GITHUB_TOKEN"} \
            if self.mode == "app" else dict(self.environ)
        env["GH_TOKEN"] = self.token
        return env

    def login(self) -> str | None:
        """The App's comment login, `<slug>[bot]`; None outside App mode or when
        it cannot be read (the caller then asks `gh api user`)."""
        if self.mode != "app" or not self.settings:
            return None
        try:
            return app_login(self.settings, self.now, request=self.request, **self.jwt_kw)
        except Exception:  # noqa: BLE001
            return None

    def failed(self) -> bool:
        """Whether an App was configured and is unusable — resolved first."""
        self._resolve()
        return bool(self.error)

    def secrets(self) -> set[str]:
        """Every token this identity holds or cached — stripped from workers."""
        out = {self.token} if self.token else set()
        tok = _read_cache(self.cache_path).get("token") if self.mode == "app" else None
        if tok:
            out.add(tok)
        return out
