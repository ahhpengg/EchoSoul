"""Spotify Authorization Code with PKCE flow for the desktop app.

Runtime user auth: no ``client_secret`` is shipped; the PKCE challenge replaces
it. Tokens live in the OS keychain via :class:`KeyringCacheHandler`. See
docs/SPOTIFY_INTEGRATION.md for the full flow diagram and scope rationale.

Redirect URI — fixed-port loopback + custom path
-------------------------------------------------
Spotify's dashboard requires HTTPS for every redirect URI *except* a loopback
address, which must be the explicit IP literal **with a port**:
``http://127.0.0.1:8888/echosoul-callback``. (`localhost` and port-less forms
are rejected as "not secure".) We keep a custom callback *path* and serve a
small branded page from our own loopback server, with CSRF ``state`` validation.
The port and path come from ``SPOTIFY_REDIRECT_URI`` and must match the value
registered in the Spotify dashboard byte-for-byte.

Public surface (also the Spotify half of the PyWebView bridge):
    has_spotify_session()     -> bool
    start_login_flow()        -> dict   {"success": bool, "error": str | None}
    get_valid_access_token()  -> str    (refreshes if near expiry)
    logout()                  -> None
"""

from __future__ import annotations

import os
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyPKCE

from src.spotify.keyring_cache import KeyringCacheHandler

# Load .env from the repo root regardless of CWD (mirrors src/db/connection.py).
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH)

# Fixed loopback redirect (must match the Spotify dashboard registration
# byte-for-byte). Spotify requires the explicit IP literal and a port.
REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/echosoul-callback")
_parsed = urlparse(REDIRECT_URI)
CALLBACK_HOST = _parsed.hostname or "127.0.0.1"
CALLBACK_PORT = _parsed.port or 8888
CALLBACK_PATH = _parsed.path or "/echosoul-callback"

# How long to wait for the user to complete the browser consent step.
LOGIN_TIMEOUT_SECONDS = 180

# Request only the scopes we use (docs/SPOTIFY_INTEGRATION.md). Excess scopes
# look intrusive on Spotify's consent screen.
SPOTIFY_SCOPES = [
    "streaming",
    "user-read-email",
    "user-read-private",
    "user-modify-playback-state",
    "user-read-playback-state",
]

# One process-wide cache handler; both login and refresh share it.
CACHE_HANDLER = KeyringCacheHandler()

