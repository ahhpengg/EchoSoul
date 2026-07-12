/*
 * Manual mood selection.
 *
 * Records the chosen emotion (manual source) and advances to the loading
 * screen, which runs generate_playlist (docs/FRONTEND.md > loading.html).
 * A manual pick skips inference entirely, so any capture left over from an
 * abandoned photo run is dropped — a full-res PNG is multi-MB of
 * sessionStorage we shouldn't keep alive for the rest of the session.
 */
let picked = false;

document.querySelectorAll(".mood-card").forEach((card) => {
  card.addEventListener("click", () => {
    if (picked) return; // already navigating; a second card must not win
    picked = true;
    sessionStorage.setItem("last_emotion", card.dataset.emotion);
    sessionStorage.setItem("emotion_source", "manual");
    sessionStorage.removeItem("captured_image_b64");
    window.location.assign("loading.html");
  });
});
