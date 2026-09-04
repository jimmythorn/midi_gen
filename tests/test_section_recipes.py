"""Style Lab section recipes: who+section → flat Engine progression."""

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

from midi_gen.cursor_style_lookup import STYLE_PROFILE_JSON_SCHEMA
from midi_gen.musician_styles import (
    MUSICIAN_STYLE_CATALOG,
    find_progression_bearing_neighbors,
    get_profile_by_id,
    parse_section_role_from_text,
    profile_from_dict,
    progression_pitch_classes,
    resolve_section_recipe,
)


LOCKED_SECTION_IDS = (
    "glass_minimal",
    "reich_phase",
    "eno_ambient",
    "coltrane_sheets",
)


def _section_prog(profile, role: str):
    assert profile.sections, profile.id
    for entry in profile.sections:
        if entry.get("role") == role:
            return list(entry["chord_progression"])
    raise AssertionError(f"{profile.id} missing section role={role}")


def test_parse_section_role_from_text():
    assert parse_section_role_from_text("Philip Glass bridge") == "bridge"
    assert parse_section_role_from_text("chorus feel") == "chorus"
    assert parse_section_role_from_text("quiet verse pad") == "verse"
    assert parse_section_role_from_text("no section cue") is None


def test_schema_round_trip_section_block_to_options():
    profile = profile_from_dict(
        {
            "name": "Custom Section Artist",
            "styles": ["modal"],
            "section": {
                "role": "bridge",
                "chord_progression": ["E3", "B3", "A3", "E3"],
                "mode": "dorian",
                "bars": 8,
            },
            "development": {
                "enabled": True,
                "seed_bars": 1,
                "mutate_every_n": 2,
                "mutate_ops": ["invert", "thin"],
            },
        },
        source="cursor_sdk",
    )
    assert profile.section_role == "bridge"
    assert profile.chord_progression == ["E3", "B3", "A3", "E3"]
    assert profile.mode == "dorian"
    assert profile.bars == 8
    opts = profile.to_options()
    assert opts["chord_progression"] == ["E3", "B3", "A3", "E3"]
    assert opts["mode"] == "dorian"
    assert opts["bars"] == 8
    assert opts.get("section_role") == "bridge"


def test_schema_round_trip_sections_catalog_and_old_profiles():
    profile = profile_from_dict(
        {
            "name": "Section Catalog Sketch",
            "styles": ["jazz"],
            "chord_progression": ["D3", "G3", "D3", "C3"],
            "sections": [
                {
                    "role": "chorus",
                    "chord_progression": ["D3", "G3", "D3", "C3"],
                    "mode": "dorian",
                    "bars": 8,
                },
                {
                    "role": "bridge",
                    "chord_progression": ["D3", "Bb3", "A3", "C3"],
                    "mode": "dorian",
                    "bars": 8,
                },
            ],
            "development": {
                "enabled": True,
                "seed_bars": 1,
                "mutate_every_n": 1,
                "mutate_ops": ["add_attack"],
            },
        },
        source="cursor_sdk",
    )
    assert profile.sections is not None
    assert {s["role"] for s in profile.sections} == {"chorus", "bridge"}
    opts = profile.to_options(section_role="bridge")
    assert opts["chord_progression"] == ["D3", "Bb3", "A3", "C3"]

    # Old profiles without sections still load.
    legacy = profile_from_dict(
        {
            "name": "Legacy No Sections",
            "styles": ["piano"],
            "chord_progression": ["G3", "D3", "C3", "G3"],
            "mode": "major",
        },
        source="sparse",
    )
    assert legacy.sections is None
    assert legacy.chord_progression == ["G3", "D3", "C3", "G3"]
    assert "chord_progression" in legacy.to_options()


def test_resolve_section_recipe_picks_role():
    glass = get_profile_by_id("glass_minimal")
    assert glass is not None
    chorus = resolve_section_recipe(glass, "chorus")
    bridge = resolve_section_recipe(glass, "bridge")
    assert chorus.chord_progression == _section_prog(glass, "chorus")
    assert bridge.chord_progression == _section_prog(glass, "bridge")
    assert bridge.chord_progression != chorus.chord_progression
    assert bridge.section_role == "bridge"
    assert bridge.bars == 8
    assert chorus.bars == 16

    # Unknown role → top-level progression, stamped role.
    stamped = resolve_section_recipe(glass, "verse")
    # verse exists on glass
    assert stamped.chord_progression == _section_prog(glass, "verse")

    reich = get_profile_by_id("reich_phase")
    missing = resolve_section_recipe(reich, "verse")
    assert missing.section_role == "verse"
    assert missing.chord_progression == reich.chord_progression


