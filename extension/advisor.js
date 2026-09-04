/*
 * advisor.js — the panel that watches you type and names the model to pick.
 *
 * Two variations, and they answer different questions.
 *
 *   SAVE  "what is the cheapest model that will still do this properly?"
 *         The reason most people install this. A greeting does not need the
 *         model you are paying frontier rates for, and nobody remembers that
 *         at the moment of typing "thanks".
 *
 *   BEST  "which model actually FITS this request?"
 *         Not the biggest — the one whose strengths match the job. A greeting
 *         still gets the fast model here, because a larger one would produce
 *         the same reply more slowly. That is what makes this advice rather
 *         than a rate card.
 *
 * Nothing is intercepted. Your message goes to Claude, or ChatGPT, or Gemini,
 * exactly as before; the page is untouched beyond one floating card, and the
 * only thing LANE sees is the draft text, on 127.0.0.1.
 *
 * Mechanics worth knowing:
 *
 * The composer is found by LISTENING rather than by selector. These are React
 * apps that rename their classes on a whim, so querySelector is a bet on
 * someone else's refactor; watching input events and reading whatever element
 * received them survives a redesign.
 *
 * The panel lives in a shadow root, so the host page's CSS cannot reach in and
 * nothing here leaks out.
 *
 * The running total counts messages SENT, never keystrokes. The panel
 * re-advises as you type; counting those would turn one message into forty and
 * make the headline number worthless.
 */

