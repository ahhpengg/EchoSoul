/*
 * Live saved-playlists sidebar (docs/FRONTEND.md).
 *
 * chrome.js renders the sidebar shell (library controls strip + empty
 * #sidebar-playlists container) on every chrome page; this module drives it
 * from the Python bridge:
 *   - list_user_playlists -> the rows (kept raw in module state; filtering and
 *                            sorting happen client-side on re-render)
 *   - rename_playlist     -> kebab menu > Rename (inline input in place)
 *   - delete_playlist     -> kebab menu > Delete (second click confirms —
 *                            PyWebView doesn't reliably support confirm())
 * Library search (#sidebar-search-btn) swaps the controls strip for a text
 * field and live-filters the rows by name (case-insensitive substring).
 * The sort button (#sidebar-sort-btn) opens a menu of sort orders; the choice
 * persists across pages and app restarts in localStorage.sidebar_sort.
 * The filter button (#sidebar-filter-btn) opens an emotion-checkbox dropdown
 * (5 emotions + tri-state Select all + Apply); the applied filter composes
 * with the library search and lives in sessionStorage.sidebar_filter —
 * session-only by design, so every app launch starts unfiltered.
 * Clicking a row opens the playlist as result.html#playlist=<id>; result.js
 * reloads on hashchange, so switching playlists from the result page works.
 * The row for the playlist currently open on the result page is highlighted.
 */
import { callPy } from "./bridge.js";
import { EMOTION_THEMES, formatCreatedDate } from "./playlists_ui.js";

const container = document.getElementById("sidebar-playlists");

// ---- Module state -----------------------------------------------------------

let allPlaylists = []; // raw rows from list_user_playlists
let filterQuery = ""; // live library-search text ("" = no filter)

function note(text) {
  const p = document.createElement("p");
  p.className = "px-3 py-2 text-label-sm font-label-sm text-on-surface-variant opacity-60";
  p.textContent = text;
  return p;
}

// The playlist id open on the result page, or null anywhere else.
function activePlaylistId() {
  if (!window.location.pathname.toLowerCase().endsWith("result.html")) return null;
  const m = window.location.hash.match(/^#playlist=(\d+)$/);
  return m ? Number(m[1]) : null;
}

// ---- Sort orders --------------------------------------------------------------

// Owner-approved emotion group order (2026-07-15); ties inside a group (and in
// the alphabetical sort) fall back to recently-edited. Playlists without a
// recognised source_emotion sort after all groups.
const EMOTION_ORDER = ["happy", "surprised", "sad", "angry", "neutral"];

function emotionRank(playlist) {
  const i = EMOTION_ORDER.indexOf((playlist.source_emotion || "").toLowerCase());
  return i === -1 ? EMOTION_ORDER.length : i;
}

// ISO-8601 strings compare correctly as plain strings; missing values sink.
function newestFirst(key) {
  return (a, b) => (b[key] || "").localeCompare(a[key] || "");
}

const SORTS = {
  edited: { label: "Recently edited", compare: newestFirst("updated_at") },
  created: { label: "Recently created", compare: newestFirst("created_at") },
  alpha: {
    label: "Alphabetical",
    compare: (a, b) =>
      (a.name || "").localeCompare(b.name || "", undefined, { sensitivity: "base" }) ||
      newestFirst("updated_at")(a, b),
  },
  emotion: {
    label: "Emotion",
    compare: (a, b) => emotionRank(a) - emotionRank(b) || newestFirst("updated_at")(a, b),
  },
};

const DEFAULT_SORT = "edited";
const SORT_STORAGE_KEY = "sidebar_sort";

let sortKey = (() => {
  try {
    const stored = localStorage.getItem(SORT_STORAGE_KEY);
    return stored in SORTS ? stored : DEFAULT_SORT;
  } catch {
    return DEFAULT_SORT;
  }
})();

function setSort(key) {
  sortKey = key;
  try {
    localStorage.setItem(SORT_STORAGE_KEY, key);
  } catch {
    /* storage unavailable: the choice just won't persist */
  }
  updateSortLabel();
  render();
}

function updateSortLabel() {
  const label = document.getElementById("sidebar-sort-label");
  if (label) label.textContent = SORTS[sortKey].label;
}

// ---- Emotion filter -----------------------------------------------------------

const FILTER_STORAGE_KEY = "sidebar_filter";

// null = no filter; else a non-empty proper subset of EMOTION_ORDER. Applying
// all five emotions is the same as no filter (nothing would be hidden), so it
// normalises to null. Playlists without a recognised source_emotion are hidden
// while a filter is active (owner decision, 2026-07-15).
let emotionFilter = (() => {
  try {
    const stored = JSON.parse(sessionStorage.getItem(FILTER_STORAGE_KEY) || "null");
    if (!Array.isArray(stored)) return null;
    const valid = new Set(stored.filter((e) => EMOTION_ORDER.includes(e)));
    return valid.size && valid.size < EMOTION_ORDER.length ? valid : null;
  } catch {
    return null;
  }
})();

function setEmotionFilter(filter) {
  emotionFilter = filter;
  try {
    if (filter) sessionStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify([...filter]));
    else sessionStorage.removeItem(FILTER_STORAGE_KEY);
  } catch {
    /* storage unavailable: the choice just won't survive navigation */
  }
  updateFilterButton();
  render();
}

