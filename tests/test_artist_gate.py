"""Tests for reject-before-generate artist gate (catalog / Spotify)."""

from __future__ import annotations

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

from midi_gen.artist_gate import (
    ArtistGateAccept,
    ArtistGateReject,
    ArtistRejected,
    require_artist,
    resolve_artist_query,
)
from midi_gen.cursor_style_lookup import generate_midi_for_style, lookup_musician_style
from midi_gen.spotify_client import MIN_SPOTIFY_FOLLOWERS, SpotifyArtist


def _artist(
    name: str = "Philip Glass",
    *,
    type_: str = "artist",
    followers_total: int | None = MIN_SPOTIFY_FOLLOWERS,
) -> SpotifyArtist:
    raw: dict = {"id": "spotify-artist-1", "name": name, "type": type_}
    if followers_total is not None:
        raw["followers"] = {"total": followers_total}
    return SpotifyArtist(
        id="spotify-artist-1",
        name=name,
        type=type_,
        followers_total=followers_total,
        raw=raw,
    )


def test_catalog_hit_skips_spotify():
    calls = []

    def boom(query: str):
        calls.append(query)
        raise AssertionError("Spotify must not be called on catalog hit")

    result = resolve_artist_query("Philip Glass", spotify_search=boom)
    assert isinstance(result, ArtistGateAccept)
    assert result.accepted
    assert result.source == "catalog"
    assert calls == []

    satie = resolve_artist_query("Erik Satie", spotify_search=boom)
    assert satie.source == "catalog"
    assert calls == []


def test_identity_pin_skips_spotify_even_with_odd_feel_query():
    calls = []

    def boom(query: str):
        calls.append(query)
        raise AssertionError("Spotify must not run when identity is catalog")

    result = resolve_artist_query(
        "Philip Glass — zzzz totally unknown vibe 999",
        identity_name="Philip Glass",
        spotify_search=boom,
    )
    assert result.accepted
    assert result.source == "catalog"
    assert calls == []


def test_ted_bundy_class_query_rejected():
    def empty(_query: str):
        return []

    result = resolve_artist_query("Ted Bundy", spotify_search=empty)
    assert isinstance(result, ArtistGateReject)
    assert not result.accepted
    assert result.reason == "no_match"

    with pytest.raises(ArtistRejected) as caught:
        require_artist("Ted Bundy", spotify_search=empty)
    assert caught.value.result.reason == "no_match"


def test_spotify_non_artist_type_rejected():
    def weird(_query: str):
        return [_artist("Podcast Host", type_="show", followers_total=999_999)]

    result = resolve_artist_query("zzzz-artist-probe-9f3a", spotify_search=weird)
    assert isinstance(result, ArtistGateReject)
    assert result.reason == "not_a_musician"


def test_spotify_artist_9999_followers_rejected():
    def hit(_query: str):
        return [_artist("Almost Famous", followers_total=9_999)]

    result = resolve_artist_query("Almost Famous", spotify_search=hit)
    assert isinstance(result, ArtistGateReject)
    assert result.reason == "too_small"


def test_spotify_artist_10000_followers_accepted():
    def hit(_query: str):
        return [_artist("Miles Davis", followers_total=10_000)]

    result = resolve_artist_query("Miles Davis", spotify_search=hit)
    assert isinstance(result, ArtistGateAccept)
    assert result.source == "spotify"
    assert result.spotify_artist is not None
    assert result.spotify_artist.name == "Miles Davis"
    assert result.spotify_artist.type == "artist"
    assert result.spotify_artist.followers_total == 10_000


def test_spotify_artist_missing_followers_accepted():
    """Client Credentials search omits followers.total — still a named artist."""
    def hit(_query: str):
        return [_artist("Miles Davis", followers_total=None)]

    result = resolve_artist_query("Miles Davis", spotify_search=hit)
    assert isinstance(result, ArtistGateAccept)
    assert result.source == "spotify"
    assert result.spotify_artist is not None
    assert result.spotify_artist.name == "Miles Davis"


def test_spotify_artist_accepted():
    def hit(_query: str):
        return [_artist("Miles Davis", followers_total=1_500_000)]

    result = resolve_artist_query("Miles Davis", spotify_search=hit)
    assert isinstance(result, ArtistGateAccept)
    assert result.source == "spotify"
    assert result.spotify_artist is not None
    assert result.spotify_artist.name == "Miles Davis"
    assert result.spotify_artist.type == "artist"


