"""Unit tests for the isolated Spotify HTTP client (no network)."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if "midi_gen" not in sys.modules:
    _pkg = types.ModuleType("midi_gen")
    _pkg.__path__ = [str(_ROOT)]  # type: ignore[attr-defined]
    _pkg.__file__ = str(_ROOT / "__init__.py")
    sys.modules["midi_gen"] = _pkg

from midi_gen.spotify_client import (
    MissingSpotifyCredentials,
    SEARCH_URL,
    TOKEN_URL,
    fetch_client_credentials_token,
    load_spotify_credentials,
    search_artists,
    search_artists_with_credentials,
)


class _FakeResp:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_load_credentials_missing(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    assert load_spotify_credentials() is None


def test_load_credentials_from_env(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "cid")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "sec")
    assert load_spotify_credentials() == ("cid", "sec")


def test_token_and_search_urls_via_opener(monkeypatch):
    seen = []

    def opener(req, timeout=20):
        seen.append((req.full_url, req.get_method(), dict(req.header_items())))
        if req.full_url == TOKEN_URL:
            return _FakeResp({"access_token": "tok-123", "token_type": "Bearer"})
        assert req.full_url.startswith(SEARCH_URL)
        assert "type=artist" in req.full_url
        return _FakeResp(
            {
                "artists": {
                    "items": [
                        {"id": "a1", "name": "Miles Davis", "type": "artist"},
                        {"id": "x1", "name": "Nope", "type": "show"},
                    ]
                }
            }
        )

    token = fetch_client_credentials_token("cid", "sec", opener=opener)
    assert token == "tok-123"
    artists = search_artists("Miles Davis", access_token=token, opener=opener)
    assert [a.name for a in artists] == ["Miles Davis", "Nope"]
    assert artists[0].type == "artist"
    assert artists[1].type == "show"
    assert seen[0][0] == TOKEN_URL
    assert seen[1][0].startswith(SEARCH_URL)


def test_search_with_credentials_missing_raises(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    with pytest.raises(MissingSpotifyCredentials):
        search_artists_with_credentials("anyone")