// Active filter = accented funnel icon + a badge with the checked-emotion count.
function updateFilterButton() {
  const btn = document.getElementById("sidebar-filter-btn");
  const badge = document.getElementById("sidebar-filter-badge");
  if (!btn || !badge) return;
  btn.classList.toggle("text-primary", Boolean(emotionFilter));
  badge.textContent = emotionFilter ? String(emotionFilter.size) : "";
  badge.classList.toggle("hidden", !emotionFilter);
}

// ---- Menus (kebab + sort share one slot, so opening either closes the other) --

let openMenu = null;

function closeMenu() {
  if (openMenu) {
    openMenu.remove();
    openMenu = null;
  }
}

document.addEventListener("click", (e) => {
  if (openMenu && !e.target.closest("[data-sidebar-menu]")) closeMenu();
});

function openMenuFor(item, playlist) {
  closeMenu();
  const menu = document.createElement("div");
  menu.dataset.sidebarMenu = "";
  menu.className =
    "absolute right-2 top-10 z-50 w-44 rounded-lg bg-surface-container-high border border-white/10 shadow-xl py-1";
  menu.innerHTML = `
    <button data-act="rename" class="w-full flex items-center gap-2 px-3 py-2 text-label-md font-label-md text-on-surface hover:bg-white/5 text-left transition-colors"><span class="material-symbols-outlined text-[18px]">edit</span>Rename</button>
    <button data-act="delete" class="w-full flex items-center gap-2 px-3 py-2 text-label-md font-label-md text-red-400 hover:bg-white/5 text-left transition-colors"><span class="material-symbols-outlined text-[18px]">delete</span>Delete</button>`;

  let deleteArmed = false;
  menu.addEventListener("click", (e) => {
    e.preventDefault(); // the menu lives inside the row's <a>
    e.stopPropagation();
    const action = e.target.closest("[data-act]")?.dataset.act;
    if (action === "rename") {
      closeMenu();
      startRename(item, playlist);
    } else if (action === "delete") {
      if (!deleteArmed) {
        deleteArmed = true;
        menu.querySelector('[data-act="delete"]').innerHTML =
          `<span class="material-symbols-outlined text-[18px]">delete</span>Confirm delete?`;
        return;
      }
      deletePlaylist(playlist);
    }
  });

  item.appendChild(menu);
  openMenu = menu;
}

function openSortMenu(controls) {
  closeMenu();
  const menu = document.createElement("div");
  menu.dataset.sidebarMenu = "";
  menu.dataset.menuKind = "sort";
  menu.className =
    "absolute right-1 top-10 z-50 w-48 rounded-lg bg-surface-container-high border border-white/10 shadow-xl py-1";
  menu.innerHTML = `
    <p class="px-3 pt-2 pb-1 text-label-sm font-label-sm text-on-surface-variant uppercase tracking-wider">Sort by</p>
    ${Object.entries(SORTS)
      .map(
        ([key, sort]) => `
    <button data-sort="${key}" class="w-full flex items-center justify-between gap-2 px-3 py-2 text-label-md font-label-md text-left transition-colors hover:bg-white/5 ${key === sortKey ? "text-primary" : "text-on-surface"}">
      <span>${sort.label}</span>
      ${key === sortKey ? '<span class="material-symbols-outlined text-[18px]">check</span>' : ""}
    </button>`
      )
      .join("")}`;

  menu.addEventListener("click", (e) => {
    e.stopPropagation();
    const key = e.target.closest("[data-sort]")?.dataset.sort;
    if (!key) return;
    closeMenu();
    if (key !== sortKey) setSort(key);
  });

  controls.appendChild(menu);
  openMenu = menu;
}

function emotionTitle(key) {
  return key.charAt(0).toUpperCase() + key.slice(1);
}

