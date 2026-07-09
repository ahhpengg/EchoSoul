"""Spotify account checks: Premium verification and profile fetch.

The Web Playback SDK produces no audio for Free accounts, so we gate on
``product == "premium"`` right after login and on every app start
(docs/SPOTIFY_INTEGRATION.md). The frontend hard-blocks non-Premium users.
"""

from __future__ import annotations

import requests
import spotipy

from src.spotify import auth

# Session cache of the last profile fetched by verify_premium(); the Premium
# result is not re-checked between recommendations.
_profile_cache: dict | None = None


class SpotifyUserNotRegisteredError(RuntimeError):
    """The Spotify app is in Development Mode and this account is not allowlisted.

    Spotify lets a non-allowlisted account complete the OAuth consent flow and
    issues it a token, then rejects its Web API calls with 403 "User not
    registered in the Developer Dashboard". The class name doubles as the
    frontend discriminator: pywebview rejects the JS promise with
    ``error.name == "SpotifyUserNotRegisteredError"``.
    """

    def __init__(self) -> None:
        super().__init__(
            "This Spotify account isn't authorized to use EchoSoul yet. "
            "Ask the app owner to add it under User Management in the Spotify "
            "Developer Dashboard, then log in again."
        )


def verify_premium() -> dict:
    """Fetch the current user and report Premium status.

    Returns:
        ``{"premium": bool, "product": str | None,
        "display_name": str | None, "email": str | None}``.

    Raises:
        RuntimeError: if there is no valid Spotify session.
        SpotifyUserNotRegisteredError: if the account is not in the app's
            Development-Mode allowlist (``/me`` returned 403).
        auth.SpotifySessionExpiredError: if the refresh token was revoked.
        auth.SpotifyNetworkError: if Spotify is unreachable.
    """
    global _profile_cache
    token = auth.get_valid_access_token()
    sp = spotipy.Spotify(auth=token)
    try:
        me = sp.current_user()
    except spotipy.SpotifyException as exc:
        # With a valid token, /me returns 403 only for the Development-Mode
        # allowlist case (a bad token gives 401, and /me omits scope-gated
        # fields rather than 403-ing).
        if exc.http_status == 403:
            raise SpotifyUserNotRegisteredError() from exc
        raise
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        # Spotipy passes connection-level failures through untouched.
        raise auth.SpotifyNetworkError() from exc
    _profile_cache = {
        "premium": me.get("product") == "premium",
        "product": me.get("product"),
        "display_name": me.get("display_name"),
        "email": me.get("email"),
    }
    return _profile_cache


def get_user_profile() -> dict:
    """Return the cached profile, fetching once via :func:`verify_premium`.

    Used by the frontend after the initial gate; avoids a second ``/me`` call
    per recommendation.
    """
    if _profile_cache is None:
        return verify_premium()
    return _profile_cache
