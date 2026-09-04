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

  /* Ask the extension to open its own page.
   *
   * Opening it directly from here is what Chrome refuses: a content script
   * lives in the web page's world, and navigating that world to a
   * chrome-extension:// URL is blocked outright - ERR_BLOCKED_BY_CLIENT, with
   * no way to tell it apart from an ad blocker. The alternative, listing the
   * page in web_accessible_resources, would let any site on the internet frame
   * it, which is a worse trade than a message. */
  function openSetup() {
    try {
      if (typeof chrome !== "undefined" && chrome.runtime
          && chrome.runtime.sendMessage) {
        chrome.runtime.sendMessage({ type: "lane:open-setup" });
        return;
      }
    } catch (e) { /* fall through to the dev harness */ }
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
      <button class="l-row pick" data-site="${esc(pick.site)}">
        <span class="l-row__tag l-label">${label}</span>
        <span class="l-row__main">
          <span class="l-row__name">${esc(pick.rec.display)}</span>
          <span class="l-row__note">${esc(bits.join(" \u00b7 "))}</span>
        </span>
        <span class="l-row__end l-num">${money(pick.rec.cost)}</span>
      </button>`;
    };

    root.innerHTML = `
<style>
${LaneUI.css}

/* Only what is particular to this card. The shell, the rows, the pill and the
   buttons are the shared ones, so the search card and the panel read as the
   same object seen in two places rather than two things that look similar. */
:host { display: block; }
.card { pointer-events: auto; animation: l-rise .16s cubic-bezier(.2,.7,.3,1) both; }
.lead  { margin-top: 6px; }
.picks { margin-top: var(--l-2); }
.setup { margin-top: var(--l-3); padding-top: var(--l-3);
         border-top: 1px dashed var(--l-line); }
.foot  { margin-top: var(--l-3); }
.foot button { color: var(--l-faint); font-size: 11px; text-decoration: underline; }
.foot button:hover { color: var(--l-ink); }
</style>
<div class="l-card card">
  <div class="l-head">
    <span class="l-brand">L.A.N.E.</span>
    <span class="l-grow"></span>
    <button class="l-icon" id="close" title="Not this time"
            aria-label="Dismiss">${LaneUI.icons.close}</button>
  </div>
  <div class="l-pad">
    <span class="l-pill l-pill--${esc(a.lane)}">${esc(a.lane_label)}</span>
    <div class="lead l-sub">A model would answer this better than a list of links.</div>

    <div class="picks">
      ${same
        ? row("Use", p.cheap, "cheapest and the best fit")
        : (p.cheap ? row("Cheapest", p.cheap, null) : "") +
          (p.best ? row("Best", p.best, p.best.fit ? "" : null) : "")}
    </div>

    ${needsSetup ? `<div class="setup">
        <button class="l-btn--link" id="setup">
          Tell LANE which models you actually have
        </button>
        <div class="l-micro" style="margin-top:2px">
          Right now it is guessing from the full list.
        </div>
      </div>` : ""}

    <div class="foot">
      <button class="l-btn--link" id="never">Never on searches</button>
    </div>
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
