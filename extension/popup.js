/*
 * popup.js — the behaviour behind popup.html.
 *
 * In a file rather than inline because an extension page runs under
 * `script-src 'self'`: MV3 refuses every <script> with a body in it,
 * and it refuses it quietly - the markup renders, the handlers simply
 * never attach.
 */

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s)
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
const money = (n) => n <= 0 ? "free"
  : n < 0.001 ? "$" + n.toFixed(5)
  : n < 0.01 ? "$" + n.toFixed(4)
  : n < 1 ? "$" + n.toFixed(3) : "$" + n.toFixed(2);

$("gear").innerHTML = LaneUI.icons.gear;
$("logo").innerHTML = LaneUI.icons.mark;

const SITE_URL = { claude:"https://claude.ai/new",
                   chatgpt:"https://chatgpt.com/",
                   gemini:"https://gemini.google.com/app" };
const SITE_NAME = { claude:"Claude", chatgpt:"ChatGPT", gemini:"Gemini" };
const PROVIDER_SITE = { anthropic:"claude", openai:"chatgpt", google:"gemini" };

// Shortcuts, ordered by what they told us they do. Not a substitute for typing
// — they are there for the times somebody knows the shape of the job but has
// not written the sentence yet.
const QUICK = {
  code:     ["debug this error", "write a function that", "review this code"],
  writing:  ["draft an email about", "summarise this", "rewrite this to be"],
  research: ["what is the latest on", "explain how", "look up"],
  images:   ["create a picture of", "make a logo for"],
};

let profile = null;
let variation = "save";
let current = null;

function openTab(url) {
  try {
    if (typeof chrome !== "undefined" && chrome.tabs) chrome.tabs.create({ url });
    else window.open(url, "_blank");
  } catch (e) { window.open(url, "_blank"); }
}

/* The popup is an extension page, so it may use the proper API. Content
   scripts may not - see search.js, where the same call is a message. */
function openSetup() {
  try {
    if (typeof chrome !== "undefined" && chrome.runtime
        && chrome.runtime.openOptionsPage) {
      chrome.runtime.openOptionsPage();
      return;
    }
    if (typeof chrome !== "undefined" && chrome.runtime) {
      openTab(chrome.runtime.getURL("onboarding.html"));
      return;
    }
  } catch (e) { /* fall through */ }
  openTab("onboarding.html");
}

