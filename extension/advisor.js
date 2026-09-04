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
/* The same green and amber as the rows in the search card, so SAVE and
   PERFORMANCE mean one thing across every surface. */
.alts tr[data-mode="save"] td.m       { color: var(--l-save); }
.alts tr[data-mode="performance"] td.m { color: var(--l-best); }

.favs { margin-top: var(--l-3); padding-top: var(--l-3);
        border-top: 1px solid var(--l-line);
        display: flex; gap: 5px; align-items: center; flex-wrap: wrap; }

.why { margin-top: var(--l-3); padding-top: var(--l-3);
       border-top: 1px solid var(--l-line); }

/* Amber, the same amber that means "best" on every row, because that is what
   this is: the better answer, with a price on it. */
.paidnote { margin-top: var(--l-3); padding: 9px 10px;
            border-radius: var(--l-r-md); background: var(--l-best-soft);
            box-shadow: inset 3px 0 0 var(--l-best); }
.paidnote b { font-weight: 620; color: var(--l-ink); }

.settings { padding: var(--l-3); background: var(--l-panel);
            border-bottom: 1px solid var(--l-line);
            animation: l-rise .14s cubic-bezier(.2,.7,.3,1) both; }

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
.mark { display: inline-flex; width: 15px; height: 15px; flex: none; }
.mark svg { width: 100%; height: 100%; display: block; }
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
    <button class="l-icon" id="gear" title="Settings"
            aria-label="Settings" aria-expanded="false">${LaneUI.icons.gear}</button>
    <button class="l-icon" id="close" title="Hide until next reload"
            aria-label="Hide">${LaneUI.icons.close}</button>
  </div>
  <div class="settings" id="settings" hidden>
    <div class="l-toggle">
      <span class="l-toggle__text">
        <span class="l-body">Models that cost extra</span>
        <span class="l-micro" style="display:block">
          Off means only what your plan already includes.
        </span>
      </span>
      <button class="l-switch" id="paidSwitch" role="switch"
              aria-checked="false"
              aria-label="Include models that cost extra"></button>
    </div>
    <button class="l-btn--link" id="setupFull" style="margin-top:10px">
      Which models do you have?
    </button>
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
  /* Models this page has proved it does not offer.
   *
   * The catalog is a good guess about what a site's menu contains and it is
   * only a guess - menus differ by plan, by region, by whatever is being
   * rolled out this week. Rather than be wrong twice, a failed switch is
   * remembered for the rest of the page's life and the advice is recomputed
   * without it. The second suggestion is then one that works.
   *
   * Not persisted. A menu that lacked a model this morning may list it after
   * an upgrade, and a preference that outlives its evidence is a bug that
   * takes a reinstall to clear. */
  const missingHere = new Set();

  /* What a model picker's label looks like. Deliberately loose: ChatGPT's own
   * switcher has read plain "ChatGPT", and its newer one reads "Auto",
   * "Instant" or "Thinking" with no model name in it at all. */
  const MODEL_WORDS =
    /\b(opus|sonnet|haiku|chatgpt|gpt-?\s?\d|gemini|claude|o\d\s?mini|flash|pro|auto|instant|thinking)\b/i;

  const norm = (t) => String(t || "").toLowerCase()
    .replace(/[^a-z0-9.]+/g, " ").replace(/\s+/g, " ").trim();

  /* Words that make a model a DIFFERENT model rather than the same one under
   * a longer name. This is the whole difficulty: "GPT-5" and "GPT-5 mini" are
   * two models, and every containment test in the world says one is the
   * other. So the qualifiers have to match exactly, both ways. */
  const QUALIFIERS = ["mini", "nano", "lite", "micro", "small", "pro", "max",
                      "ultra", "turbo", "flash", "thinking", "instant",
                      "preview", "air", "plus", "high", "low"];

  const VENDOR = ["claude", "gpt", "chatgpt", "gemini", "openai", "google",
                  "anthropic", "the", "model"];

  const qualifiersOf = (words) =>
    QUALIFIERS.filter((q) => words.includes(q)).join(",");

  /* Does this element's text name the model we want?
   *
   * Compared on the distinctive part, because the site may show "Sonnet 5"
   * where the catalog says "Claude Sonnet 5" and the shared word "claude"
   * must not be what makes them match.
   *
   * But NOT by containment, which was the bug: "gpt 5" is a substring of
   * "gpt 5 mini", so a picker sitting on GPT-5 reported that it was already
   * on GPT-5 mini and the panel congratulated itself without switching
   * anything. Same for Gemini Pro against Gemini Pro Preview, and for every
   * other model that ships next to a smaller version of itself.
   *
   * So: the size qualifiers must be the same set on both sides, and then the
   * target's remaining distinctive words must all appear. */
  function namesModel(text, target) {
    const a = norm(text), b = norm(target);
    if (!a || !b) return false;
    if (a === b) return true;

    const aw = a.split(" "), bw = b.split(" ");
    if (qualifiersOf(aw) !== qualifiersOf(bw)) return false;

    const key = bw.filter((w) => !VENDOR.includes(w));
    return key.length > 0 && key.every((w) => aw.includes(w));
  }

  function findPicker() {
    const nodes = document.querySelectorAll(
      'button, [role="combobox"], [role="button"], [aria-haspopup]');
    const found = [];

    /* Attributes first. A control that calls itself the model selector is a
     * surer thing than one whose visible text happens to contain a model
     * name, and it keeps working when the label is "Auto". */
    for (const el of document.querySelectorAll(
        '[data-testid*="model" i], [aria-label*="model" i], [id*="model" i]')) {
      const box = el.getBoundingClientRect();
      if (!box.width || !box.height) continue;
      const text = (el.innerText || el.textContent || "").trim();
      if (text.length > 60) continue;
      found.push({ el, text, area: box.width * box.height });
    }
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

  /* The provider's mark, coloured for the ground it sits on. */
  const PROVIDER_OF = { claude: "anthropic", chatgpt: "openai", gemini: "google",
                        Claude: "anthropic", ChatGPT: "openai", Gemini: "google" };
  function markFor(key) {
    const b = LaneUI.brands[PROVIDER_OF[key] || key];
    if (!b) return "";
    const dark = matchMedia && matchMedia("(prefers-color-scheme: dark)").matches;
    return `<span class="mark" style="color:${dark ? b.dark : b.on}"
                  aria-hidden="true">${b.svg}</span>`;
  }


  /* A content script may not navigate to a chrome-extension:// URL - Chrome
   * refuses it as ERR_BLOCKED_BY_CLIENT, indistinguishable from an ad
   * blocker - so it asks the service worker to open the page instead. */
  function openSetupPage() {
    try {
      if (typeof chrome !== "undefined" && chrome.runtime
          && chrome.runtime.sendMessage) {
        chrome.runtime.sendMessage({ type: "lane:open-setup" });
        return;
      }
    } catch (e) { /* fall through to the dev harness */ }
    window.open(BASE.replace(/\/$/, "") + "/dev/ext/onboarding.html", "_blank");
  }

  /* A pointer sequence, not a .click().
   *
   * el.click() fires exactly one untrusted `click` and nothing else. Claude,
   * ChatGPT and Gemini all build their pickers on headless component
   * libraries - Radix and friends - whose menus open on POINTERDOWN and whose
   * items commit on pointerup or mousedown. None of those handlers ever sees
   * a bare click, so the menu stays shut, the option is never found, and the
   * panel says the model is "not in this page's list" while the list is right
   * there unopened.
   *
   * Everything below is dispatched in the order a real mouse produces it, at
   * the element's own centre, with the button flags a primary click carries.
   * They are still untrusted events - an extension cannot forge trusted ones
   * - but untrusted events with the right names in the right order are what
   * these libraries listen for. */
  function realClick(el) {
    if (!el) return false;
    const box = el.getBoundingClientRect();
    const x = box.left + box.width / 2;
    const y = box.top + box.height / 2;
    const base = {
      bubbles: true, cancelable: true, composed: true, view: window,
      clientX: x, clientY: y, screenX: x, screenY: y,
      button: 0, buttons: 1, detail: 1,
    };
    const pointer = Object.assign({ pointerId: 1, pointerType: "mouse",
                                    isPrimary: true, width: 1, height: 1 }, base);

    const fire = (Type, name, init) => {
      try { el.dispatchEvent(new Type(name, init)); } catch (e) { /* older API */ }
    };

    // Hover first: some menus only mount their trigger's handlers on enter.
    fire(PointerEvent, "pointerover", pointer);
    fire(PointerEvent, "pointerenter", pointer);
    fire(MouseEvent, "mouseover", base);
    fire(MouseEvent, "mousemove", base);

    fire(PointerEvent, "pointerdown", pointer);
    fire(MouseEvent, "mousedown", base);
    try { if (el.focus) el.focus({ preventScroll: true }); } catch (e) { /* fine */ }
    fire(PointerEvent, "pointerup", Object.assign({}, pointer, { buttons: 0 }));
    fire(MouseEvent, "mouseup", Object.assign({}, base, { buttons: 0 }));
    fire(MouseEvent, "click", Object.assign({}, base, { buttons: 0 }));

    // And the plain call as well, for anything that only wired onclick. It is
    // idempotent for a menu that has already acted on the sequence above.
    try { el.click(); } catch (e) { /* fine */ }
    return true;
  }

  /* Some pickers are a div with the handler on an ancestor, and some put it on
   * an inner span. Walking up a few levels costs nothing and catches both. */
  function clickThrough(el) {
    realClick(el);
    for (let up = el.parentElement, i = 0; up && i < 2; up = up.parentElement, i++) {
      if (up.getAttribute && (up.getAttribute("role") === "option"
          || up.getAttribute("role") === "menuitem"
          || up.tagName === "BUTTON")) {
        realClick(up);
        break;
      }
    }
  }

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
      () => realClick(picker.el),
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

    realClick(picker.el);
    const option = await findOption(target);
    if (!option) {
      await closeMenu(picker);
      return { ok: false, why: target + " is not in this page's list" };
    }
    clickThrough(option);
    await sleep(220);
    await closeMenu(picker);

    /* These pickers update from state, not synchronously from the click, and
     * on a slow tab that can take longer than one 220ms nap. Checking once
     * and reporting failure was calling a switch that did work a failure,
     * which is worse than being slow to confirm it. */
    const deadline = Date.now() + 1200;
    for (;;) {
      const after = findPicker();
      if (after && namesModel(after.text, target)) return { ok: true };
      if (Date.now() >= deadline) break;
      await sleep(90);
    }
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
        ${markFor(e.site)}
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
      <tr class="${o.id === rec.id ? "on" : ""}" data-mode="${esc(o.mode)}">
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
            <span class="l-lead" style="flex:1">${esc(rec.display)}${
              LaneProfile.isPaid(rec.id)
                ? ` <span class="l-label l-warn">costs extra</span>` : ""}</span>
            <span class="l-num" style="font-size:13px;font-weight:600">${money(rec.cost)}</span>
          </div>
          ${headline}
          ${findPicker() ? `
          <button class="l-btn l-btn--primary l-btn--block" id="use"
                  style="margin-top:10px">
            Use ${esc(rec.display)} ${LaneUI.icons.arrow}
          </button>` : `
          <button class="l-btn l-btn--block" id="copy" style="margin-top:10px">
            Copy \u201c${esc(rec.display)}\u201d
          </button>
          <div class="l-micro" style="margin-top:5px">
            This page has no model menu to switch \u2014 sign in, or open a
            chat, and the button becomes a switch.
          </div>`}
          <div class="useout" id="useout"></div>
        </div>
        ${rows ? `<table class="alts">${rows}</table>` : ""}
        ${favouriteRow(rec.id)}
        <div class="why l-sub">${esc(a.explain)}</div>
        ${(a.withPaid || a.paidOn) ? `<div class="paidnote">
           <span class="l-label l-warn">${a.paidOn ? "Paid models on" : "Costs extra"}</span>
           ${a.withPaid ? `<div class="l-sub" style="margin-top:3px">
             <b>${esc(a.withPaid.display)}</b> would ${
               a.withPaid.cost < (rec.cost || 0) ? "cost less" : "fit this better"
             }, but it is not on the free plan${a.withPaid.cost ? " \u2014 about "
               + money(a.withPaid.cost) + " on the API" : ""}.
           </div>` : `<div class="l-sub" style="margin-top:3px">
             Suggestions may name a model your plan does not include.
           </div>`}
           <div class="l-toggle" style="margin-top:7px">
             <span class="l-toggle__text l-sub">Include models that cost extra</span>
             <button class="l-switch" id="showPaid" role="switch"
                     aria-checked="${a.paidOn ? "true" : "false"}"
                     aria-label="Include models that cost extra"></button>
           </div>
         </div>` : ""}
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

    const copyBtn = root.getElementById("copy");
    if (copyBtn) copyBtn.addEventListener("click", async () => {
      copyBtn.textContent = (await copyName(rec.display))
        ? "copied" : "could not copy \u2014 " + rec.display;
    });

    const showPaid = root.getElementById("showPaid");
    if (showPaid) showPaid.addEventListener("click",
      () => setPaid(showPaid.getAttribute("aria-checked") !== "true"));

    const setupLink = root.getElementById("setupLink");
    if (setupLink) setupLink.addEventListener("click", openSetupPage);

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
        /* Whatever the detail, this model could not be selected here.
         *
         * There are two ways that comes back - the menu did not contain it,
         * or it was clicked and the label never changed - and from where
         * somebody is sitting those are one thing: the panel offered a model
         * and the model did not happen. Both strike it off for this page and
         * recompute, so the next line is a suggestion that works rather than
         * an apology. Only a page with no menu at all is different, and that
         * is caught before the button is drawn. */
        if (/not in this page|did not switch/.test(r.why || "")) {
          missingHere.add(rec.id);
          out.className = "useout";
          out.textContent = rec.display + " is not in this page's menu \u2014 "
                          + "finding you another";
          allowedModels = withoutMissing(LaneProfile.allowed(profile));
          if (lastText) { advise(lastText); return; }
        }
        out.className = "useout bad";
        out.textContent = r.why;
        if (await copyName(rec.display)) {
          out.textContent = r.why + " \u2014 name copied instead";
        }
      }
    });
    show();
  }

  /* The settings drawer.
   *
   * Wired once, here, rather than in renderAdvice: it lives outside #content
   * so it survives every re-render, and a listener attached per render would
   * accumulate one copy per keystroke.
   *
   * Both switches for the same setting stay in step because flipping either
   * one re-advises, and re-advising re-renders the note that holds the other.
   */
  const gearBtn = root.getElementById("gear");
  const settingsEl = root.getElementById("settings");
  const paidSwitch = root.getElementById("paidSwitch");

  gearBtn.addEventListener("click", () => {
    const open = settingsEl.hidden;
    settingsEl.hidden = !open;
    gearBtn.setAttribute("aria-expanded", String(open));
    if (open) paintPaidSwitch();
  });

  function paintPaidSwitch() {
    paidSwitch.setAttribute("aria-checked",
                            String(!!(profile && profile.paid)));
  }

  function setPaid(on) {
    if (!profile) return;
    profile.paid = on;
    LaneProfile.patch({ paid: on });
    allowedModels = withoutMissing(LaneProfile.allowed(profile));
    paintPaidSwitch();
    if (lastText) advise(lastText);
  }

  paidSwitch.addEventListener("click",
    () => setPaid(paidSwitch.getAttribute("aria-checked") !== "true"));

  root.getElementById("setupFull").addEventListener("click", openSetupPage);

  /* The scoreboard. Deliberately says "could have saved": LANE cannot see
     which model you actually picked, and a tool that counts its own advice as
     though it were always taken is flattering itself with the very number it
     is selling on. */
  let serverPresent = false;

  /* Kept in the browser, so the number is there on a machine that has never
     run `lane serve` - which is every machine, for anybody who installed this
     from the store and quite reasonably expects an extension to be an
     extension. The local proxy, when it is running, is the more accurate
     source and takes over. */
  const LEDGER_KEY = "lane.ledger";
  let ledger = { messages: 0, saved: 0 };

  function readLedger() {
    return new Promise((resolve) => {
      try {
        if (typeof chrome !== "undefined" && chrome.storage) {
          chrome.storage.local.get(LEDGER_KEY, (v) =>
            resolve((v || {})[LEDGER_KEY] || { messages: 0, saved: 0 }));
          return;
        }
        resolve(JSON.parse(localStorage.getItem(LEDGER_KEY) || "null")
                || { messages: 0, saved: 0 });
      } catch (e) { resolve({ messages: 0, saved: 0 }); }
    });
  }

  function writeLedger(v) {
    try {
      if (typeof chrome !== "undefined" && chrome.storage) {
        chrome.storage.local.set({ [LEDGER_KEY]: v });
        return;
      }
      localStorage.setItem(LEDGER_KEY, JSON.stringify(v));
    } catch (e) { /* a counter that will not stick is not an error */ }
  }

  function countLocally(a) {
    ledger = {
      messages: ledger.messages + 1,
      saved: ledger.saved + Math.max(0, (a.top.cost || 0) - (a.recommend.cost || 0)),
    };
    writeLedger(ledger);
    renderScore(ledger.messages, ledger.saved);
  }

  function renderScore(messages, saved) {
    if (!messages) { scoreEl.style.display = "none"; return; }
    scoreEl.style.display = "flex";
    scoreEl.innerHTML =
      `could have saved <b>${money(saved)}</b>` +
      `<span class="n">${messages} message${messages === 1 ? "" : "s"}</span>`;
  }

  async function refreshScore() {
    if (!serverPresent) { renderScore(ledger.messages, ledger.saved); return; }
    try {
      const s = await (await fetch(BASE + "/lane/advice-stats")).json();
      renderScore(s.messages, s.potential_saving);
    } catch { renderScore(ledger.messages, ledger.saved); }
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

      /* What this would have said if money were no object.
       *
       * Filtering paid models out and saying nothing about it turns the panel
       * into a liar by omission: somebody on a free plan would be told Sonnet
       * is the answer to a question Opus is measurably better at, with no way
       * to know the trade was made on their behalf. So the comparison is run
       * both ways and the difference is reported - once, quietly, with the
       * price attached and a switch beside it.
       *
       * Only when it is a DIFFERENT model. Most requests do not have a better
       * paid answer, and a paywall note under every one of those is an advert.
       */
      /* Computed when paid models are ON as well as off.
       *
       * A control that only exists while it is switched off is a control you
       * cannot undo: the old link turned paid models on and then vanished
       * along with the note it lived in, and the only way back was a
       * different screen. */
      a.paidOn = !!(profile && profile.paid);
      a.withPaid = null;
      if (profile && profile.paid) {
        // Nothing to offer - the switch is on. The note reports that.
      } else if (profile && !profile.paid && !a.unavailable_here) {
        const uncapped = LaneCore.advise(
          text, SITE, variation, LaneProfile.allowedIgnoringCost(profile));
        if (uncapped && uncapped.recommend
            && uncapped.recommend.id !== (a.recommend || {}).id
            && LaneProfile.isPaid(uncapped.recommend.id)) {
          a.withPaid = uncapped.recommend;
        }
      }
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
  /* Whatever this person allows, minus what this page has proved it lacks. */
  function withoutMissing(ids) {
    if (!missingHere.size) return ids;
    const all = (ids && ids.length ? ids : LaneCore.MODELS.map((m) => m.id));
    return all.filter((id) => !missingHere.has(id));
  }

  let allowedModels = null;
  let profile = null;

  async function loadProfile() {
    try {
      profile = await LaneProfile.load();
      allowedModels = withoutMissing(LaneProfile.allowed(profile));
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
    if (a && !a.unavailable_here && a.recommend && a.top) countLocally(a);
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
  /* The panel is complete before any of this resolves. Everything below only
     makes it know more: who this person is, then - if and only if something
     is listening on this machine - what it has recorded. Nothing here is a
     precondition, which is why there is no command to run. */
  /* ── arriving from a search ────────────────────────────────────────────
   * Somebody clicked a model on Google and this is the tab that opened. The
   * question is waiting in extension storage; put it in the box.
   *
   * Typed rather than assigned. Every one of these composers is driven by a
   * framework that tracks its own state, and setting .value or .textContent
   * behind its back leaves the visible text and the state disagreeing - the
   * words are on screen and the send button stays disabled. The native
   * setter plus an input event is how you tell React; execCommand is how you
   * tell a contenteditable. */
  const HANDOFF_KEY = "lane.handoff";
  const HANDOFF_TTL = 90 * 1000;

  function fillComposer(text) {
    /* The biggest visible text field on the page.
     *
     * NOT "wider than 120px", which is what this said first and which is a
     * guess about somebody else's layout: a composer in a narrow window, a
     * split view or a phone is none of those things, and the handoff then
     * silently did nothing. Largest area is the honest version of the same
     * idea - on a chat site the thing you type into is the biggest box on
     * the screen. */
    let el = null, best = 0;
    for (const n of document.querySelectorAll(
        'textarea, [contenteditable="true"], [role="textbox"]')) {
      const b = n.getBoundingClientRect();
      const area = b.width * b.height;
      if (!area) continue;                         // hidden
      if (n.disabled || n.readOnly) continue;
      if (area > best) { best = area; el = n; }
    }
    if (!el) return false;

    try { el.focus({ preventScroll: false }); } catch (e) { /* fine */ }

    if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") {
      const proto = el.tagName === "TEXTAREA"
        ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
      setter.call(el, text);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    }

    // contenteditable: execCommand is deprecated and is still the only thing
    // every rich composer treats as real typing.
    let ok = false;
    try { ok = document.execCommand("insertText", false, text); } catch (e) { /* fine */ }
    if (!ok) {
      el.textContent = text;
      el.dispatchEvent(new InputEvent("input", {
        bubbles: true, inputType: "insertText", data: text }));
    }
    return true;
  }

  function readHandoff() {
    return new Promise((resolve) => {
      try {
        if (typeof chrome !== "undefined" && chrome.storage) {
          chrome.storage.local.get(HANDOFF_KEY, (v) =>
            resolve((v || {})[HANDOFF_KEY] || null));
          return;
        }
        resolve(JSON.parse(localStorage.getItem(HANDOFF_KEY) || "null"));
      } catch (e) { resolve(null); }
    });
  }

  function clearHandoff() {
    try {
      if (typeof chrome !== "undefined" && chrome.storage) {
        chrome.storage.local.remove(HANDOFF_KEY);
        return;
      }
      localStorage.removeItem(HANDOFF_KEY);
    } catch (e) { /* it will time out on its own */ }
  }

  async function collectHandoff() {
    const held = await readHandoff();
    if (!held || held.site !== SITE) return;
    // Consumed once, and only if it is recent: a tab opened today must not
    // pick up a question from last week.
    clearHandoff();
    if (Date.now() - (held.at || 0) > HANDOFF_TTL) return;

    // The composer may not exist yet on a site that is still booting.
    const deadline = Date.now() + 8000;
    for (;;) {
      if (fillComposer(held.text)) return;
      if (Date.now() >= deadline) return;
      await sleep(200);
    }
  }

  collectHandoff();

  readLedger()
    .then((v) => { ledger = v; renderScore(v.messages, v.saved); })
    .then(loadProfile)
    .then(loadLocalPreferences)
    .then(refreshScore);
})();
