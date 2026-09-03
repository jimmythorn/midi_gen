"""Interesting-returns B: kill wallpaper leaks; feel still layers on who-chip."""

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

from midi_gen.artist_gate import ArtistGateAccept
from midi_gen.cursor_style_lookup import lookup_musician_style
from midi_gen.musician_styles import (
    MUSICIAN_STYLE_CATALOG,
    get_profile_by_id,
    has_full_recipe_contract,
    profile_from_dict,
    recipe_structure_fingerprint,
    sparse_unknown_profile,
)
from midi_gen.spotify_client import SpotifyArtist
from midi_gen.style_prompting import preview_recipe, resolve_lookup_inputs


def _eno_fp():
    return recipe_structure_fingerprint(get_profile_by_id("eno_ambient"))


def _glass_fp():
    return recipe_structure_fingerprint(get_profile_by_id("glass_minimal"))


def test_custom_query_not_eno_ambient_fingerprint():
    """Leak (a): unknown / custom_query must not equal eno_ambient recipe fingerprint."""
    sparse = sparse_unknown_profile("zzzz-totally-unknown-musician-xyz")
    assert sparse.id == "custom_query"
    assert recipe_structure_fingerprint(sparse) != _eno_fp()
    assert recipe_structure_fingerprint(sparse) != _glass_fp()
    assert has_full_recipe_contract(sparse)

    blank = profile_from_dict(
        {
            "id": "custom_query",
            "name": "Mystery",
            "styles": ["mystery"],
            "generation_type": "arpeggio",
            "mode": "minor",
            "bpm": 100,
            "effects_preset": "subtle_tape",
        },
        source="sparse",
    )
    assert recipe_structure_fingerprint(blank) != _eno_fp()
    assert MUSICIAN_STYLE_CATALOG[0].id == "eno_ambient"


def test_lookup_unknown_not_wallpaper_eno(monkeypatch):
    monkeypatch.setattr(
        "midi_gen.cursor_style_lookup.require_artist",
        lambda query, identity_name=None, **_kwargs: ArtistGateAccept(
            query=query,
            source="spotify",
            message="test",
            spotify_artist=SpotifyArtist(
                id="x",
                name=query,
                type="artist",
                followers_total=50_000,
                raw={"genres": []},
            ),
        ),
    )
    result = lookup_musician_style(
        "zzzz-unknown-vibe-no-catalog-hit-42",
        use_cursor_sdk=False,
    )
    assert result.profile.id == "custom_query"
    assert not result.matched_locally
    assert recipe_structure_fingerprint(result.profile) != _eno_fp()
    assert recipe_structure_fingerprint(result.profile) != _glass_fp()
    assert has_full_recipe_contract(result.profile)


def test_spotify_stranger_not_glass_from_catalog_pick():
    """Leak (b): stranger must not emit glass_minimal just because who-chip is Glass."""
    artist = SpotifyArtist(
        id="richter1",
        name="Max Richter",
        type="artist",
        followers_total=1_200_000,
        raw={"genres": ["compositional ambient", "neo-classical", "post-minimalism"]},
    )
    gate = ArtistGateAccept(
        query="Max Richter",
        source="spotify",
        spotify_artist=artist,
        message="spotify accept",
    )
    query, identity_name = resolve_lookup_inputs(
        "Philip Glass", "Max Richter", gate_accept=gate
    )
    assert query == "Max Richter"
    assert identity_name is None

    result = lookup_musician_style(
        query,
        use_cursor_sdk=False,
        identity_name=identity_name,
        skip_artist_gate=True,
        gate_accept=gate,
    )
    assert result.profile.id != "glass_minimal"
    assert result.profile.id != "eno_ambient"
    assert result.profile.name == "Max Richter"
    assert has_full_recipe_contract(result.profile)
    assert "followers.total" in (result.profile.style_notes or "")
    assert result.profile.source in ("cousin", "sparse", "hybrid")


def test_require_artist_genres_drive_cousin_few_shot():
    """Leak (c): genres from gate accept must drive cousin selection."""
    artist = SpotifyArtist(
        id="monk-like",
        name="Stranger Jazz Pianist",
        type="artist",
        followers_total=80_000,
        raw={"genres": ["jazz", "bebop", "hard bop", "angular"]},
    )
    gate = ArtistGateAccept(
        query="Stranger Jazz Pianist",
        source="spotify",
        spotify_artist=artist,
        message="spotify",
    )
    result = lookup_musician_style(
        "Stranger Jazz Pianist",
        use_cursor_sdk=False,
        skip_artist_gate=True,
        gate_accept=gate,
    )
    assert result.profile.id == "custom_query"
    assert has_full_recipe_contract(result.profile)
    assert result.profile.source == "cousin"
    assert result.profile.development is not None
    assert result.profile.chord_progression
    # Jazz/angular genres → Monk cousin fingerprint (not tautology).
    monk = get_profile_by_id("monk_angles")
    assert any(s in result.profile.styles for s in ("jazz", "bebop", "hard bop", "angular"))
    assert "Monk" in result.message or result.candidates[0].id == "monk_angles"
    assert result.profile.generation_type == monk.generation_type
    assert result.profile.mode == monk.mode
    assert result.profile.development.get("mutate_ops") == monk.development.get("mutate_ops")
    opts = result.profile.to_options()
    assert "development" in opts
    assert "chord_progression" in opts