# Branded page shown in the browser tab after the redirect lands.
_CALLBACK_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>EchoSoul - Spotify connected</title>
  <style>
    body { font-family: system-ui, -apple-system, sans-serif; background: #121212;
           color: #fff; margin: 0; height: 100vh; display: flex;
           align-items: center; justify-content: center; }
    .card { text-align: center; }
    h1 { color: #1DB954; margin-bottom: .5rem; }
    p { color: #b3b3b3; }
  </style>
</head>
<body>
  <div class="card">
    <h1>EchoSoul</h1>
    <p>Spotify connected. You can close this tab and return to the app.</p>
  </div>
</body>
</html>"""


def _pkce_manager() -> SpotifyPKCE:
    """Build a configured ``SpotifyPKCE`` auth manager.

    ``open_browser=False`` because we drive the browser and capture the callback
    ourselves (see :class:`_CallbackServer`); Spotipy is used only to build the
    authorize URL, exchange the code, and refresh tokens.
    """
    return SpotifyPKCE(
        client_id=os.environ["SPOTIFY_CLIENT_ID"],
        redirect_uri=REDIRECT_URI,
        scope=" ".join(SPOTIFY_SCOPES),
        cache_handler=CACHE_HANDLER,
        open_browser=False,
    )


class _CallbackHandler(BaseHTTPRequestHandler):
    """Records the OAuth query params from the single redirect request."""

    def do_GET(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        if parsed.path != self.server.expected_path:  # type: ignore[attr-defined]
            self.send_response(404)
            self.end_headers()
            return
        params = parse_qs(parsed.query)
        self.server.auth_code = params.get("code", [None])[0]  # type: ignore[attr-defined]
        self.server.auth_state = params.get("state", [None])[0]  # type: ignore[attr-defined]
        self.server.auth_error = params.get("error", [None])[0]  # type: ignore[attr-defined]
        body = _CALLBACK_PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # silence default stderr logging
        pass


class _CallbackServer:
    """One-shot loopback HTTP server that captures the OAuth redirect.

    Binds to the fixed loopback port from the redirect URI (pass ``0`` to let
    the OS pick a free port — used only in tests). Raises ``OSError`` if the
    port is already in use.
    """

    def __init__(self, host: str, port: int, expected_path: str) -> None:
        self._server = HTTPServer((host, port), _CallbackHandler)
        self._server.expected_path = expected_path  # type: ignore[attr-defined]
        self._server.auth_code = None  # type: ignore[attr-defined]
        self._server.auth_state = None  # type: ignore[attr-defined]
        self._server.auth_error = None  # type: ignore[attr-defined]

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def __enter__(self) -> "_CallbackServer":
        return self

    def __exit__(self, *exc) -> bool:
        self._server.server_close()
        return False

    def wait_for_code(self, expected_state: str, timeout: float) -> tuple[str | None, str | None]:
        """Block until the browser hits the callback (or ``timeout`` elapses).

        Returns ``(code, error)``: exactly one is non-``None``. ``code`` is
        ``None`` on timeout, an explicit OAuth error, or a ``state`` mismatch,
        with a human-readable reason in ``error``.
        """
        self._server.timeout = timeout
        self._server.handle_request()  # serves one request or times out
        if self._server.auth_error:  # type: ignore[attr-defined]
            return None, f"Spotify returned an error: {self._server.auth_error}"  # type: ignore[attr-defined]
        if self._server.auth_code is None:  # type: ignore[attr-defined]
            return None, "Login timed out or the browser tab was closed."
        if self._server.auth_state != expected_state:  # type: ignore[attr-defined]
            return None, "State mismatch (possible CSRF); login aborted."
        return self._server.auth_code, None  # type: ignore[attr-defined]


def _open_authorize_page(auth: SpotifyPKCE, state: str) -> None:
    """Open the Spotify consent page in the user's default browser."""
    webbrowser.open(auth.get_authorize_url(state=state))


def has_spotify_session() -> bool:
    """True if a token is cached (the user has logged in before).

    Presence only — validity/refresh is handled lazily by
    :func:`get_valid_access_token`.
    """
    return CACHE_HANDLER.get_cached_token() is not None


def start_login_flow() -> dict:
    """Run the interactive PKCE login. Blocks until the OAuth callback returns.

    Binds the loopback callback server on the fixed redirect port, opens the
    Spotify consent page, and captures the redirect. Returns a JSON-serialisable
    result so the PyWebView bridge can forward it straight to the frontend.
    """
    try:
        with _CallbackServer(CALLBACK_HOST, CALLBACK_PORT, CALLBACK_PATH) as server:
            auth = _pkce_manager()
            state = secrets.token_urlsafe(16)
            _open_authorize_page(auth, state)
            code, error = server.wait_for_code(state, LOGIN_TIMEOUT_SECONDS)
            if error:
                return {"success": False, "error": error}
            # check_cache=False forces exchange of the fresh code even if an old
            # token is still cached; spotipy saves the new token to the keychain.
            auth.get_access_token(code=code, check_cache=False)
            return {"success": True, "error": None}
    except OSError as exc:
        # Most likely the fixed callback port is already in use.
        return {
            "success": False,
            "error": f"Could not start the login server on port {CALLBACK_PORT}: {exc}",
        }
    except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
        return {"success": False, "error": str(exc)}


def get_valid_access_token() -> str:
    """Return a fresh access token, refreshing it if it is near expiry.

    Called immediately before any operation that needs a live token — including
    just before handing the token to the Web Playback SDK.

    Raises:
        RuntimeError: if there is no cached session (user must log in first).
    """
    auth = _pkce_manager()
    token_info = auth.get_cached_token()  # refreshes in-place when expired
    if not token_info:
        raise RuntimeError("No Spotify session; call start_login_flow() first.")
    return token_info["access_token"]


def logout() -> None:
    """Delete the cached token. The frontend then returns to the login page."""
    CACHE_HANDLER.delete_cached_token()
