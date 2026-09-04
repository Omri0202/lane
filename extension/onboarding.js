/*
 * onboarding.js — the behaviour behind onboarding.html.
 *
 * In a file rather than inline because an extension page runs under
 * `script-src 'self'`: MV3 refuses every <script> with a body in it,
 * and it refuses it quietly - the markup renders, the handlers simply
 * never attach.
 */

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s)
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");

$("logo").innerHTML = LaneUI.icons.mark;

const SITES = [
  { id:"claude",  provider:"anthropic", name:"Claude",  d:"claude.ai" },
  { id:"chatgpt", provider:"openai",    name:"ChatGPT", d:"chatgpt.com" },
  { id:"gemini",  provider:"google",    name:"Gemini",  d:"gemini.google.com" },
];

const FOCUS = [
  { id:"code",     t:"Code",            d:"debugging, writing functions, reviewing" },
  { id:"writing",  t:"Writing",         d:"drafting, editing, summarising" },
  { id:"research", t:"Looking things up", d:"questions, explanations, current information" },
  { id:"images",   t:"Images",          d:"making pictures, or reading them" },
];

let profile = null;
let step = 0;

const money = (n) => n < 0.01 ? "$" + n.toFixed(4) : "$" + n.toFixed(2);

// ── the questions ────────────────────────────────────────────────────────────
const steps = [
  {
    title: "Which of these do you actually use?",
    sub: "The panel only appears on sites you pick, and only ever suggests models those sites can give you.",
    render() {
      return `<div class="opts">${SITES.map((s) => `
        <label class="opt ${profile.sites.includes(s.id) ? "on" : ""}">
          <input type="checkbox" data-site="${s.id}" ${profile.sites.includes(s.id) ? "checked" : ""}>
          <span><span class="t">${s.name}</span><span class="d">${s.d}</span></span>
        </label>`).join("")}</div>
        <div class="note">You can change any of this later from the panel.</div>`;
    },
    read() {
      profile.sites = [...document.querySelectorAll("[data-site]")]
        .filter((c) => c.checked).map((c) => c.dataset.site);
      if (!profile.sites.length) profile.sites = SITES.map((s) => s.id);
    },
  },
  {
    title: "Which models can you pick?",
    sub: "Ticked is what LANE may suggest. Models marked ‘costs extra’ are off to begin with — being told to use one you cannot reach is not advice, it is a chore with a paywall at the end.",
    render() {
      const wanted = new Set(profile.sites.map(
        (id) => (SITES.find((s) => s.id === id) || {}).provider));
      const chosen = new Set(profile.models);
      const known = profile.models.length > 0;
      // An unanswered question shows the default that is actually in force -
      // free models ticked, paid ones not - rather than everything ticked and
      // a panel that then quietly ignores half of it.
      const ticked = (m) => known ? chosen.has(m.id)
                                  : (profile.paid || m.plan !== "paid");
      const groups = SITES.filter((s) => wanted.has(s.provider)).map((s) => {
        const models = LaneCore.MODELS
          .filter((m) => m.provider === s.provider && m.kind === "chat")
          .sort((a, b) => b.tier - a.tier);
        if (!models.length) return "";
        return `<div class="group"><span class="l-label">${s.name}</span><div class="opts">${
          models.map((m) => `
            <label class="opt ${ticked(m) ? "on" : ""}">
              <input type="checkbox" data-model="${esc(m.id)}"
                     ${ticked(m) ? "checked" : ""}>
              <span><span class="t">${esc(m.display)}${m.plan === "paid"
                      ? ` <span class="l-label l-warn">costs extra</span>` : ""}</span>
                    <span class="d">${esc(m.strengths.join(" · ") || "general")}</span></span>
              <span class="p">${money(m.in_price)} / ${money(m.out_price)} per Mtok</span>
            </label>`).join("")}</div></div>`;
      }).join("");
      return groups || `<div class="note">Nothing to choose — go back and pick a site.</div>`;
    },
    read() {
      const boxes = [...document.querySelectorAll("[data-model]")];
      const on = boxes.filter((c) => c.checked).map((c) => c.dataset.model);
      // Everything ticked means "no restriction", not a list that goes stale
      // the next time a model is added.
      profile.models = on.length === boxes.length ? [] : on;
      // Ticking one is the consent. Otherwise somebody enables Opus here and
      // the panel keeps hiding it because a switch two screens away is off.
      if (on.some((id) => LaneProfile.isPaid(id))) profile.paid = true;
    },
  },
  {
    title: "Star the ones you reach for.",
    sub: "Favourites get offered as one-click switches, whatever the classifier thinks. Optional — skip if you have no strong feelings.",
    render() {
      const permitted = LaneProfile.allowed(profile);
      const models = LaneCore.MODELS
        .filter((m) => m.kind === "chat" && (!permitted || permitted.includes(m.id)))
        .sort((a, b) => b.tier - a.tier);
      return `<div class="opts">${models.map((m) => {
        const on = profile.favourites.includes(m.id);
        return `
        <div class="opt">
          <span><span class="t">${esc(m.display)}</span>
                <span class="d">${esc(m.provider)} · ${esc(m.strengths.join(" · ") || "general")}</span></span>
          <button class="l-icon star ${on ? "on" : ""}" data-fav="${esc(m.id)}"
                  title="Favourite" aria-pressed="${on}"
                  >${on ? LaneUI.icons.star : LaneUI.icons.starOutline}</button>
        </div>`; }).join("")}</div>`;
    },
    wire() {
      for (const b of document.querySelectorAll("[data-fav]")) {
        b.addEventListener("click", () => {
          const id = b.dataset.fav;
          const i = profile.favourites.indexOf(id);
          if (i === -1) profile.favourites.push(id);
          else profile.favourites.splice(i, 1);
          const on = i === -1;
          b.classList.toggle("on", on);
          b.setAttribute("aria-pressed", String(on));
          b.innerHTML = on ? LaneUI.icons.star : LaneUI.icons.starOutline;
        });
      }
    },
    read() {},
  },
  {
    title: "What do you mostly do?",
    sub: "Used to order the shortcuts in the launcher. It never overrides what you actually type — the request in front of it always wins.",
    render() {
      return `<div class="opts">${FOCUS.map((f) => `
        <label class="opt ${profile.focus.includes(f.id) ? "on" : ""}">
          <input type="checkbox" data-focus="${f.id}" ${profile.focus.includes(f.id) ? "checked" : ""}>
          <span><span class="t">${f.t}</span><span class="d">${f.d}</span></span>
        </label>`).join("")}</div>`;
    },
    read() {
      profile.focus = [...document.querySelectorAll("[data-focus]")]
        .filter((c) => c.checked).map((c) => c.dataset.focus);
    },
  },
  {
    title: "By default, cheap or best?",
    sub: "You can flip this on any message with the toggle in the panel.",
    render() {
      const opt = (id, t, d) => `
        <label class="opt ${profile.variation === id ? "on" : ""}">
          <input type="radio" name="v" data-var="${id}" ${profile.variation === id ? "checked" : ""}>
          <span><span class="t">${t}</span><span class="d">${d}</span></span>
        </label>`;
      return `<div class="opts">
        ${opt("save","Save money","The cheapest model that still does the job properly.")}
        ${opt("best","Best answer","The model whose strengths fit the request. Not always the priciest.")}
      </div>
      <div class="note">
        That is everything. It runs entirely in your browser — no account, no
        API key, no server, nothing sent anywhere. Close this and it is already
        working.
      </div>`;
    },
    read() {
      const on = document.querySelector("[data-var]:checked");
      profile.variation = on ? on.dataset.var : "save";
    },
  },
];

