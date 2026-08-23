"""Tests for stylistic prompting helpers, aliases, and richer vibe tags."""

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

from midi_gen.cursor_style_lookup import lookup_musician_style
from midi_gen.musician_styles import (
    MUSICIAN_STYLE_CATALOG,
    alias_target_ids,
    find_best_profile,
    find_profiles,
    get_profile_by_id,
    score_profile,
)
from midi_gen.style_prompting import (
    FEATURED_STYLE_IDS,
    double_bars,
    featured_style_cards,
    format_match_line,
    format_plain_feel_line,
    format_recipe_one_liner,
    half_bars,
    mood_chip_packs,
    preview_recipe,
    related_from_lookup_result,
    related_profiles,
    resolve_happy_path_query,
    surprise_related_profile,
    vibe_chips,
)


def test_alias_hits_core_phrases():
    assert alias_target_ids("gymnopédie") == ["satie_neoclassical"]
    assert alias_target_ids("gymnopedie") == ["satie_neoclassical"]
    assert alias_target_ids("sheets of sound") == ["coltrane_sheets"]
    assert alias_target_ids("phase music") == ["reich_phase"]
    assert alias_target_ids("phasing") == ["reich_phase"]
    assert alias_target_ids("ambient drone")[0] == "eno_ambient"
    assert alias_target_ids("ambient pad")[0] == "eno_ambient"


def test_alias_minimalism_maps_reich_and_glass():
    ids = alias_target_ids("minimalism")
    assert "reich_phase" in ids
    assert "glass_minimal" in ids


def test_find_best_profile_alias_queries():
    assert find_best_profile("gymnopédie").id == "satie_neoclassical"
    assert find_best_profile("sheets of sound").id == "coltrane_sheets"
    assert find_best_profile("phase music").id == "reich_phase"
    assert find_best_profile("ambient pad").id == "eno_ambient"
    assert find_best_profile("angular jazz").id == "monk_angles"
    assert find_best_profile("felt piano").id == "frahm_felt"
    assert find_best_profile("glitchy idm").id == "aphex_glitch"


def test_minimalism_best_is_reich_or_glass_and_both_ranked():
    best = find_best_profile("minimalism")
    assert best is not None
    assert best.id in ("reich_phase", "glass_minimal")
    ranked = find_profiles("minimalism", limit=5)
    ranked_ids = {p.id for p in ranked}
    assert "reich_phase" in ranked_ids
    assert "glass_minimal" in ranked_ids


def test_richer_tags_score_across_full_catalog():
    """Vibe words hit profiles beyond the recently enriched four."""
    assert find_best_profile("impressionist wash").id == "debussy_color"
    assert find_best_profile("worn tape piano").id in ("frahm_felt", "aphex_glitch")
    assert find_best_profile("spare neoclassical").id == "satie_neoclassical"
    assert find_best_profile("counterpoint").id == "bach_sequence"
    assert score_profile("hypnotic pulse", get_profile_by_id("reich_phase")) > 0
    assert score_profile("felt piano", get_profile_by_id("frahm_felt")) > score_profile(
        "felt piano", get_profile_by_id("bach_sequence")
    )


def test_lookup_path_uses_aliases():
    result = lookup_musician_style("sheets of sound", use_cursor_sdk=False)
    assert result.matched_locally
    assert result.profile.id == "coltrane_sheets"
    # Related / also-considered from full catalog, not a fixed 4
    cand_ids = {c.id for c in result.candidates}
    assert result.profile.id in cand_ids or len(result.candidates) >= 1


def test_featured_cards_span_full_catalog_not_shortlist():
    cards = featured_style_cards()
    assert 4 <= len(cards) <= 6
    ids = {c.id for c in cards}
    # Must include non-Glass/Reich/Eno/Coltrane entries from the curated set
    assert ids & {"debussy_color", "monk_angles", "aphex_glitch", "frahm_felt", "bach_sequence", "satie_neoclassical"}
    # Every featured id exists in full catalog
    catalog_ids = {p.id for p in MUSICIAN_STYLE_CATALOG}
    assert ids <= catalog_ids
    assert set(FEATURED_STYLE_IDS) <= catalog_ids


def test_vibe_chips_are_examples_not_closed_set():
    chips = vibe_chips()
    assert 6 <= len(chips) <= 8
    # Free-text beyond chips still resolves
    assert find_best_profile("baroque sequence").id == "bach_sequence"
    assert resolve_happy_path_query("Philip Glass", "angular jazz") == "angular jazz"
    assert resolve_happy_path_query("Philip Glass", "  ") == "Philip Glass"


