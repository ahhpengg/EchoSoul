"""EchoSoul desktop app entry point: PyWebView window + JS bridge binding.

Run from the repository root:

    python -m src.main

Opens the native window over ``frontend/index.html`` (the auth gate), binds
:class:`BridgeApi` as ``pywebview.api``, and warms the FER model on a worker
thread so the first detection doesn't pay the model-load + graph-build cost.

Set ``ECHOSOUL_DEBUG=1`` (env or ``.env``) to open the webview devtools.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import webview
from dotenv import load_dotenv
from mysql.connector import Error as MySQLError

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Allow running this file directly (python src/main.py, or an IDE Run button):
# the absolute `src.*` imports need the repo root on sys.path, which
# `python -m src.main` provides but direct execution does not.
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.api import BridgeApi  # noqa: E402
from src.db import connection  # noqa: E402
from src.fer import inference  # noqa: E402

logger = logging.getLogger(__name__)
FRONTEND_INDEX = _REPO_ROOT / "frontend" / "index.html"

WINDOW_TITLE = "EchoSoul"
WINDOW_WIDTH = 1280  # design target 1280×800 (docs/FRONTEND.md "Styling notes")
WINDOW_HEIGHT = 800
MIN_SIZE = (800, 600)  # responsive floor is ≈700 px wide; stay safely above it


def _check_database() -> None:
    """Fail fast with a diagnostic if MySQL is unreachable (docs/ARCHITECTURE.md).

    Every screen after login needs the catalogue, so starting without a
    database would only defer the failure to a less debuggable place.
    """
    try:
        connection.fetchone("SELECT 1")
    except (KeyError, MySQLError) as exc:
        # KeyError = missing DB_* variable in .env; MySQLError = server/creds.
        logger.critical(
            "Cannot connect to MySQL (%s). Check the server is running and the "
            "DB_* values in .env are correct, then start the app again.",
            exc,
        )
        raise SystemExit(1) from exc


def _warm_up_model() -> None:
    """Load + warm the FER model in the background (via ``webview.start(func=...)``).

    A missing model file is not fatal: manual mood selection and playback still
    work; only the camera flow needs the model.
    """
    try:
        inference.warmup()
        logger.info("FER model loaded and warmed up.")
    except FileNotFoundError as exc:
        logger.error("FER model unavailable — camera flow will fail: %s", exc)


def main() -> None:
    """Start the EchoSoul desktop app."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_dotenv(_REPO_ROOT / ".env")
    debug = os.environ.get("ECHOSOUL_DEBUG", "0").lower() in {"1", "true", "yes"}

    _check_database()

    webview.create_window(
        WINDOW_TITLE,
        url=FRONTEND_INDEX.as_uri(),
        js_api=BridgeApi(),
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=MIN_SIZE,
    )
    # private_mode=False so localStorage and cookies persist across runs — the
    # Spotify Web Playback SDK keeps state in localStorage
    # (docs/SPOTIFY_INTEGRATION.md, "SDK + PyWebView gotchas").
    webview.start(func=_warm_up_model, debug=debug, private_mode=False)


if __name__ == "__main__":
    main()
