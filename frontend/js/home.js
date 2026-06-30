/*
 * Home page interactions.
 *
 * Static navigation only for this design import — no Python bridge calls yet
 * (see docs/FRONTEND.md for where the real detect_emotion / generate_playlist
 * calls will hook in later). The sidebar "Scan Emotion" button is wired by
 * chrome.js; this file handles the page's own hero + manual-mood controls.
 */
const hero = document.getElementById("camera-hero-section");
const cameraImg = document.getElementById("local-camera-img");
const caption = document.getElementById("hero-caption");

if (hero && cameraImg) {
  hero.addEventListener("click", () => {
    // Zoom the camera toward the viewer, then advance to the capture screen.
    if (caption) caption.style.opacity = "0";
    cameraImg.style.transform = "translateY(-10%) scale(6)";
    cameraImg.style.opacity = "0";
    setTimeout(() => window.location.assign("photo.html"), 650);
  });
}

// "Your Mood" opens the full manual-selection page.
document.getElementById("manual-mood-btn")?.addEventListener("click", () => {
  window.location.assign("mood.html");
});

// The quick emotion chips are a shortcut: each one is already a specific
// emotion, so skip the mood page and go straight through loading -> result.
document.querySelectorAll(".mood-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    sessionStorage.setItem("last_emotion", chip.dataset.emotion);
    sessionStorage.setItem("emotion_source", "manual");
    window.location.assign("loading.html");
  });
});
