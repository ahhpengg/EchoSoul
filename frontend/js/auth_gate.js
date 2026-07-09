/*
 * Auth gate — runs on index.html (docs/FRONTEND.md).
 *
 * Routes to exactly one of: login (no session), premium_required (session but
 * Free account), or home (session + Premium, profile stashed for the chrome).
 * Uses location.replace so the gate page never lands in the back-history.
 *
 * If the cached session can't be used (refresh token revoked, network down),
 * we do NOT log out — a transient network failure would destroy a perfectly
 * good refresh token. We just route to login with a one-shot notice; a fresh
 * login overwrites the cache anyway. Known failures show their own actionable
 * message from Python (see USER_FACING_ERRORS); anything unexpected falls back
 * to a generic notice.
 */

import { callPy } from "./bridge.js";

// Bridge rejections carry the Python exception class name as error.name
// (pywebview sets it from type(e).__name__). These classes raise with a
// message written for the end user, shown verbatim on the login page.
const USER_FACING_ERRORS = new Set([
  "SpotifyUserNotRegisteredError", // account not in the app's dev-mode allowlist
  "SpotifySessionExpiredError", // refresh token revoked/expired — re-login fixes it
  "SpotifyNetworkError", // offline / Spotify unreachable — retry fixes it
]);

const statusEl = document.querySelector("#gate-status");

function setStatus(text) {
  if (statusEl) statusEl.textContent = text;
}

window.addEventListener("load", async () => {
  try {
    setStatus("Checking your Spotify session…");
    if (!(await callPy("has_spotify_session"))) {
      window.location.replace("pages/login.html");
      return;
    }

    setStatus("Verifying Spotify Premium…");
    const profile = await callPy("verify_premium");
    if (!profile.premium) {
      window.location.replace("pages/premium_required.html");
      return;
    }

    // For the sidebar / header (display name, avatar) on later pages.
    sessionStorage.setItem("spotify_profile", JSON.stringify(profile));
    window.location.replace("pages/home.html");
  } catch (err) {
    const notice = USER_FACING_ERRORS.has(err?.name)
      ? err.message
      : "We couldn't restore your Spotify session. Please log in again.";
    sessionStorage.setItem("login_notice", notice);
    window.location.replace("pages/login.html");
  }
});
