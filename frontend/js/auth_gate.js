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
 * login overwrites the cache anyway.
 */

import { callPy } from "./bridge.js";

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
    sessionStorage.setItem(
      "login_notice",
      "We couldn't restore your Spotify session. Please log in again.",
    );
    window.location.replace("pages/login.html");
  }
});
