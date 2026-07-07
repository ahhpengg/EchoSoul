"""Spotify account checks: Premium verification and profile fetch.

The Web Playback SDK produces no audio for Free accounts, so we gate on
``product == "premium"`` right after login and on every app start
(docs/SPOTIFY_INTEGRATION.md). The frontend hard-blocks non-Premium users.
"""

from __future__ import annotations

import spotipy

from src.spotify import auth

# Session cache of the last profile fetched by verify_premium(); the Premium
# result is not re-checked between recommendations.
_profile_cache: dict | None = None


def verify_premium() -> dict:
    """Fetch the current user and report Premium status.

    Returns:
        ``{"premium": bool, "product": str | None,
        "display_name": str | None, "email": str | None}``.

    Raises:
        RuntimeError: if there is no valid Spotify session.
    """
    global _profile_cache
    token = auth.get_valid_access_token()
    sp = spotipy.Spotify(auth=token)
    me = sp.current_user()
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
