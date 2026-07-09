/*
 * Bridge wrapper for pywebview.api (docs/FRONTEND.md).
 *
 * Every bridge call goes through callPy() so all pages get the same guards:
 *   - waits for the `pywebviewready` event before the first call (on fast page
 *     loads window.pywebview may not exist yet — pitfall #5 in docs/FRONTEND.md);
 *   - rejects after a timeout so a hung Python call can't freeze a page forever.
 *
 * The 30 s default is generous for everything except start_spotify_login, which
 * legitimately blocks while the user finishes OAuth in their browser (Python
 * waits up to 180 s) — use callPyWithTimeout for calls like that.
 */

const BRIDGE_TIMEOUT_MS = 30000;

let readyPromise = null;

function bridgeReady() {
  if (window.pywebview?.api) return Promise.resolve();
  if (!readyPromise) {
    readyPromise = new Promise((resolve) => {
      window.addEventListener("pywebviewready", resolve, { once: true });
    });
  }
  return readyPromise;
}

async function invoke(method, args) {
  await bridgeReady();
  const fn = window.pywebview?.api?.[method];
  if (typeof fn !== "function") {
    throw new Error(`Bridge method not found: ${method}`);
  }
  return fn(...args);
}

export async function callPyWithTimeout(timeoutMs, method, ...args) {
  let timer;
  const timedOut = new Promise((_, reject) => {
    timer = setTimeout(
      () => reject(new Error(`Bridge call timed out: ${method}`)),
      timeoutMs,
    );
  });
  try {
    return await Promise.race([invoke(method, args), timedOut]);
  } finally {
    clearTimeout(timer);
  }
}

export async function callPy(method, ...args) {
  return callPyWithTimeout(BRIDGE_TIMEOUT_MS, method, ...args);
}
