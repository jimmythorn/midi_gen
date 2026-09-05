"""Sample Musician drip UX — pre-Generate gate, blank recipe, plain copy."""

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

from midi_gen.artist_gate import ArtistGateAccept, ArtistGateReject
from midi_gen.spotify_client import MIN_SPOTIFY_FOLLOWERS, SpotifyArtist, SpotifyClientError
from midi_gen.style_prompting import (
    ARTIST_REJECT_DRIP,
    artist_gate_blocks_generate,
    artist_gate_wipes_sketch,
    artist_gate_query_for_ui,
    artist_reject_drip_copy,
    resolve_artist_gate_for_ui,
    session_clears_on_artist_reject,
)


def test_gate_query_prefers_typed_vibe_over_catalog_pin():
    assert artist_gate_query_for_ui("Philip Glass", "Ted Bundy") == "Ted Bundy"
    assert artist_gate_query_for_ui("Philip Glass", "  ambient drone  ") == "ambient drone"
    assert artist_gate_query_for_ui("Philip Glass", "") == "Philip Glass"
    assert artist_gate_query_for_ui("Philip Glass", "   ") == "Philip Glass"


def test_plain_drip_copy_never_surfaces_reason_enums():
    assert artist_reject_drip_copy() == "Not finding a musician…"
    assert artist_reject_drip_copy("not_a_musician") == ARTIST_REJECT_DRIP
    assert artist_reject_drip_copy("missing_credentials") == ARTIST_REJECT_DRIP
    assert artist_reject_drip_copy("too_small") == ARTIST_REJECT_DRIP
    assert "Rejected" not in artist_reject_drip_copy("not_a_musician")
    assert "not_a_musician" not in artist_reject_drip_copy("not_a_musician")
    assert "too_small" not in artist_reject_drip_copy("too_small")
    assert artist_reject_drip_copy("too_small") == "Not finding a musician…"


def test_session_clears_include_last_run_and_match_line():
    keys = session_clears_on_artist_reject()
    assert "last_run" in keys
    assert "match_line" in keys


def test_pre_generate_ted_bundy_rejects_despite_catalog_pin():
    def empty(_query: str):
        return []

    result = resolve_artist_gate_for_ui(
        "Philip Glass",
        "Ted Bundy",
        spotify_search=empty,
    )
    assert isinstance(result, ArtistGateReject)
    assert not result.accepted
    assert result.reason == "no_match"


def _spotify_artist(name: str) -> SpotifyArtist:
    return SpotifyArtist(
        id="spotify-artist-1",
        name=name,
        type="artist",
        followers_total=MIN_SPOTIFY_FOLLOWERS,
        raw={"id": "spotify-artist-1", "name": name, "type": "artist"},
    )


def test_pre_generate_feel_vibe_queries_spotify():
    calls = []

    def hit(query: str):
        calls.append(query)
        return [_spotify_artist("Brian Eno")]

    result = resolve_artist_gate_for_ui(
        "Philip Glass",
        "ambient drone",
        spotify_search=hit,
    )
    assert isinstance(result, ArtistGateAccept)
    assert result.source == "spotify"
    assert result.spotify_artist is not None
    assert result.spotify_artist.name == "Brian Eno"
    assert calls == ["ambient drone"]


def test_pre_generate_classic_rock_queries_spotify():
    calls = []

    def hit(query: str):
        calls.append(query)
        return [_spotify_artist("Led Zeppelin")]

    result = resolve_artist_gate_for_ui(
        "Philip Glass",
        "classic rock",
        spotify_search=hit,
    )
    assert isinstance(result, ArtistGateAccept)
    assert result.source == "spotify"
    assert result.spotify_artist is not None
    assert result.spotify_artist.name == "Led Zeppelin"
    assert calls == ["classic rock"]


def test_typed_search_hits_spotify_even_for_catalog_name():
    calls = []

    def hit(query: str):
        calls.append(query)
        return [_spotify_artist("Philip Glass")]

    result = resolve_artist_gate_for_ui(
        "",
        "Philip Glass",
        spotify_search=hit,
    )
    assert isinstance(result, ArtistGateAccept)
    assert result.source == "spotify"
    assert calls == ["Philip Glass"]


def test_pre_generate_empty_vibe_uses_catalog_identity():
    calls = []

    def boom(query: str):
        calls.append(query)
        raise AssertionError("empty vibe + catalog who must skip Spotify")

    result = resolve_artist_gate_for_ui("Erik Satie", "", spotify_search=boom)
    assert isinstance(result, ArtistGateAccept)
    assert result.source == "catalog"
    assert calls == []


def test_unknown_name_missing_creds_fail_closed(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(
        "midi_gen.artist_gate._default_music_identity",
        lambda _q: None,
    )

    result = resolve_artist_gate_for_ui("Philip Glass", "Ted Bundy")
    assert isinstance(result, ArtistGateReject)
    assert result.reason == "missing_credentials"
    assert artist_reject_drip_copy(result.reason) == ARTIST_REJECT_DRIP


def test_feel_alias_queries_spotify():
    calls = []

    def hit(query: str):
        calls.append(query)
        return [_spotify_artist("Erik Satie")]

    result = resolve_artist_gate_for_ui("Philip Glass", "gymnopedie", spotify_search=hit)
    assert result.accepted
    assert result.source == "spotify"
    assert calls == ["gymnopedie"]


def test_ui_gate_does_not_ask_cursor_on_spotify_429():
    def down(_query: str):
        raise SpotifyClientError("HTTP 429")

    def boom(_query: str):
        raise AssertionError("pre-paint gate must not ask Cursor")

    result = resolve_artist_gate_for_ui(
        "",
        "DIIV",
        spotify_search=down,
    )
    assert isinstance(result, ArtistGateReject)
    assert result.reason == "spotify_error"
    # Injected search without music_identity already skips the agent;
    # flag must stay off so a live UI 429 can reach Generate.
    from midi_gen.artist_gate import resolve_artist_query

    result2 = resolve_artist_query(
        "DIIV",
        spotify_search=down,
        music_identity=boom,
        force_spotify=True,
        allow_cursor_fallback=False,
    )
    assert isinstance(result2, ArtistGateReject)
    assert result2.reason == "spotify_error"


def test_spotify_down_does_not_drip_when_cursor_is_available():
    down = ArtistGateReject(query="DIIV", reason="spotify_error")
    assert artist_gate_blocks_generate(down, cursor_available=True) is False
    assert artist_gate_blocks_generate(down, cursor_available=False) is True
    miss = ArtistGateReject(query="DIIV", reason="missing_credentials")
    assert artist_gate_blocks_generate(miss, cursor_available=True) is False
    no_match = ArtistGateReject(query="Ted Bundy", reason="no_match")
    assert artist_gate_blocks_generate(no_match, cursor_available=True) is True
    ok = ArtistGateAccept(query="DIIV", source="spotify")
    assert artist_gate_blocks_generate(ok, cursor_available=True) is False


def test_finished_sketch_survives_later_gate_reject():
    assert (
        artist_gate_wipes_sketch(
            blocks_generate=True, generating=False, has_sketch=True
        )
        is False
    )
    assert (
        artist_gate_wipes_sketch(
            blocks_generate=True, generating=True, has_sketch=True
        )
        is True
    )
    assert (
        artist_gate_wipes_sketch(
            blocks_generate=True, generating=False, has_sketch=False
        )
        is True
    )
    assert (
        artist_gate_wipes_sketch(
            blocks_generate=False, generating=False, has_sketch=True
        )
        is False
    )
