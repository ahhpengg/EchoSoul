/*
 * Login page logic (docs/FRONTEND.md > login.html).
 *
 * start_spotify_login blocks on the Python side while the user completes the
 * consent flow in their system browser (up to 180 s), so this one call gets a
 * longer bridge timeout than the 30 s default — Python must time out first so
 * its error message, not a generic bridge timeout, reaches the user.
 */

import { callPyWithTimeout } from "./bridge.js";

const LOGIN_TIMEOUT_MS = 190000;

const els = {
  loginBtn: document.querySelector("#login-btn"),
  status: document.querySelector("#login-status"),
};

function setStatus(text, isError = false) {
  els.status.textContent = text;
  els.status.classList.toggle("text-error", isError);
  els.status.classList.toggle("text-on-surface-variant", !isError);
}

// One-shot notice left by the auth gate (e.g. session restore failed).
const notice = sessionStorage.getItem("login_notice");
if (notice) {
  setStatus(notice, true);
  sessionStorage.removeItem("login_notice");
}

els.loginBtn.addEventListener("click", async () => {
  els.loginBtn.disabled = true;
  setStatus("Opening Spotify in your browser… finish logging in there.");
  try {
    const result = await callPyWithTimeout(LOGIN_TIMEOUT_MS, "start_spotify_login");
    if (result.success) {
      setStatus("Connected! Loading EchoSoul…");
      window.location.replace("../index.html"); // re-runs the auth gate
      return;
    }
    setStatus(result.error || "Login failed. Please try again.", true);
  } catch (err) {
    setStatus(err.message || "Login failed. Please try again.", true);
  }
  els.loginBtn.disabled = false;
});