function render() {
  if (!profile.onboarded) {
    $("root").innerHTML = `
      <div class="first">
        <div class="mark">${LaneUI.icons.spark}</div>
        <div class="l-h2">Five quick questions</div>
        <p>Which sites you use, which models you can pick, what you mostly do.
           Then every suggestion is about you rather than about models in
           general.</p>
        <div class="go">
          <button class="l-btn l-btn--primary" id="start">
            Set up ${LaneUI.icons.arrow}
          </button>
        </div>
      </div>`;
    $("start").addEventListener("click", openSetup);
    return;
  }

  const favs = LaneProfile.favourites(profile)
    .map((id) => LaneCore.MODELS.find((m) => m.id === id))
    .filter(Boolean);

  const quick = [];
  for (const f of (profile.focus.length ? profile.focus : Object.keys(QUICK))) {
    for (const q of (QUICK[f] || [])) if (quick.length < 5) quick.push(q);
  }

  $("root").innerHTML = `
    <div class="l-pad">
      <textarea class="l-field" id="what"
                placeholder="What do you want to do?" autofocus></textarea>
      <div class="quick">${quick.map((q) =>
        `<button data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>
      <div class="answer" id="answer"></div>
      ${favs.length ? `<div class="favs">
        <span class="l-label">Your favourites</span>
        <div class="favrow">${favs.map((m) =>
          `<button class="l-btn" data-open="${esc(m.provider)}">${esc(m.display)}</button>`).join("")}</div>
      </div>` : ""}
    </div>`;

  const what = $("what");
  what.addEventListener("input", () => schedule(what.value));
  for (const b of document.querySelectorAll("[data-q]")) {
    b.addEventListener("click", () => {
      what.value = b.dataset.q + " ";
      what.focus();
      schedule(what.value);
    });
  }
  for (const b of document.querySelectorAll("[data-open]")) {
    b.addEventListener("click", () =>
      openTab(SITE_URL[PROVIDER_SITE[b.dataset.open]] || SITE_URL.claude));
  }
}

let timer = null;
function schedule(text) {
  clearTimeout(timer);
  timer = setTimeout(() => answer(text), 260);
}

function answer(text) {
  const box = $("answer");
  if (String(text || "").trim().split(/\s+/).filter(Boolean).length < 3) {
    box.classList.remove("show");
    return;
  }

  // Which site, chosen for THEM: only the ones they said they use, and only
  // ones whose models can actually do this.
  const sites = profile.sites.length ? profile.sites : Object.keys(SITE_URL);
  const allowed = LaneProfile.allowed(profile);

  let best = null;
  for (const site of sites) {
    const a = LaneCore.advise(text, site, variation, allowed);
    if (a.unavailable_here) continue;
    if (!best || a.recommend.cost < best.a.recommend.cost) best = { site, a };
  }

  if (!best) {
    // Nowhere they use can do it. Say where can.
    const any = LaneCore.advise(text, sites[0], variation, allowed);
    box.innerHTML = `
      <span class="l-pill l-pill--${esc(any.lane)}">${esc(any.lane_label)}</span>
      <div class="gone">
        <div class="l-label l-alert">None of your sites can do this</div>
        ${(any.elsewhere || []).slice(0, 3).map((e) => `
          <div class="l"><b>${esc(e.site)}</b><span>${esc(e.display)}</span>
            <span class="l-num" style="flex:none">${money(e.cost)}</span></div>`).join("")}
      </div>
      <div class="go">
        ${(any.elsewhere || []).slice(0, 1).map((e) =>
          `<button class="l-btn l-btn--primary" data-goto="${esc(PROVIDER_SITE[e.provider] || "claude")}">
             Open ${esc(e.site)} ${LaneUI.icons.arrow}</button>`).join("")}
      </div>`;
    box.classList.add("show");
    wireGo();
    return;
  }

  current = best;
  const a = best.a;
  const rec = a.recommend;
  box.innerHTML = `
    <div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap">
      <span class="l-pill l-pill--${esc(a.lane)}">${esc(a.lane_label)}</span>
      <span class="l-micro">on ${esc(SITE_NAME[best.site])}</span>
    </div>
    <div class="name">
      <span class="l-lead" style="flex:1">${esc(rec.display)}</span>
      <span class="l-num" style="font-size:13px;font-weight:600">${money(rec.cost)}</span>
    </div>
    ${a.is_top ? ""
      : `<div class="save">saves ${money(a.saving)} · ${a.factor}× cheaper than ${esc((a.top||{}).display)}</div>`}
    <div class="why l-sub">${esc(a.explain)}</div>
    <div class="go">
      <button class="l-btn l-btn--primary" data-goto="${esc(best.site)}">
        Open ${esc(SITE_NAME[best.site])} ${LaneUI.icons.arrow}</button>
      <button class="l-btn" id="copy">Copy prompt</button>
    </div>`;
  box.classList.add("show");
  wireGo();

  const copy = $("copy");
  if (copy) copy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText($("what").value); copy.textContent = "copied"; }
    catch (e) { copy.textContent = "could not copy"; }
  });
}

function wireGo() {
  for (const b of document.querySelectorAll("[data-goto]")) {
    b.addEventListener("click", () => openTab(SITE_URL[b.dataset.goto]));
  }
}

$("seg").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  variation = b.dataset.v;
  for (const x of $("seg").children)
    x.setAttribute("aria-pressed", String(x.dataset.v === variation));
  LaneProfile.patch({ variation });
  const what = $("what");
  if (what && what.value.trim()) answer(what.value);
});

$("gear").addEventListener("click", openSetup);

LaneProfile.load().then((p) => {
  profile = p;
  variation = p.variation === "best" ? "best" : "save";
  for (const x of $("seg").children)
    x.setAttribute("aria-pressed", String(x.dataset.v === variation));
  render();
});
