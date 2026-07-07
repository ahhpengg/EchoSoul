"""OS-keychain cache handler for Spotify OAuth tokens.

Spotipy persists the access/refresh token pair through a ``CacheHandler``. Per
docs/SPOTIFY_INTEGRATION.md we keep it in the OS keychain (Windows Credential
Locker, macOS Keychain, Linux Secret Service) via ``keyring`` rather than a
plaintext file. If the platform has no working keyring backend (e.g. a headless
Linux box without Secret Service), we fall back to a ``0o600`` JSON file in the
user's home directory.

The token blob is JSON (``access_token``, ``refresh_token``, ``expires_at`` …).
Never log its contents.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import keyring
from keyring.errors import KeyringError
from spotipy.cache_handler import CacheHandler

SERVICE = "EchoSoul"
USERNAME = "spotify_token"

_DEFAULT_FALLBACK = Path.home() / ".echosoul" / "spotify_token.json"


class KeyringCacheHandler(CacheHandler):
    """Store the Spotify token in the OS keychain, falling back to a file.

    The file fallback only activates when the keyring backend itself raises
    (no Secret Service available). On Windows and macOS the keychain path is
    always used.
    """

    def __init__(self, fallback_path: Path | None = None) -> None:
        self.service = SERVICE
        self.username = USERNAME
        self._fallback_path = fallback_path or _DEFAULT_FALLBACK

    # -- CacheHandler interface -------------------------------------------------

    def get_cached_token(self) -> dict | None:
        """Return the cached token dict, or ``None`` if nothing is stored."""
        raw = self._read()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Corrupt cache — treat as absent so the app re-authenticates.
            return None

    def save_token_to_cache(self, token_info: dict) -> None:
        """Persist the token dict to the keychain (or fallback file)."""
        self._write(json.dumps(token_info))

    # -- extra: used by auth.logout() ------------------------------------------

    def delete_cached_token(self) -> None:
        """Remove the stored token (used at logout). Idempotent."""
        try:
            keyring.delete_password(self.service, self.username)
        except KeyringError:
            # No keyring backend, or nothing stored — nothing to remove there.
            pass
        try:
            self._fallback_path.unlink()
        except FileNotFoundError:
            pass

    # -- storage backends -------------------------------------------------------

    def _read(self) -> str | None:
        try:
            return keyring.get_password(self.service, self.username)
        except KeyringError:
            try:
                return self._fallback_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                return None

    def _write(self, blob: str) -> None:
        try:
            keyring.set_password(self.service, self.username, blob)
        except KeyringError:
            self._write_fallback_file(blob)

    def _write_fallback_file(self, blob: str) -> None:
        self._fallback_path.parent.mkdir(parents=True, exist_ok=True)
        self._fallback_path.write_text(blob, encoding="utf-8")
        try:
            os.chmod(self._fallback_path, 0o600)
        except OSError:
            # Windows lacks POSIX mode bits; best-effort only.
            pass
