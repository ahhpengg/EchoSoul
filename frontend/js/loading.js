/*
 * Loading / "Analyzing Emotion" screen.
 *
 * Static import: after a short delay we advance to the result screen. Once the
 * backend exists this is where the real flow runs (see docs/FRONTEND.md >
 * loading.html):
 *
 *   const source = sessionStorage.getItem("emotion_source");
 *   if (source === "camera") {
 *     const result = await callPy("detect_emotion", capturedImageB64);
 *     if (result.status === "error" || result.status === "out_of_scope") {
 *       sessionStorage.setItem("error_code",
 *         result.status === "out_of_scope" ? "out_of_scope" : result.error);
 *       window.location.assign("error.html");   // <-- error path lives here
 *       return;
 *     }
 *     sessionStorage.setItem("last_emotion", result.emotion);
 *   }
 *   // manual source: last_emotion is already set by the chip / mood card.
 *   const playlist = await callPy("generate_playlist", emotion, 25);
 *   ...store playlist... then go to result.html
 *
 * Until that exists we just play the animation and move on. error.html is
 * therefore only reachable via the (future) detection failure above — it can
 * still be opened directly to preview its design.
 */
window.addEventListener("load", () => {
  // Default to a happy result if no emotion was chosen (e.g. camera path demo).
  if (!sessionStorage.getItem("last_emotion")) {
    sessionStorage.setItem("last_emotion", "happy");
  }
  setTimeout(() => window.location.assign("result.html"), 2600);
});
