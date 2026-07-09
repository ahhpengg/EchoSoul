/*
 * Premium-required page logic (docs/FRONTEND.md, docs/SPOTIFY_INTEGRATION.md).
 *
 * The upgrade link must open in the SYSTEM browser — navigating the embedded
 * webview away from the app would strand the user — so it goes through the
 * allowlisted open_external_url bridge method. "Check again" re-runs the auth
 * gate, whose verify_premium() does a fresh /me fetch.
 */

import { callPy } from "./bridge.js";

const els = {
  upgradeBtn: document.querySelector("#upgrade-btn"),
  recheckBtn: document.querySelector("#recheck-btn"),
  switchBtn: document.querySelector("#switch-btn"),
  accountLine: document.querySelector("#account-line"),
  status: document.querySelector("#premium-status"),
};

function setError(text) {
  els.status.textContent = text;
}

// Best-effort "who is logged in" line; the page works fine without it.
(async () => {
  try {
    const profile = await callPy("get_user_profile");
    if (profile?.display_name) {
      els.accountLine.textContent =
        `Logged in as ${profile.display_name} (${profile.product || "free"} account)`;
    }
  } catch {
    // Ignore: purely informational.
  }
})();

els.upgradeBtn.addEventListener("click", async () => {
  setError("");
  try {
    await callPy("open_external_url", "https://www.spotify.com/premium/");
  } catch (err) {
    setError(err.message || "Couldn't open the browser. Visit spotify.com/premium manually.");
  }
});

els.recheckBtn.addEventListener("click", () => {
  window.location.replace("../index.html"); // re-runs the auth gate
});

els.switchBtn.addEventListener("click", async () => {
  setError("");
  try {
    await callPy("logout");
    window.location.replace("login.html");
  } catch (err) {
    setError(err.message || "Logout failed. Please try again.");
  }
});
