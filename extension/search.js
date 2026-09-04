/*
 * search.js — you searched for something a model would answer better.
 *
 * The moment somebody types a question into Google is the moment the choice is
 * being made, and it is usually made by habit. This offers the alternative,
 * once, quietly, in the corner.
 *
 * WHEN IT STAYS SILENT IS THE WHOLE DESIGN.
 *
 * A card on every search is adware, and gets the extension uninstalled inside a
 * day. Most searches are not model-shaped: "facebook", "weather", "train times",
 * a product name, an error string somebody wants a Stack Overflow page for.
 * Google is genuinely the better tool for finding a site, for anything current,
 * and for the enormous class of queries that are really navigation.
 *
 * So the offer appears only when a model is honestly better — a question with
 * reasoning in it, something to write, something to translate, a picture to
 * make — and never when the query needs live information, because a model would
 * answer that from a stale memory and the search results are right there.
 *
 * The query is read from the URL rather than scraped from the page: it is
 * already in ?q=, it is stable across every redesign, and reading it needs no
 * access to the results themselves.
 */

(() => {
  "use strict";
  if (window.__laneSearch) return;
  window.__laneSearch = true;

  const ENGINES = [
    { host: "google.", param: "q" },
    { host: "bing.com", param: "q" },
    { host: "duckduckgo.com", param: "q" },
    { host: "search.brave.com", param: "q" },
    { host: "ecosia.org", param: "q" },
  ];

  // The local harness counts as a search engine, so the card - and more
  // importantly the long list of queries it must stay quiet for - can be
  // driven in a browser without waiting on a real Google page.
  const isDev = /^(127\.0\.0\.1|localhost)$/.test(location.hostname)
                && location.pathname.startsWith("/dev/search");
  const engine = isDev ? { host: "dev", param: "q" }
                       : ENGINES.find((e) => location.hostname.includes(e.host));
  if (!engine) return;

  const query = (new URLSearchParams(location.search).get(engine.param) || "").trim();
  if (!query) return;

  const SITE_URL = {
    claude: "https://claude.ai/new?q=",
    chatgpt: "https://chatgpt.com/?q=",
    gemini: "https://gemini.google.com/app",
  };
  const SITE_NAME = { claude: "Claude", chatgpt: "ChatGPT", gemini: "Gemini" };
  // Gemini has no documented prefill parameter, so the query is put on the
  // clipboard for it instead of pretending it will arrive in the box.
  const PREFILLS = { claude: true, chatgpt: true, gemini: false };

  const esc = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const money = (n) => n <= 0 ? "free"
    : n < 0.001 ? "$" + n.toFixed(5)
    : n < 0.01 ? "$" + n.toFixed(4)
    : n < 1 ? "$" + n.toFixed(3) : "$" + n.toFixed(2);

  /* Is a model actually the better tool for this?
   *
   * Every rule here is a reason to say nothing. Being wrong in this direction
   * costs a suggestion nobody sees; being wrong in the other direction puts a
   * box over somebody's search results for a query about train times. */
  function worthOffering(q, verdict) {
    const words = q.split(/\s+/).filter(Boolean).length;

    // Short queries are navigation. "facebook", "npm install", "bbc news".
    if (words < 4) return false;

    // A URL or a bare domain is somebody going somewhere.
    if (/^\w+:\/\//.test(q) || /^[\w-]+\.(com|org|net|io|ai|co\.uk)\b/i.test(q))
      return false;

    // The one lane where the search engine is right and a model is wrong: this
    // needs live information, and a model would answer it from memory while
    // the actual answer is on the page behind this card.
    if (verdict.lane === "web_search") return false;

    // Nothing to think about, or a fact Google shows in the box at the top.
    if (verdict.lane === "trivial") return false;
    if (verdict.lane === "simple" && words < 9) return false;

    return true;
  }

  const DISMISS_KEY = "lane.searchOffer";

  function readDismissed() {
    return new Promise((resolve) => {
      try {
        if (typeof chrome !== "undefined" && chrome.storage) {
          chrome.storage.local.get(DISMISS_KEY, (v) =>
            resolve((v || {})[DISMISS_KEY] || {}));
          return;
        }
        resolve(JSON.parse(localStorage.getItem(DISMISS_KEY) || "{}"));
      } catch (e) { resolve({}); }
    });
  }

  function writeDismissed(value) {
    try {
      if (typeof chrome !== "undefined" && chrome.storage) {
        chrome.storage.local.set({ [DISMISS_KEY]: value });
        return;
      }
      localStorage.setItem(DISMISS_KEY, JSON.stringify(value));
    } catch (e) { /* a preference that will not stick is not an error */ }
  }

  async function main() {
    const dismissed = await readDismissed();
    if (dismissed.off) return;              // they said never; that is final

    const profile = await LaneProfile.load();
    const verdict = LaneCore.classify(query);
    if (!worthOffering(query, verdict)) return;

    const sites = (profile.sites && profile.sites.length)
      ? profile.sites : Object.keys(SITE_URL);
    const allowed = LaneProfile.allowed(profile);
    const variation = profile.variation === "best" ? "best" : "save";

    let best = null;
    for (const site of sites) {
      const a = LaneCore.advise(query, site, variation, allowed);
      if (a.unavailable_here) continue;
      if (!best || a.recommend.cost < best.a.recommend.cost) best = { site, a };
    }
    if (!best) return;

    render(best.site, best.a);
  }

  function render(site, a) {
    const host = document.createElement("div");
    host.id = "lane-search-host";
    host.style.cssText =
      "position:fixed;right:18px;bottom:18px;z-index:2147483600;" +
      "width:300px;pointer-events:none;";
    const root = host.attachShadow({ mode: "open" });
    const rec = a.recommend;
    const prefills = PREFILLS[site];

    root.innerHTML = `
<style>
  :host { all: initial;
    --bg:#fff; --panel:#f6f7f9; --line:#e3e6ea; --ink:#14171a;
    --dim:#6b7480; --faint:#99a1ac; --good:#1a8a5a;
    --accent:#3b6df5; --accent-ink:#fff; }
  @media (prefers-color-scheme: dark) {
    :host { --bg:#171a1f; --panel:#1e222a; --line:#2b313a; --ink:#e8eaed;
            --dim:#9aa3ae; --faint:#6d7681; --good:#4ec98a;
            --accent:#5b87ff; --accent-ink:#0b0d10; }
  }
  * { box-sizing:border-box; }
  .card { pointer-events:auto;
    font:13px/1.5 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif;
    background:var(--bg); color:var(--ink);
    border:1px solid var(--line); border-radius:13px; overflow:hidden;
    box-shadow:0 8px 28px rgba(0,0,0,.16), 0 1px 3px rgba(0,0,0,.08);
    animation:in .18s ease both; }
  @keyframes in { from { opacity:0; transform:translateY(8px); } }
  .top { display:flex; align-items:center; gap:7px; padding:7px 9px 7px 11px;
         background:var(--panel); border-bottom:1px solid var(--line); }
  .brand { font-size:10px; font-weight:700; letter-spacing:.11em; color:var(--faint); }
  .grow { flex:1; }
  .x { border:0; background:transparent; color:var(--faint); cursor:pointer;
       font-size:15px; line-height:1; padding:2px 5px; border-radius:5px; }
  .x:hover { color:var(--ink); background:var(--line); }
  .body { padding:11px; }
  .tag { display:inline-block; padding:2px 8px; border-radius:999px;
         font-size:10px; font-weight:700; letter-spacing:.04em;
         text-transform:uppercase; background:#3b82f622; color:#3b6df5; }
  @media (prefers-color-scheme: dark) { .tag { color:#7ba2ff; } }
  .lead { font-size:12.5px; color:var(--dim); margin-top:8px; }
  .row { display:flex; align-items:baseline; gap:8px; margin-top:6px; }
  .name { font-size:15px; font-weight:650; flex:1; }
  .price { font-size:12.5px; font-weight:600; font-variant-numeric:tabular-nums; }
  .save { color:var(--good); font-size:11.5px; font-weight:600; margin-top:3px; }
  button.go { width:100%; margin-top:10px; border:0; border-radius:9px;
              padding:9px; background:var(--accent); color:var(--accent-ink);
              font:inherit; font-weight:650; font-size:12.5px; cursor:pointer; }
  .foot { margin-top:8px; display:flex; gap:10px; align-items:center; }
  .foot button { border:0; background:none; color:var(--faint); font:inherit;
                 font-size:11px; cursor:pointer; text-decoration:underline; }
  .foot button:hover { color:var(--ink); }
  .note { font-size:11px; color:var(--faint); margin-top:6px; }
</style>
<div class="card">
  <div class="top">
    <span class="brand">L.A.N.E.</span>
    <span class="grow"></span>
    <button class="x" id="close" title="Not this time">×</button>
  </div>
  <div class="body">
    <span class="tag">${esc(a.lane_label)}</span>
    <div class="lead">A model would answer this better than a list of links.</div>
    <div class="row">
      <span class="name">${esc(rec.display)}</span>
      <span class="price">${money(rec.cost)}</span>
    </div>
    ${a.is_top ? "" :
      `<div class="save">${a.factor}× cheaper than ${esc((a.top || {}).display)}</div>`}
    <button class="go" id="go">Ask ${esc(SITE_NAME[site])} instead</button>
    ${prefills ? "" : `<div class="note">Your search will be copied — paste it in.</div>`}
    <div class="foot">
      <button id="never">Never on searches</button>
    </div>
  </div>
</div>`;

    document.documentElement.appendChild(host);

    root.getElementById("close").addEventListener("click", () => host.remove());
    root.getElementById("never").addEventListener("click", () => {
      writeDismissed({ off: true });
      host.remove();
    });
    root.getElementById("go").addEventListener("click", async () => {
      if (!prefills) {
        try { await navigator.clipboard.writeText(query); } catch (e) { /* fine */ }
      }
      const url = prefills
        ? SITE_URL[site] + encodeURIComponent(query)
        : SITE_URL[site];
      window.open(url, "_blank", "noopener");
      host.remove();
    });
  }

  main();
})();
