"""Unit tests for the keyring-backed token cache.

The real ``keyring`` module is replaced with an in-memory fake so tests never
touch the OS credential store. A ``raises=True`` fake simulates a machine with
no keyring backend to exercise the file fallback.
"""

from __future__ import annotations

from keyring.errors import NoKeyringError, PasswordDeleteError, PasswordSetError

import pytest

from src.spotify import keyring_cache
from src.spotify.keyring_cache import KeyringCacheHandler

TOKEN = {"access_token": "abc", "refresh_token": "ref", "expires_at": 123}


class _FakeKeyring:
    """In-memory stand-in for the keyring module functions."""

    def __init__(self, raises: bool = False) -> None:
        self.store: dict[tuple[str, str], str] = {}
        self.raises = raises

    def get_password(self, service, username):
        if self.raises:
            raise NoKeyringError("no backend")
        return self.store.get((service, username))

    def set_password(self, service, username, blob):
        if self.raises:
            raise PasswordSetError("no backend")
        self.store[(service, username)] = blob

    def delete_password(self, service, username):
        if self.raises or (service, username) not in self.store:
            raise PasswordDeleteError("missing")
        del self.store[(service, username)]


@pytest.fixture
def fake_keyring(monkeypatch):
    fake = _FakeKeyring()
    monkeypatch.setattr(keyring_cache, "keyring", fake)
    return fake


@pytest.fixture
def no_keyring(monkeypatch):
    fake = _FakeKeyring(raises=True)
    monkeypatch.setattr(keyring_cache, "keyring", fake)
    return fake


# -- keychain path --------------------------------------------------------------


def test_roundtrip_via_keyring(fake_keyring, tmp_path):
    handler = KeyringCacheHandler(fallback_path=tmp_path / "tok.json")
    handler.save_token_to_cache(TOKEN)
    assert handler.get_cached_token() == TOKEN
    # Stored in keyring, not the fallback file.
    assert not (tmp_path / "tok.json").exists()


def test_get_returns_none_when_empty(fake_keyring, tmp_path):
    handler = KeyringCacheHandler(fallback_path=tmp_path / "tok.json")
    assert handler.get_cached_token() is None


def test_corrupt_blob_returns_none(fake_keyring, tmp_path):
    handler = KeyringCacheHandler(fallback_path=tmp_path / "tok.json")
    fake_keyring.store[(handler.service, handler.username)] = "not-json{"
    assert handler.get_cached_token() is None


def test_delete_removes_token(fake_keyring, tmp_path):
    handler = KeyringCacheHandler(fallback_path=tmp_path / "tok.json")
    handler.save_token_to_cache(TOKEN)
    handler.delete_cached_token()
    assert handler.get_cached_token() is None


def test_delete_is_idempotent(fake_keyring, tmp_path):
    handler = KeyringCacheHandler(fallback_path=tmp_path / "tok.json")
    # Nothing stored — must not raise.
    handler.delete_cached_token()


# -- file fallback (no keyring backend) -----------------------------------------


def test_fallback_roundtrip(no_keyring, tmp_path):
    path = tmp_path / "nested" / "tok.json"
    handler = KeyringCacheHandler(fallback_path=path)
    handler.save_token_to_cache(TOKEN)
    assert path.exists()
    assert handler.get_cached_token() == TOKEN


def test_fallback_get_missing_returns_none(no_keyring, tmp_path):
    handler = KeyringCacheHandler(fallback_path=tmp_path / "missing.json")
    assert handler.get_cached_token() is None


def test_fallback_delete_removes_file(no_keyring, tmp_path):
    path = tmp_path / "tok.json"
    handler = KeyringCacheHandler(fallback_path=path)
    handler.save_token_to_cache(TOKEN)
    handler.delete_cached_token()
    assert not path.exists()