def test_catalog_bridge_roots_differ_from_chorus():
    for pid in LOCKED_SECTION_IDS:
        profile = get_profile_by_id(pid)
        assert profile is not None, pid
        assert profile.sections, f"{pid} needs sections[]"
        roles = {s["role"] for s in profile.sections}
        assert "bridge" in roles and "chorus" in roles, pid
        bridge = progression_pitch_classes(_section_prog(profile, "bridge"))
        chorus = progression_pitch_classes(_section_prog(profile, "chorus"))
        assert bridge is not None and chorus is not None, pid
        assert bridge != chorus, f"{pid} bridge roots must differ from chorus"

    # Thin fingerprints on other progression-bearing profiles.
    for profile in MUSICIAN_STYLE_CATALOG:
        if not profile.sections:
            continue
        roles = {s["role"]: s for s in profile.sections}
        if "bridge" in roles and "chorus" in roles:
            b = progression_pitch_classes(roles["bridge"]["chord_progression"])
            c = progression_pitch_classes(roles["chorus"]["chord_progression"])
            assert b != c, profile.id


def test_eno_wash_stays_unheld_after_section_resolve():
    eno = get_profile_by_id("eno_ambient")
    assert eno is not None
    assert eno.drone_held is False
    bridge = resolve_section_recipe(eno, "bridge")
    assert bridge.drone_held is False
    opts = bridge.to_options()
    assert opts.get("drone_held") is False
    assert opts["chord_progression"] == _section_prog(eno, "bridge")


def test_glass_bridge_not_reich_identity():
    glass_bridge = resolve_section_recipe(get_profile_by_id("glass_minimal"), "bridge")
    reich = get_profile_by_id("reich_phase")
    assert glass_bridge.chord_progression != reich.chord_progression
    assert glass_bridge.development.get("additive_only") is True
    assert glass_bridge.development.get("phase_creep") is not True


def test_sdk_schema_includes_section_fields():
    assert "section_role" in STYLE_PROFILE_JSON_SCHEMA
    assert '"sections"' in STYLE_PROFILE_JSON_SCHEMA or "sections" in STYLE_PROFILE_JSON_SCHEMA
    assert "bridge roots must differ" in STYLE_PROFILE_JSON_SCHEMA
    assert "Glass/Eno wallpaper" in STYLE_PROFILE_JSON_SCHEMA
    assert "drone_held" in STYLE_PROFILE_JSON_SCHEMA
    assert "extend_factor" in STYLE_PROFILE_JSON_SCHEMA


def test_few_shot_helper_picks_progression_bearing_neighbors():
    neighbors = find_progression_bearing_neighbors("modal jazz sheets", limit=3)
    assert neighbors
    assert len(neighbors) <= 3
    for profile in neighbors:
        assert profile.chord_progression or profile.sections

    # Ambient seed should still land on progression-bearing recipes (Eno has both).
    ambient = find_progression_bearing_neighbors("ambient drone pad", limit=2)
    assert ambient
    assert all(p.chord_progression or p.sections for p in ambient)


def test_to_options_emits_extend_factor_when_set():
    profile = profile_from_dict(
        {
            "name": "Extend Sketch",
            "styles": ["drone"],
            "generation_type": "drone",
            "chord_progression": ["C3", "G2", "F3", "D3"],
            "drone_held": False,
            "extend_factor": 3,
            "development": {
                "enabled": True,
                "seed_bars": 2,
                "mutate_every_n": 2,
                "mutate_ops": ["add_attack"],
            },
        },
        source="cursor_sdk",
    )
    opts = profile.to_options()
    assert opts["extend_factor"] == 3
    assert opts["drone_held"] is False
    assert opts["chord_progression"] == ["C3", "G2", "F3", "D3"]
