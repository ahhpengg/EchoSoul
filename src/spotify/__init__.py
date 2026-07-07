"""Spotify integration: PKCE OAuth, token cache, and account checks.

Runtime user authentication for the desktop app. No ``client_secret`` is
shipped — the PKCE challenge replaces it. See docs/SPOTIFY_INTEGRATION.md.
"""