function openFilterMenu(controls) {
  closeMenu();
  const menu = document.createElement("div");
  menu.dataset.sidebarMenu = "";
  menu.dataset.menuKind = "filter";
  menu.className =
    "absolute right-1 top-10 z-50 w-52 rounded-lg bg-surface-container-high border border-white/10 shadow-xl py-1";
  // Pending state starts from what is applied; no filter shows all five checked.
  const applied = emotionFilter || new Set(EMOTION_ORDER);
  menu.innerHTML = `
    <p class="px-3 pt-2 pb-1 text-label-sm font-label-sm text-on-surface-variant uppercase tracking-wider">Filter by emotion</p>
    ${EMOTION_ORDER.map(
      (key) => `
    <label class="flex items-center gap-3 px-3 py-2 text-label-md font-label-md text-on-surface hover:bg-white/5 cursor-pointer transition-colors">
      <input type="checkbox" data-emotion="${key}" class="w-4 h-4 accent-primary shrink-0" ${applied.has(key) ? "checked" : ""}>
      <img src="${EMOTION_THEMES[key].emoji}" alt="" class="w-5 h-5 object-contain shrink-0">
      <span>${emotionTitle(key)}</span>
    </label>`
    ).join("")}
    <div class="border-t border-white/10 mt-1 pt-1">
      <label class="flex items-center gap-3 px-3 py-2 text-label-md font-label-md text-on-surface hover:bg-white/5 cursor-pointer transition-colors">
        <input type="checkbox" data-select-all class="w-4 h-4 accent-primary shrink-0">
        <span>Select all</span>
      </label>
      <div class="px-3 pt-1 pb-2">
        <button data-apply class="w-full py-2 rounded-full bg-primary text-background text-label-md font-label-md font-bold hover:brightness-110 transition-all disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:brightness-100">Apply</button>
      </div>
    </div>`;

  const boxes = [...menu.querySelectorAll("[data-emotion]")];
  const selectAll = menu.querySelector("[data-select-all]");
  const apply = menu.querySelector("[data-apply]");

  // Tri-state Select all + Apply needs >= 1 emotion (applying an empty filter
  // that shows nothing is never allowed — owner decision, 2026-07-15).
  function sync() {
    const n = boxes.filter((b) => b.checked).length;
    selectAll.checked = n === boxes.length;
    selectAll.indeterminate = n > 0 && n < boxes.length;
    apply.disabled = n === 0;
  }
  sync();

  menu.addEventListener("change", (e) => {
    if (e.target === selectAll) boxes.forEach((b) => (b.checked = selectAll.checked));
    sync();
  });

  apply.addEventListener("click", () => {
    const checked = boxes.filter((b) => b.checked).map((b) => b.dataset.emotion);
    closeMenu();
    setEmotionFilter(checked.length === EMOTION_ORDER.length ? null : new Set(checked));
  });

  controls.appendChild(menu);
  openMenu = menu;
}

// ---- Rename / delete --------------------------------------------------------

function startRename(item, playlist) {
  const nameEl = item.querySelector("[data-name]");
  const input = document.createElement("input");
  input.type = "text";
  input.value = playlist.name;
  input.className =
    "w-full bg-surface-container-high border border-primary/50 rounded px-2 py-1 " +
    "text-label-md font-label-md text-on-surface focus:outline-none focus:border-primary";
  // The input sits inside the row's <a>: keep clicks from navigating.
  input.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
  });

  let done = false;
  async function finish(commit) {
    if (done) return;
    done = true;
    const value = input.value.trim();
    input.remove();
    nameEl.classList.remove("hidden");
    if (!commit || !value || value === playlist.name) return;
    try {
      await callPy("rename_playlist", playlist.playlist_id, value);
      playlist.name = value;
      // Re-render rather than patching the row: the rename may move the row
      // (alphabetical sort) or change whether it matches the library filter.
      render();
    } catch (err) {
      console.error("rename_playlist failed:", err);
    }
  }

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault(); // Enter inside an <a> would also follow the link
      finish(true);
    } else if (e.key === "Escape") {
      finish(false);
    }
  });
  input.addEventListener("blur", () => finish(false));

  nameEl.classList.add("hidden");
  nameEl.after(input);
  input.focus();
  input.select();
}

async function deletePlaylist(playlist) {
  closeMenu();
  try {
    await callPy("delete_playlist", playlist.playlist_id);
  } catch (err) {
    console.error("delete_playlist failed:", err);
    return;
  }
  const wasOpen = activePlaylistId() === playlist.playlist_id;
  allPlaylists = allPlaylists.filter((p) => p.playlist_id !== playlist.playlist_id);
  render();
  // The playlist being viewed no longer exists: don't leave a dead page up.
  if (wasOpen) window.location.assign("home.html");
}

// ---- Rendering ---------------------------------------------------------------