(() => {
  "use strict";
  if (window.__laneAdvisor) return;      // survive SPA re-injection
  window.__laneAdvisor = true;

  const DEBOUNCE_MS = 320;
  const MIN_WORDS = 3;

  const DEV_SITE =
    /^(127\.0\.0\.1|localhost)$/.test(location.hostname)
      ? new URLSearchParams(location.search).get("site")
      : null;

  const SITE = DEV_SITE ||
    (location.hostname.includes("claude") ? "claude" :
     location.hostname.includes("openai") || location.hostname.includes("chatgpt") ? "chatgpt" :
     location.hostname.includes("gemini") || location.hostname.includes("aistudio") ? "gemini" :
     null);
  if (!SITE) return;

  const SITE_NAME = { claude: "Claude", chatgpt: "ChatGPT", gemini: "Gemini" }[SITE];
  const BASE = DEV_SITE ? location.origin : "http://127.0.0.1:8080";

  let variation = "save";                // the user's choice, remembered
  const store = {
    get(k, dflt, cb) {
      try {
        if (!DEV_SITE && typeof chrome !== "undefined" && chrome.storage)
          return chrome.storage.local.get(k, (v) => cb((v || {})[k] ?? dflt));
        cb(localStorage.getItem("lane." + k) ?? dflt);
      } catch { cb(dflt); }
    },
    set(k, v) {
      try {
        if (!DEV_SITE && typeof chrome !== "undefined" && chrome.storage)
          return chrome.storage.local.set({ [k]: v });
        localStorage.setItem("lane." + k, v);
      } catch { /* a preference that will not persist is not an error */ }
    },
  };

  const money = (n) =>
    n <= 0 ? "free"
    : n < 0.001 ? "$" + n.toFixed(5)
    : n < 0.01 ? "$" + n.toFixed(4)
    : n < 1 ? "$" + n.toFixed(3)
    : "$" + n.toFixed(2);

  const esc = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  // ── the panel ────────────────────────────────────────────────────────────
  const host = document.createElement("div");
  host.id = "lane-advisor-host";
  host.style.cssText =
    "position:fixed;right:18px;bottom:18px;z-index:2147483600;" +
    "width:312px;pointer-events:none;";
  const root = host.attachShadow({ mode: "open" });

  root.innerHTML = `
<style>
${LaneUI.css}

/* Only what is genuinely particular to this panel. Everything structural -
   the card, the rows, the buttons, the pills, the type scale - comes from
   ui.js, so the panel, the search card and the launcher are recognisably the
   same object rather than three that happen to share a colour. */

/* The same mark as the search card and the toolbar, so all three read as one
   product rather than three that happen to share a colour. */
.logo { display: flex; color: var(--l-accent); }
.logo svg { width: 15px; height: 15px; display: block; }

.pick { margin-top: var(--l-3); }
.headline { margin-top: 5px; font-size: 12px; }
.headline.save { color: var(--l-good); font-weight: 600; }

.alts { width:100%; margin-top: var(--l-3); border-collapse: collapse;
        font-size: 11px; color: var(--l-dim); }
.alts td { padding: 3px 0; }
/* Wide enough for PERFORMANCE, which is the longest label and was running
   into the model name beside it. */
.alts td.m { width: 82px; padding-right: 6px; }
.alts td.n { padding-right: 4px; }
.alts tr.on td { color: var(--l-ink); font-weight: 600; }

.favs { margin-top: var(--l-3); padding-top: var(--l-3);
        border-top: 1px solid var(--l-line);
        display: flex; gap: 5px; align-items: center; flex-wrap: wrap; }

.why { margin-top: var(--l-3); padding-top: var(--l-3);
       border-top: 1px solid var(--l-line); }

.setup { margin-top: var(--l-3); display: flex; gap: 9px;
         align-items: flex-start; padding: 9px 10px;
         border-radius: var(--l-r-md); background: var(--l-sunk); }
.setup .ico { flex: none; color: var(--l-dim); display: flex; margin-top: 1px; }
.setup .ico svg { width: 14px; height: 14px; display: block; }
.setup button { display: block; text-align: left; }

.useout { margin-top: 6px; font-size: 11px; color: var(--l-dim);
          min-height: 15px; }

.gone { margin-top: var(--l-3); padding-top: var(--l-3);
        border-top: 1px solid var(--l-line); }
.go { display:flex; align-items:baseline; gap: var(--l-2); margin-top: 6px;
      font-size: 12px; }
.go .site { font-weight: 620; }
.go .mdl  { color: var(--l-dim); flex: 1; }

.score { border-top: 1px solid var(--l-line); background: var(--l-panel);
         padding: 8px var(--l-3); font-size: 11px; color: var(--l-dim);
         display: flex; align-items: baseline; gap: 6px; }
.score b { color: var(--l-good); font-size: 12px; }
.score .n { margin-left: auto; color: var(--l-faint); }

.card { transform: translateY(6px); opacity: 0;
        transition: transform .16s cubic-bezier(.2,.7,.3,1), opacity .16s ease; }
.card.show { transform: none; opacity: 1; }
</style>
<div class="l-card card" id="card">
  <div class="l-head">
    <span class="logo">${LaneUI.icons.mark}</span>
    <span class="l-brand">LANE</span>
    <span class="l-grow"></span>
    <div class="l-seg" id="seg" role="group" aria-label="What to optimise for">
      <button data-v="save" aria-pressed="true"  title="Cheapest model that still does the job">SAVE</button>
      <button data-v="best" aria-pressed="false" title="Model whose strengths fit this request">BEST</button>
    </div>
    <button class="l-icon" id="close" title="Hide until next reload"
            aria-label="Hide">${LaneUI.icons.close}</button>
  </div>
  <div id="content"></div>
  <div class="score" id="score" style="display:none"></div>
</div>`;

  document.documentElement.appendChild(host);

  const card = root.getElementById("card");
  const content = root.getElementById("content");
  const scoreEl = root.getElementById("score");
  let dismissed = false;
  let last = null;                       // the advice currently on screen

  root.getElementById("close").addEventListener("click", () => {
    dismissed = true;
    hide();
  });

  root.getElementById("seg").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    setVariation(b.dataset.v);
    if (lastText) advise(lastText);      // re-ask immediately, same message
  });

  function setVariation(v) {
    variation = v;
    for (const b of root.getElementById("seg").children)
      b.setAttribute("aria-pressed", String(b.dataset.v === v));
    store.set("variation", v);
  }
  store.get("variation", "save", (v) => setVariation(v === "best" ? "best" : "save"));

  const show = () => card.classList.add("show");
  const hide = () => card.classList.remove("show");


  /* ── taking the suggestion ────────────────────────────────────────────────
   *
   * The panel spent its whole life so far naming a model and then leaving the
   * person to go and find it. That is the hole the product leaks out of:
   * advice you have to act on by hand is advice most people scroll past. This
   * closes it — one click and the page is on the model that was suggested.
   *
   * Finding somebody else's dropdown is the hard part, and it is done by
   * BEHAVIOUR rather than by selector. These pages are React apps whose class
   * names change weekly, so the search looks for what a model picker
   * unavoidably is: a small clickable thing whose visible text is the name of
   * a model. That survives a redesign; `.model-selector-button` does not.
   *
   * When it cannot find one it says so and copies the name instead, which is
   * still better than nothing and is honest about having failed. Silently
   * doing nothing would be the worst outcome — the person would believe they
   * had switched.
   */

  // Words that only appear in a model name. Used to recognise a picker, so it
  // must stay short: something matching ordinary page text would turn any
  // button into a candidate.
  const MODEL_WORDS = /\b(opus|sonnet|haiku|gpt-?\s?\d|gemini|claude|o\d\s?mini|flash|pro)\b/i;

  const norm = (t) => String(t || "").toLowerCase()
    .replace(/[^a-z0-9.]+/g, " ").replace(/\s+/g, " ").trim();

  /* Does this element's text name the model we want?
   * Compared on the distinctive part: the site may show "Sonnet 5" where the
   * catalog says "Claude Sonnet 5", and the shared word "claude" must not be
   * what makes them match. */
  function namesModel(text, target) {
    const a = norm(text), b = norm(target);
    if (!a || !b) return false;
    if (a === b || a.includes(b) || b.includes(a)) return true;
    const key = b.split(" ").filter((w) => !["claude", "gpt", "gemini"].includes(w));
    return key.length > 0 && key.every((w) => a.includes(w));
  }

  function findPicker() {
    const nodes = document.querySelectorAll(
      'button, [role="combobox"], [role="button"], [aria-haspopup]');
    const found = [];
    for (const el of nodes) {
      const text = (el.innerText || el.textContent || "").trim();
      if (!text || text.length > 40) continue;      // a paragraph is not a picker
      if (!MODEL_WORDS.test(text)) continue;
      const box = el.getBoundingClientRect();
      if (!box.width || !box.height) continue;      // hidden
      found.push({ el, text, area: box.width * box.height });
    }
    // The smallest match is the most likely: a picker is a compact control,
    // while a big container that happens to contain the model name is not.
    found.sort((a, b) => a.area - b.area);
    return found.length ? found[0] : null;
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  /* Bounded by the CLOCK, not by a count of sleeps.
   *
   * A background or hidden tab throttles setTimeout to roughly once a second,
   * so a 12-try loop with a 70ms sleep is 840ms in a focused tab and twelve
   * seconds in an unfocused one - and the person watching sees a button stuck
   * on "switching..." with no way to tell whether it is working. A deadline
   * gives the same short wait either way. */
  async function findOption(target, budgetMs = 1500) {
    const deadline = Date.now() + budgetMs;
    for (;;) {
      const opts = document.querySelectorAll(
        '[role="option"], [role="menuitem"], [role="menuitemradio"], li');
      for (const o of opts) {
        const text = (o.innerText || o.textContent || "").trim();
        if (text && text.length < 60 && namesModel(text, target)) return o;
      }
      if (Date.now() >= deadline) return null;
      await sleep(70);                              // menus render late
    }
  }

  /* Put the page back exactly as it was found.
   *
   * Toggling the trigger a second time is not enough: plenty of these menus
   * close on Escape or on an outside click and treat a second trigger click as
   * a re-open. Leaving somebody's model dropdown hanging open over their
   * conversation is the most visible way this feature can misbehave, so all
   * three are tried and the result is checked. */
  async function closeMenu(picker) {
    const open = () => document.querySelector(
      '[role="listbox"], [role="menu"], [aria-expanded="true"]');
    if (!open()) return true;

    const esc = (el) => el.dispatchEvent(new KeyboardEvent("keydown", {
      key: "Escape", code: "Escape", keyCode: 27, which: 27, bubbles: true }));

    // Every attempt is fired first, and only then is anything awaited.
    //
    // The earlier version slept between attempts, which in a throttled tab
    // meant a full second each and the deadline expiring before the last one
    // was ever tried - so the fallback that actually works never ran. These
    // are cheap synchronous events; there is no reason to pace them.
    const attempts = [
      () => esc(picker.el),
      () => esc(document.activeElement || document.body),
      () => esc(document.body),
      () => picker.el.click(),
      () => document.body.dispatchEvent(
        new MouseEvent("click", { bubbles: true })),
    ];
    for (const attempt of attempts) {
      try { attempt(); } catch (e) { /* try the next one */ }
      if (!open()) return true;
    }

    // Give the page one frame to react to whichever of those it honoured.
    await sleep(120);
    return !open();
  }

  async function applyModel(target) {
    const picker = findPicker();
    if (!picker) return { ok: false, why: "no model picker found on this page" };

    if (namesModel(picker.text, target))
      return { ok: true, already: true };

    picker.el.click();
    const option = await findOption(target);
    if (!option) {
      await closeMenu(picker);
      return { ok: false, why: target + " is not in this page's list" };
    }
    option.click();
    await sleep(220);
    await closeMenu(picker);

    const after = findPicker();
    if (after && namesModel(after.text, target)) return { ok: true };
    return { ok: false, why: "clicked it, but the page did not switch" };
  }

  /* Best-effort, and on a leash. navigator.clipboard.writeText never settles
     when the document is not focused - it does not reject, it simply hangs -
     so awaiting it plainly left the button reading "switching..." forever, on
     the one path where something had already gone wrong. */
  function copyName(name) {
    return Promise.race([
      navigator.clipboard.writeText(name).then(function () { return true; })
        .catch(function () { return false; }),
      new Promise(function (r) { setTimeout(function () { r(false); }, 600); }),
    ]);
  }

  /* Starred models, offered whatever the classifier decided.
   *
   * The advice is a recommendation, not a ruling. Somebody who always reaches
   * for one model should be one click from it, and having to disagree with the
   * panel by going around it is how a panel gets dismissed. */
  function favouriteRow(recommendedId) {
    if (!profile) return "";
    const favs = LaneProfile.favourites(profile)
      .filter((id) => id !== recommendedId)
      .map((id) => LaneCore.MODELS.find((m) => m.id === id))
      .filter(Boolean)
      .slice(0, 3);
    if (!favs.length) return "";
    return `<div class="favs" id="favs">
      <span class="l-label">Yours</span>
      ${favs.map((m) => `<button class="l-btn" style="padding:3px 9px;font-size:11px"
        data-fav="${esc(m.id)}"
        data-fav-name="${esc(m.display)}">${esc(m.display)}</button>`).join("")}
    </div>`;
  }

  function header(a) {
    const tokens = a.kind === "image"
      ? "priced per image"
      : "~" + a.est_in + " in · ~" + Number(a.est_out).toLocaleString() + " out";
    return `
      <div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap">
        <span class="l-pill l-pill--${esc(a.lane)}">${esc(a.lane_label)}</span>
        <span class="l-micro l-num">${tokens}</span>
      </div>`;
  }

  function renderElsewhere(a) {
    const rows = (a.elsewhere || []).slice(0, 3).map((e) => `
      <div class="go">
        <span class="site">${esc(e.site)}</span>
        <span class="mdl">${esc(e.display)}</span>
        <span class="l-num">${money(e.cost)}</span>
      </div>`).join("");
    content.innerHTML = `
      <div class="l-pad">
        ${header(a)}
        <div class="gone">
          <div class="l-label l-alert">${esc(a.site_name)} can't do this</div>
          ${rows}
        </div>
        <div class="why l-sub">${esc(a.explain)}</div>
      </div>`;
    show();
  }

  function renderAdvice(a) {
    const rec = a.recommend || {};
    const rows = (a.options || []).map((o) => `
      <tr class="${o.id === rec.id ? "on" : ""}">
        <td class="m l-label" style="font-size:9px">${esc(o.mode)}</td>
        <td>${esc(o.display)}</td>
        <td class="l-num" style="text-align:right;white-space:nowrap">${money(o.cost)}</td>
      </tr>`).join("");

    // SAVE leads with the money; BEST leads with why this model suits the job.
    // Same data, different question, so a different headline.
    let headline;
    if (a.variation === "best") {
      headline = a.fit
        ? `<div class="headline l-sub">${esc(a.fit)}</div>`
        : `<div class="headline l-sub">the strongest fit available to you</div>`;
    } else if (a.is_top) {
      // a.explain already says this, and in more useful words. Two
      // sentences that mean the same thing read as padding.
      headline = "";
    } else {
      headline = `<div class="headline save">saves ${money(a.saving)} · ${a.factor}× cheaper than ${esc((a.top || {}).display)}</div>`;
    }

    content.innerHTML = `
      <div class="l-pad">
        ${header(a)}
        <div class="pick">
          <div class="l-label">${a.variation === "best" ? "Best fit on" : "Cheapest that fits on"} ${esc(SITE_NAME)}</div>
          <div style="display:flex;align-items:baseline;gap:8px;margin-top:3px">
            <span class="l-lead" style="flex:1">${esc(rec.display)}</span>
            <span class="l-num" style="font-size:13px;font-weight:600">${money(rec.cost)}</span>
          </div>
          ${headline}
          <button class="l-btn l-btn--primary l-btn--block" id="use"
                  style="margin-top:10px">
            Use ${esc(rec.display)} ${LaneUI.icons.arrow}
          </button>
          <div class="useout" id="useout"></div>
        </div>
        ${rows ? `<table class="alts">${rows}</table>` : ""}
        ${favouriteRow(rec.id)}
        <div class="why l-sub">${esc(a.explain)}</div>
        ${a.assuming_all ? `<div class="setup">
           <span class="ico">${LaneUI.icons.gear}</span>
           <span>
             <button class="l-btn--link" id="setupLink">Which models do you have?</button>
             <span class="l-micro" style="display:block;margin-top:1px">
               Guessing from all ${LaneCore.MODELS.length} until you say.
             </span>
           </span>
         </div>` : ""}
      </div>`;

    const setupLink = root.getElementById("setupLink");
    if (setupLink) setupLink.addEventListener("click", () => {
      try {
        if (typeof chrome !== "undefined" && chrome.runtime
            && chrome.runtime.sendMessage) {
          chrome.runtime.sendMessage({ type: "lane:open-setup" });
          return;
        }
      } catch (e) { /* fall through */ }
      window.open(BASE.replace(/\/$/, "") + "/dev/ext/onboarding.html", "_blank");
    });

    const favRow = root.getElementById("favs");
    if (favRow) {
      for (const b of favRow.querySelectorAll("[data-fav]")) {
        b.addEventListener("click", async () => {
          const name = b.dataset.favName;
          const out = root.getElementById("useout");
          out.className = "useout";
          out.textContent = "switching\u2026";
          const r = await applyModel(name);
          out.className = "useout " + (r.ok ? "ok" : "bad");
          out.textContent = r.ok
            ? (r.already ? "already on " + name : "switched to " + name)
            : r.why;
        });
      }
    }

    const use = root.getElementById("use");
    if (use) use.addEventListener("click", async () => {
      const out = root.getElementById("useout");
      use.disabled = true;
      out.className = "useout";
      out.textContent = "switching\u2026";
      const r = await applyModel(rec.display);
      use.disabled = false;
      if (r.ok) {
        out.className = "useout ok";
        out.textContent = r.already
          ? "already on " + rec.display
          : "switched to " + rec.display;
      } else {
        // The reason goes up FIRST. Everything after it is a nicety, and
        // a nicety must never be what stands between somebody and being
        // told that their click did nothing.
        out.className = "useout bad";
        out.textContent = r.why;
        if (await copyName(rec.display)) {
          out.textContent = r.why + " \u2014 name copied instead";
        }
      }
    });
    show();
  }

  function renderOffline() {
    content.innerHTML = `
      <div class="l-pad l-sub">
        LANE is not running. Start it with <code>lane serve</code> and this
        panel will pick up on its own.<br><br>
        First time? Open <a href="${BASE}/setup" target="_blank"
        rel="noreferrer">${BASE.replace(/^https?:\/\//, "")}/setup</a> to say
        which models you can actually use.
      </div>`;
    show();
  }

  /* The scoreboard. Deliberately says "could have saved": LANE cannot see
     which model you actually picked, and a tool that counts its own advice as
     though it were always taken is flattering itself with the very number it
     is selling on. */
  let serverPresent = false;

  async function refreshScore() {
    if (!serverPresent) { scoreEl.style.display = "none"; return; }
    try {
      const s = await (await fetch(BASE + "/lane/advice-stats")).json();
      if (!s.messages) { scoreEl.style.display = "none"; return; }
      scoreEl.style.display = "flex";
      scoreEl.innerHTML =
        `could have saved <b>${money(s.potential_saving)}</b>` +
        `<span class="n">${s.messages} message${s.messages === 1 ? "" : "s"}</span>`;
    } catch { scoreEl.style.display = "none"; }
  }

  // ── reading the composer ─────────────────────────────────────────────────
  function textOf(el) {
    if (!el) return "";
    if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") return el.value || "";
    if (el.isContentEditable) return el.innerText || "";
    return "";
  }

  function isComposer(el) {
    if (!el) return false;
    if (el.tagName === "INPUT" && el.type !== "text" && el.type !== "search")
      return false;
    return el.tagName === "TEXTAREA" || el.tagName === "INPUT" ||
           el.isContentEditable;
  }

  let timer = null, lastText = "";

  function onType(e) {
    if (dismissed || !isComposer(e.target)) return;
    const text = textOf(e.target).trim();

    if (text.split(/\s+/).filter(Boolean).length < MIN_WORDS) {
      hide();
      lastText = "";
      last = null;
      return;
    }
    if (text === lastText) return;

    clearTimeout(timer);
    lastText = text;
    timer = setTimeout(() => advise(text), DEBOUNCE_MS);
  }

  /* The advice is worked out HERE, in the page, with no server involved.
   *
   * This is the difference between a tool people use and a tool people would
   * have used. Asking somebody to clone a repository, install Python and keep a
   * terminal open before they see their first suggestion loses almost all of
   * them at step one, and nothing downstream of that matters if nobody gets
   * past it.
   *
   * A local LANE, when one happens to be running, still adds the running
   * savings total and the model selection from the setup page. Neither is
   * required, and neither failing is allowed to stop the advice appearing. */
  async function advise(text) {
    let a;
    try {
      a = LaneCore.advise(text, SITE, variation, allowedModels);
    } catch (e) {
      last = null;
      return;                        // never take the host page down with us
    }
    last = a;
    if (a.unavailable_here) renderElsewhere(a);
    else renderAdvice(a);
    refreshScore();
  }

  /* What this person told us, which is what makes the advice about them.
   *
   * The profile is the primary source and needs nothing running. A local LANE,
   * if there is one, only fills in what the browser cannot know on its own -
   * the running savings total, and a model selection made on its setup page by
   * somebody who prefers that screen to the interview. */
  let allowedModels = null;
  let profile = null;

  async function loadProfile() {
    try {
      profile = await LaneProfile.load();
      allowedModels = LaneProfile.allowed(profile);
      if (profile.variation) setVariation(
        profile.variation === "best" ? "best" : "save");
    } catch (e) { profile = null; }
  }

  async function loadLocalPreferences() {
    try {
      const r = await fetch(BASE + "/lane/setup-state", { cache: "no-store" });
      if (!r.ok) return;
      const state = await r.json();
      // Only defer to the server when the browser has nothing of its own; an
      // answer somebody gave in the interview should not be overwritten by a
      // setting on a machine they may have forgotten about.
      if (state.explicit_selection && !allowedModels) {
        allowedModels = state.models.filter((m) => m.enabled).map((m) => m.id);
      }
      serverPresent = true;
    } catch {
      serverPresent = false;         // the normal case, and not a problem
    }
  }

  document.addEventListener("input", onType, true);

  // Sending is the moment the advice was either taken or ignored, so it is the
  // only honest thing to count. Keystrokes are not messages.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.shiftKey || !isComposer(e.target)) return;
    const a = last;
    if (serverPresent && a && !a.unavailable_here && a.recommend && a.top) {
      fetch(BASE + "/lane/advice-log", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          lane: a.lane, site: SITE, model: a.recommend.id,
          top: a.top.id, est_in: a.est_in, est_out: a.est_out,
        }),
      }).then(refreshScore).catch(() => {});
    }
    setTimeout(() => { hide(); lastText = ""; last = null; }, 60);
  }, true);

  // Ask the local LANE about itself once, in the background. Whether it
  // answers changes only how much the panel can show, never whether it works.
  loadProfile().then(loadLocalPreferences).then(refreshScore);
})();
