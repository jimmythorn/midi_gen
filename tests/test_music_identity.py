"""Music-identity parser and Spotify-down Cursor fallback (no live SDK)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if "midi_gen" not in sys.modules:
    _pkg = types.ModuleType("midi_gen")
    _pkg.__path__ = [str(_ROOT)]  # type: ignore[attr-defined]
    _pkg.__file__ = str(_ROOT / "__init__.py")
    sys.modules["midi_gen"] = _pkg

from midi_gen.artist_gate import (
    ArtistGateAccept,
    ArtistGateReject,
    clear_spotify_down_cache,
    resolve_artist_query,
)
from midi_gen.music_agent import (
    MUSIC_AGENT_DISALLOWED_TOOLS,
    MUSIC_SANDBOX_RULES,
    agent_sandbox_dir,
    music_local_options,
)
from midi_gen.music_identity import (
    MusicIdentityAccept,
    MusicIdentityReject,
    _cache_put,
    clear_music_identity_cache,
    lookup_music_identity_with_sdk,
    parse_music_identity,
)
from midi_gen.spotify_client import (
    MissingSpotifyCredentials,
    SpotifyArtist,
    SpotifyClientError,
)


def test_parse_accepts_artist_and_genre():
    artist = parse_music_identity(
        {
            "ok": True,
            "kind": "artist",
            "name": "DIIV",
            "genres": ["shoegaze", "indie"],
            "confidence": 0.9,
        },
        query="diiv",
    )
    assert isinstance(artist, MusicIdentityAccept)
    assert artist.kind == "artist"
    assert artist.name == "DIIV"
    assert artist.genres == ("shoegaze", "indie")

    genre = parse_music_identity(
        {"ok": True, "kind": "genre", "name": "classic rock", "genres": ["classic rock"]},
        query="classic rock",
    )
    assert isinstance(genre, MusicIdentityAccept)
    assert genre.kind == "genre"
    assert genre.name == "classic rock"


def test_parse_rejects_non_musician():
    hit = parse_music_identity(
        {"ok": False, "reason": "not_a_musician"},
        query="Ted Bundy",
    )
    assert isinstance(hit, MusicIdentityReject)
    assert hit.reason == "not_a_musician"


def test_parse_returns_none_for_unusable_payload():
    assert parse_music_identity("nope", query="x") is None
    assert parse_music_identity({"ok": True, "kind": "person", "name": "X"}, query="x") is None
    assert parse_music_identity({"ok": True, "kind": "artist", "name": ""}, query="x") is None
    assert parse_music_identity({"kind": "artist", "name": "X"}, query="x") is None


def test_spotify_down_bypasses_to_cursor_agent():
    def down(_query: str):
        raise SpotifyClientError("HTTP 503")

    def agent(_query: str):
        return MusicIdentityAccept(
            query="DIIV",
            kind="artist",
            name="DIIV",
            genres=("shoegaze",),
            confidence=0.8,
        )

    result = resolve_artist_query(
        "DIIV",
        spotify_search=down,
        music_identity=agent,
        force_spotify=True,
    )
    assert isinstance(result, ArtistGateAccept)
    assert result.source == "agent"
    assert result.agent_name == "DIIV"
    assert result.agent_kind == "artist"
    assert result.agent_genres == ("shoegaze",)


def test_spotify_down_agent_reject_stays_reject():
    def down(_query: str):
        raise SpotifyClientError("HTTP 503")

    def agent(_query: str):
        return MusicIdentityReject(query="Ted Bundy", reason="not_a_musician")

    result = resolve_artist_query(
        "Ted Bundy",
        spotify_search=down,
        music_identity=agent,
        force_spotify=True,
    )
    assert isinstance(result, ArtistGateReject)
    assert result.reason == "not_a_musician"


def test_spotify_accept_skips_agent():
    def hit(_query: str):
        return [
            SpotifyArtist(
                id="x",
                name="Miles Davis",
                type="artist",
                followers_total=10_000,
                raw={"id": "x", "name": "Miles Davis", "type": "artist"},
            )
        ]

    def boom(_query: str):
        raise AssertionError("agent must not run when Spotify accepts")

    result = resolve_artist_query(
        "Miles Davis",
        spotify_search=hit,
        music_identity=boom,
        force_spotify=True,
    )
    assert isinstance(result, ArtistGateAccept)
    assert result.source == "spotify"
    assert result.spotify_artist is not None
    assert result.spotify_artist.name == "Miles Davis"


def test_spotify_content_reject_does_not_ask_agent():
    def empty(_query: str):
        return []

    def boom(_query: str):
        raise AssertionError("agent must not rescue Spotify no_match")

    result = resolve_artist_query(
        "Ted Bundy",
        spotify_search=empty,
        music_identity=boom,
        force_spotify=True,
    )
    assert isinstance(result, ArtistGateReject)
    assert result.reason == "no_match"


def test_identity_cache_skips_second_sdk_call(monkeypatch):
    clear_music_identity_cache()
    hit = MusicIdentityAccept(query="DIIV", kind="artist", name="DIIV")
    _cache_put("DIIV", hit)
    monkeypatch.setattr(
        "midi_gen.cursor_style_lookup.cursor_sdk_available",
        lambda: True,
    )

    def boom(*_a, **_k):
        raise AssertionError("cached identity must not create an agent")

    monkeypatch.setattr("midi_gen.music_agent.create_music_agent", boom)
    assert lookup_music_identity_with_sdk("diiv") is hit
    clear_music_identity_cache()


def test_missing_spotify_credentials_bypasses_to_cursor_agent():
    def down(_query: str):
        raise MissingSpotifyCredentials("SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET are required")

    def agent(_query: str):
        return MusicIdentityAccept(
            query="classic rock",
            kind="genre",
            name="classic rock",
            genres=("classic rock",),
        )

    result = resolve_artist_query(
        "classic rock",
        spotify_search=down,
        music_identity=agent,
        force_spotify=True,
    )
    assert isinstance(result, ArtistGateAccept)
    assert result.source == "agent"
    assert result.agent_kind == "genre"
    assert result.agent_name == "classic rock"


def test_spotify_down_and_agent_unavailable_still_generates():
    def down(_query: str):
        raise SpotifyClientError("HTTP 503")

    result = resolve_artist_query(
        "classic rock",
        spotify_search=down,
        music_identity=lambda _q: None,
        force_spotify=True,
    )
    assert isinstance(result, ArtistGateAccept)
    assert result.source == "agent"
    assert result.agent_name == "classic rock"


def test_cached_spotify_down_skips_live_search():
    from midi_gen import artist_gate as gate_mod

    clear_spotify_down_cache()
    gate_mod._mark_spotify_down()
    try:
        result = resolve_artist_query(
            "DIIV",
            force_spotify=True,
            music_identity=lambda _q: None,
        )
        assert isinstance(result, ArtistGateAccept)
        assert result.source == "agent"
        assert result.agent_name == "DIIV"
    finally:
        clear_spotify_down_cache()


def test_music_agent_sandbox_is_music_only():
    root = agent_sandbox_dir()
    assert (root / "DOMAIN.txt").is_file()
    domain = (root / "DOMAIN.txt").read_text(encoding="utf-8")
    assert "Allowed:" in domain
    assert "Forbidden:" in domain
    assert "musical" in MUSIC_SANDBOX_RULES.lower() or "composition" in MUSIC_SANDBOX_RULES.lower()
    assert "non-music" in MUSIC_SANDBOX_RULES
    opts = music_local_options()
    assert str(opts.cwd) == str(root)
    assert list(opts.dirs) == [str(root)]
    assert opts.setting_sources == []
    assert opts.sandbox_options.enabled is True
    assert "Shell" in MUSIC_AGENT_DISALLOWED_TOOLS
    assert "WebSearch" in MUSIC_AGENT_DISALLOWED_TOOLS
    src_ident = (_ROOT / "music_identity.py").read_text(encoding="utf-8")
    src_lookup = (_ROOT / "cursor_style_lookup.py").read_text(encoding="utf-8")
    assert "create_music_agent" in src_ident
    assert "create_music_agent" in src_lookup
    assert "MUSIC_SANDBOX_RULES" in src_ident
    assert "MUSIC_SANDBOX_RULES" in src_lookup
    assert "LocalAgentOptions(cwd=cwd)" not in src_lookup
    assert "sandboxed to music" in src_lookup
    src_agent = (_ROOT / "music_agent.py").read_text(encoding="utf-8")
    assert "mcp_servers" not in src_agent
    assert "disallowed_tools=" not in src_agent
