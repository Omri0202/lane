/*
 * profile.js — what this particular person uses, so the advice is about them.
 *
 * Generic advice is easy to ignore. "Use Sonnet 5" means nothing to somebody
 * whose plan has no Sonnet, and "you could save 90%" means nothing to somebody
 * who never opens ChatGPT. Everything here exists to narrow the advice down to
 * models this person can actually pick, on sites they actually visit, for the
 * work they actually do.
 *
 * It is deliberately small. Five answers, none of them required, all of them
 * changeable later — an interview that feels like a form is one people abandon,
 * and a tool that will not work until you have configured it is a tool most
 * people never configure.
 *
 * Nothing here leaves the browser. There is no account, no sync and no server:
 * the profile lives in extension storage, which is per-browser and private, and
 * the panel reads it locally to shape what it says.
 */

const LaneProfile = (() => {
  "use strict";

  const KEY = "lane.profile";

  const DEFAULT = {
    onboarded: false,
    // Which chat sites they actually use. The panel already knows which one it
    // is on; this is for the launcher, which has to guess where to send them.
    sites: [],
    // Model ids they can genuinely pick. Empty means "assume everything",
    // which is the right default before anybody has said otherwise.
    models: [],
    // A short list they reach for. Shown first, and offered as one-click
    // switches regardless of what the classifier thinks.
    favourites: [],
    // What they mostly do. Used to order the launcher's suggestions, never to
    // override the classifier — the request in front of it always wins.
    focus: [],
    // Their default answer to "cheap or best".
    variation: "save",
  };

  const usingChromeStorage = () => {
    try {
      return typeof chrome !== "undefined" && chrome.storage
        && chrome.storage.local;
    } catch (e) { return false; }
  };

  function load() {
    return new Promise((resolve) => {
      try {
        if (usingChromeStorage()) {
          chrome.storage.local.get(KEY, (v) => {
            resolve(Object.assign({}, DEFAULT, (v || {})[KEY] || {}));
          });
          return;
        }
        const raw = localStorage.getItem(KEY);
        resolve(Object.assign({}, DEFAULT, raw ? JSON.parse(raw) : {}));
      } catch (e) {
        // A profile that cannot be read is not a reason to stop working; it is
        // a reason to behave as though nobody had answered anything yet.
        resolve(Object.assign({}, DEFAULT));
      }
    });
  }

  function save(profile) {
    const merged = Object.assign({}, DEFAULT, profile || {});
    return new Promise((resolve) => {
      try {
        if (usingChromeStorage()) {
          chrome.storage.local.set({ [KEY]: merged }, () => resolve(merged));
          return;
        }
        localStorage.setItem(KEY, JSON.stringify(merged));
        resolve(merged);
      } catch (e) { resolve(merged); }
    });
  }

  async function patch(changes) {
    return save(Object.assign(await load(), changes || {}));
  }

  /* The models this person can pick, or null for "assume everything".
   *
   * Returned as null rather than a full list on purpose: the panel says
   * "assuming you can use every Claude model" when it has not been told, and
   * that admission is only possible if the two states stay distinguishable. */
  function allowed(profile) {
    return profile && profile.models && profile.models.length
      ? profile.models : null;
  }

  /* Favourites this person can still reach, in their own order. A model they
   * starred and later untick should not keep being offered. */
  function favourites(profile) {
    if (!profile || !profile.favourites) return [];
    const permitted = allowed(profile);
    return profile.favourites.filter(
      (id) => !permitted || permitted.includes(id));
  }

  return { load, save, patch, allowed, favourites, DEFAULT, KEY };
})();

if (typeof module !== "undefined" && module.exports) module.exports = LaneProfile;