function playlistItem(playlist, isActive) {
  const item = document.createElement("div");
  item.dataset.playlistItem = "";
  item.className = "relative group";

  const row = document.createElement("a");
  row.href = `result.html#playlist=${playlist.playlist_id}`;
  row.className =
    "flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors cursor-pointer " +
    (isActive
      ? "text-primary font-bold bg-primary/10 border-r-2 border-primary"
      : "text-on-surface-variant hover:bg-white/5 hover:text-on-surface");

  const theme = EMOTION_THEMES[(playlist.source_emotion || "").toLowerCase()];
  const thumb = theme
    ? `<img src="${theme.emoji}" alt="" class="w-5 h-5 object-contain shrink-0">`
    : `<span class="material-symbols-outlined text-[20px] shrink-0">music_note</span>`;
  const count = playlist.track_count;
  const created = formatCreatedDate(playlist.created_at);
  row.innerHTML = `${thumb}
    <span class="flex-grow min-w-0">
      <span data-name class="block text-label-md font-label-md truncate"></span>
      <span class="block text-label-sm font-label-sm opacity-60 truncate">${count} song${count === 1 ? "" : "s"}${created ? " · " + created : ""}</span>
    </span>
    <button data-kebab aria-label="Playlist options" class="w-7 h-7 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 focus:opacity-100 hover:bg-white/10 transition-opacity shrink-0">
      <span class="material-symbols-outlined text-[18px]">more_horiz</span>
    </button>`;
  row.querySelector("[data-name]").textContent = playlist.name;

  row.querySelector("[data-kebab]").addEventListener("click", (e) => {
    e.preventDefault(); // don't follow the row's link
    e.stopPropagation(); // don't let the document handler instantly close it
    if (openMenu && openMenu.parentElement === item) {
      closeMenu();
    } else {
      openMenuFor(item, playlist);
    }
  });

  item.appendChild(row);
  return item;
}

function visiblePlaylists() {
  const q = filterQuery.toLowerCase();
  let rows = allPlaylists;
  if (emotionFilter) {
    rows = rows.filter((p) => emotionFilter.has((p.source_emotion || "").toLowerCase()));
  }
  if (q) rows = rows.filter((p) => (p.name || "").toLowerCase().includes(q));
  return rows.slice().sort(SORTS[sortKey].compare);
}

function render() {
  if (!container) return;
  closeMenu(); // replaceChildren would orphan an open kebab menu
  if (!allPlaylists.length) {
    container.replaceChildren(note("No saved playlists yet."));
    return;
  }
  const rows = visiblePlaylists();
  if (!rows.length) {
    container.replaceChildren(
      note(
        filterQuery
          ? `No playlists match "${filterQuery}".`
          : "No playlists match the emotion filter."
      )
    );
    return;
  }
  const active = activePlaylistId();
  container.replaceChildren(...rows.map((p) => playlistItem(p, p.playlist_id === active)));
}

export async function refreshSidebarPlaylists() {
  if (!container) return;
  try {
    allPlaylists = await callPy("list_user_playlists");
    render();
  } catch (err) {
    console.error("list_user_playlists failed:", err);
    container.replaceChildren(note("Couldn't load playlists."));
  }
}

// ---- Library controls (search toggle + sort button) ---------------------------

(function initControls() {
  const controls = document.getElementById("sidebar-controls");
  if (!controls) return;
  const row = document.getElementById("sidebar-controls-row");
  const wrap = document.getElementById("sidebar-search-wrap");
  const input = document.getElementById("sidebar-search");

  function openSearch() {
    row.classList.add("hidden");
    wrap.classList.remove("hidden");
    input.focus();
  }

  function closeSearch() {
    wrap.classList.add("hidden");
    row.classList.remove("hidden");
    if (filterQuery || input.value) {
      input.value = "";
      filterQuery = "";
      render();
    }
  }

  document.getElementById("sidebar-search-btn").addEventListener("click", openSearch);
  document.getElementById("sidebar-search-clear").addEventListener("click", closeSearch);

  input.addEventListener("input", () => {
    filterQuery = input.value.trim();
    render();
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeSearch();
  });
  // An abandoned empty search collapses back to the strip; a non-empty one
  // stays open so it's obvious why the list is filtered.
  input.addEventListener("blur", () => {
    // Let a click on the clear button run first (it would re-close anyway).
    setTimeout(() => {
      if (!wrap.classList.contains("hidden") && !input.value.trim()) closeSearch();
    }, 150);
  });

  document.getElementById("sidebar-sort-btn").addEventListener("click", (e) => {
    e.stopPropagation(); // don't let the document handler instantly close it
    if (openMenu && openMenu.dataset.menuKind === "sort") {
      closeMenu();
    } else {
      openSortMenu(controls);
    }
  });

  document.getElementById("sidebar-filter-btn").addEventListener("click", (e) => {
    e.stopPropagation(); // don't let the document handler instantly close it
    if (openMenu && openMenu.dataset.menuKind === "filter") {
      closeMenu();
    } else {
      openFilterMenu(controls);
    }
  });

  updateSortLabel();
  updateFilterButton();
})();

refreshSidebarPlaylists();
