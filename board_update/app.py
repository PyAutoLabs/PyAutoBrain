"""Single-process, bounded-memory GitHub App OAuth/dispatch service.

Tokens never leave this process. Restarting signs users out; deploy one worker.
There is no generic workflow executor and no background dispatch or polling.
"""

import base64
import hashlib
import json
import os
import secrets
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from flask import Flask, abort, jsonify, make_response, redirect, render_template, request

from .targets import WORKFLOWS, workflow_url

COOKIE = "__Host-board-update"
SESSION_TTL = 8 * 60 * 60
COOLDOWN = 60


class GitHubError(Exception):
    def __init__(self, status=502):
        self.status = status


def github(method, path, token=None, data=None):
    """Fixed hosts, finite timeout; never return/log upstream bodies or tokens."""
    url = ("https://github.com/login/oauth/access_token" if path == "oauth"
           else "https://api.github.com" + path)
    headers = {"Accept": "application/json", "User-Agent": "PyAutoBoardUpdate",
               "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = None if data is None else json.dumps(data).encode()
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        with urlopen(Request(url, data=body, headers=headers, method=method), timeout=15) as r:
            raw = r.read(1024 * 1024)
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        raise GitHubError(exc.code) from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise GitHubError() from None


def create_app(config=None, api=github, clock=time.time):
    app = Flask(__name__)
    app.config.update(
        PUBLIC_URL=os.environ.get("BOARD_UPDATE_PUBLIC_URL", ""),
        BOARD_ORIGIN=os.environ.get("BOARD_UPDATE_BOARD_ORIGIN", "https://pyautolabs.github.io"),
        CLIENT_ID=os.environ.get("BOARD_UPDATE_CLIENT_ID", ""),
        CLIENT_SECRET=os.environ.get("BOARD_UPDATE_CLIENT_SECRET", ""),
        ALLOWED_USERS=os.environ.get("BOARD_UPDATE_ALLOWED_USERS", "").split(","),
        MAX_CONTENT_LENGTH=4096,
    )
    if config:
        app.config.update(config)
    for key in ("PUBLIC_URL", "BOARD_ORIGIN"):
        value = app.config[key]
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.path or parsed.query or parsed.fragment
                or value != value.strip() or "\\" in value
                or any(c.isspace() or ord(c) < 32 for c in value)):
            raise ValueError(f"{key} must be an HTTPS origin without a trailing slash")
    allowed = {u.strip().lower() for u in app.config["ALLOWED_USERS"] if u.strip()}
    if not allowed or not app.config["CLIENT_ID"] or not app.config["CLIENT_SECRET"]:
        raise ValueError("Configure GitHub App client credentials and allowed users")
    sessions, recent = {}, {}
    lock = threading.RLock()
    public = app.config["PUBLIC_URL"]

    def new_session():
        now = clock()
        with lock:
            for key in list(sessions):
                if sessions[key]["expires"] <= now:
                    del sessions[key]
            if len(sessions) >= 1000:
                abort(503)
            sid = secrets.token_urlsafe(32)
            sessions[sid] = {"expires": now + SESSION_TTL, "csrf": secrets.token_urlsafe(32)}
            return sid, sessions[sid]

    def current():
        with lock:
            session = sessions.get(request.cookies.get(COOKIE))
            if session and session["expires"] > clock():
                return session
        abort(401)

    def mutation():
        if request.headers.get("Origin") != public:
            abort(403)
        session = current()
        if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), session["csrf"]):
            abort(403)
        return session

    def set_cookie(response, sid):
        response.set_cookie(COOKIE, sid, max_age=SESSION_TTL, secure=True,
                            httponly=True, samesite="Lax", path="/")
        return response

    @app.after_request
    def headers(response):
        response.headers.update({
            "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        })
        return response

    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(403)
    @app.errorhandler(413)
    @app.errorhandler(503)
    def error(exc):
        return jsonify(error={400: "Invalid update request", 401: "Session expired; reopen Update",
                              403: "Update request denied", 413: "Request too large",
                              503: "Service busy; try later"}[exc.code]), exc.code

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/")
    def index():
        sid = request.cookies.get(COOKIE)
        with lock:
            session = sessions.get(sid)
            if not session or session["expires"] <= clock():
                sid, session = new_session()
            # Pending intent was set only by a CSRF-protected POST before OAuth.
            pending = session.pop("resume", "")
            response = make_response(render_template("update.html", csrf=session["csrf"],
                board_origin=app.config["BOARD_ORIGIN"], pending=pending))
        return set_cookie(response, sid)

    @app.post("/api/login")
    def login():
        session = mutation()
        body = request.get_json(silent=True)
        if (not isinstance(body, dict) or not isinstance(body.get("target"), str)
                or body["target"] not in WORKFLOWS):
            abort(400)
        with lock:
            state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
            session["oauth"] = {"state": state, "verifier": verifier,
                                "target": body["target"], "expires": clock() + 600}
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        return jsonify(url="https://github.com/login/oauth/authorize?" + urlencode({
            "client_id": app.config["CLIENT_ID"], "redirect_uri": public + "/oauth/callback",
            "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        }))

    @app.get("/oauth/callback")
    def callback():
        session = current()
        with lock:
            oauth = session.pop("oauth", None)
        if (not oauth or oauth["expires"] <= clock()
                or not secrets.compare_digest(request.args.get("state", ""), oauth["state"])
                or not request.args.get("code")):
            abort(403)
        try:
            result = api("POST", "oauth", data={"client_id": app.config["CLIENT_ID"],
                "client_secret": app.config["CLIENT_SECRET"], "code": request.args["code"],
                "redirect_uri": public + "/oauth/callback", "code_verifier": oauth["verifier"]})
            token = result.get("access_token")
            if not token:
                abort(403)
            user = api("GET", "/user", token=token).get("login", "").lower()
            if user not in allowed:
                abort(403)
        except GitHubError:
            return "GitHub sign-in failed. Close this window and retry Update.", 502
        with lock:
            sessions.pop(request.cookies.get(COOKIE), None)
            sid, session = new_session()
            session.update(token=token, user=user, resume=oauth["target"])
            session["expires"] = clock() + min(SESSION_TTL, int(result.get("expires_in", SESSION_TTL)))
        return set_cookie(redirect(public + "/"), sid)

    @app.post("/api/dispatch")
    def dispatch():
        session = mutation()
        body = request.get_json(silent=True)
        if (not isinstance(body, dict) or set(body) != {"target"}
                or not isinstance(body.get("target"), str) or body["target"] not in WORKFLOWS):
            abort(400)
        target = body["target"]
        if "token" not in session:
            return jsonify(login_required=True), 401
        # Serialize short requests: two tabs cannot race into two dispatches.
        with lock:
            now = clock()
            for key in list(recent):
                if now - recent[key][0] >= COOLDOWN:
                    del recent[key]
            key = (session["user"], target)
            if key in recent:
                return jsonify(**recent[key][1]), recent[key][2]
            url = workflow_url(target)
            try:
                repo = api("GET", f"/repos/PyAutoLabs/{target}", token=session["token"])
                if not repo.get("permissions", {}).get("push"):
                    abort(403)
                # A timeout can mean GitHub accepted the request: suppress retries too.
                uncertain = {"error": "GitHub acceptance is unknown. Check the workflow before retrying in one minute.", "url": url}
                recent[key] = (now, uncertain, 502)
                result = api("POST", f"/repos/PyAutoLabs/{target}/actions/workflows/{WORKFLOWS[target]}/dispatches",
                             token=session["token"], data={"ref": "main"})
                # Older API versions return 204; never invent a run-specific URL.
                run_url = result.get("html_url", "")
                prefix = f"https://github.com/PyAutoLabs/{target}/actions/runs/"
                if not (run_url.startswith(prefix) and run_url[len(prefix):].isdigit()):
                    run_url = url
                payload = {"queued": True, "url": run_url}
                recent[key] = (now, payload, 200)
                return jsonify(**payload)
            except GitHubError as exc:
                if exc.status == 401:
                    session.pop("token", None)
                    recent.pop(key, None)
                    return jsonify(login_required=True), 401
                if key not in recent:
                    return jsonify(error="GitHub permission check failed; update was not sent"), 502
                return jsonify(**recent[key][1]), recent[key][2]

    @app.post("/api/logout")
    def logout():
        mutation()
        with lock:
            sessions.pop(request.cookies.get(COOKIE), None)
        response = jsonify(signed_out=True)
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="Lax")
        return response

    return app