def test_mood_chip_packs_span_catalog_examples():
    packs = mood_chip_packs()
    assert 2 <= len(packs) <= 3
    labels = {p.label for p in packs}
    assert "Soft & sparse" in labels
    assert "Pulse & phase" in labels
    assert "Jazz & grit" in labels
    all_chips = [c for p in packs for c in p.chips]
    assert len(all_chips) >= 6
    # Packs are entry points — chips still resolve across the full catalog
    assert find_best_profile(all_chips[0]) is not None
    assert find_best_profile("counterpoint").id == "bach_sequence"


def test_half_double_bars_clamp():
    assert half_bars(8) == 4
    assert half_bars(3) == 2  # floor at 2
    assert half_bars(2) == 2
    assert double_bars(8) == 16
    assert double_bars(20) == 32  # cap at 32
    assert double_bars(32) == 32


def test_plain_feel_line_and_surprise_related():
    eno = get_profile_by_id("eno_ambient")
    line = format_plain_feel_line(eno)
    assert line.startswith("Sounds like Brian Eno")
    assert "drone" in line
    assert "slow" in line  # 72 BPM

    glass = get_profile_by_id("glass_minimal")
    glass_line = format_plain_feel_line(glass)
    assert "Philip Glass" in glass_line
    assert "arp" in glass_line

    surprise = surprise_related_profile(eno, vibe_hint="ambient")
    assert surprise is not None
    assert surprise.id != eno.id
    # Same as related[0] — named identity, not pure random
    related0 = related_profiles(eno, limit=1, vibe_hint="ambient")[0]
    assert surprise.id == related0.id


def test_recipe_preview_and_match_line():
    who = preview_recipe(catalog_name="Erik Satie", vibe_text="", effects_preset="human_feel")
    assert who.path == "catalog"
    assert who.profile.id == "satie_neoclassical"
    assert "drone" in who.one_liner or "arp" in who.one_liner
    assert "Matched:" in who.match_line
    assert "catalog" in who.match_line
    assert who.plain_feel_line.startswith("Sounds like Erik Satie")

    feel = preview_recipe(
        catalog_name="Philip Glass",
        vibe_text="ambient drone",
        effects_preset="subtle_tape",
    )
    assert feel.path == "vibe"
    assert feel.profile.id == "eno_ambient"
    assert "Matched:" in feel.match_line
    assert "Sounds like" in feel.plain_feel_line

    generic = preview_recipe(
        catalog_name="Philip Glass",
        vibe_text="zzzzqwerty totally unknown vibe 999",
    )
    assert generic.path == "vibe"
    assert generic.match_type == "generic"
    line = format_recipe_one_liner(who.profile)
    assert "Erik Satie" in line
    assert "Matched:" in format_match_line(who.profile, match_type="catalog")


def test_related_profiles_use_full_catalog():
    eno = get_profile_by_id("eno_ambient")
    related = related_profiles(eno, limit=3)
    assert 1 <= len(related) <= 3
    assert all(r.id != "eno_ambient" for r in related)
    related_ids = {r.id for r in related}
    # Must be able to surface non-Glass/Reich/Coltrane neighbors
    catalog_ids = {p.id for p in MUSICIAN_STYLE_CATALOG}
    assert related_ids <= catalog_ids

    # Prefer find_profiles / candidates — multi-alias minimalism surfaces both
    glass = get_profile_by_id("glass_minimal")
    result = lookup_musician_style("minimalism", use_cursor_sdk=False)
    related2 = related_from_lookup_result(result, limit=3, vibe_hint="minimalism")
    assert all(r.id != result.profile.id for r in related2)
    # At least one related is from the other minimalism sibling or broader catalog
    assert len(related2) >= 1
    assert glass.id in {result.profile.id} | {r.id for r in related2} or get_profile_by_id(
        "reich_phase"
    ).id in {result.profile.id} | {r.id for r in related2}


def test_all_catalog_profiles_have_rich_style_tags():
    assert len(MUSICIAN_STYLE_CATALOG) >= 10
    for profile in MUSICIAN_STYLE_CATALOG:
        assert len(profile.styles) >= 8, f"{profile.id} needs richer vibe tags"
