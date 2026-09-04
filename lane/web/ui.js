/*
 * ui.js — one design system, used by every surface.
 *
 * There were six. The panel, the search card, the launcher, the interview, the
 * chat page and the setup page each carried their own token block with values
 * that had drifted a shade apart, their own button styles and their own idea of
 * how big a label is. That is what "looks unprofessional" actually means most
 * of the time: not bad taste in any one place, but six places that were never
 * decided together.
 *
 * Everything below is deliberate and small enough to hold in your head:
 *
 *   A 4px spacing scale, so nothing sits at an arbitrary distance from
 *   anything else.
 *
 *   Six type sizes and no more. A label is 10px with wide tracking, body is
 *   13px, the one thing a view is about is 15px, headings are 19 and 23. When
 *   every size means something, hierarchy comes for free.
 *
 *   One accent colour, used only for the action a person is meant to take. A
 *   second accent would make both of them decorative.
 *
 *   One elevation. Cards float; nothing else does.
 *
 * Shadow roots take `LaneUI.css` as a string; ordinary pages call
 * `LaneUI.mount()`, which puts the same string in a <style> tag. One source,
 * so they cannot drift again.
 */

const LaneUI = (() => {
  "use strict";

  const css = `
:host, :root {
  /* Neutral ramp. Light by default, redefined once for dark, never per-file. */
  --l-bg:      #ffffff;
  --l-panel:   #f7f8fa;
  --l-sunk:    #f0f2f5;
  --l-line:    #e4e7ec;
  --l-line-2:  #d3d8e0;
  --l-ink:     #14171a;
  --l-dim:     #616a75;
  --l-faint:   #98a1ad;

  /* One accent, for the action you are meant to take. */
  --l-accent:      #3455f0;
  --l-accent-ink:  #ffffff;
  --l-accent-soft: #3455f014;

  --l-good:  #12805c;
  --l-warn:  #9a6700;
  --l-alert: #c0362c;

  /* 4px scale. */
  --l-1: 4px;  --l-2: 8px;  --l-3: 12px;
  --l-4: 16px; --l-5: 24px; --l-6: 32px;

  --l-r-sm: 8px; --l-r-md: 11px; --l-r-lg: 15px;

  --l-shadow: 0 12px 32px -8px rgba(16,24,40,.18),
              0 2px 6px -1px rgba(16,24,40,.08),
              0 0 0 1px rgba(16,24,40,.05);

  --l-font: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI",
            Roboto, "Helvetica Neue", Arial, sans-serif;
  --l-mono: ui-monospace, "Cascadia Mono", "SF Mono", Menlo, monospace;
}

@media (prefers-color-scheme: dark) {
  :host, :root {
    --l-bg:      #16181d;
    --l-panel:   #1d2027;
    --l-sunk:    #22262e;
    --l-line:    #2a2f38;
    --l-line-2:  #39404b;
    --l-ink:     #e9ebef;
    --l-dim:     #9aa3af;
    --l-faint:   #6b7480;

    --l-accent:      #6d8bff;
    --l-accent-ink:  #0d1016;
    --l-accent-soft: #6d8bff1f;

    --l-good:  #46c88f;
    --l-warn:  #e0b050;
    --l-alert: #ff7b6b;

    --l-shadow: 0 14px 40px -10px rgba(0,0,0,.6),
                0 2px 8px -2px rgba(0,0,0,.4),
                0 0 0 1px rgba(255,255,255,.06);
  }
}

*, *::before, *::after { box-sizing: border-box; }

/* ── shadow-root isolation ────────────────────────────────────────────────
   A shadow root is not a style boundary for inherited properties: the host
   page's font, colour, text-align and direction all come straight through.

   'all: initial' catches most of it and pointedly does NOT catch 'direction'
   or 'unicode-bidi' - the spec exempts them. That exemption is why the card
   came out mirrored on a Hebrew page: close button on the wrong side, labels
   flushed right, full stops leading the sentence instead of ending it. Our
   text is English wherever the page is, so it is stated rather than
   inherited.

   Custom properties survive 'all', so the tokens above are untouched.        */
:host {
  all: initial;
  display: block;
  direction: ltr;
  unicode-bidi: isolate;
  text-align: left;
  font: 13px/1.55 var(--l-font);
  color: var(--l-ink);
  -webkit-font-smoothing: antialiased;
}

/* ── type ─────────────────────────────────────────────────────────────────
   Six sizes. A label is not a small body; it is its own thing, and giving it
   tracking and weight is what stops a dense panel reading as a wall.        */
.l-label {
  font-size: 10px; font-weight: 700; letter-spacing: .09em;
  text-transform: uppercase; color: var(--l-faint);
}
.l-micro { font-size: 11px; color: var(--l-faint); line-height: 1.45; }
.l-sub   { font-size: 12px; color: var(--l-dim);   line-height: 1.5; }
.l-body  { font-size: 13px; color: var(--l-ink);   line-height: 1.55; }
.l-lead  { font-size: 15px; font-weight: 620; letter-spacing: -.005em; }
.l-h2    { font-size: 19px; font-weight: 640; letter-spacing: -.012em;
           line-height: 1.3; }
.l-h1    { font-size: 23px; font-weight: 650; letter-spacing: -.018em;
           line-height: 1.25; }

/* Prices line up under each other or they look like a mistake. */
.l-num { font-variant-numeric: tabular-nums; font-feature-settings: "tnum" 1; }

/* ── surfaces ─────────────────────────────────────────────────────────── */
.l-card {
  background: var(--l-bg); color: var(--l-ink);
  border-radius: var(--l-r-lg);
  box-shadow: var(--l-shadow);
  overflow: hidden;
  font-family: var(--l-font);
}
.l-head {
  display: flex; align-items: center; gap: var(--l-2);
  padding: 10px var(--l-3);
  background: var(--l-panel);
  border-bottom: 1px solid var(--l-line);
}
.l-brand {
  font-size: 10px; font-weight: 800; letter-spacing: .16em;
  color: var(--l-faint);
}
.l-grow { flex: 1 1 auto; min-width: 0; }
.l-pad  { padding: var(--l-3); }
.l-rule { border: 0; border-top: 1px solid var(--l-line);
          margin: var(--l-3) 0; }

/* ── controls ─────────────────────────────────────────────────────────────
   One primary. Everything else recedes, because two things competing for the
   same click means neither is the answer.                                   */
.l-btn {
  display: inline-flex; align-items: center; justify-content: center;
  gap: 6px; font: inherit; font-size: 13px; font-weight: 560;
  padding: 9px var(--l-3); border-radius: var(--l-r-md);
  border: 1px solid var(--l-line-2); background: var(--l-bg);
  color: var(--l-ink); cursor: pointer;
  transition: background .13s ease, border-color .13s ease,
              transform .06s ease;
}
.l-btn:hover  { background: var(--l-sunk); }
.l-btn:active { transform: translateY(.5px); }
.l-btn:disabled { opacity: .45; cursor: default; transform: none; }
.l-btn:focus-visible {
  outline: 2px solid var(--l-accent); outline-offset: 2px;
}

.l-btn--primary {
  background: var(--l-accent); color: var(--l-accent-ink);
  border-color: transparent; font-weight: 620;
}
.l-btn--primary:hover { background: var(--l-accent); filter: brightness(1.08); }

.l-btn--quiet {
  border-color: transparent; background: transparent; color: var(--l-dim);
  padding: 6px var(--l-2);
}
.l-btn--quiet:hover { background: var(--l-sunk); color: var(--l-ink); }

.l-btn--link {
  border: 0; background: none; padding: 0; color: var(--l-accent);
  font-size: 12px; font-weight: 520; cursor: pointer;
}
.l-btn--link:hover { text-decoration: underline; }

.l-btn--block { width: 100%; }

/* An inline <svg> with no width is a replaced element: the browser gives it
   300x150 and flex squashes it into something enormous. Every button that
   carries an icon needs this, and it is easy to miss because it looks fine
   until the first time you actually put an icon in one. */
.l-btn svg { width: 15px; height: 15px; flex: none; }

/* An icon button is square and quiet, and never smaller than a fingertip. */
.l-icon {
  display: inline-flex; align-items: center; justify-content: center;
  width: 26px; height: 26px; padding: 0;
  border: 0; border-radius: var(--l-r-sm);
  background: transparent; color: var(--l-faint); cursor: pointer;
  transition: background .13s ease, color .13s ease;
}
.l-icon:hover { background: var(--l-sunk); color: var(--l-ink); }
.l-icon svg { width: 15px; height: 15px; display: block; }

/* Segmented control, for a choice between two or three things. */
.l-seg {
  display: inline-flex; gap: 2px; padding: 2px;
  background: var(--l-sunk); border-radius: var(--l-r-sm);
}
.l-seg button {
  border: 0; background: transparent; color: var(--l-dim);
  font: inherit; font-size: 10px; font-weight: 700; letter-spacing: .07em;
  padding: 4px 10px; border-radius: 6px; cursor: pointer;
  transition: background .13s ease, color .13s ease;
}
.l-seg button[aria-pressed="true"] {
  background: var(--l-bg); color: var(--l-ink);
  box-shadow: 0 1px 2px rgba(16,24,40,.10);
}

/* ── a choosable row ───────────────────────────────────────────────────────
   The workhorse: a label, a name with its context under it, and a number on
   the right. Used for model picks, providers and options alike, so those all
   read as the same kind of thing.                                           */
.l-row {
  display: flex; align-items: center; gap: 10px; width: 100%;
  padding: 9px 11px; text-align: left;
  border: 1px solid var(--l-line); border-radius: var(--l-r-md);
  background: var(--l-bg); color: var(--l-ink);
  font: inherit; cursor: pointer;
  transition: border-color .13s ease, background .13s ease;
}
.l-row:hover { border-color: var(--l-accent); background: var(--l-accent-soft); }
.l-row:focus-visible { outline: 2px solid var(--l-accent); outline-offset: 2px; }
/* A chevron that leans in on hover. A row that opens something should say so
   before it is clicked, not after. */
.l-row__go { flex: none; color: var(--l-faint); display: flex;
             transition: transform .13s ease, color .13s ease; }
.l-row__go svg { width: 14px; height: 14px; display: block; }
.l-row:hover .l-row__go { color: var(--l-accent); transform: translateX(2px); }
.l-row + .l-row { margin-top: 6px; }
.l-row__tag  { width: 54px; flex: none; }
.l-row__main { flex: 1 1 auto; min-width: 0; }
.l-row__name { font-size: 13px; font-weight: 620; display: block;
               overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.l-row__note { font-size: 11px; color: var(--l-dim); display: block;
               overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.l-row__end  { font-size: 12px; font-weight: 600; white-space: nowrap;
               font-variant-numeric: tabular-nums; }

/* ── lane pills ───────────────────────────────────────────────────────────
   One hue per kind of request, at low saturation so a page of them does not
   look like a toybox.                                                       */
.l-pill {
  display: inline-block; padding: 3px 9px; border-radius: 999px;
  font-size: 10px; font-weight: 700; letter-spacing: .05em;
  text-transform: uppercase;
}
.l-pill--trivial    { background: #8a919b1f; color: var(--l-dim); }
.l-pill--simple     { background: #0d94881f; color: #0b7c72; }
.l-pill--general    { background: #3455f01f; color: #2c47cc; }
.l-pill--longform   { background: #b4780a1f; color: #9a6700; }
.l-pill--reasoning  { background: #7c4ddd1f; color: #6a3fc4; }
.l-pill--vision     { background: #0891b21f; color: #0a7d99; }
.l-pill--tools      { background: #15954c1f; color: #12804a; }
.l-pill--translate  { background: #8b3fd41f; color: #7734b8; }
.l-pill--web_search { background: #0277b81f; color: #0369a1; }
.l-pill--image_gen  { background: #be2e681f; color: #a82a5c; }
@media (prefers-color-scheme: dark) {
  .l-pill--simple     { color: #2dd4bf; }
  .l-pill--general    { color: #8ba4ff; }
  .l-pill--longform   { color: #e0b050; }
  .l-pill--reasoning  { color: #b39bff; }
  .l-pill--vision     { color: #22d3ee; }
  .l-pill--tools      { color: #4ade80; }
  .l-pill--translate  { color: #c9a0ff; }
  .l-pill--web_search { color: #56b8f0; }
  .l-pill--image_gen  { color: #f472b6; }
}

/* ── states ───────────────────────────────────────────────────────────── */
.l-good  { color: var(--l-good); }
.l-warn  { color: var(--l-warn); }
.l-alert { color: var(--l-alert); }

.l-notice {
  padding: 10px 11px; border-radius: var(--l-r-md);
  background: var(--l-sunk); font-size: 12px; color: var(--l-dim);
  line-height: 1.5;
}

/* Fields, wherever somebody types. */
.l-field {
  width: 100%; font: inherit; font-size: 13px;
  padding: 9px 11px; border-radius: var(--l-r-md);
  border: 1px solid var(--l-line-2); background: var(--l-bg);
  color: var(--l-ink);
}
.l-field:focus {
  outline: none; border-color: var(--l-accent);
  box-shadow: 0 0 0 3px var(--l-accent-soft);
}
.l-field::placeholder { color: var(--l-faint); }

/* One entrance, used everywhere, short enough not to be noticed. */
@keyframes l-rise { from { opacity: 0; transform: translateY(6px); } }
.l-rise { animation: l-rise .16s cubic-bezier(.2,.7,.3,1) both; }

@media (prefers-reduced-motion: reduce) {
  * { animation-duration: .01ms !important; transition-duration: .01ms !important; }
}
`;

  /* Line icons at 15px. Drawn rather than typed: "×" and "⚙" inherit whatever
     the host page's font decides they look like, which on some sites is
     nothing like the rest of the card. */
  const icons = {
    close: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8"/></svg>',
    gear: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M2 4.5h4M9.5 4.5H14M2 11.5h4.5M10 11.5H14"/><circle cx="7.75" cy="4.5" r="1.75"/><circle cx="8.25" cy="11.5" r="1.75"/></svg>',
    star: '<svg viewBox="0 0 16 16" fill="currentColor"><path d="M8 1.8l1.9 3.9 4.3.6-3.1 3 .7 4.3L8 11.6l-3.8 2 .7-4.3-3.1-3 4.3-.6z"/></svg>',
    starOutline: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"><path d="M8 1.8l1.9 3.9 4.3.6-3.1 3 .7 4.3L8 11.6l-3.8 2 .7-4.3-3.1-3 4.3-.6z"/></svg>',
    arrow: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8h9M8.5 4.5L12 8l-3.5 3.5"/></svg>',
    check: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8.5l3.2 3.2L13 5"/></svg>',
    spark: '<svg viewBox="0 0 16 16" fill="currentColor"><path d="M8 1l1.5 4.2L13.7 7 9.5 8.4 8 12.6 6.5 8.4 2.3 7l4.2-1.8z"/></svg>',
    /* The extension's own mark, so the card is recognisably the same product
       as the thing in the toolbar: three tracks converging into one. */
    mark: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3.4L7 8M2 12.6L7 8M2 8h5"/><path d="M7 8h7"/></svg>',
    chevron: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3.5L10.5 8 6 12.5"/></svg>',
  };

  /* For ordinary pages. Shadow roots take `css` directly instead. */
  function mount(doc) {
    const d = doc || document;
    if (d.getElementById("lane-ui")) return;
    const style = d.createElement("style");
    style.id = "lane-ui";
    style.textContent = css;
    (d.head || d.documentElement).appendChild(style);
  }

  return { css, icons, mount };
})();

/* Ordinary pages of ours mark themselves with <html data-lane> and get the
   stylesheet automatically. It has to be automatic: an extension page runs
   under `script-src \'self\'`, so <script>LaneUI.mount()</script> is refused
   outright. Content scripts have no such attribute on the host page, which is
   the point - they take `css` into their own shadow root and leave the page
   they are visiting alone. */
if (typeof document !== "undefined"
    && document.documentElement
    && document.documentElement.hasAttribute("data-lane")) {
  LaneUI.mount();
}

if (typeof module !== "undefined" && module.exports) module.exports = LaneUI;
