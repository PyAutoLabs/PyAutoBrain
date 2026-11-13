// The write side of the Mind dashboard (PyAutoMind#565, design C).
//
// A ★ on a task row, or an edit in the Goals box, opens ONE small issue in the
// Mind repo, whose body is a fixed key: value form, then adds the
// `dashboard-input` label to it. The Mind's `dashboard_input.yml` (always the
// default branch's copy, run by the `issues: labeled` event) validates it,
// commits queue.md / goals.md, and closes and locks the issue with a one-line
// result comment. The page holds only a fine-grained token of a dedicated
// machine account (never the human's) with Issues permission on the Mind repo.
//
// The UI is optimistic: a tap flips at once, shows "pending", and turns into
// "confirmed" when the issue closes as applied (about 20-40 s), or reverts
// with the workflow's own reason. One issue is in flight at a time; taps made
// meanwhile are coalesced behind it (the latest state per task wins, a tap
// and its undo cancel out), so one device never makes the workflow drop a run.
//
// Inlined by `render_dashboard_html` into the page's one <script>, whose
// sha256 the page's CSP pins. No external script, no eval, no inline
// handlers. The pure half (MindEdit.*) touches no DOM so node can test it.
(function () {
  "use strict";

  var MindEdit = {};
  MindEdit.TOKEN_KEY = "pyautomind.dashboard.token.v1";
  MindEdit.LABEL = "dashboard-input";
  MindEdit.ISSUE_MARKER = "<!-- mind-dashboard-input v1 -->";
  MindEdit.BOT = "github-actions[bot]";
  MindEdit.API = "https://api.github.com";
  MindEdit.GOALS_MAX = 10;
  MindEdit.GOAL_TEXT_MAX = 200;
  // Mirrors scripts/dashboard_input.py: the workflow refuses anything else.
  var SEG = "[A-Za-z0-9_][A-Za-z0-9_.-]*";
  MindEdit.REF_RE = new RegExp("^(?:draft/" + SEG + "/" + SEG + "(?:/" + SEG +
    "){0,2}|active/" + SEG + ")\\.md$");
  MindEdit.REPO_RE = /^[A-Za-z0-9-]+\/[A-Za-z0-9._-]+$/;
  var GOAL_FORBIDDEN = /[`$<>\\|\u0000-\u0008\u000b-\u001f\u007f-\u009f​-‏‪-‮⁠-⁤﻿]/;
  var GOAL_MARKER = /^(?:\d+[.)]|[-*+]|#+)\s+/;

  MindEdit.basename = function (path) {
    var parts = String(path).split("/");
    return parts[parts.length - 1];
  };

  // queue.md's live entries, in file order: [{pos, label, kind, ref}].
  // Read as PyAutoBrain `_batch.read_queue` and `lifecycle.py` read it: a
  // fenced block is the schema's example, any heading ends an entry, and only
  // a numbered `## <n>.` heading starts one.
  MindEdit.parseQueue = function (text) {
    var out = [], cur = null, fenced = false;
    var lines = String(text).split("\n").concat(["#"]);
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      if (/^\s*```/.test(line)) { fenced = !fenced; continue; }
      if (fenced) continue;
      if (line.charAt(0) === "#") {
        if (cur) out.push(cur);
        var m = /^##\s+\d+\.\s+(.+?)\s*$/.exec(line);
        cur = m ? { pos: out.length + 1, label: m[1], kind: "", ref: "" } : null;
        continue;
      }
      if (!cur) continue;
      var f = /^-\s+(kind|ref):\s*(.+?)\s*$/.exec(line);
      if (f) cur[f[1]] = f[2].split("#")[0].trim();
    }
    return out;
  };

  // {basename: position} of every queued prompt.
  MindEdit.queuedNames = function (entries) {
    var map = {};
    entries.forEach(function (e) {
      if (e.kind === "prompt" && e.ref && !(MindEdit.basename(e.ref) in map))
        map[MindEdit.basename(e.ref)] = e.pos;
    });
    return map;
  };

  // goals.md's goals, top first, as plain strings.
  MindEdit.parseGoals = function (text) {
    var out = [], fenced = false, lines = String(text).split("\n");
    for (var i = 0; i < lines.length; i++) {
      if (/^\s*```/.test(lines[i])) { fenced = !fenced; continue; }
      if (fenced) continue;
      var m = /^##\s+\d+\.\s+(.+?)\s*$/.exec(lines[i]);
      if (m) out.push(m[1]);
    }
    return out;
  };

  // The Goals box's text as goals, or the reason the workflow would refuse it.
  MindEdit.validateGoals = function (raw) {
    var goals = [], lines = String(raw).replace(/\r\n/g, "\n").split("\n");
    if (String(raw).length > 4000) return { ok: false, error: "Too long." };
    for (var i = 0; i < lines.length; i++) {
      if (GOAL_FORBIDDEN.test(lines[i]))
        return { ok: false, error: "Line " + (i + 1) + ": goals cannot use ` $ < > \\ | or control characters." };
      var text = lines[i].replace(/\t/g, " ").trim().replace(GOAL_MARKER, "").trim().replace(/\s+/g, " ");
      if (!text) continue;
      if (text.length > MindEdit.GOAL_TEXT_MAX)
        return { ok: false, error: "Line " + (i + 1) + " is " + text.length + " characters; at most " + MindEdit.GOAL_TEXT_MAX + "." };
      goals.push(text);
    }
    if (goals.length > MindEdit.GOALS_MAX)
      return { ok: false, error: goals.length + " goals; at most " + MindEdit.GOALS_MAX + "." };
    return { ok: true, goals: goals };
  };

  // The issue for one op: the form scripts/dashboard_input.py parses.
  MindEdit.issueBody = function (op, nonce) {
    var lines = [MindEdit.ISSUE_MARKER, "op: " + op.op];
    if (op.op === "goals") {
      lines.push("goals:");
      op.goals.forEach(function (g) { lines.push("- " + g); });
    } else {
      lines.push("ref: " + op.ref);
    }
    lines.push("nonce: " + nonce);
    return lines.join("\n") + "\n";
  };
  MindEdit.issueRequest = function (op, nonce) {
    var what = op.op === "goals" ? "goals (" + op.goals.length + ")" :
      (op.op === "star" ? "★ " : "unstar ") + MindEdit.basename(op.ref).replace(/\.md$/, "");
    // No labels here: GitHub drops labels set at creation by an account
    // without push access. The label is added next, and that event runs.
    return { title: "dashboard: " + what, body: MindEdit.issueBody(op, nonce) };
  };

  // The workflow's one-line answer among an issue's comments:
  // {word: "applied" | "no change" | "refused" | "superseded", text}, or null.
  // Only the workflow's own bot counts; anyone else's comment is ignored.
  MindEdit.parseResult = function (comments) {
    for (var i = 0; i < (comments || []).length; i++) {
      var c = comments[i] || {};
      if (!c.user || c.user.login !== MindEdit.BOT) continue;
      var m = /^dashboard-input: (applied|no change|refused|superseded) \u2014 (.*)/.exec(String(c.body || ""));
      if (m) return { word: m[1], text: m[2].split("\n")[0].slice(0, 300) };
    }
    return null;
  };

  // Which queued taps one new tap replaces. Same task (or the goals): the new
  // one wins, and a star and its unstar cancel out entirely.
  MindEdit.opKey = function (op) {
    return op.op === "goals" ? "goals" : "ref:" + MindEdit.basename(op.ref);
  };
  MindEdit.coalesce = function (waiting, op) {
    var key = MindEdit.opKey(op), out = [], dropped = null;
    waiting.forEach(function (w) {
      if (!dropped && MindEdit.opKey(w) === key) dropped = w; else out.push(w);
    });
    if (dropped && op.op !== "goals" && dropped.op !== op.op) return { waiting: out, dropped: dropped, cancelled: true };
    if (dropped && op.op === "goals") op.previous = dropped.previous;
    out.push(op);
    return { waiting: out, dropped: dropped, cancelled: false };
  };

  if (typeof module !== "undefined" && module.exports) module.exports = MindEdit;
  if (typeof document === "undefined") return;

  // ------------------------------------------------------------------ DOM --
  var steer = document.getElementById("steer");
  if (!steer) return;
  var repo = steer.getAttribute("data-repo") || "";
  if (!MindEdit.REPO_RE.test(repo)) return;
  var framed = false;
  try { framed = window.top !== window.self; } catch (e) { framed = true; }

  var memoryToken = "";
  function getToken() {
    try { return window.localStorage.getItem(MindEdit.TOKEN_KEY) || memoryToken; }
    catch (e) { return memoryToken; }
  }
  function setToken(value) {
    memoryToken = value;
    try { window.localStorage.setItem(MindEdit.TOKEN_KEY, value); } catch (e) { /* tab only */ }
  }
  function forgetToken() {
    memoryToken = "";
    try { window.localStorage.removeItem(MindEdit.TOKEN_KEY); } catch (e) { /* nothing stored */ }
  }

  var toastEl = document.getElementById("steer-toast");
  var toastTimer = null;
  function toast(text, link) {
    if (!toastEl) return;
    toastEl.textContent = text;
    if (link && /^https:\/\/github\.com\//.test(link)) {
      var a = document.createElement("a");
      a.href = link; a.textContent = " Run ›"; a.rel = "noreferrer";
      toastEl.appendChild(a);
    }
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.hidden = true; }, link ? 12000 : 5000);
  }

  function api(path, opts) {
    opts = opts || {};
    var headers = { "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" };
    var token = opts.auth === false ? "" : getToken();
    if (token) headers.Authorization = "Bearer " + token;
    if (opts.body) headers["Content-Type"] = "application/json";
    if (opts.raw) headers.Accept = "application/vnd.github.raw+json";
    var url = /^https:\/\/api\.github\.com\//.test(path) ? path : MindEdit.API + path;
    return fetch(url, {
      method: opts.method || "GET", headers: headers, cache: "no-store",
      credentials: "omit", referrerPolicy: "no-referrer", mode: "cors",
      body: opts.body ? JSON.stringify(opts.body) : undefined
    });
  }

  // ---- connect panel -------------------------------------------------------
  var connect = document.getElementById("steer-connect");
  var input = document.getElementById("steer-token");
  var saveBtn = document.getElementById("steer-save");
  var forgetBtn = document.getElementById("steer-forget");
  var state = document.getElementById("steer-state");

  function connected() { return !!getToken() && !framed; }
  function refreshControls() {
    var on = connected();
    document.querySelectorAll("button.star, #steer-edit").forEach(function (b) {
      b.disabled = !on;
    });
    if (forgetBtn) forgetBtn.hidden = !getToken();
    if (state) state.textContent = framed ? "Writes are off inside a frame." :
      (on ? "Connected on this device." : "Not connected: ★ and goals are read-only.");
  }
  if (saveBtn) saveBtn.addEventListener("click", function () {
    var value = (input.value || "").trim();
    input.value = "";
    if (!/^(github_pat_|ghp_)[A-Za-z0-9_]{20,255}$/.test(value)) {
      toast("That does not look like a GitHub token.");
      return;
    }
    setToken(value);
    if (connect) connect.open = false;
    refreshControls();
    toast("Token saved on this device.");
  });
  if (forgetBtn) forgetBtn.addEventListener("click", function () {
    forgetToken();
    refreshControls();
    toast("Token forgotten on this device.");
  });

  // ---- stars ---------------------------------------------------------------
  var queueList = document.getElementById("steer-queue");
  function starsFor(name) {
    return Array.prototype.filter.call(document.querySelectorAll("button.star"),
      function (b) { return MindEdit.basename(b.getAttribute("data-ref")) === name; });
  }
  function markStar(name, on, pos, pending) {
    starsFor(name).forEach(function (b) {
      b.setAttribute("aria-pressed", on ? "true" : "false");
      b.setAttribute("aria-label", on ? "Unqueue this task" : "Queue this task");
      b.classList.toggle("pending", !!pending);
      var span = b.querySelector(".qpos");
      if (span) span.textContent = on && pos ? String(pos) : "";
    });
  }
  function renderQueue(entries) {
    if (!queueList) return;
    while (queueList.firstChild) queueList.removeChild(queueList.firstChild);
    entries.forEach(function (e) {
      var li = document.createElement("li");
      li.className = "task";
      li.setAttribute("data-ref", e.ref);
      var b = document.createElement("button");
      b.type = "button"; b.className = "star"; b.setAttribute("data-ref", e.ref);
      b.setAttribute("aria-pressed", "true");
      b.setAttribute("aria-label", "Unqueue this task");
      b.textContent = "★";
      var span = document.createElement("span"); span.className = "qpos";
      span.textContent = String(e.pos); b.appendChild(span);
      b.disabled = !connected();
      var p = document.createElement("p"); p.textContent = e.label;
      li.appendChild(b); li.appendChild(p);
      queueList.appendChild(li);
    });
    var empty = document.getElementById("steer-queue-empty");
    if (empty) empty.hidden = entries.length > 0;
  }
  function currentQueue() {
    if (!queueList) return [];
    return Array.prototype.map.call(queueList.querySelectorAll("li[data-ref]"), function (li, i) {
      var p = li.querySelector("p");
      return { pos: i + 1, label: p ? p.textContent : "", kind: "prompt", ref: li.getAttribute("data-ref") };
    });
  }
  function applyQueue(entries) {
    var names = MindEdit.queuedNames(entries);
    document.querySelectorAll("button.star").forEach(function (b) {
      var name = MindEdit.basename(b.getAttribute("data-ref"));
      if (pendingKeys["ref:" + name]) return;
      markStar(name, name in names, names[name], false);
    });
    renderQueue(entries.filter(function (e) { return e.kind === "prompt" && e.ref; }));
  }

  // ---- goals ---------------------------------------------------------------
  var goalsList = document.getElementById("steer-goals");
  var goalsEmpty = document.getElementById("steer-goals-empty");
  var editBtn = document.getElementById("steer-edit");
  var area = document.getElementById("steer-goals-text");
  var doneBtn = document.getElementById("steer-done");
  var shownGoals = goalsList ? Array.prototype.map.call(goalsList.querySelectorAll("li"),
    function (li) { return li.textContent; }) : [];
  function renderGoals(goals) {
    shownGoals = goals.slice();
    if (!goalsList) return;
    while (goalsList.firstChild) goalsList.removeChild(goalsList.firstChild);
    goals.forEach(function (g) {
      var li = document.createElement("li"); li.textContent = g; goalsList.appendChild(li);
    });
    if (goalsEmpty) goalsEmpty.hidden = goals.length > 0;
  }
  function closeEditor(save) {
    if (!area || area.hidden) return;
    var check = MindEdit.validateGoals(area.value);
    if (save && !check.ok) { toast(check.error); return; }
    area.hidden = true; if (doneBtn) doneBtn.hidden = true;
    if (goalsList) goalsList.hidden = false;
    if (!save || check.goals.join("\n") === shownGoals.join("\n")) return;
    var previous = shownGoals.slice();
    renderGoals(check.goals);
    if (goalsList) goalsList.classList.add("pending");
    enqueue({ op: "goals", goals: check.goals, previous: previous });
  }
  if (editBtn && area) {
    editBtn.addEventListener("click", function () {
      if (!connected()) return;
      area.value = shownGoals.join("\n");
      area.hidden = false; if (doneBtn) doneBtn.hidden = false;
      if (goalsList) goalsList.hidden = true;
      area.focus();
    });
    area.addEventListener("blur", function () { closeEditor(true); });
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "hidden") closeEditor(true);
    });
  }
  if (doneBtn) doneBtn.addEventListener("click", function () { area.blur(); });

  // ---- send: open the issue, then follow it ------------------------------
  var waiting = [], busy = false, pendingKeys = {};
  function holdKey(key, d) {
    pendingKeys[key] = (pendingKeys[key] || 0) + d;
    if (pendingKeys[key] <= 0) delete pendingKeys[key];
  }
  function enqueue(op) {
    var r = MindEdit.coalesce(waiting, op);
    waiting = r.waiting;
    if (r.dropped) holdKey(MindEdit.opKey(r.dropped), -1);
    if (r.cancelled) {
      // A tap and its undo before either was sent: nothing to send. An
      // un-star undone puts the entry back where it was.
      var name = MindEdit.basename(op.ref), entries = currentQueue();
      if (op.op === "star" && r.dropped.entry) {
        entries = entries.filter(function (e) { return MindEdit.basename(e.ref) !== name; });
        entries.splice(Math.max(0, r.dropped.entry.pos - 1), 0, r.dropped.entry);
        entries = entries.map(function (e, i) { e.pos = i + 1; return e; });
        renderQueue(entries);
      }
      entries.forEach(function (e) { markStar(MindEdit.basename(e.ref), true, e.pos, false); });
      if (op.op === "unstar") markStar(name, false, 0, false);
      return;
    }
    holdKey(MindEdit.opKey(op), 1);
    pump();
  }
  function pump() {
    if (busy || !waiting.length) return;
    busy = true;
    var op = waiting.shift();
    send(op).catch(function () { /* reported in send */ }).then(function () {
      holdKey(MindEdit.opKey(op), -1);
      busy = false;
      pump();
    });
  }

  function revert(op, why, link) {
    if (op.op === "goals") {
      renderGoals(op.previous);
      if (goalsList) goalsList.classList.remove("pending");
    } else {
      var name = MindEdit.basename(op.ref);
      markStar(name, op.op !== "star", op.pos, false);
      if (op.op === "star") renderQueue(currentQueue().filter(function (e) {
        return MindEdit.basename(e.ref) !== name;
      }).map(function (e, i) { e.pos = i + 1; return e; }));
      else if (op.entry) renderQueue(currentQueue().concat([op.entry]).map(function (e, i) {
        e.pos = i + 1; return e;
      }));
    }
    toast(why, link);
  }

  function confirmOp(op, word) {
    var same = word === "no change" ? " (already so)" : "";
    if (op.op === "goals") {
      if (goalsList) goalsList.classList.remove("pending");
      toast("Goals saved ✓" + same);
    } else {
      var name = MindEdit.basename(op.ref);
      starsFor(name).forEach(function (b) { b.classList.remove("pending"); });
      toast((op.op === "star" ? "★ queued ✓" : "Unqueued ✓") + same);
    }
  }

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function nonce() {
    var a = new Uint8Array(8);
    window.crypto.getRandomValues(a);
    return "d-" + Array.prototype.map.call(a, function (x) {
      return ("0" + x.toString(16)).slice(-2);
    }).join("");
  }

  function follow(number, op, link) {
    var started = Date.now();
    var base = "/repos/" + repo + "/issues/" + number;
    function poll() {
      return api(base).then(function (r) {
        if (!r.ok) throw new Error("issue status " + r.status);
        return r.json();
      }).then(function (issue) {
        if (issue.state !== "closed") {
          if (Date.now() - started > 180000) {
            toast("Still waiting for the Mind; it will land on its own.", link);
            return;
          }
          return sleep(4000).then(poll);
        }
        return api(base + "/comments?per_page=20").then(function (r) {
          return r.ok ? r.json() : [];
        }).then(function (comments) {
          var res = MindEdit.parseResult(comments);
          if (res && (res.word === "applied" || res.word === "no change")) confirmOp(op, res.word);
          else revert(op, res ? (res.word === "refused" ? "Refused: " : "Not applied: ") + res.text
            : "The issue was closed without a result.", link);
        });
      });
    }
    return sleep(5000).then(poll);
  }

  function send(op) {
    if (!connected()) { revert(op, "Not connected."); return Promise.resolve(); }
    return api("/repos/" + repo + "/issues", {
      method: "POST", body: MindEdit.issueRequest(op, nonce())
    }).then(function (r) {
      if (r.status === 401) {
        forgetToken(); refreshControls();
        if (connect) connect.open = true;
        revert(op, "GitHub rejected the token (expired or revoked). Paste a new one.");
        return;
      }
      if (r.status !== 201) {
        revert(op, "The token cannot open Mind issues (it needs Issues: read and write on the Mind repo; HTTP " + r.status + ").");
        return;
      }
      return r.json().then(function (issue) {
        var link = /^https:\/\/github\.com\//.test(issue.html_url || "") ? issue.html_url : "";
        if (typeof issue.number !== "number") { revert(op, "GitHub returned no issue number."); return; }
        var base = "/repos/" + repo + "/issues/" + issue.number;
        return api(base + "/labels", { method: "POST", body: { labels: [MindEdit.LABEL] } })
          .then(function (lr) { return lr.ok ? lr.json() : []; })
          .catch(function () { return []; })
          .then(function (labels) {
            var labelled = (labels || []).some(function (l) { return l && l.name === MindEdit.LABEL; });
            if (!labelled) {
              // No label, no run: close the stray issue rather than leave it open.
              api(base, { method: "PATCH", body: { state: "closed", state_reason: "not_planned" } });
              revert(op, "Could not add the dashboard-input label (the account needs Triage on the Mind repo), so nothing ran.", link);
              return;
            }
            return follow(issue.number, op, link);
          });
      });
    }).catch(function () {
      revert(op, "Network error: nothing was sent, or its result is unknown. Check the queue in a minute.");
    });
  }

  document.addEventListener("click", function (event) {
    var b = event.target.closest ? event.target.closest("button.star") : null;
    if (!b || b.disabled || !connected()) return;
    var ref = b.getAttribute("data-ref") || "";
    if (!MindEdit.REF_RE.test(ref)) { toast("This row cannot be queued."); return; }
    var name = MindEdit.basename(ref);
    var on = b.getAttribute("aria-pressed") !== "true";
    var entries = currentQueue();
    var op = { op: on ? "star" : "unstar", ref: ref };
    if (on) {
      var title = b.getAttribute("data-title") || name;
      entries.push({ pos: entries.length + 1, label: title, kind: "prompt", ref: ref });
      op.pos = entries.length;
    } else {
      op.entry = entries.filter(function (e) { return MindEdit.basename(e.ref) === name; })[0];
      op.pos = op.entry ? op.entry.pos : 0;
      entries = entries.filter(function (e) { return MindEdit.basename(e.ref) !== name; })
        .map(function (e, i) { e.pos = i + 1; return e; });
    }
    renderQueue(entries);
    entries.forEach(function (e) { markStar(MindEdit.basename(e.ref), true, e.pos, false); });
    markStar(name, on, on ? op.pos : 0, true);
    enqueue(op);
  });

  // ---- live state: the files on main, not the possibly-lagging Pages copy --
  function loadLive() {
    var base = "/repos/" + repo + "/contents/";
    api(base + "queue.md?ref=main", { raw: true, auth: false }).then(function (r) {
      return r.ok ? r.text() : null;
    }).then(function (text) {
      if (text !== null && !Object.keys(pendingKeys).some(function (k) { return k.indexOf("ref:") === 0; }))
        applyQueue(MindEdit.parseQueue(text));
    }).catch(function () { /* the rendered state stands */ });
    api(base + "goals.md?ref=main", { raw: true, auth: false }).then(function (r) {
      return r.ok ? r.text() : null;
    }).then(function (text) {
      if (text !== null && !pendingKeys.goals && (!area || area.hidden))
        renderGoals(MindEdit.parseGoals(text));
    }).catch(function () { /* the rendered state stands */ });
  }

  refreshControls();
  if (connected()) loadLive();
})();
