/*
 * background.js — opens the interview once, the first time this is installed.
 *
 * A tool that waits to be configured stays unconfigured. The five questions
 * are what turn "use Sonnet 5" into advice about this particular person, so
 * they are put in front of somebody at the one moment they are guaranteed to
 * be paying attention: immediately after they chose to install it.
 *
 * Only on install, never on update - reopening a setup page after every
 * version bump is how an extension teaches people to uninstall it.
 */
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason !== "install") return;
  chrome.tabs.create({ url: chrome.runtime.getURL("onboarding.html") });
});
