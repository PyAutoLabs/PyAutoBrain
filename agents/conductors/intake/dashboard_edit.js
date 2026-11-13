// The write side of the Mind dashboard (PyAutoMind#565, design B).
//
// A ★ on a task row, or an edit in the Goals box, dispatches the Mind's
// `dashboard_input.yml` workflow through the GitHub REST API. The workflow, not
// this page, validates the input and commits queue.md / goals.md. The page only
// holds a fine-grained token with Actions permission on the Mind repo, pasted
// once per device and kept in this browser.
//
// The UI is optimistic: a tap flips at once, shows "pending", and turns into
// "confirmed" when the run succeeds (about 20-40 s), or reverts with the
// workflow's own refusal reason.
//
// Inlined by `render_dashboard_html` into the page's one <script>, whose
// sha256 the page's CSP pins. No external script, no eval, no inline
// handlers. The pure half (MindEdit.*) touches no DOM so node can test it.
(function () {
  "use strict";

  var MindEdit = {};
  MindEdit.TOKEN_KEY = "pyautomind.dashboard.token.v1";
  MindEdit.WORKFLOW = "dashboard_input.yml";
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

  // The dispatch request body for one op.
  MindEdit.dispatchBody = function (op, nonce) {
    var inputs = { op: op.op, nonce: nonce };
    if (op.op === "goals") inputs.goals = op.goals.join("\n");
    else inputs.ref = op.ref;
    return { ref: "main", inputs: inputs, return_run_details: true };
  };

  // Ops on one task (or on the goals) run one after another, so a fast
  // star-unstar can never land in the wrong order. Different tasks run in
  // parallel: the workflow rebuilds on the tip of main and retries its push.
  MindEdit.opKey = function (op) {
    return op.op === "goals" ? "goals" : "ref:" + MindEdit.basename(op.ref);
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

  // ---- send: dispatch, then follow the run ---------------------------------
  var chains = {}, pendingKeys = {};
  function enqueue(op) {
    var key = MindEdit.opKey(op);
    pendingKeys[key] = (pendingKeys[key] || 0) + 1;
    chains[key] = (chains[key] || Promise.resolve()).then(function () {
      return send(op);
    }).catch(function () { /* reported in send */ }).then(function () {
      pendingKeys[key] -= 1;
      if (!pendingKeys[key]) delete pendingKeys[key];
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

  function confirmOp(op) {
    if (op.op === "goals") {
      if (goalsList) goalsList.classList.remove("pending");
      toast("Goals saved ✓");
    } else {
      var name = MindEdit.basename(op.ref);
      starsFor(name).forEach(function (b) { b.classList.remove("pending"); });
      toast(op.op === "star" ? "★ queued ✓" : "Unqueued ✓");
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

  function findRun(tag, since) {
    var path = "/repos/" + repo + "/actions/workflows/" + MindEdit.WORKFLOW +
      "/runs?event=workflow_dispatch&per_page=10&created=%3E%3D" +
      encodeURIComponent(since);
    var tries = 0;
    function look() {
      tries += 1;
      return api(path).then(function (r) { return r.ok ? r.json() : { workflow_runs: [] }; })
        .then(function (j) {
          var hit = (j.workflow_runs || []).filter(function (run) {
            return String(run.display_title || "").indexOf(tag) >= 0;
          })[0];
          if (hit) return hit.id;
          if (tries >= 10) throw new Error("run not found");
          return sleep(3000).then(look);
        });
    }
    return look();
  }

  function refusalReason(runId) {
    return api("/repos/" + repo + "/actions/runs/" + runId + "/jobs")
      .then(function (r) { return r.ok ? r.json() : { jobs: [] }; })
      .then(function (j) {
        var url = ((j.jobs || [])[0] || {}).check_run_url || "";
        if (!/^https:\/\/api\.github\.com\//.test(url)) return "";
        return api(url + "/annotations").then(function (r) { return r.ok ? r.json() : []; })
          .then(function (notes) {
            var hit = (notes || []).filter(function (n) {
              return n.title === "Dashboard input refused";
            })[0];
            return hit ? String(hit.message).slice(0, 300) : "";
          });
      }).catch(function () { return ""; });
  }

  function follow(runId, op) {
    var started = Date.now();
    function poll() {
      return api("/repos/" + repo + "/actions/runs/" + runId).then(function (r) {
        if (!r.ok) throw new Error("run status " + r.status);
        return r.json();
      }).then(function (run) {
        if (run.status !== "completed") {
          if (Date.now() - started > 180000) {
            toast("Still running; it will land on its own.", run.html_url);
            return;
          }
          return sleep(4000).then(poll);
        }
        if (run.conclusion === "success") { confirmOp(op); return; }
        return refusalReason(runId).then(function (why) {
          revert(op, why ? "Refused: " + why : "The workflow did not apply it (" + run.conclusion + ").",
            run.html_url);
        });
      });
    }
    return sleep(5000).then(poll);
  }

  function send(op) {
    if (!connected()) { revert(op, "Not connected."); return Promise.resolve(); }
    var tag = nonce();
    var since = new Date(Date.now() - 60000).toISOString().replace(/\.\d+Z$/, "Z");
    var path = "/repos/" + repo + "/actions/workflows/" + MindEdit.WORKFLOW + "/dispatches";
    var body = MindEdit.dispatchBody(op, tag);
    return api(path, { method: "POST", body: body }).then(function (r) {
      // An API that predates `return_run_details` refuses the unknown key:
      // send the plain dispatch and find the run by its nonce instead.
      if (r.status !== 422) return r;
      delete body.return_run_details;
      return api(path, { method: "POST", body: body });
    }).then(function (r) {
      if (r.status === 401) {
        forgetToken(); refreshControls();
        if (connect) connect.open = true;
        revert(op, "GitHub rejected the token (expired or revoked). Paste a new one.");
        return;
      }
      if (r.status === 403 || r.status === 404) {
        revert(op, "The token cannot run Mind workflows (it needs Actions: read and write on the Mind repo).");
        return;
      }
      if (r.status !== 200 && r.status !== 204) {
        revert(op, "GitHub refused the dispatch (HTTP " + r.status + ").");
        return;
      }
      var idp = r.status === 200 ? r.json().then(function (j) {
        return j.workflow_run_id || findRun(tag, since);
      }) : findRun(tag, since);
      return idp.then(function (id) { return follow(id, op); });
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