def test_weak_description_keyword_does_not_skip_spotify():
    """\"Not Music\" must not catalog-accept via description token noise."""
    calls = []

    def empty(query: str):
        calls.append(query)
        return []

    result = resolve_artist_query("Not Music", spotify_search=empty)
    assert isinstance(result, ArtistGateReject)
    assert result.reason == "no_match"
    assert calls == ["Not Music"]


def test_force_spotify_does_not_skip_catalog_name():
    calls = []

    def hit(query: str):
        calls.append(query)
        return [_artist("Philip Glass", followers_total=1_000_000)]

    result = resolve_artist_query(
        "Philip Glass",
        spotify_search=hit,
        force_spotify=True,
    )
    assert result.accepted
    assert result.source == "spotify"
    assert calls == ["Philip Glass"]


def test_short_catalog_surname_still_skips_spotify():
    calls = []

    def boom(query: str):
        calls.append(query)
        raise AssertionError("surname catalog hit must skip Spotify")

    for q in ("Glass", "Satie", "Reich"):
        result = resolve_artist_query(q, spotify_search=boom)
        assert result.accepted and result.source == "catalog", q
    assert calls == []


def test_missing_env_rejects_unknown_without_create_arp(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)

    create_calls = []

    def fake_create_arp(options):
        create_calls.append(options)
        return "/tmp/should-not-exist.mid"

    monkeypatch.setattr(
        "midi_gen.arpeggio_generation.create_arp",
        fake_create_arp,
    )
    # Also patch the late import path used inside generate_midi_for_style
    import midi_gen.arpeggio_generation as ag

    monkeypatch.setattr(ag, "create_arp", fake_create_arp)

    with pytest.raises(ArtistRejected) as caught:
        generate_midi_for_style(
            "Ted Bundy",
            use_cursor_sdk=False,
            overrides={"bars": 2, "debug": False},
        )
    assert caught.value.result.reason == "missing_credentials"
    assert create_calls == []


def test_missing_env_catalog_path_still_generates(monkeypatch, tmp_path):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)

    path, result, options = generate_midi_for_style(
        "Philip Glass",
        use_cursor_sdk=False,
        overrides={"bars": 2, "effects_preset": "clean", "debug": False},
    )
    assert Path(path).exists()
    assert result.profile.id == "glass_minimal"
    assert options["bars"] == 2


def test_satie_name_still_generates(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)

    path, result, _options = generate_midi_for_style(
        "Erik Satie",
        use_cursor_sdk=False,
        overrides={"bars": 2, "effects_preset": "clean", "debug": False},
    )
    assert Path(path).exists()
    assert result.profile.id == "satie_neoclassical"


def test_feel_phrase_queries_spotify_not_catalog_tags():
    calls = []

    def hit(query: str):
        calls.append(query)
        return [_artist("Led Zeppelin", followers_total=20_000_000)]

    result = resolve_artist_query("classic rock", spotify_search=hit)
    assert isinstance(result, ArtistGateAccept)
    assert result.source == "spotify"
    assert result.spotify_artist is not None
    assert result.spotify_artist.name == "Led Zeppelin"
    assert calls == ["classic rock"]

    gym = resolve_artist_query("gymnopedie", spotify_search=hit)
    assert gym.source == "spotify"
    assert "gymnopedie" in calls


def test_generate_rejects_before_sdk_and_create_arp(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)

    sdk_calls = []
    create_calls = []

    monkeypatch.setattr(
        "midi_gen.cursor_style_lookup.cursor_sdk_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "midi_gen.cursor_style_lookup.lookup_with_cursor_sdk",
        lambda *a, **k: sdk_calls.append((a, k)) or (None, None),
    )
    monkeypatch.setattr(
        "midi_gen.arpeggio_generation.create_arp",
        lambda options: create_calls.append(options) or "/tmp/no.mid",
    )

    with pytest.raises(ArtistRejected) as caught:
        generate_midi_for_style("Ted Bundy", use_cursor_sdk=True)
    assert caught.value.result.reason == "missing_credentials"
    assert sdk_calls == []
    assert create_calls == []


def test_lookup_catalog_does_not_need_spotify(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    result = lookup_musician_style("Steve Reich", use_cursor_sdk=False)
    assert result.matched_locally
    assert result.profile.id == "reich_phase"


def test_no_secrets_in_repo():
    """Sanity: committed tree must not contain Spotify secret material."""
    root = Path(__file__).resolve().parents[1]
    assert not (root / ".env").exists()
    for path in (root / "spotify_client.py", root / "artist_gate.py", root / "README.md"):
        text = path.read_text(encoding="utf-8")
        assert "SPOTIFY_CLIENT_SECRET=sk_" not in text
        assert 'SPOTIFY_CLIENT_SECRET="' not in text
