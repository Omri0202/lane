/*
 * background.js — the two things only the extension itself can do.
 *
 * Opening the interview, once, when it is installed; and opening it again when
 * something asks. A content script running on google.com cannot navigate to a
 * chrome-extension:// page - Chrome blocks it with ERR_BLOCKED_BY_CLIENT unless
 * the page is declared web-accessible, and declaring it that way would let any
 * website on the internet frame it. Messaging the worker is the way in, and it
 * needs no such declaration.
 */

chrome.runtime.onInstalled.addListener((details) => {
  // Install only, never update: reopening a setup page after every version
  // bump is how an extension teaches people to uninstall it.
  if (details.reason !== "install") return;
  chrome.tabs.create({ url: chrome.runtime.getURL("onboarding.html") });
});

chrome.runtime.onMessage.addListener((msg, _sender, respond) => {
  if (msg && msg.type === "lane:open-setup") {
    chrome.tabs.create({ url: chrome.runtime.getURL("onboarding.html") });
    respond({ ok: true });
  }
  return false;
});
