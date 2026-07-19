/*
 * Genre filter for generated playlists (docs/FRONTEND.md § "Genre filter").
 *
 * State: sessionStorage.genre_filter = JSON array of the canonical buckets the
 * user kept checked, or ABSENT while every bucket is checked — the default,
 * which is identical to "no filter" (loading.js then sends null and the
 * backend takes the unfiltered CP1 path). The selection sticks for the whole
 * session and applies to every generation, camera or manual, until changed.
 *
 * The picker is a modal in the create-playlist style: one checkbox tile per
 * canonical bucket (get_genre_buckets — the vocabulary stays single-sourced
 * from the DB), ALL CHECKED by default, plus a "Select all" tickbox that
 * checks/clears everything at once (its icon goes indeterminate on a partial
 * selection). Zero-checked is allowed only while choosing — the usual path to
 * a small selection is untick-all then pick a few — and Apply stays disabled
 * until at least one bucket is checked (owner-specified floor). Opened only
 * from the home page's "Genres" chip — the owner removed the result page's
 * refine/re-roll row (2026-07-18); the result page just shows a thin-pool
 * note when a filter left it short. Esc and backdrop clicks close the modal —
 * nothing destructive is lost, unlike the create-playlist builder step.
 */
import { callPy } from "./bridge.js";
import { showToast } from "./playlists_ui.js";

const STORAGE_KEY = "genre_filter";

let bucketsPromise = null; // cached vocabulary fetch; reset on failure so retry works
let overlay = null; // the open picker, or null

/** The active filter: array of bucket names, or null = all genres (default). */
export function getGenreFilter() {
  try {
    const stored = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "null");
    return Array.isArray(stored) && stored.length ? stored : null;
  } catch {
    return null;
  }
}

/**
 * Persist a selection. A selection of every bucket (or nothing) clears the
 * key — all-checked IS the default state, not a filter. Callers restoring a
 * previously-read filter (rollback) can omit bucketCount: a stored filter is
 * a proper subset by construction, so the all-selected check can't apply.
 */
export function setGenreFilter(selection, bucketCount = Infinity) {
  if (!selection || !selection.length || selection.length === bucketCount) {
    sessionStorage.removeItem(STORAGE_KEY);
  } else {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(selection));
  }
}

/** Short human label for chips: "All", "Pop", "Pop & K-Pop", "5 selected". */
export function describeGenreFilter(filter) {
  if (!filter || !filter.length) return "All";
  if (filter.length === 1) return filter[0];
  if (filter.length === 2) return `${filter[0]} & ${filter[1]}`;
  return `${filter.length} selected`;
}

function loadBuckets() {
  if (!bucketsPromise) {
    bucketsPromise = callPy("get_genre_buckets").catch((err) => {
      bucketsPromise = null; // let a later open retry
      throw err;
    });
  }
  return bucketsPromise;
}

function closePicker() {
  overlay?.remove();
  overlay = null;
  document.removeEventListener("keydown", onKeydown);
}

function onKeydown(e) {
  if (e.key === "Escape") closePicker();
}

/**
 * Open the picker. `onApply(filterOrNull)` fires only when the user hits
 * Apply and the selection actually changed; the new state is already
 * persisted by then.
 */