def test_empty_vibe_catalog_stick():
    q, ident = resolve_lookup_inputs("Philip Glass", "")
    assert q == "Philip Glass"
    assert ident == "Philip Glass"
    who = lookup_musician_style(q, use_cursor_sdk=False, identity_name=ident)
    assert who.profile.id == "glass_minimal"


def test_feel_layers_on_who_not_eno():
    """Mood/feel stays pinned to who — ambient drone must NOT become eno_ambient."""
    q, ident = resolve_lookup_inputs("Philip Glass", "ambient drone")
    assert ident == "Philip Glass"
    assert "Philip Glass" in q
    assert "ambient drone" in q
    result = lookup_musician_style(q, use_cursor_sdk=False, identity_name=ident)
    assert result.profile.id == "glass_minimal"
    assert result.profile.id != "eno_ambient"

    q2, ident2 = resolve_lookup_inputs("Philip Glass", "angular jazz")
    assert ident2 == "Philip Glass"
    assert lookup_musician_style(
        q2, use_cursor_sdk=False, identity_name=ident2
    ).profile.id == "glass_minimal"


def test_unknown_feel_still_layers_on_who():
    """Unknown feel text + Glass → still Glass identity, feel layered."""
    q, ident = resolve_lookup_inputs(
        "Philip Glass", "zzzzqwerty totally unknown vibe 999"
    )
    assert ident == "Philip Glass"
    assert "Philip Glass" in q
    result = lookup_musician_style(q, use_cursor_sdk=False, identity_name=ident)
    assert result.profile.id == "glass_minimal"


def test_other_catalog_musician_unpins():
    q, ident = resolve_lookup_inputs("Philip Glass", "Erik Satie")
    assert q == "Erik Satie"
    assert ident is None
    result = lookup_musician_style(q, use_cursor_sdk=False, identity_name=ident)
    assert result.profile.id == "satie_neoclassical"


def test_catalog_identity_still_binds():
    glass = lookup_musician_style(
        "Philip Glass",
        use_cursor_sdk=False,
        identity_name="Philip Glass",
    )
    assert glass.profile.id == "glass_minimal"

    eno = lookup_musician_style("Brian Eno", use_cursor_sdk=False)
    assert eno.profile.id == "eno_ambient"

    satie = lookup_musician_style(
        "Erik Satie",
        use_cursor_sdk=False,
        identity_name="Erik Satie",
    )
    assert satie.profile.id == "satie_neoclassical"


def test_preview_feel_vs_stranger():
    feel = preview_recipe(
        catalog_name="Philip Glass",
        vibe_text="ambient drone",
        effects_preset="subtle_tape",
    )
    assert feel.path == "both"
    assert feel.profile.id == "glass_minimal"
    assert "Philip Glass" in feel.query
    assert "ambient drone" in feel.query
    assert "feel ambient drone" in feel.plain_feel_line

    artist = SpotifyArtist(
        id="x",
        name="Nils Frahm Cousin",
        type="artist",
        followers_total=200_000,
        raw={"genres": ["felt piano", "neo-classical", "modern classical"]},
    )
    gate = ArtistGateAccept(
        query="Nils Frahm Cousin",
        source="spotify",
        spotify_artist=artist,
    )
    preview = preview_recipe(
        catalog_name="Philip Glass",
        vibe_text="Nils Frahm Cousin",
        gate_accept=gate,
    )
    assert preview.profile.id != "glass_minimal"
    assert preview.query == "Nils Frahm Cousin"
    assert has_full_recipe_contract(preview.profile)


def test_few_shot_rejects_effects_only():
    from midi_gen.musician_styles import (
        cousin_recipe_from_neighbors,
        is_effects_only_overlay,
    )

    sparse = sparse_unknown_profile("X")
    effects_only = profile_from_dict(
        {
            **sparse.as_dict(),
            "effects_preset": "worn_tape",
            "name": "Effects Only",
        },
        source="cousin",
    )
    assert is_effects_only_overlay(effects_only, sparse)

    monk = get_profile_by_id("monk_angles")
    frahm = get_profile_by_id("frahm_felt")
    cousin = cousin_recipe_from_neighbors(
        "Stranger",
        [monk, frahm],
        styles=["jazz"],
        followers_total=50_000,
    )
    assert cousin is not None
    assert has_full_recipe_contract(cousin)
    assert not is_effects_only_overlay(cousin, sparse)
    assert cousin.development is not None
    assert cousin.chord_progression
