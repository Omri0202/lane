/*
 * search.js — while you are still typing into the search box.
 *
 * The choice between a search engine and a model is made in the second before
 * Enter is pressed, so that is where this lives: the card appears as the query
 * is typed, not on the results page afterwards. By the time results are on
 * screen the decision has already been made and undoing it costs another
 * click and a page load.
 *
 * It offers TWO models, not one. "Use this" is a ruling; the cheapest that
 * will do the job beside the one that fits it best is a choice, and the person
 * typing knows which of those they want far better than any classifier does.
 * They may be on different sites, which is worth seeing.
 *
 * WHEN IT STAYS SILENT IS STILL THE WHOLE DESIGN.
 *
 * A card on every keystroke is adware and gets an extension uninstalled inside
 * a day. Most searches are not model-shaped: navigation, a product name, a bare
 * domain, a short fact the engine puts in a box at the top. And it never
 * competes with the engine on live information, because there a model would
 * answer from a stale memory while the real answer is on the page behind it.
 */

(() => {
  "use strict";
  if (window.__laneSearch) return;
  window.__laneSearch = true;

  /* Whole hosts, anchored.
   *
   * A substring check for "google." is also true of gemini.google.com, which
   * is a chat site the PANEL owns and this script has no business on. The
   * manifest does not load it there today, so nothing was broken - but the two
   * scripts agreeing about which host is which should not depend on a match
   * pattern somebody might widen later. */
  const ENGINE_HOSTS = [
    /^(www\.)?google\.[a-z.]+$/,
    /^(www\.)?bing\.com$/,
    /^(www\.)?duckduckgo\.com$/,
    /^search\.brave\.com$/,
    /^(www\.)?ecosia\.org$/,
  ];

  const isDev = /^(127\.0\.0\.1|localhost)$/.test(location.hostname)
                && location.pathname.startsWith("/dev/search");
  const onEngine = isDev
    || ENGINE_HOSTS.some((re) => re.test(location.hostname));
  if (!onEngine) return;

  const SITE_URL = {
    claude: "https://claude.ai/new?q=",
    chatgpt: "https://chatgpt.com/?q=",
    gemini: "https://gemini.google.com/app",
  };
  const SITE_NAME = { claude: "Claude", chatgpt: "ChatGPT", gemini: "Gemini" };
  // Gemini has no documented prefill parameter, so the query goes on the
  // clipboard rather than being silently dropped.
  const PREFILLS = { claude: true, chatgpt: true, gemini: false };
  const DISMISS_KEY = "lane.searchOffer";
  const DEBOUNCE_MS = 340;

  const esc = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const money = (n) => n <= 0 ? "free"
    : n < 0.001 ? "$" + n.toFixed(5)
    : n < 0.01 ? "$" + n.toFixed(4)
    : n < 1 ? "$" + n.toFixed(3) : "$" + n.toFixed(2);

  let profile = null;
  let dismissedThisPage = false;
  let host = null;
  let lastQuery = "";

  // ── when to speak ──────────────────────────────────────────────────────────
  function worthOffering(q, verdict) {
    const words = q.split(/\s+/).filter(Boolean).length;
    if (words < 4) return false;                       // navigation
    if (/^\w+:\/\//.test(q)) return false;             // a URL
    if (/^[\w-]+\.(com|org|net|io|ai|co\.uk)\b/i.test(q)) return false;
    if (verdict.lane === "web_search") return false;   // the engine is right
    if (verdict.lane === "trivial") return false;
    if (verdict.lane === "simple" && words < 9) return false;
    return true;
  }

  // ── storage ────────────────────────────────────────────────────────────────
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

  function openSetup() {
    try {
      if (typeof chrome !== "undefined" && chrome.runtime
          && chrome.runtime.getURL) {
        window.open(chrome.runtime.getURL("onboarding.html"), "_blank");
        return;
      }
    } catch (e) { /* fall through */ }
    window.open("/dev/ext/onboarding.html", "_blank");
  }

  // ── the two picks ──────────────────────────────────────────────────────────
  /* The cheapest that will do it, and the one that fits it best.
   *
   * Both are searched across every site this person uses, so the answer can be
   * "cheapest is on ChatGPT, best is on Claude" — which is a real and useful
   * thing to know, and something no single-site view can tell them. */
  function picks(query) {
    const sites = (profile.sites && profile.sites.length)
      ? profile.sites : Object.keys(SITE_URL);
    const allowed = LaneProfile.allowed(profile);

    let cheap = null, best = null, lane = null;
    for (const site of sites) {
      const s = LaneCore.advise(query, site, "save", allowed);
      if (s.unavailable_here) continue;
      lane = lane || s;
      if (!cheap || s.recommend.cost < cheap.rec.cost) {
        cheap = { site, rec: s.recommend, a: s };
      }
      const b = LaneCore.advise(query, site, "best", allowed);
      if (b.unavailable_here) continue;
      if (!best || b.recommend.tier > best.rec.tier
          || (b.recommend.tier === best.rec.tier
              && b.recommend.cost < best.rec.cost)) {
        best = { site, rec: b.recommend, a: b, fit: b.fit };
      }
    }
    return { cheap, best, lane };
  }

  // ── the card ───────────────────────────────────────────────────────────────
  function hide() {
    if (host) { host.remove(); host = null; }
  }

  function show(query, p) {
    hide();
    const a = p.lane;
    const same = p.cheap && p.best && p.cheap.rec.id === p.best.rec.id;
    const needsSetup = !profile.onboarded;

    host = document.createElement("div");
    host.id = "lane-search-host";
    host.style.cssText =
      "position:fixed;right:18px;bottom:18px;z-index:2147483600;" +
      "width:318px;pointer-events:none;";
    const root = host.attachShadow({ mode: "open" });

    /* The row says where the query is going AND whether it travels.
     *
     * Claude and ChatGPT take it in the URL; Gemini has no such parameter, so
     * it goes on the clipboard instead. Saying "paste it in" costs four words
     * and is the difference between arriving with your question and arriving
     * at an empty box wondering what happened to it. */
    const row = (label, pick, note) => {
      const bits = [SITE_NAME[pick.site]];
      if (note) bits.push(note);
      if (!PREFILLS[pick.site]) bits.push("copied - paste it in");
      return `
      <button class="pick" data-site="${esc(pick.site)}">
        <span class="lbl">${label}</span>
        <span class="mid">
          <span class="mdl">${esc(pick.rec.display)}</span>
          <span class="via">${esc(bits.join(" \u00b7 "))}</span>
        </span>
        <span class="cost">${money(pick.rec.cost)}</span>
      </button>`;
    };

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
    animation:in .16s ease both; }
  @keyframes in { from { opacity:0; transform:translateY(6px); } }
  .top { display:flex; align-items:center; gap:7px; padding:7px 9px 7px 11px;
         background:var(--panel); border-bottom:1px solid var(--line); }
  .brand { font-size:10px; font-weight:700; letter-spacing:.11em; color:var(--faint); }
  .grow { flex:1; }
  .x { border:0; background:transparent; color:var(--faint); cursor:pointer;
       font-size:15px; line-height:1; padding:2px 5px; border-radius:5px; }
  .x:hover { color:var(--ink); background:var(--line); }
  .body { padding:10px 11px 11px; }
  .tag { display:inline-block; padding:2px 8px; border-radius:999px;
         font-size:10px; font-weight:700; letter-spacing:.04em;
         text-transform:uppercase; background:#3b82f622; color:#3b6df5; }
  @media (prefers-color-scheme: dark) { .tag { color:#7ba2ff; } }
  .lead { font-size:11.5px; color:var(--dim); margin-top:7px; }

  .pick { width:100%; display:flex; align-items:center; gap:9px;
          margin-top:7px; padding:8px 10px; text-align:left;
          border:1px solid var(--line); border-radius:10px;
          background:var(--bg); color:var(--ink); font:inherit; cursor:pointer; }
  .pick:hover { border-color:var(--accent); }
  .lbl { font-size:9px; font-weight:700; letter-spacing:.07em;
         text-transform:uppercase; color:var(--faint); width:52px; flex:none; }
  .mid { flex:1; min-width:0; }
  .mdl { display:block; font-weight:650; font-size:13px; }
  .via { display:block; font-size:11px; color:var(--dim); }
  .cost { font-size:12px; font-weight:600; font-variant-numeric:tabular-nums;
          white-space:nowrap; }

  .setup { margin-top:9px; padding-top:9px; border-top:1px dashed var(--line); }
  .setup button { border:0; background:none; color:var(--accent); font:inherit;
                  font-size:11.5px; cursor:pointer; padding:0; text-align:left; }
  .setup .d { font-size:11px; color:var(--faint); margin-top:2px; }

  .foot { margin-top:9px; }
  .foot button { border:0; background:none; color:var(--faint); font:inherit;
                 font-size:10.5px; cursor:pointer; text-decoration:underline; }
  .foot button:hover { color:var(--ink); }
  .note { font-size:10.5px; color:var(--faint); margin-top:6px; }
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

    ${same
      ? row("Use", p.cheap, "cheapest and the best fit")
      : (p.cheap ? row("Cheapest", p.cheap, null) : "") +
        (p.best ? row("Best", p.best, p.best.fit ? "" : null) : "")}

    ${needsSetup ? `<div class="setup">
        <button id="setup">Tell LANE which models you actually have →</button>
        <div class="d">Right now it is guessing from the full list.</div>
      </div>` : ""}

    <div class="foot"><button id="never">Never on searches</button></div>
  </div>
</div>`;

    document.documentElement.appendChild(host);

    root.getElementById("close").addEventListener("click", () => {
      dismissedThisPage = true;
      hide();
    });
    root.getElementById("never").addEventListener("click", () => {
      writeDismissed({ off: true });
      dismissedThisPage = true;
      hide();
    });
    const setupBtn = root.getElementById("setup");
    if (setupBtn) setupBtn.addEventListener("click", openSetup);

    for (const b of root.querySelectorAll(".pick")) {
      b.addEventListener("click", async () => {
        const site = b.dataset.site;
        if (!PREFILLS[site]) {
          try { await navigator.clipboard.writeText(query); } catch (e) { /* fine */ }
        }
        const url = PREFILLS[site]
          ? SITE_URL[site] + encodeURIComponent(query)
          : SITE_URL[site];
        window.open(url, "_blank", "noopener");
        hide();
      });
    }
  }

  // ── what they are typing ───────────────────────────────────────────────────
  function consider(query) {
    query = String(query || "").trim();
    if (query === lastQuery) return;
    lastQuery = query;

    if (dismissedThisPage) return;
    if (!query) { hide(); return; }

    const verdict = LaneCore.classify(query);
    if (!worthOffering(query, verdict)) { hide(); return; }

    const p = picks(query);
    if (!p.cheap && !p.best) { hide(); return; }
    show(query, p);
  }

  /* Found by listening, not by selector.
   *
   * Every one of these engines renames its classes on its own schedule, and a
   * search box is unmistakable from its behaviour: a text input somebody is
   * typing into on a search engine. */
  function isSearchBox(el) {
    if (!el) return false;
    if (el.tagName === "TEXTAREA") return true;
    if (el.tagName === "INPUT")
      return ["text", "search", ""].includes((el.type || "").toLowerCase());
    return !!el.isContentEditable;
  }

  function textOf(el) {
    if (!el) return "";
    if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") return el.value || "";
    return el.innerText || "";
  }

  let timer = null;
  document.addEventListener("input", (e) => {
    if (!isSearchBox(e.target)) return;
    clearTimeout(timer);
    const text = textOf(e.target);
    timer = setTimeout(() => consider(text), DEBOUNCE_MS);
  }, true);

  // Pressing Enter hands off to the engine; the card should go with it rather
  // than hang over the results that are about to load.
  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && isSearchBox(e.target)) hide();
  }, true);

  async function main() {
    const dismissed = await readDismissed();
    if (dismissed.off) { dismissedThisPage = true; return; }
    profile = await LaneProfile.load();

    // Already on a results page: the query is in the URL, so offer against it
    // straight away. Somebody who searched before installing this still gets
    // one chance to see it.
    const fromUrl = (new URLSearchParams(location.search).get("q") || "").trim();
    if (fromUrl) consider(fromUrl);
  }

  main();
})();
