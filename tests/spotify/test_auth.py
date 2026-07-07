"""Unit tests for the PKCE auth flow and dynamic-port callback server.

Spotipy's ``SpotifyPKCE`` and the loopback server are stubbed for the
orchestration tests so no browser opens and no network call is made. The
``_CallbackServer`` itself is exercised with a real loopback request.
"""

from __future__ import annotations

import threading
import urllib.request
from urllib.parse import urlparse

import pytest

from src.spotify import auth

# -- config ---------------------------------------------------------------------


def test_scopes_are_the_documented_minimum():
    assert set(auth.SPOTIFY_SCOPES) == {
        "streaming",
        "user-read-email",
        "user-read-private",
        "user-modify-playback-state",
        "user-read-playback-state",
    }


def test_redirect_uri_is_fixed_port_loopback():
    parsed = urlparse(auth.REDIRECT_URI)
    assert parsed.hostname == "127.0.0.1"  # IP literal, not localhost
    assert parsed.port == auth.CALLBACK_PORT  # explicit port (Spotify requires it)
    assert auth.CALLBACK_PATH == parsed.path


def test_pkce_manager_uses_env_and_config(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "cid123")
    mgr = auth._pkce_manager()
    assert mgr.client_id == "cid123"
    assert mgr.redirect_uri == auth.REDIRECT_URI
    for scope in auth.SPOTIFY_SCOPES:
        assert scope in mgr.scope


# -- _CallbackServer (real loopback) --------------------------------------------


def _hit_callback(port: int, query: str) -> None:
    url = f"http://127.0.0.1:{port}{auth.CALLBACK_PATH}?{query}"
    try:
        urllib.request.urlopen(url, timeout=5).read()
    except Exception:
        pass  # the assertion is on what the server captured, not the client


# Bind port 0 so tests grab a free ephemeral port instead of the fixed 8888.
def test_callback_server_captures_code_and_state():
    with auth._CallbackServer("127.0.0.1", 0, auth.CALLBACK_PATH) as server:
        assert server.port > 0
        client = threading.Thread(target=_hit_callback, args=(server.port, "code=xyz&state=st123"))
        client.start()
        code, error = server.wait_for_code("st123", timeout=5)
        client.join()
    assert code == "xyz"
    assert error is None


def test_callback_server_rejects_state_mismatch():
    with auth._CallbackServer("127.0.0.1", 0, auth.CALLBACK_PATH) as server:
        client = threading.Thread(target=_hit_callback, args=(server.port, "code=xyz&state=wrong"))
        client.start()
        code, error = server.wait_for_code("expected", timeout=5)
        client.join()
    assert code is None
    assert "state mismatch" in error.lower()


def test_callback_server_times_out():
    with auth._CallbackServer("127.0.0.1", 0, auth.CALLBACK_PATH) as server:
        code, error = server.wait_for_code("st", timeout=0.3)
    assert code is None
    assert "timed out" in error.lower()


# -- start_login_flow (mocked) --------------------------------------------------


class _FakeManager:
    def __init__(self):
        self.exchanged = None
        self._cached = None

    def get_authorize_url(self, state=None):
        return "https://accounts.spotify.com/authorize?fake"

    def get_access_token(self, code=None, check_cache=True):
        self.exchanged = {"code": code, "check_cache": check_cache}
        return "access-tok"

    def get_cached_token(self):
        return self._cached


class _FakeServer:
    def __init__(self, code, error):
        self._code = code
        self._error = error
        self.port = 5555

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def wait_for_code(self, expected_state, timeout):
        return self._code, self._error


def _patch_login(monkeypatch, manager, server):
    monkeypatch.setattr(auth, "_pkce_manager", lambda: manager)
    monkeypatch.setattr(auth, "_CallbackServer", lambda host, port, path: server)
    monkeypatch.setattr(auth, "_open_authorize_page", lambda a, s: None)


def test_start_login_flow_success_exchanges_code(monkeypatch):
    manager = _FakeManager()
    _patch_login(monkeypatch, manager, _FakeServer("abc", None))
    result = auth.start_login_flow()
    assert result == {"success": True, "error": None}
    # Fresh code must be force-exchanged, bypassing any stale cached token.
    assert manager.exchanged == {"code": "abc", "check_cache": False}


def test_start_login_flow_reports_callback_error(monkeypatch):
    _patch_login(
        monkeypatch,
        _FakeManager(),
        _FakeServer(None, "Login timed out or the browser tab was closed."),
    )
    result = auth.start_login_flow()
    assert result["success"] is False
    assert "timed out" in result["error"]


def test_start_login_flow_handles_exception(monkeypatch):
    def _boom():
        raise RuntimeError("missing SPOTIFY_CLIENT_ID")

    monkeypatch.setattr(auth, "_pkce_manager", _boom)
    monkeypatch.setattr(auth, "_CallbackServer", lambda host, port, path: _FakeServer(None, None))
    monkeypatch.setattr(auth, "_open_authorize_page", lambda a, s: None)
    result = auth.start_login_flow()
    assert result["success"] is False
    assert "missing SPOTIFY_CLIENT_ID" in result["error"]


def test_start_login_flow_reports_port_in_use(monkeypatch):
    def _raise_oserror(host, port, path):
        raise OSError("address already in use")

    monkeypatch.setattr(auth, "_CallbackServer", _raise_oserror)
    result = auth.start_login_flow()
    assert result["success"] is False
    assert str(auth.CALLBACK_PORT) in result["error"]


# -- token + session helpers ----------------------------------------------------


def test_get_valid_access_token_returns_token(monkeypatch):
    manager = _FakeManager()
    manager._cached = {"access_token": "abc"}
    monkeypatch.setattr(auth, "_pkce_manager", lambda: manager)
    assert auth.get_valid_access_token() == "abc"


def test_get_valid_access_token_raises_without_session(monkeypatch):
    monkeypatch.setattr(auth, "_pkce_manager", lambda: _FakeManager())
    with pytest.raises(RuntimeError):
        auth.get_valid_access_token()


def test_has_spotify_session(monkeypatch):
    monkeypatch.setattr(auth.CACHE_HANDLER, "get_cached_token", lambda: {"access_token": "x"})
    assert auth.has_spotify_session() is True
    monkeypatch.setattr(auth.CACHE_HANDLER, "get_cached_token", lambda: None)
    assert auth.has_spotify_session() is False


def test_logout_delegates_to_cache_handler(monkeypatch):
    called = {}
    monkeypatch.setattr(
        auth.CACHE_HANDLER,
        "delete_cached_token",
        lambda: called.__setitem__("done", True),
    )
    auth.logout()
    assert called.get("done") is True