export async function openGenrePicker(onApply) {
  let buckets;
  try {
    buckets = await loadBuckets();
  } catch (err) {
    console.error("get_genre_buckets failed:", err);
    showToast("Couldn't load the genre list — please try again.");
    return;
  }
  closePicker();

  const before = getGenreFilter();
  // Stale stored buckets (vocabulary changed between sessions) drop out via
  // the intersection; an empty intersection falls back to the default (all).
  let selected = new Set((before || buckets).filter((b) => buckets.includes(b)));
  if (!selected.size) selected = new Set(buckets);

  overlay = document.createElement("div");
  overlay.className = "fixed inset-0 z-[60] bg-black/50 flex items-center justify-center p-4";
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closePicker();
  });
  document.addEventListener("keydown", onKeydown);

  const card = document.createElement("div");
  card.className =
    "w-[34rem] max-w-full max-h-[90vh] rounded-2xl bg-surface-container-high " +
    "border border-white/10 shadow-2xl p-5 flex flex-col";
  card.innerHTML = `
    <p class="text-body-md font-body-md text-on-surface font-bold">Playlist genres</p>
    <p class="text-label-sm font-label-sm text-on-surface-variant mt-0.5 text-justify">
      Choose which genres your generated playlists will include. All genres are on by
      default — untick the ones you don't want. Your choice applies to every playlist
      you generate until you change it again.
    </p>
    <div class="flex items-center justify-between mt-3 shrink-0">
      <button data-select-all class="flex items-center gap-1.5 text-label-md font-label-md text-on-surface hover:opacity-80 transition-opacity">
        <span class="material-symbols-outlined text-[20px] text-primary"></span>
        <span>Select all</span>
      </button>
      <span data-count class="text-label-sm font-label-sm text-on-surface-variant"></span>
    </div>
    <div data-tiles class="grid grid-cols-2 sm:grid-cols-3 gap-1.5 mt-3 overflow-y-auto"></div>
    <div class="flex justify-end gap-2 pt-4 shrink-0">
      <button data-cancel class="px-4 py-2 rounded-full bg-white/10 text-on-surface text-label-md font-label-md hover:bg-white/15 transition-colors">Cancel</button>
      <button data-apply class="px-4 py-2 rounded-full bg-primary text-on-primary text-label-md font-label-md hover:opacity-90 transition-opacity disabled:opacity-40">Apply</button>
    </div>`;

  const countEl = card.querySelector("[data-count]");
  const tilesBox = card.querySelector("[data-tiles]");
  const selectAllBtn = card.querySelector("[data-select-all]");
  const applyBtn = card.querySelector("[data-apply]");

  function refresh() {
    countEl.textContent = `${selected.size} of ${buckets.length} selected`;
    // The select-all tickbox mirrors the whole selection: checked when
    // everything is, blank when nothing is, indeterminate in between.
    selectAllBtn.querySelector(".material-symbols-outlined").textContent =
      selected.size === buckets.length
        ? "check_box"
        : selected.size === 0
          ? "check_box_outline_blank"
          : "indeterminate_check_box";
    // The at-least-one floor is enforced here rather than per tile, so
    // untick-all -> pick a few remains a natural path to a small selection.
    applyBtn.disabled = selected.size === 0;
    applyBtn.title = applyBtn.disabled ? "Select at least one genre" : "";
    tilesBox.querySelectorAll("[data-bucket]").forEach((tile) => {
      const on = selected.has(tile.dataset.bucket);
      tile.querySelector(".material-symbols-outlined").textContent = on
        ? "check_box"
        : "check_box_outline_blank";
      tile.classList.toggle("text-on-surface", on);
      tile.classList.toggle("text-on-surface-variant", !on);
    });
  }

  buckets.forEach((bucket) => {
    const tile = document.createElement("button");
    tile.dataset.bucket = bucket;
    tile.className =
      "flex items-start gap-2 px-2.5 py-2 rounded-lg text-left " +
      "hover:bg-white/5 transition-colors text-label-md font-label-md";
    tile.innerHTML = `
      <span class="material-symbols-outlined text-[20px] text-primary shrink-0"></span>
      <span class="leading-snug">${bucket}</span>`;
    tile.addEventListener("click", () => {
      if (selected.has(bucket)) selected.delete(bucket);
      else selected.add(bucket);
      refresh();
    });
    tilesBox.appendChild(tile);
  });
  refresh();

  selectAllBtn.addEventListener("click", () => {
    // Ticked when everything is selected -> unticking clears the board;
    // any other state ticks everything.
    selected = selected.size === buckets.length ? new Set() : new Set(buckets);
    refresh();
  });
  card.querySelector("[data-cancel]").addEventListener("click", closePicker);
  card.querySelector("[data-apply]").addEventListener("click", () => {
    // Keep the stored order stable (vocabulary order, not click order).
    const selection = buckets.filter((b) => selected.has(b));
    setGenreFilter(selection, buckets.length);
    closePicker();
    const after = getGenreFilter();
    if (JSON.stringify(after) !== JSON.stringify(before)) onApply?.(after);
  });

  overlay.appendChild(card);
  document.body.appendChild(overlay);
}
