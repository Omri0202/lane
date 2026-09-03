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
  :host { all: initial;
    --bg:#fff; --panel:#f6f7f9; --line:#e3e6ea; --ink:#14171a;
    --dim:#6b7480; --faint:#99a1ac; --good:#1a8a5a; --alert:#c2410c;
    --accent:#3b6df5; --accent-ink:#fff; }
  @media (prefers-color-scheme: dark) {
    :host { --bg:#171a1f; --panel:#1e222a; --line:#2b313a; --ink:#e8eaed;
            --dim:#9aa3ae; --faint:#6d7681; --good:#4ec98a; --alert:#fb923c;
            --accent:#5b87ff; --accent-ink:#0b0d10; }
  }
  * { box-sizing: border-box; }
  .card {
    pointer-events: auto;
    font: 13px/1.5 ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--ink);
    border: 1px solid var(--line); border-radius: 13px;
    box-shadow: 0 8px 28px rgba(0,0,0,.16), 0 1px 3px rgba(0,0,0,.08);
    overflow: hidden;
    transform: translateY(8px); opacity: 0;
    transition: transform .16s ease, opacity .16s ease;
  }
  .card.show { transform: translateY(0); opacity: 1; }

  .top { display:flex; align-items:center; gap:7px; padding:7px 9px 7px 11px;
         background:var(--panel); border-bottom:1px solid var(--line); }
  .brand { font-size:10px; font-weight:700; letter-spacing:.11em;
           color:var(--faint); }
  .grow { flex:1; }
  .seg { display:flex; gap:2px; background:var(--bg); padding:2px;
         border:1px solid var(--line); border-radius:7px; }
  .seg button { border:0; background:transparent; color:var(--dim);
                font:inherit; font-size:10px; font-weight:700;
                letter-spacing:.06em; padding:3px 9px; border-radius:5px;
                cursor:pointer; }
  .seg button[aria-pressed="true"] { background:var(--accent);
                                     color:var(--accent-ink); }
  .x { border:0; background:transparent; color:var(--faint); cursor:pointer;
       font-size:15px; line-height:1; padding:2px 4px; border-radius:5px; }
  .x:hover { color:var(--ink); background:var(--line); }

  .body { padding: 10px 11px 11px; }
  .lead { display:flex; align-items:center; gap:7px; flex-wrap:wrap; }
  .tag { padding:2px 8px; border-radius:999px; font-size:10px;
         font-weight:700; letter-spacing:.04em; text-transform:uppercase; }
  .toks { font-size:10.5px; color:var(--faint);
          font-variant-numeric:tabular-nums; }

  .pick { margin-top:9px; padding-top:9px; border-top:1px solid var(--line); }
  .label { font-size:9.5px; color:var(--faint); letter-spacing:.07em;
           text-transform:uppercase; }
  .row { display:flex; align-items:baseline; gap:8px; margin-top:2px; }
  .name { font-size:15px; font-weight:650; flex:1; }
  .price { font-size:13px; font-weight:600;
           font-variant-numeric:tabular-nums; }
  .save { margin-top:4px; font-size:11.5px; color:var(--good); font-weight:600; }
  .same { margin-top:4px; font-size:11.5px; color:var(--dim); }
  .fit  { margin-top:4px; font-size:11.5px; color:var(--dim); }

  .use { margin-top:9px; width:100%; border:0; border-radius:8px;
         background:var(--accent); color:var(--accent-ink); font:inherit;
         font-size:12.5px; font-weight:650; padding:7px 10px; cursor:pointer; }
  .use:hover { filter:brightness(1.07); }
  .use:disabled { opacity:.55; cursor:default; }
  .useout { margin-top:5px; font-size:11px; color:var(--dim); }
  .useout.ok { color:var(--good); }
  .useout.bad { color:var(--alert); }

  table { width:100%; margin-top:9px; border-collapse:collapse;
          font-size:11px; color:var(--dim); }
  td { padding:2px 0; }
  td.m { color:var(--faint); text-transform:uppercase; letter-spacing:.04em;
         font-size:9.5px; width:66px; }
  td.p { text-align:right; font-variant-numeric:tabular-nums; }
  tr.on td { color:var(--ink); font-weight:600; }

  .why { margin-top:9px; padding-top:9px; border-top:1px solid var(--line);
         font-size:11.5px; color:var(--dim); }

  .alert { margin-top:9px; padding-top:9px; border-top:1px solid var(--line); }
  .alert .head { color:var(--alert); font-weight:700; font-size:11px;
                 letter-spacing:.04em; text-transform:uppercase; }
  .go { display:flex; align-items:baseline; gap:6px; margin-top:6px;
        font-size:12px; }
  .go .site { font-weight:650; }
  .go .mdl { color:var(--dim); flex:1; }
  .go .p { font-variant-numeric:tabular-nums; color:var(--dim); }

  .score { border-top:1px solid var(--line); background:var(--panel);
           padding:7px 11px; font-size:10.5px; color:var(--dim);
           display:flex; align-items:baseline; gap:6px; }
  .score b { color:var(--good); font-size:11.5px; }
  .score .n { margin-left:auto; color:var(--faint); }

  .setup { margin-top:8px; padding-top:8px; border-top:1px dashed var(--line);
           font-size:10.5px; color:var(--faint); }
  .setup a, .offline a { color:var(--accent); }
  .offline { padding:11px; font-size:11.5px; color:var(--dim); }
  .offline code { background:var(--panel); padding:1px 5px; border-radius:4px; }

  .tag-trivial   { background:#8a919b22; color:var(--dim); }
  .tag-simple    { background:#14b8a622; color:#0d9488; }
  .tag-general   { background:#3b82f622; color:#3b6df5; }
  .tag-longform  { background:#f59e0b22; color:#b4780a; }
  .tag-reasoning { background:#8b5cf622; color:#7c4ddd; }
  .tag-vision    { background:#06b6d422; color:#0891b2; }
  .tag-tools     { background:#22c55e22; color:#15954c; }
  .tag-image_gen { background:#ec489922; color:#be2e68; }
  .tag-translate { background:#a855f722; color:#8b3fd4; }
  .tag-web_search{ background:#0ea5e922; color:#0277b8; }
  @media (prefers-color-scheme: dark) {
    .tag-simple{color:#2dd4bf} .tag-general{color:#7ba2ff}
    .tag-longform{color:#e0b050} .tag-reasoning{color:#a98bff}
    .tag-vision{color:#22d3ee} .tag-tools{color:#4ade80}
    .tag-image_gen{color:#f472b6} .tag-translate{color:#c084fc}
    .tag-web_search{color:#38bdf8}
  }
</style>
<div class="card" id="card">
  <div class="top">
    <span class="brand">L.A.N.E.</span>
    <span class="grow"></span>
    <div class="seg" id="seg" role="group" aria-label="What to optimise for">
      <button data-v="save" aria-pressed="true"  title="Cheapest model that still does the job">SAVE</button>
      <button data-v="best" aria-pressed="false" title="Model whose strengths fit this request">BEST</button>
    </div>
    <button class="x" id="close" title="Hide until next reload">×</button>
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

  function header(a) {
    const tokens = a.kind === "image"
      ? "priced per image"
      : "~" + a.est_in + " in · ~" + Number(a.est_out).toLocaleString() + " out";
    return `
      <div class="lead">
        <span class="tag tag-${esc(a.lane)}">${esc(a.lane_label)}</span>
        <span class="toks">${tokens}</span>
      </div>`;
  }

  function renderElsewhere(a) {
    const rows = (a.elsewhere || []).slice(0, 3).map((e) => `
      <div class="go">
        <span class="site">${esc(e.site)}</span>
        <span class="mdl">${esc(e.display)}</span>
        <span class="p">${money(e.cost)}</span>
      </div>`).join("");
    content.innerHTML = `
      <div class="body">
        ${header(a)}
        <div class="alert">
          <div class="head">${esc(a.site_name)} can't do this</div>
          ${rows}
        </div>
        <div class="why">${esc(a.explain)}</div>
      </div>`;
    show();
  }

  function renderAdvice(a) {
    const rec = a.recommend || {};
    const rows = (a.options || []).map((o) => `
      <tr class="${o.id === rec.id ? "on" : ""}">
        <td class="m">${esc(o.mode)}</td>
        <td>${esc(o.display)}</td>
        <td class="p">${money(o.cost)}</td>
      </tr>`).join("");

    // SAVE leads with the money; BEST leads with why this model suits the job.
    // Same data, different question, so a different headline.
    let headline;
    if (a.variation === "best") {
      headline = a.fit
        ? `<div class="fit">${esc(a.fit)}</div>`
        : `<div class="same">the strongest fit available to you</div>`;
    } else if (a.is_top) {
      headline = `<div class="same">Nothing lighter clears the bar.</div>`;
    } else {
      headline = `<div class="save">saves ${money(a.saving)} · ${a.factor}× cheaper than ${esc((a.top || {}).display)}</div>`;
    }

    content.innerHTML = `
      <div class="body">
        ${header(a)}
        <div class="pick">
          <div class="label">${a.variation === "best" ? "Best fit on" : "Cheapest that fits on"} ${esc(SITE_NAME)}</div>
          <div class="row">
            <span class="name">${esc(rec.display)}</span>
            <span class="price">${money(rec.cost)}</span>
          </div>
          ${headline}
          <button class="use" id="use">Use ${esc(rec.display)}</button>
          <div class="useout" id="useout"></div>
        </div>
        ${rows ? `<table>${rows}</table>` : ""}
        <div class="why">${esc(a.explain)}</div>
        ${a.assuming_all ? `<div class="setup">
           Assuming you can use every ${esc(SITE_NAME)} model.
           <a href="${BASE}/setup" target="_blank" rel="noreferrer">Tell LANE
           which ones you actually have</a> and this gets sharper.
         </div>` : ""}
      </div>`;

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
      <div class="offline">
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
  async function refreshScore() {
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

  let timer = null, lastText = "", offline = false;

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

  async function advise(text) {
    try {
      const res = await fetch(BASE + "/lane/advise", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text, site: SITE, variation }),
      });
      if (!res.ok) throw new Error(res.status);
      offline = false;
      const a = await res.json();
      last = a;
      if (a.unavailable_here) renderElsewhere(a);
      else renderAdvice(a);
      refreshScore();
    } catch {
      // A LANE that is not running is a normal state, not an error worth
      // shouting about. The panel must never be why a page misbehaves.
      last = null;
      if (!offline) { offline = true; renderOffline(); }
    }
  }

  document.addEventListener("input", onType, true);

  // Sending is the moment the advice was either taken or ignored, so it is the
  // only honest thing to count. Keystrokes are not messages.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.shiftKey || !isComposer(e.target)) return;
    const a = last;
    if (a && !a.unavailable_here && a.recommend && a.top) {
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

  refreshScore();
})();
