"""Unit tests for Mood path: genre → ranked artist candidates (no network)."""

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

from midi_gen.mood_search import (
    ArtistCandidate,
    candidates_as_combo_rows,
    clear_genre_artist_cache,
    genre_artist_candidates,
    mood_combo_names,
    rank_artist_candidates,
)
from midi_gen.spotify_client import (
    MIN_SPOTIFY_FOLLOWERS,
    MissingSpotifyCredentials,
    SEARCH_URL,
    SpotifyArtist,
    SpotifyClientError,
    search_artists_by_genre,
    search_artists_by_genre_with_credentials,
)


@pytest.fixture(autouse=True)
def _clear_mood_genre_cache():
    clear_genre_artist_cache()
    yield
    clear_genre_artist_cache()


def _artist(
    name: str,
    *,
    artist_id: str = "a1",
    type_: str = "artist",
    followers_total: int | None = 50_000,
    genres: list[str] | None = None,
) -> SpotifyArtist:
    raw: dict = {
        "id": artist_id,
        "name": name,
        "type": type_,
        "genres": list(genres or []),
    }
    if followers_total is not None:
        raw["followers"] = {"total": followers_total}
    return SpotifyArtist(
        id=artist_id,
        name=name,
        type=type_,
        followers_total=followers_total,
        raw=raw,
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


def test_search_artists_by_genre_always_uses_genre_field():
    seen = []

    def opener(req, timeout=20):
        seen.append(req.full_url)
        assert "genre" in req.full_url
        assert "type=artist" in req.full_url
        return _FakeResp(
            {
                "artists": {
                    "items": [
                        {
                            "id": "brian",
                            "name": "Brian Eno",
                            "type": "artist",
                            "followers": {"total": 1_200_000},
                            "genres": ["ambient", "art rock"],
                        }
                    ]
                }
            }
        )

    artists = search_artists_by_genre("ambient", access_token="tok", opener=opener)
    assert [a.name for a in artists] == ["Brian Eno"]
    assert artists[0].genres == ["ambient", "art rock"]
    assert all("genre" in u for u in seen if u.startswith(SEARCH_URL))


def test_search_artists_by_genre_empty_query():
    assert search_artists_by_genre("", access_token="tok") == []
    assert search_artists_by_genre("   ", access_token="tok") == []


def test_rank_prefers_genre_overlap_then_followers():
    artists = [
        _artist(
            "Generic Star",
            artist_id="g1",
            followers_total=5_000_000,
            genres=["pop"],
        ),
        _artist(
            "Ambient Small",
            artist_id="a2",
            followers_total=20_000,
            genres=["ambient"],
        ),
        _artist(
            "Ambient Big",
            artist_id="a1",
            followers_total=900_000,
            genres=["ambient", "drone"],
        ),
        _artist(
            "Show Host",
            artist_id="s1",
            type_="show",
            followers_total=9_000_000,
            genres=["ambient"],
        ),
    ]
    candidates, reason, _msg = rank_artist_candidates(
        artists, genre_query="ambient", limit=10
    )
    assert reason is None
    # Genre overlap first, then followers; non-artist types dropped.
    assert [c.name for c in candidates] == [
        "Ambient Big",
        "Ambient Small",
        "Generic Star",
    ]
    assert candidates[0].id == "a1"
    assert candidates[0].genres == ("ambient", "drone")
    assert "Show Host" not in [c.name for c in candidates]


def test_rank_fail_closed_all_too_small():
    artists = [
        _artist("Tiny A", artist_id="t1", followers_total=100, genres=["rock"]),
        _artist("Tiny B", artist_id="t2", followers_total=9_999, genres=["rock"]),
    ]
    candidates, reason, message = rank_artist_candidates(
        artists, genre_query="rock", min_followers=MIN_SPOTIFY_FOLLOWERS
    )
    assert candidates == ()
    assert reason == "too_small"
    assert "10000" in message or "10_000" in message or "floor" in message


def test_rank_fail_closed_no_artists():
    candidates, reason, message = rank_artist_candidates([], genre_query="xyz")
    assert candidates == ()
    assert reason == "no_match"
    assert "xyz" in message


def test_missing_followers_still_usable_for_gate_parity():
    """Gate accepts missing followers.total — mood candidates do too."""
    artists = [
        _artist(
            "Unknown Count",
            artist_id="u1",
            followers_total=None,
            genres=["jazz"],
        ),
        _artist(
            "Known Jazz",
            artist_id="u2",
            followers_total=80_000,
            genres=["jazz"],
        ),
    ]
    candidates, reason, _ = rank_artist_candidates(artists, genre_query="jazz")
    assert reason is None
    assert [c.name for c in candidates] == ["Known Jazz", "Unknown Count"]
    assert candidates[1].followers_total is None


def test_genre_artist_candidates_ok_path():
    def fake_search(genre: str):
        assert genre == "classic rock"
        return [
            _artist(
                "Led Zeppelin",
                artist_id="zep",
                followers_total=20_000_000,
                genres=["classic rock", "album rock"],
            ),
            _artist(
                "Local Cover Band",
                artist_id="local",
                followers_total=50,
                genres=["classic rock"],
            ),
        ]

    result = genre_artist_candidates("classic rock", genre_search=fake_search)
    assert result.ok
    assert result.reason is None
    assert len(result.candidates) == 1
    assert result.candidates[0].name == "Led Zeppelin"
    rows = candidates_as_combo_rows(result)
    assert rows == [
        {
            "id": "zep",
            "name": "Led Zeppelin",
            "followers": 20_000_000,
            "genres": ["classic rock", "album rock"],
        }
    ]


def test_genre_artist_candidates_empty_query():
    result = genre_artist_candidates("  ", genre_search=lambda g: [])
    assert not result.ok
    assert result.reason == "empty_query"
    assert result.candidates == ()


def test_genre_artist_candidates_no_match():
    result = genre_artist_candidates("obscure-mood-zzz", genre_search=lambda g: [])
    assert not result.ok
    assert result.reason == "no_match"
    assert candidates_as_combo_rows(result) == []


def test_genre_artist_candidates_too_small():
    def tiny(_genre: str):
        return [_artist("Bedroom", artist_id="b1", followers_total=12, genres=["lo-fi"])]

    result = genre_artist_candidates("lo-fi", genre_search=tiny)
    assert not result.ok
    assert result.reason == "too_small"


def test_genre_artist_candidates_missing_credentials(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)

    def boom(_genre: str):
        raise MissingSpotifyCredentials("SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET are required for genre search")

    result = genre_artist_candidates("ambient", genre_search=boom)
    assert not result.ok
    assert result.reason == "missing_credentials"


def test_genre_artist_candidates_spotify_error():
    def boom(_genre: str):
        raise SpotifyClientError("HTTP 503")

    result = genre_artist_candidates("ambient", genre_search=boom)
    assert not result.ok
    assert result.reason == "spotify_error"
    assert "503" in result.message


def test_genre_artist_candidates_caches_same_query():
    """Same mood query must not re-hit Spotify on rerun / chip click."""
    calls: list[str] = []

    def fake_search(genre: str):
        calls.append(genre)
        return [
            _artist(
                "Brian Eno",
                artist_id="eno",
                followers_total=2_000_000,
                genres=["ambient", "art rock"],
            )
        ]

    first = genre_artist_candidates("Ambient", genre_search=fake_search)
    second = genre_artist_candidates(" ambient ", genre_search=fake_search)
    assert first.ok and second.ok
    assert first.candidates[0].name == "Brian Eno"
    assert second.candidates == first.candidates
    assert calls == ["Ambient"]  # second call served from cache


def test_genre_artist_candidates_session_cache_isolated():
    calls: list[str] = []

    def fake_search(genre: str):
        calls.append(genre)
        return [
            _artist(
                "Nils Frahm",
                artist_id="nf",
                followers_total=500_000,
                genres=["ambient"],
            )
        ]

    session: dict = {}
    a = genre_artist_candidates(
        "ambient", genre_search=fake_search, session_cache=session
    )
    b = genre_artist_candidates(
        "ambient", genre_search=fake_search, session_cache=session
    )
    assert a.ok and b.ok
    assert calls == ["ambient"]
    assert session  # keyed entry stored for Streamlit session_state reuse


def test_spotify_error_not_cached_allows_retry():
    calls = {"n": 0}

    def boom(_genre: str):
        calls["n"] += 1
        if calls["n"] == 1:
            raise SpotifyClientError("HTTP 503")
        return [
            _artist(
                "Aphex Twin",
                artist_id="afx",
                followers_total=1_000_000,
                genres=["ambient", "idm"],
            )
        ]

    first = genre_artist_candidates("idm", genre_search=boom)
    assert not first.ok and first.reason == "spotify_error"
    second = genre_artist_candidates("idm", genre_search=boom)
    assert second.ok
    assert second.candidates[0].name == "Aphex Twin"
    assert calls["n"] == 2


def test_mood_combo_names_uses_cache_no_fingerprint_invent():
    """Helper returns Spotify names only — never invents Glass/Eno wallpaper."""
    calls: list[str] = []

    def fake_search(genre: str):
        calls.append(genre)
        return [
            _artist(
                "Grouper",
                artist_id="grp",
                followers_total=200_000,
                genres=["ambient", "drone"],
            )
        ]

    session: dict = {}
    names = mood_combo_names(
        "drone", limit=10, session_cache=session, genre_search=fake_search
    )
    again = mood_combo_names(
        "drone", limit=10, session_cache=session, genre_search=fake_search
    )
    assert names == ["Grouper"]
    assert again == names
    assert calls == ["drone"]
    assert "Philip Glass" not in names
    assert "Brian Eno" not in names
    assert mood_combo_names("", genre_search=fake_search) == []
    assert mood_combo_names("zzz-none", genre_search=lambda _g: []) == []


def test_genre_with_credentials_missing_raises(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    with pytest.raises(MissingSpotifyCredentials):
        search_artists_by_genre_with_credentials("ambient")


def test_artist_path_unchanged_name_first_still_preferred():
    """Regression: mood genre helper must not alter name-first artist search."""
    from midi_gen.spotify_client import search_artists_for_query

    seen = []

    def opener(req, timeout=20):
        seen.append(req.full_url)
        if req.full_url.startswith(SEARCH_URL) and "genre" not in req.full_url:
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
        raise AssertionError("genre fallback must not run when name hits")

    artists = search_artists_for_query("Miles Davis", access_token="tok", opener=opener)
    assert artists[0].name == "Miles Davis"
    assert sum(1 for u in seen if "genre" in u) == 0


def test_package_exports_mood_api():
    """Public mood API is re-exported from package __init__ (and importable)."""
    init_text = (_ROOT / "__init__.py").read_text(encoding="utf-8")
    for name in (
        "ArtistCandidate",
        "GenreArtistCandidates",
        "candidates_as_combo_rows",
        "clear_genre_artist_cache",
        "genre_artist_candidates",
        "mood_combo_names",
    ):
        assert name in init_text
        assert f'"{name}"' in init_text or f"'{name}'" in init_text
    # Smoke: ArtistCandidate shape for gate → recipe handoff
    c = ArtistCandidate(
        id="x",
        name="Test",
        followers_total=10_000,
        genres=("ambient",),
    )
    assert c.followers_total >= MIN_SPOTIFY_FOLLOWERS
    assert callable(genre_artist_candidates)
    assert callable(candidates_as_combo_rows)
    assert callable(mood_combo_names)
    assert callable(clear_genre_artist_cache)
