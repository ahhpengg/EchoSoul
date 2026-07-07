"""Unit tests for Premium verification and profile caching.

``spotipy.Spotify`` and the access-token lookup are stubbed so no network call
is made.
"""

from __future__ import annotations

import pytest

from src.spotify import account


class _FakeSpotify:
    def __init__(self, product, name="Jane", email="jane@example.com"):
        self._me = {"product": product, "display_name": name, "email": email}

    def current_user(self):
        return self._me


@pytest.fixture(autouse=True)
def _clear_profile_cache(monkeypatch):
    # Each test starts with an empty session cache.
    monkeypatch.setattr(account, "_profile_cache", None)


def _patch_spotify(monkeypatch, product):
    monkeypatch.setattr(account.auth, "get_valid_access_token", lambda: "tok")
    monkeypatch.setattr(account.spotipy, "Spotify", lambda auth: _FakeSpotify(product))


def test_verify_premium_true_for_premium(monkeypatch):
    _patch_spotify(monkeypatch, "premium")
    result = account.verify_premium()
    assert result["premium"] is True
    assert result["product"] == "premium"
    assert result["display_name"] == "Jane"
    assert result["email"] == "jane@example.com"


def test_verify_premium_false_for_free(monkeypatch):
    _patch_spotify(monkeypatch, "free")
    result = account.verify_premium()
    assert result["premium"] is False
    assert result["product"] == "free"


def test_verify_premium_raises_without_session(monkeypatch):
    def _no_token():
        raise RuntimeError("No Spotify session")

    monkeypatch.setattr(account.auth, "get_valid_access_token", _no_token)
    with pytest.raises(RuntimeError):
        account.verify_premium()


def test_get_user_profile_returns_cache_without_refetch(monkeypatch):
    monkeypatch.setattr(account, "_profile_cache", {"premium": True, "product": "premium"})

    def _should_not_be_called():
        raise AssertionError("verify_premium should not run when cache is warm")

    monkeypatch.setattr(account.auth, "get_valid_access_token", _should_not_be_called)
    assert account.get_user_profile()["premium"] is True


def test_get_user_profile_fetches_when_cache_empty(monkeypatch):
    _patch_spotify(monkeypatch, "premium")
    profile = account.get_user_profile()
    assert profile["product"] == "premium"
