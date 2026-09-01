/*
 * advisor.js — the panel that watches you type and names the model to pick.
 *
 * This is LANE without the proxy. Nothing is intercepted, nothing is sent
 * anywhere, and the page is not modified beyond one floating card: you are
 * still talking to Claude, or ChatGPT, or Gemini, exactly as before. The only
 * claim being made is "this looks like a reasoning problem, Sonnet handles it,
 * and that is a quarter of the cost of Opus" — made while there is still time
 * to act on it, which is the whole point. Advice that arrives after you press
 * send is a report, not advice.
 *
 * Three decisions worth knowing about:
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
 * It only ever advises within the models THAT SITE offers. Telling somebody
 * sitting in claude.ai to use Gemini Flash is not a saving, it is a chore.
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

  // Where to ask. In the dev harness the page is already being served BY lane,
  // so same-origin is both correct and immune to the port having moved. In the
  // extension the port is whatever `lane config port` says, which this script
  // cannot read — so it tries the default, and a stored override wins when the
  // user has moved it.
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

  // ── the panel ────────────────────────────────────────────────────────────
  const host = document.createElement("div");
  host.id = "lane-advisor-host";
  host.style.cssText =
    "position:fixed;right:18px;bottom:18px;z-index:2147483600;" +
    "width:296px;pointer-events:none;";
  const root = host.attachShadow({ mode: "open" });

  root.innerHTML = `
<style>
  :host { all: initial; }
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

  :host { --bg:#fff; --panel:#f6f7f9; --line:#e3e6ea; --ink:#14171a;
          --dim:#6b7480; --faint:#99a1ac; --good:#1a8a5a; --warn:#a8710a; }
  @media (prefers-color-scheme: dark) {
    :host { --bg:#171a1f; --panel:#1e222a; --line:#2b313a; --ink:#e8eaed;
            --dim:#9aa3ae; --faint:#6d7681; --good:#4ec98a; --warn:#e0b050; }
  }

  .top { display:flex; align-items:center; gap:8px; padding:9px 11px;
         background:var(--panel); border-bottom:1px solid var(--line); }
  .brand { font-size:10.5px; font-weight:700; letter-spacing:.1em;
           color:var(--faint); }
  .grow { flex:1; }
  .x { border:0; background:transparent; color:var(--faint); cursor:pointer;
       font-size:15px; line-height:1; padding:2px 4px; border-radius:5px; }
  .x:hover { color:var(--ink); background:var(--line); }

  .body { padding: 11px; }
  .lead { display:flex; align-items:baseline; gap:7px; flex-wrap:wrap; }
  .tag { padding:2px 8px; border-radius:999px; font-size:10.5px;
         font-weight:700; letter-spacing:.03em; text-transform:uppercase; }
  .why { color:var(--dim); font-size:11.5px; margin-top:7px; }

  .pick { margin-top:10px; padding-top:10px; border-top:1px solid var(--line); }
  .pick .label { font-size:10.5px; color:var(--faint); letter-spacing:.05em;
                 text-transform:uppercase; }
  .pick .name { font-size:15px; font-weight:650; margin-top:2px; }
  .save { margin-top:5px; font-size:11.5px; color:var(--good); font-weight:600; }
  .same { margin-top:5px; font-size:11.5px; color:var(--dim); }

  .alts { margin-top:9px; display:flex; gap:5px; flex-wrap:wrap; }
  .alt { font-size:10.5px; color:var(--dim); background:var(--panel);
         border:1px solid var(--line); border-radius:6px; padding:2px 6px; }

  .offline { padding:11px; font-size:11.5px; color:var(--dim); }
  .offline code { background:var(--panel); padding:1px 5px; border-radius:4px;
                  font-size:11px; }

  .tag-trivial   { background:#8a919b22; color:var(--dim); }
  .tag-simple    { background:#14b8a622; color:#0d9488; }
  .tag-general   { background:#3b82f622; color:#3b6df5; }
  .tag-longform  { background:#f59e0b22; color:#b4780a; }
  .tag-reasoning { background:#8b5cf622; color:#7c4ddd; }
  .tag-vision    { background:#06b6d422; color:#0891b2; }
  .tag-tools     { background:#22c55e22; color:#15954c; }
  @media (prefers-color-scheme: dark) {
    .tag-simple{color:#2dd4bf} .tag-general{color:#7ba2ff}
    .tag-longform{color:#e0b050} .tag-reasoning{color:#a98bff}
    .tag-vision{color:#22d3ee} .tag-tools{color:#4ade80}
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

  function render(a) {
    const lane = a.lane || "general";
    const rec = a.recommend || {};
    const alts = Object.entries(a.picks || {})
      .filter(([, p]) => p.id !== rec.id)
      .map(([mode, p]) => `<span class="alt">${mode}: ${p.display}</span>`);

    content.innerHTML = `
      <div class="body">
        <div class="lead">
          <span class="tag tag-${lane}">${a.lane_label || lane}</span>
          <span class="why">${a.words} word${a.words === 1 ? "" : "s"}</span>
        </div>
        <div class="why">${a.reason || ""}</div>
        <div class="pick">
          <div class="label">Use on ${SITE_NAME}</div>
          <div class="name">${rec.display || "—"}</div>
          ${a.is_top
            ? `<div class="same">Nothing lighter will do this well.</div>`
            : `<div class="save">~${a.factor}× cheaper than ${
                 (a.top || {}).display || "the top model"}</div>`}
        </div>
        ${alts.length ? `<div class="alts">${alts.join("")}</div>` : ""}
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
      render(await res.json());
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
