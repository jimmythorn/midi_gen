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
    ARTISTS_URL,
    MissingSpotifyCredentials,
    SEARCH_URL,
    TOKEN_URL,
    artist_name_matches_query,
    fetch_client_credentials_token,
    genre_field_query,
    hydrate_artists,
    load_spotify_credentials,
    search_artists,
    search_artists_for_query,
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
                        {
                            "id": "a1",
                            "name": "Miles Davis",
                            "type": "artist",
                            "followers": {"total": 1_500_000},
                        },
                        {
                            "id": "x1",
                            "name": "Nope",
                            "type": "show",
                            "followers": {"total": 50},
                        },
                    ]
                }
            }
        )

    token = fetch_client_credentials_token("cid", "sec", opener=opener)
    assert token == "tok-123"
    artists = search_artists("Miles Davis", access_token=token, opener=opener)
    assert [a.name for a in artists] == ["Miles Davis", "Nope"]
    assert artists[0].type == "artist"
    assert artists[0].followers_total == 1_500_000
    assert artists[1].type == "show"
    assert artists[1].followers_total == 50
    assert seen[0][0] == TOKEN_URL
    assert seen[1][0].startswith(SEARCH_URL)


def test_parse_followers_total_missing_is_none():
    artists = search_artists(
        "Someone",
        access_token="tok",
        opener=lambda req, timeout=20: _FakeResp(
            {
                "artists": {
                    "items": [
                        {"id": "a1", "name": "No Followers Field", "type": "artist"},
                        {
                            "id": "a2",
                            "name": "Malformed",
                            "type": "artist",
                            "followers": "nope",
                        },
                        {
                            "id": "a3",
                            "name": "Null Total",
                            "type": "artist",
                            "followers": {"total": None},
                        },
                    ]
                }
            }
        ),
    )
    assert [a.followers_total for a in artists] == [None, None, None]


def test_genre_field_query_and_name_match():
    assert genre_field_query("classic rock") == 'genre:"classic rock"'
    assert genre_field_query('genre:"rock"') == 'genre:"rock"'
    assert artist_name_matches_query("Miles Davis", "Miles Davis") is True
    assert artist_name_matches_query("miles davis quintet", "Miles Davis") is True
    assert artist_name_matches_query("classic rock", "Led Zeppelin") is False
    assert artist_name_matches_query("classic rock", "Classic Rock All Stars") is False


def test_search_for_query_uses_genre_when_name_is_not_an_artist():
    seen = []

    def opener(req, timeout=20):
        seen.append(req.full_url)
        if req.full_url.startswith(SEARCH_URL) and "genre" not in req.full_url:
            return _FakeResp({"artists": {"items": []}})
        if req.full_url.startswith(SEARCH_URL):
            assert "genre" in req.full_url
            return _FakeResp(
                {
                    "artists": {
                        "items": [
                            {
                                "id": "zep",
                                "name": "Led Zeppelin",
                                "type": "artist",
                                "followers": {"total": 20_000_000},
                                "genres": [],
                            }
                        ]
                    }
                }
            )
        assert req.full_url.startswith(ARTISTS_URL)
        return _FakeResp(
            {
                "artists": [
                    {
                        "id": "zep",
                        "name": "Led Zeppelin",
                        "type": "artist",
                        "followers": {"total": 20_000_000},
                        "genres": ["classic rock", "album rock"],
                    }
                ]
            }
        )

    artists = search_artists_for_query("classic rock", access_token="tok", opener=opener)
    assert [a.name for a in artists] == ["Led Zeppelin"]
    assert artists[0].genres == ["classic rock", "album rock"]
    assert any(u.startswith(SEARCH_URL) and "genre" in u for u in seen)
    assert any(u.startswith(ARTISTS_URL) for u in seen)


def test_search_for_query_uses_name_hits_for_genre_phrase():
    seen = []

    def opener(req, timeout=20):
        seen.append(req.full_url)
        if req.full_url.startswith(SEARCH_URL):
            assert "genre" not in req.full_url
            return _FakeResp(
                {
                    "artists": {
                        "items": [
                            {
                                "id": "acdc",
                                "name": "AC/DC",
                                "type": "artist",
                            }
                        ]
                    }
                }
            )
        return _FakeResp({"artists": [{"id": "acdc", "name": "AC/DC", "type": "artist"}]})

    artists = search_artists_for_query("classic rock", access_token="tok", opener=opener)
    assert [a.name for a in artists] == ["AC/DC"]
    assert sum(1 for u in seen if u.startswith(SEARCH_URL)) == 1


def test_search_for_query_keeps_name_hit_without_genre_fallback():
    seen = []

    def opener(req, timeout=20):
        seen.append(req.full_url)
        if req.full_url.startswith(SEARCH_URL):
            assert "genre" not in req.full_url
            return _FakeResp(
                {
                    "artists": {
                        "items": [
                            {
                                "id": "miles",
                                "name": "Miles Davis",
                                "type": "artist",
                                "followers": {"total": 1_500_000},
                            }
                        ]
                    }
                }
            )
        return _FakeResp(
            {
                "artists": [
                    {
                        "id": "miles",
                        "name": "Miles Davis",
                        "type": "artist",
                        "followers": {"total": 1_500_000},
                        "genres": ["jazz"],
                    }
                ]
            }
        )

    artists = search_artists_for_query("Miles Davis", access_token="tok", opener=opener)
    assert artists[0].name == "Miles Davis"
    assert artists[0].genres == ["jazz"]
    assert sum(1 for u in seen if u.startswith(SEARCH_URL)) == 1


def test_hydrate_artists_fills_genres():
    seed = search_artists(
        "Anyone",
        access_token="tok",
        opener=lambda req, timeout=20: _FakeResp(
            {
                "artists": {
                    "items": [
                        {
                            "id": "a1",
                            "name": "Anyone",
                            "type": "artist",
                            "followers": {"total": 12_000},
                            "genres": [],
                        }
                    ]
                }
            }
        ),
    )
    assert seed[0].genres == []
    filled = hydrate_artists(
        seed,
        access_token="tok",
        opener=lambda req, timeout=20: _FakeResp(
            {
                "artists": [
                    {
                        "id": "a1",
                        "name": "Anyone",
                        "type": "artist",
                        "followers": {"total": 12_000},
                        "genres": ["classic rock"],
                    }
                ]
            }
        ),
    )
    assert filled[0].genres == ["classic rock"]


def test_search_with_credentials_missing_raises(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    with pytest.raises(MissingSpotifyCredentials):
        search_artists_with_credentials("anyone")
