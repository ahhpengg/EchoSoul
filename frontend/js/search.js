/*
 * Header search (docs/FRONTEND.md § "Header search").
 *
 * Drives the top-app-bar search box chrome.js renders on the five full-header
 * pages (home / mood / loading / result / error). As-you-type (debounced)
 * catalogue search via the bridge's search_tracks — FULLTEXT word-prefix match
 * on title + artists, most popular first. Clicking a result plays it: Premium
 * starts a single-track queue on the in-app SDK device (playback.js), Free
 * opens the song in Spotify externally. Each row's add button opens a
 * multi-select popup of saved playlists — ones already containing the song are
 * shown checked and locked — and confirming appends the song and reports the
 * outcome with a transient toast.
 */
import { callPy } from "./bridge.js";
import { playTracks } from "./playback.js";
import {
  EMOTION_THEMES,
  formatDuration,
  isFreeUser,
  openInSpotify,
  showToast,
} from "./playlists_ui.js";
import { refreshSidebarPlaylists } from "./sidebar.js";

// Below this the backend returns nothing anyway — don't even call.
const MIN_QUERY_CHARS = 2;
// One search per typing pause, not one per keystroke.
const DEBOUNCE_MS = 250;
const RESULT_LIMIT = 10;

const input = document.getElementById("header-search");
const dropdown = document.getElementById("search-dropdown");

let seq = 0; // stale-response guard: only the latest search may render
let debounceTimer = null;
let lastQuery = ""; // the query lastResults belongs to (re-open on focus)
let lastResults = null;

// The photo page uses the "back" header (no search box) and the pre-auth
// pages have no chrome at all — this module is a no-op there.
if (input && dropdown) init();

function init() {
  input.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    const query = input.value.trim();
    if (query.length < MIN_QUERY_CHARS) {
      seq++; // invalidate any in-flight search
      lastResults = null;
      hideDropdown();
      return;
    }
    debounceTimer = setTimeout(() => runSearch(query), DEBOUNCE_MS);
  });

  // Clicking back into the box re-opens the previous results.
  input.addEventListener("focus", () => {
    if (lastResults && input.value.trim() === lastQuery) showDropdown();
  });

  document.addEventListener("click", (e) => {
    if (e.target.closest("#header-search-wrap") || e.target.closest("#search-add-overlay")) return;
    hideDropdown();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (document.getElementById("search-add-overlay")) {
      closeAddPopup();
      return;
    }
    hideDropdown();
  });
}

function showDropdown() {
  dropdown.classList.remove("hidden");
}

function hideDropdown() {
  dropdown.classList.add("hidden");
}

// ---- Searching ---------------------------------------------------------------

async function runSearch(query) {
  const mySeq = ++seq;
  renderMessage("Searching…");
  let results;
  try {
    results = await callPy("search_tracks", query, RESULT_LIMIT);
  } catch (err) {
    console.error("search_tracks failed:", err);
    if (mySeq === seq) renderMessage("Search isn't working right now — try again.");
    return;
  }
  if (mySeq !== seq) return; // a newer search superseded this one
  lastQuery = query;
  lastResults = results;
  renderResults(results, query);
}

function renderMessage(text) {
  dropdown.innerHTML = "";
  const p = document.createElement("p");
  p.className = "px-4 py-3 text-label-md font-label-md text-on-surface-variant";
  p.textContent = text;
  dropdown.appendChild(p);
  showDropdown();
}

function renderResults(results, query) {
  if (!results.length) {
    renderMessage(`No songs found for "${query}"`);
    return;
  }
  dropdown.innerHTML = "";
  results.forEach((row) => dropdown.appendChild(resultRow(row)));
  showDropdown();
}

