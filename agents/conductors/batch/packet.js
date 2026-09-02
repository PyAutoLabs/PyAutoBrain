/* agents/conductors/batch/packet.js — the review packet's whole script.
 *
 * A near-verbatim port of the reference packet's script
 * (`PyAutoMind/batches/packets/2026-08-31-pm.html`), which the human has
 * already reviewed a slot through. Kept as a FILE, not a Python string: it is
 * full of `{`, `}` and `%`, and the renderer substitutes only the `%%TOKEN%%`
 * placeholders below by plain `str.replace`.
 *
 * Its two jobs: persist the human's review as they make it (chips, notes, the
 * Ruled ticks, the two header inputs), and assemble the parse-stable submit
 * markdown of `batches/packets/TEMPLATE.md` — the exact file the orchestrator
 * reads back at close-out. Every `localStorage` access sits inside a `try`,
 * because the packet is opened from Pages, from a file:// path and from inside
 * an artifact viewer, and two of those can throw on the accessor itself.
 *
 * ES5 on purpose: an archived packet must render in ten years with no build.
 */
(function () {
  "use strict";
  /* Versioned so a schema change orphans the old state rather than
   * half-reading it. Keyed by slot: one page, one review. */
  var KEY = "slot-review-%%SLOT%%-v1";
  var SLOT = "%%SLOT%%";
  var PACKET_PATH = "%%PACKET_PATH%%";
  var REVIEW_PATH = "%%REVIEW_PATH%%";
  var GITHUB_NEW = "%%GITHUB_NEW%%";
  var MEMBERS = %%MEMBERS_JSON%%;

  function readState() {
    var raw = null;
    try { raw = window.localStorage.getItem(KEY); } catch (e) { raw = null; }
    if (raw) {
      try {
        var parsed = JSON.parse(raw);
        if (parsed && typeof parsed === "object") { return parsed; }
      } catch (e) { /* corrupt or unreadable — start clean */ }
    }
    return { ruled: {}, decision: {}, note: {}, meta: {} };
  }

  var state = readState();
  state.ruled = state.ruled || {};
  state.decision = state.decision || {};
  state.note = state.note || {};
  state.meta = state.meta || {};

  /* Debounced: a note is typed a character at a time and a synchronous write
   * per keystroke is what makes a long note feel slow. */
  var saveTimer = null;
  function save() {
    if (saveTimer) { window.clearTimeout(saveTimer); }
    saveTimer = window.setTimeout(function () {
      try { window.localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* ok */ }
    }, 250);
  }

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function nowStamp() {
    var d = new Date();
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
      " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  var i;

  var progressEl = document.getElementById("progress-count");
  function updateProgress() {
    var ruled = 0, decided = 0;
    for (i = 0; i < MEMBERS.length; i++) {
      if (state.ruled[MEMBERS[i].id] === true) { ruled++; }
      if (state.decision[MEMBERS[i].id]) { decided++; }
    }
    if (progressEl) {
      progressEl.textContent = "Ruled " + ruled + " of " + MEMBERS.length +
        " · decisions " + decided + " of " + MEMBERS.length;
    }
  }

  var boxes = document.querySelectorAll("input[data-ruled]");
  for (i = 0; i < boxes.length; i++) {
    (function (box) {
      var id = box.getAttribute("data-ruled");
      var section = document.getElementById(id);
      if (state.ruled[id] === true) {
        box.checked = true;
        if (section) { section.classList.add("is-ruled"); }
      }
      box.addEventListener("change", function () {
        state.ruled[id] = box.checked;
        save();
        updateProgress();
        if (section) { section.classList.toggle("is-ruled", box.checked); }
      });
    }(boxes[i]));
  }

  var radios = document.querySelectorAll("input[data-decision]");
  for (i = 0; i < radios.length; i++) {
    (function (radio) {
      var id = radio.getAttribute("data-decision");
      if (state.decision[id] === radio.value) { radio.checked = true; }
      radio.addEventListener("change", function () {
        if (radio.checked) {
          state.decision[id] = radio.value;
          save();
          updateProgress();
        }
      });
    }(radios[i]));
  }

  function autogrow(area) {
    area.style.height = "auto";
    area.style.height = (area.scrollHeight + 2) + "px";
  }
  var notes = document.querySelectorAll("textarea[data-note]");
  for (i = 0; i < notes.length; i++) {
    (function (area) {
      var id = area.getAttribute("data-note");
      if (typeof state.note[id] === "string" && state.note[id]) {
        area.value = state.note[id];
      }
      autogrow(area);
      area.addEventListener("input", function () {
        state.note[id] = area.value;
        save();
        autogrow(area);
      });
    }(notes[i]));
  }

  var metas = document.querySelectorAll("input[data-meta]");
  for (i = 0; i < metas.length; i++) {
    (function (input) {
      var key = input.getAttribute("data-meta");
      if (typeof state.meta[key] === "string" && state.meta[key]) {
        input.value = state.meta[key];
      } else if (key === "reviewedAt") {
        input.value = nowStamp();
        state.meta[key] = input.value;
        save();
      }
      input.addEventListener("input", function () {
        state.meta[key] = input.value;
        save();
      });
    }(metas[i]));
  }

  updateProgress();

  /* The submit schema of `batches/packets/TEMPLATE.md`, exactly: the
   * orchestrator parses on these heading forms and these two `- key:` lines,
   * so nothing here is cosmetic. */
  function buildMarkdown() {
    var lines = [];
    lines.push("# Batch review " + SLOT);
    lines.push("");
    lines.push("- packet: " + PACKET_PATH);
    lines.push("- reviewed-at: " + (state.meta.reviewedAt || nowStamp()));
    lines.push("- review-minutes-actual: " + (state.meta.minutes || "(not given)"));
    lines.push("");
    for (var j = 0; j < MEMBERS.length; j++) {
      var m = MEMBERS[j];
      lines.push("## " + m.slug + " — " + m.health);
      lines.push("- decision: " + (state.decision[m.id] || "UNREVIEWED"));
      lines.push("- ruled: " + (state.ruled[m.id] === true ? "yes" : "no"));
      lines.push("");
      var note = (state.note[m.id] || "").replace(/\s+$/, "");
      lines.push(note ? note : "(no note)");
      lines.push("");
    }
    lines.push("## Follow-ups accepted");
    lines.push("<!-- orchestrator: fill from the tweak notes and the packet's proposed follow-ups -->");
    lines.push("");
    return lines.join("\n");
  }

  var modal = document.getElementById("submit-modal");
  var preview = document.getElementById("md-preview");
  var ghLink = document.getElementById("btn-github");
  var ghHint = document.getElementById("gh-hint");
  var copyBtn = document.getElementById("btn-copy");
  var dlBtn = document.getElementById("btn-download");
  var currentMd = "";

  function openModal() {
    currentMd = buildMarkdown();
    if (preview) { preview.textContent = currentMd; }
    if (ghLink) {
      var url = GITHUB_NEW + "?filename=" + encodeURIComponent(REVIEW_PATH) +
        "&value=" + encodeURIComponent(currentMd);
      /* GitHub's prefilled-new-file URL is the affordance that lands the review
       * without a copy-paste; past ~7,500 chars it silently truncates, which
       * would commit a review missing its last members. */
      if (!GITHUB_NEW) {
        /* The renderer found no GitHub home for this Mind (no origin remote,
         * no README link) and names none itself, so there is nothing to link. */
        ghLink.removeAttribute("href");
        ghLink.classList.add("is-disabled");
        ghLink.setAttribute("aria-disabled", "true");
        if (ghHint) {
          ghHint.textContent = "No GitHub home resolved for this Mind — use Copy, then paste into a new file at " + REVIEW_PATH + ".";
        }
      } else if (url.length > 7500) {
        ghLink.removeAttribute("href");
        ghLink.classList.add("is-disabled");
        ghLink.setAttribute("aria-disabled", "true");
        if (ghHint) {
          ghHint.textContent = "The review is too long for a prefilled GitHub URL — use Copy, then paste into a new file at " + REVIEW_PATH + ".";
        }
      } else {
        ghLink.setAttribute("href", url);
        ghLink.classList.remove("is-disabled");
        ghLink.removeAttribute("aria-disabled");
      }
    }
    if (modal) { modal.hidden = false; }
  }
  function closeModal() { if (modal) { modal.hidden = true; } }

  var submitBtn = document.getElementById("btn-submit");
  if (submitBtn) { submitBtn.addEventListener("click", openModal); }
  var closeBtn = document.getElementById("btn-close");
  if (closeBtn) { closeBtn.addEventListener("click", closeModal); }
  if (modal) {
    modal.addEventListener("click", function (ev) {
      if (ev.target === modal) { closeModal(); }
    });
  }
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") { closeModal(); }
  });

  function flash(btn, text) {
    var old = btn.textContent;
    btn.textContent = text;
    window.setTimeout(function () { btn.textContent = old; }, 2000);
  }

  if (copyBtn) {
    copyBtn.addEventListener("click", function () {
      var done = function () { flash(copyBtn, "Copied ✓"); };
      var fallback = function () {
        try {
          var ta = document.createElement("textarea");
          ta.value = currentMd;
          ta.setAttribute("readonly", "readonly");
          ta.style.position = "fixed";
          ta.style.left = "-9999px";
          document.body.appendChild(ta);
          ta.select();
          document.execCommand("copy");
          document.body.removeChild(ta);
          done();
        } catch (e) { flash(copyBtn, "Copy failed — select the preview"); }
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(currentMd).then(done, fallback);
      } else { fallback(); }
    });
  }

  if (dlBtn) {
    dlBtn.addEventListener("click", function () {
      try {
        var blob = new Blob([currentMd], { type: "text/markdown" });
        var a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = SLOT + "-review.md";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.setTimeout(function () { URL.revokeObjectURL(a.href); }, 5000);
      } catch (e) { flash(dlBtn, "Download blocked — use Copy"); }
    });
  }

  var links = document.querySelectorAll(".sidenav a[data-nav]");
  if (links.length && "IntersectionObserver" in window) {
    var map = {};
    var targets = [];
    for (i = 0; i < links.length; i++) {
      var key = links[i].getAttribute("data-nav");
      var el = document.getElementById(key);
      if (el) { map[key] = links[i]; targets.push(el); }
    }
    var visible = {};
    var observer = new IntersectionObserver(function (entries) {
      for (var j = 0; j < entries.length; j++) {
        visible[entries[j].target.id] = entries[j].isIntersecting;
      }
      var active = null;
      for (var k = 0; k < targets.length; k++) {
        if (visible[targets[k].id]) { active = targets[k].id; break; }
      }
      for (var key2 in map) {
        if (Object.prototype.hasOwnProperty.call(map, key2)) {
          map[key2].classList.toggle("active", key2 === active);
        }
      }
    }, { rootMargin: "-10% 0px -70% 0px", threshold: 0 });
    for (i = 0; i < targets.length; i++) { observer.observe(targets[i]); }
  }
}());
