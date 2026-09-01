/*
 * advisor.js — the panel that watches you type and names the model to pick.
 *
 * This is LANE without the proxy. Nothing is intercepted, nothing is sent
 * anywhere, and the page is not modified beyond one floating card: you are
 * still talking to Claude, or ChatGPT, or Gemini, exactly as before. The only
 * claim being made is "this looks like a reasoning problem, Sonnet handles it,
 * and that is a fifth of the cost" — made while there is still time to act on
 * it, which is the whole point. Advice that arrives after you press send is a
 * report, not advice.
 *
 * Four decisions worth knowing about:
 *
 * The composer is found by LISTENING rather than by selector. Every one of
 * these sites is a React app that renames its classes on a whim, so
 * `document.querySelector('.composer-input')` is a bet on someone else's
 * refactor. Watching input events and taking whatever element received them
 * survives redesigns.
 *
 * The panel lives in a shadow root, so the host page's CSS — and there is a
 * lot of it — cannot reach in and break the layout, and nothing here leaks out
 * to break theirs.
 *
 * It advises within the models THAT SITE offers, with one exception: when the
 * site cannot do the job at all — asking Claude for a picture — the honest
 * answer is which site can, so that is what it shows.
 *
 * Every number on screen is for THIS message. The prompt is measured, the
 * reply length is estimated from the kind of request, and both are priced.
 * Showing a rate card instead would be true and useless.
 */

(() => {
  "use strict";
  if (window.__laneAdvisor) return;      // survive SPA re-injection
  window.__laneAdvisor = true;

  const DEBOUNCE_MS = 320;
  const MIN_WORDS = 3;                   // below this there is nothing to read

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

  // In the dev harness the page is served BY lane, so same-origin is correct
  // and immune to the port having moved. In the extension the port is whatever
  // `lane config port` says, which this script cannot read — so it tries the
  // default and a stored override wins.
  let ENDPOINT = DEV_SITE
    ? location.origin + "/lane/advise"
    : "http://127.0.0.1:8080/lane/advise";
  try {
    if (!DEV_SITE && typeof chrome !== "undefined" && chrome.storage) {
      chrome.storage.local.get("endpoint", (v) => {
        if (v && v.endpoint) ENDPOINT = v.endpoint;
      });
    }
  } catch { /* not running as an extension; the default stands */ }

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
    "width:310px;pointer-events:none;";
  const root = host.attachShadow({ mode: "open" });

  root.innerHTML = `
<style>
  :host { all: initial;
    --bg:#fff; --panel:#f6f7f9; --line:#e3e6ea; --ink:#14171a;
    --dim:#6b7480; --faint:#99a1ac; --good:#1a8a5a; --alert:#c2410c; }
  @media (prefers-color-scheme: dark) {
    :host { --bg:#171a1f; --panel:#1e222a; --line:#2b313a; --ink:#e8eaed;
            --dim:#9aa3ae; --faint:#6d7681; --good:#4ec98a; --alert:#fb923c; }
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

  .top { display:flex; align-items:center; gap:8px; padding:8px 11px;
         background:var(--panel); border-bottom:1px solid var(--line); }
  .brand { font-size:10px; font-weight:700; letter-spacing:.11em;
           color:var(--faint); }
  .grow { flex:1; }
  .x { border:0; background:transparent; color:var(--faint); cursor:pointer;
       font-size:15px; line-height:1; padding:2px 5px; border-radius:5px; }
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
  @media (prefers-color-scheme: dark) {
    .tag-simple{color:#2dd4bf} .tag-general{color:#7ba2ff}
    .tag-longform{color:#e0b050} .tag-reasoning{color:#a98bff}
    .tag-vision{color:#22d3ee} .tag-tools{color:#4ade80}
    .tag-image_gen{color:#f472b6}
  }
</style>
<div class="card" id="card">
  <div class="top">
    <span class="brand">L.A.N.E.</span>
    <span class="grow"></span>
    <button class="x" id="close" title="Hide until next reload">×</button>
  </div>
  <div id="content"></div>
</div>`;

  document.documentElement.appendChild(host);

  const card = root.getElementById("card");
  const content = root.getElementById("content");
  let dismissed = false;

  root.getElementById("close").addEventListener("click", () => {
    dismissed = true;
    hide();
  });

  const show = () => card.classList.add("show");
  const hide = () => card.classList.remove("show");

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

  /* The site cannot do this at all. Showing its best model would be a
     confidently wrong answer on the one request where the wrongness becomes
     obvious within seconds. */
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

    const saving = a.is_top
      ? `<div class="same">Nothing lighter clears the bar.</div>`
      : `<div class="save">saves ${money(a.saving)} · ${a.factor}× cheaper than ${esc((a.top || {}).display)}</div>`;

    content.innerHTML = `
      <div class="body">
        ${header(a)}
        <div class="pick">
          <div class="label">Use on ${esc(SITE_NAME)}</div>
          <div class="row">
            <span class="name">${esc(rec.display)}</span>
            <span class="price">${money(rec.cost)}</span>
          </div>
          ${saving}
        </div>
        ${rows ? `<table>${rows}</table>` : ""}
        <div class="why">${esc(a.explain)}</div>
      </div>`;
    show();
  }

  function renderOffline() {
    content.innerHTML = `
      <div class="offline">
        LANE is not running. Start it with <code>lane serve</code> and this
        panel will pick up on its own.
      </div>`;
    show();
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

  let timer = null, lastSent = "", offline = false;

  function onType(e) {
    if (dismissed || !isComposer(e.target)) return;
    const text = textOf(e.target).trim();

    if (text.split(/\s+/).filter(Boolean).length < MIN_WORDS) {
      hide();
      lastSent = "";
      return;
    }
    if (text === lastSent) return;

    clearTimeout(timer);
    timer = setTimeout(() => advise(text), DEBOUNCE_MS);
  }

  async function advise(text) {
    lastSent = text;
    try {
      const res = await fetch(ENDPOINT, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text, site: SITE }),
      });
      if (!res.ok) throw new Error(res.status);
      offline = false;
      const a = await res.json();
      if (a.unavailable_here) renderElsewhere(a);
      else renderAdvice(a);
    } catch {
      // The panel must never become the reason a page misbehaves. A LANE that
      // is not running is a normal state, not an error worth shouting about.
      if (!offline) { offline = true; renderOffline(); }
    }
  }

  document.addEventListener("input", onType, true);

  // Sending clears the composer, so retire the advice with it rather than
  // leaving a stale recommendation hanging over an empty box.
  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && isComposer(e.target)) {
      setTimeout(() => { hide(); lastSent = ""; }, 60);
    }
  }, true);
})();