// One dropdown row: icon tile (play affordance on hover), title + artists,
// duration, and the add-to-playlist button.
function resultRow(row) {
  const free = isFreeUser();
  const el = document.createElement("div");
  el.className =
    "group flex items-center gap-3 px-4 py-2.5 hover:bg-white/5 cursor-pointer transition-colors";
  el.title = free ? "Open in Spotify" : "Play";
  el.innerHTML = `
    <div class="w-10 h-10 rounded bg-primary/15 flex items-center justify-center shrink-0">
      <span data-icon-idle class="material-symbols-outlined text-[20px] text-primary group-hover:hidden">music_note</span>
      <span data-icon-hover class="material-symbols-outlined ${free ? "" : "filled "}text-[20px] text-primary hidden group-hover:inline">${free ? "open_in_new" : "play_arrow"}</span>
    </div>
    <div class="flex-grow min-w-0">
      <p data-title class="text-body-md font-body-md text-on-surface font-medium truncate"></p>
      <p data-artists class="text-label-sm font-label-sm text-on-surface-variant truncate"></p>
    </div>
    <span data-duration class="text-label-sm font-label-sm text-on-surface-variant shrink-0"></span>
    <button data-add title="Add to playlist" class="w-9 h-9 rounded-full flex items-center justify-center text-on-surface-variant hover:text-primary hover:bg-white/10 transition-colors shrink-0">
      <span class="material-symbols-outlined text-[20px]">playlist_add</span>
    </button>`;
  el.querySelector("[data-title]").textContent = row.track_name;
  el.querySelector("[data-artists]").textContent = row.artists;
  el.querySelector("[data-duration]").textContent = formatDuration(row.duration_ms);

  el.addEventListener("click", () => {
    hideDropdown();
    if (free) {
      openInSpotify(row.track_name, row.artists, row.track_id);
      return;
    }
    playTracks([row.track_id]).catch((err) => {
      console.error("playTracks failed:", err);
      showToast(err.message || "Spotify couldn't play this track.");
    });
  });
  el.querySelector("[data-add]").addEventListener("click", (e) => {
    e.stopPropagation(); // the row click underneath would start playback
    openAddPopup(row);
  });
  return el;
}

// ---- Add-to-playlists popup ---------------------------------------------------

function closeAddPopup() {
  document.getElementById("search-add-overlay")?.remove();
}

async function openAddPopup(row) {
  closeAddPopup();
  const overlay = document.createElement("div");
  overlay.id = "search-add-overlay";
  overlay.className = "fixed inset-0 z-[60] bg-black/50 flex items-center justify-center p-4";
  overlay.innerHTML = `
    <div class="w-96 max-w-full rounded-2xl bg-surface-container-high border border-white/10 shadow-2xl p-5 flex flex-col">
      <p class="text-body-md font-body-md text-on-surface font-bold">Add to playlists</p>
      <p data-song class="text-label-sm font-label-sm text-on-surface-variant truncate mt-0.5"></p>
      <div data-list class="flex flex-col gap-1 my-4 max-h-64 overflow-y-auto">
        <p class="px-2.5 py-2 text-label-sm font-label-sm text-on-surface-variant">Loading playlists…</p>
      </div>
      <div class="flex justify-end gap-2">
        <button data-cancel class="px-4 py-2 rounded-full bg-white/10 text-on-surface text-label-md font-label-md hover:bg-white/15 transition-colors">Cancel</button>
        <button data-confirm disabled class="px-4 py-2 rounded-full bg-primary text-on-primary text-label-md font-label-md hover:opacity-90 transition-opacity disabled:opacity-40">Add</button>
      </div>
    </div>`;
  overlay.querySelector("[data-song]").textContent = `${row.track_name} — ${row.artists}`;
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeAddPopup();
  });
  overlay.querySelector("[data-cancel]").addEventListener("click", closeAddPopup);
  document.body.appendChild(overlay);

  const list = overlay.querySelector("[data-list]");
  const confirmBtn = overlay.querySelector("[data-confirm]");

  let playlists, containing;
  try {
    [playlists, containing] = await Promise.all([
      callPy("list_user_playlists"),
      callPy("get_playlists_containing_track", row.track_id),
    ]);
  } catch (err) {
    console.error("loading playlists for add popup failed:", err);
    list.innerHTML = "";
    const p = document.createElement("p");
    p.className = "px-2.5 py-2 text-label-sm font-label-sm text-on-surface-variant";
    p.textContent = "Couldn't load your playlists — try again.";
    list.appendChild(p);
    return;
  }
  if (!overlay.isConnected) return; // closed while loading

  list.innerHTML = "";
  if (!playlists.length) {
    const p = document.createElement("p");
    p.className = "px-2.5 py-2 text-label-sm font-label-sm text-on-surface-variant";
    p.textContent = "No saved playlists yet — save one from a detection result first.";
    list.appendChild(p);
    return;
  }
  const containingSet = new Set(containing);
  playlists.forEach((p) => list.appendChild(playlistOption(p, containingSet.has(p.playlist_id))));

  list.addEventListener("change", () => {
    confirmBtn.disabled = !list.querySelector("input[data-playlist-id]:checked");
  });
  confirmBtn.addEventListener("click", () => confirmAdd(row, overlay, list, confirmBtn));
}

