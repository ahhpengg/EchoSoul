/*
 * Custom window controls for the frameless window (src/main.py sets
 * frameless=True, so the OS title bar is gone on every page).
 *
 * Two layouts, chosen automatically:
 *   - Chrome pages (#app-header injected by chrome.js): minimize / maximize /
 *     close are appended INTO the top app bar, and the bar's spare flex space
 *     becomes the drag region — Spotify-desktop style, no extra bar, no layout
 *     shift. Load this script AFTER chrome.js.
 *   - Pre-auth pages (gate / login / premium, no header): a slim transparent
 *     overlay strip is injected across the top with a small brand mark on the
 *     left and the controls on the right.
 *
 * Dragging: pywebview makes any element with the `pywebview-drag-region` class
 * a drag handle (easy_drag is off). Double-clicking a drag region toggles
 * maximize, like a real title bar. Buttons call the window_* bridge methods
 * directly — plain script, so no import of the (module) bridge.js wrapper.
 */
(function () {
  "use strict";

  const BTN =
    "w-10 h-10 rounded-full flex items-center justify-center " +
    "text-on-surface-variant transition-colors";

  function controlsHTML() {
    return `
    <div id="window-controls" class="flex items-center gap-1 shrink-0 ml-1 pl-2 border-l border-white/10">
      <button id="win-min" aria-label="Minimize" class="${BTN} hover:bg-white/5 hover:text-on-surface"><span class="material-symbols-outlined text-[20px]">remove</span></button>
      <button id="win-max" aria-label="Maximize" class="${BTN} hover:bg-white/5 hover:text-on-surface"><span class="material-symbols-outlined text-[18px]">crop_square</span></button>
      <button id="win-close" aria-label="Close" class="${BTN} hover:bg-[#e81123] hover:text-white"><span class="material-symbols-outlined text-[20px]">close</span></button>
    </div>`;
  }

  const header = document.getElementById("app-header");
  if (header) {
    // Full header: the right-hand cluster is the only .flex-grow child; give
    // its free space (left of the controls, thanks to justify-end) the drag
    // class. Back header (photo) has no .flex-grow child — insert a filler.
    const cluster = header.querySelector(".flex-grow");
    const filler = document.createElement("div");
    filler.className = "pywebview-drag-region flex-grow self-stretch";
    if (cluster) {
      cluster.prepend(filler);
    } else {
      header.insertBefore(filler, header.lastElementChild);
    }
    header.insertAdjacentHTML("beforeend", controlsHTML());
  } else {
    // Pre-auth pages live at two depths; index.html has no /pages/ segment.
    const prefix = window.location.pathname.includes("/pages/") ? "../" : "";
    document.body.insertAdjacentHTML(
      "beforeend",
      `
      <div id="titlebar-overlay" class="fixed top-0 left-0 right-0 h-12 z-50 flex items-center pl-4 pr-2">
        <div class="pywebview-drag-region flex-grow self-stretch flex items-center gap-2 opacity-70">
          <img src="${prefix}assets/img/logo.png" alt="" class="w-5 h-5 object-contain">
          <span class="text-label-sm font-label-sm text-on-surface-variant">EchoSoul</span>
        </div>
        ${controlsHTML()}
      </div>`,
    );
  }

  function bridge(method, ...args) {
    const fn = window.pywebview?.api?.[method];
    return typeof fn === "function" ? fn(...args) : Promise.resolve(undefined);
  }

  const els = {
    min: document.getElementById("win-min"),
    max: document.getElementById("win-max"),
    close: document.getElementById("win-close"),
  };

  let isMaximized = false; // also gates the edge-resize handles below

  function setMaxIcon(maximized) {
    isMaximized = !!maximized;
    els.max.querySelector("span").textContent = maximized ? "filter_none" : "crop_square";
    els.max.setAttribute("aria-label", maximized ? "Restore" : "Maximize");
  }

  async function toggleMaximize() {
    try {
      setMaxIcon(await bridge("window_toggle_maximize"));
    } catch (err) {
      /* no bridge (browser preview) — ignore */
    }
  }

  els.min.addEventListener("click", () => bridge("window_minimize").catch(() => {}));
  els.max.addEventListener("click", toggleMaximize);
  els.close.addEventListener("click", () => bridge("window_close").catch(() => {}));

  // Standard title-bar behaviour: double-click the drag area to maximize.
  document.querySelectorAll(".pywebview-drag-region").forEach((el) => {
    el.addEventListener("dblclick", toggleMaximize);
  });

  // Correct the icon after a page load while maximized (each navigation
  // reloads this script, so the icon state must be re-derived, not assumed).
  async function syncMaxIcon() {
    try {
      setMaxIcon(await bridge("window_is_maximized"));
    } catch (err) {
      /* no bridge — leave default */
    }
  }
  if (window.pywebview?.api) {
    syncMaxIcon();
  } else {
    window.addEventListener("pywebviewready", syncMaxIcon, { once: true });
  }

  // ---- Edge resize handles -------------------------------------------------
  // pywebview's WinForms backend doesn't hit-test resize borders on frameless
  // windows, so invisible strips along the edges drive window_resize() with the
  // opposite edge anchored — the same technique pywebview uses for dragging.
  const HANDLES = [
    ["n", "top-0 left-3 right-3 h-1.5 cursor-ns-resize"],
    ["s", "bottom-0 left-3 right-3 h-1.5 cursor-ns-resize"],
    ["e", "right-0 top-3 bottom-3 w-1.5 cursor-ew-resize"],
    ["w", "left-0 top-3 bottom-3 w-1.5 cursor-ew-resize"],
    ["ne", "top-0 right-0 w-3 h-3 cursor-nesw-resize"],
    ["sw", "bottom-0 left-0 w-3 h-3 cursor-nesw-resize"],
    ["nw", "top-0 left-0 w-3 h-3 cursor-nwse-resize"],
    ["se", "bottom-0 right-0 w-3 h-3 cursor-nwse-resize"],
  ];

  const handleHolder = document.createElement("div");
  handleHolder.id = "resize-handles";
  handleHolder.innerHTML = HANDLES.map(
    ([edge, cls]) => `<div class="fixed z-[100] ${cls}" data-resize="${edge}"></div>`,
  ).join("");
  document.body.appendChild(handleHolder);

  handleHolder.addEventListener("pointerdown", async (e) => {
    const el = e.target.closest("[data-resize]");
    if (!el || isMaximized) return;
    e.preventDefault();

    const edge = el.dataset.resize;
    const startX = e.screenX;
    const startY = e.screenY;
    let start;
    try {
      // Captures the drag anchor Python-side (once per drag) and returns the
      // starting size; each window_resize step is then computed against that
      // fixed anchor, never against re-read (and possibly stale) geometry.
      start = await bridge("window_begin_resize", edge);
    } catch (err) {
      return; // no bridge (browser preview) — nothing to resize
    }
    if (!start) return;
    // Native px per CSS px: != 1 under Windows display scaling. Calibrating
    // from the reported size keeps the window pinned to the cursor.
    const scale = start.width / window.outerWidth || 1;
    el.setPointerCapture(e.pointerId);

    // Serialise bridge calls, last-wins: a resize takes longer than a
    // mousemove interval, so intermediate targets are dropped, not queued up.
    let busy = false;
    let pending = null;
    async function send(w, h) {
      if (busy) {
        pending = [w, h];
        return;
      }
      busy = true;
      try {
        await bridge("window_resize", w, h);
      } catch (err) {
        /* transient — next move retries */
      }
      busy = false;
      if (pending) {
        const [pw, ph] = pending;
        pending = null;
        send(pw, ph);
      }
    }

    function onMove(ev) {
      const dx = Math.round((ev.screenX - startX) * scale);
      const dy = Math.round((ev.screenY - startY) * scale);
      let w = start.width;
      let h = start.height;
      if (edge.includes("e")) w += dx;
      if (edge.includes("w")) w -= dx;
      if (edge.includes("s")) h += dy;
      if (edge.includes("n")) h -= dy;
      send(w, h);
    }
    function onUp(ev) {
      el.releasePointerCapture(ev.pointerId);
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
    }
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
  });
})();