// ── the shell ────────────────────────────────────────────────────────────────
function draw() {
  $("dots").innerHTML = steps.map((_, i) =>
    `<i class="${i <= step ? "on" : ""}"></i>`).join("");
  $("count").textContent = step < steps.length
    ? `${step + 1} of ${steps.length}` : "";

  if (step >= steps.length) return finish();

  const s = steps[step];
  $("card").innerHTML =
    `<h1 class="l-h1">${s.title}</h1><p class="sub">${s.sub}</p>${s.render()}`;
  if (s.wire) s.wire();

  for (const el of document.querySelectorAll(".opt input")) {
    el.addEventListener("change", () => {
      if (el.type === "radio") {
        for (const o of document.querySelectorAll(".opt")) o.classList.remove("on");
      }
      el.closest(".opt").classList.toggle("on", el.checked);
    });
  }

  // Hidden, not invisible: an invisible Back still holds its width, and
  // Continue then sits a button-width off the column it belongs to.
  $("back").style.display = step === 0 ? "none" : "";
  $("next").textContent = step === steps.length - 1 ? "Finish" : "Continue";
}

async function finish() {
  profile.onboarded = true;
  await LaneProfile.save(profile);
  const permitted = LaneProfile.allowed(profile);
  const count = permitted ? permitted.length : LaneCore.MODELS.length;
  $("card").innerHTML = `
    <div class="done">
      <div class="tick">${LaneUI.icons.check}</div>
      <h1 class="l-h1">Ready.</h1>
      <p class="sub">
        Open ${profile.sites.map((id) =>
          (SITES.find((s) => s.id === id) || {}).name).join(", ")} and start
        typing — the panel appears in the corner once you are a few words in.
      </p>
      <p class="note" style="margin-left:auto;margin-right:auto">
        Advising across ${count} model${count === 1 ? "" : "s"},
        ${LaneProfile.favourites(profile).length} starred,
        defaulting to ${profile.variation === "best" ? "the best fit" : "the cheapest that fits"}.
      </p>
    </div>`;
  $("back").style.display = "none";
  $("next").textContent = "Close";
  $("skip").style.display = "none";
  $("next").onclick = () => window.close();
}

$("next").addEventListener("click", () => {
  if (step < steps.length) { steps[step].read(); step++; draw(); }
});
$("back").addEventListener("click", () => { if (step > 0) { step--; draw(); } });
$("skip").addEventListener("click", () => { step++; draw(); });

LaneProfile.load().then((p) => { profile = p; draw(); });