// One selectable playlist row; playlists that already contain the song are
// shown checked and locked so the user can see where it already lives.
function playlistOption(p, alreadyIn) {
  const label = document.createElement("label");
  label.className =
    "flex items-center gap-3 px-2.5 py-2 rounded-lg " +
    (alreadyIn ? "opacity-55" : "hover:bg-white/5 cursor-pointer");

  const box = document.createElement("input");
  box.type = "checkbox";
  box.className = "w-4 h-4 accent-primary shrink-0";
  box.checked = alreadyIn;
  box.disabled = alreadyIn;
  if (!alreadyIn) box.dataset.playlistId = String(p.playlist_id);

  const theme = EMOTION_THEMES[(p.source_emotion || "").toLowerCase()];
  let icon;
  if (theme) {
    icon = document.createElement("img");
    icon.src = theme.emoji;
    icon.alt = "";
    icon.className = "w-6 h-6 object-contain shrink-0";
  } else {
    icon = document.createElement("span");
    icon.className = "material-symbols-outlined text-[20px] text-on-surface-variant shrink-0";
    icon.textContent = "music_note";
  }

  const name = document.createElement("span");
  name.className = "flex-grow min-w-0 truncate text-body-md font-body-md text-on-surface";
  name.textContent = p.name;

  const hint = document.createElement("span");
  hint.className = "text-label-sm font-label-sm text-on-surface-variant shrink-0";
  hint.textContent = alreadyIn ? "Added" : `${p.track_count} song${p.track_count === 1 ? "" : "s"}`;

  label.append(box, icon, name, hint);
  return label;
}

async function confirmAdd(row, overlay, list, confirmBtn) {
  const ids = [...list.querySelectorAll("input[data-playlist-id]:checked")].map((box) =>
    Number(box.dataset.playlistId)
  );
  if (!ids.length) return;
  confirmBtn.disabled = true;

  let result;
  try {
    result = await callPy("add_track_to_playlists", row.track_id, ids);
  } catch (err) {
    console.error("add_track_to_playlists failed:", err);
    showToast("Couldn't add the song — please try again.");
    confirmBtn.disabled = false;
    return;
  }
  closeAddPopup();

  const n = result.added.length;
  if (!n) {
    // Only possible via a race (playlist deleted / song added elsewhere while
    // the popup was open) — the popup itself locks already-added playlists.
    showToast("That song couldn't be added — the playlists may have changed.");
    return;
  }
  showToast(`Added to ${n} playlist${n === 1 ? "" : "s"}`);
  refreshSidebarPlaylists();

  // If one of the affected playlists is open on the result page right now,
  // its tracklist (and any later edit's working copy) would be stale — reload
  // once the toast has been seen. Same-document reload keeps playback alive
  // via the pagehide resume stash, like any other navigation.
  const open = window.location.hash.match(/^#playlist=(\d+)$/);
  if (open && result.added.includes(Number(open[1]))) {
    setTimeout(() => window.location.reload(), 1300);
  }
}
