"""Product-locked UI slice: section chips + Extend + section drip."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
if "midi_gen" not in sys.modules:
    _pkg = types.ModuleType("midi_gen")
    _pkg.__path__ = [str(_ROOT)]  # type: ignore[attr-defined]
    _pkg.__file__ = str(_ROOT / "__init__.py")
    sys.modules["midi_gen"] = _pkg

from midi_gen.arpeggio_generation import apply_extend_factor
from midi_gen.cursor_style_lookup import (
    LOOKUP_STICKY_OVERRIDE_KEYS,
    generate_midi_for_style,
)
from midi_gen.musician_styles import get_profile_by_id, resolve_section_recipe
from midi_gen.style_prompting import (
    EXTEND_CHIP_FACTORS,
    SECTION_CHIP_LABELS,
    SECTION_CHIP_ROLES,
    clamp_extend_factor,
    format_recipe_one_liner,
    preview_recipe,
    toggle_extend_factor,
    toggle_section_chip,
)


def test_section_chip_toggle_default_off_and_mutual_exclusive():
    assert toggle_section_chip(None, "verse") == "verse"
    assert toggle_section_chip("verse", "verse") is None
    assert toggle_section_chip("verse", "bridge") == "bridge"
    assert toggle_section_chip(None, "chorus") == "chorus"
    assert toggle_section_chip("chorus", "not-a-section") == "chorus"
    assert toggle_section_chip(None, "intro") == "intro"
    assert toggle_section_chip("intro", "outro") == "outro"
    assert toggle_section_chip("outro", "outro") is None
    assert toggle_section_chip(None, "pre-chorus") == "pre-chorus"
    assert toggle_section_chip("pre-chorus", "pre-chorus") is None
    assert set(SECTION_CHIP_ROLES) == {
        "verse",
        "chorus",
        "bridge",
        "intro",
        "outro",
        "pre-chorus",
    }
    assert [role for role, _label in SECTION_CHIP_LABELS] == list(SECTION_CHIP_ROLES)


def test_extend_chip_toggle_sets_factor_2_and_4():
    assert clamp_extend_factor(None) == 1
    assert toggle_extend_factor(1, 2) == 2
    assert toggle_extend_factor(2, 2) == 1
    assert toggle_extend_factor(1, 4) == 4
    assert toggle_extend_factor(4, 2) == 2
    assert tuple(EXTEND_CHIP_FACTORS) == (2, 4)
    stretched = apply_extend_factor({"bars": 8, "extend_factor": 2})
    assert stretched["bars"] == 16
    assert stretched["extend_factor"] == 2
    stretched4 = apply_extend_factor({"bars": 8}, factor=4)
    assert stretched4["bars"] == 32
    assert stretched4["extend_factor"] == 4


def test_drip_names_section_when_set_else_unchanged():
    glass = get_profile_by_id("glass_minimal")
    baseline = format_recipe_one_liner(glass)
    assert "bridge" not in baseline
    assert "held progression" not in baseline
    assert "Philip Glass" in baseline
    assert "arp" in baseline or "drone" in baseline

    bridge = resolve_section_recipe(glass, "bridge")
    drip = format_recipe_one_liner(bridge, section_role="bridge")
    assert drip == "Philip Glass · bridge · held progression"

    off = format_recipe_one_liner(glass, section_role=None)
    assert off == baseline


def test_preview_recipe_section_chip_resolves_role():
    plain = preview_recipe(catalog_name="Philip Glass")
    assert plain.profile.section_role is None
    assert "bridge" not in plain.one_liner

    bridged = preview_recipe(catalog_name="Philip Glass", section_role="bridge")
    assert bridged.profile.section_role == "bridge"
    assert bridged.profile.chord_progression == resolve_section_recipe(
        get_profile_by_id("glass_minimal"), "bridge"
    ).chord_progression
    assert "bridge" in bridged.one_liner
    assert "held progression" in bridged.one_liner


def test_preview_recipe_intro_outro_prechorus_resolve():
    glass = get_profile_by_id("glass_minimal")
    for role in ("intro", "outro", "pre-chorus"):
        previewed = preview_recipe(catalog_name="Philip Glass", section_role=role)
        assert previewed.profile.section_role == role
        assert previewed.profile.chord_progression == resolve_section_recipe(
            glass, role
        ).chord_progression
        assert role in previewed.one_liner
        # Distinct from chorus wallpaper.
        assert previewed.profile.chord_progression != resolve_section_recipe(
            glass, "chorus"
        ).chord_progression


def test_generate_overrides_wire_section_role_and_extend_factor(tmp_path):
    captured = {}

    def fake_create_arp(options):
        # Mirror Engine: stretch inside create_arp via apply_extend_factor.
        stretched = apply_extend_factor(dict(options))
        captured["options"] = stretched
        out = tmp_path / "sketch.mid"
        out.write_bytes(b"MThd")
        return str(out)

    with mock.patch(
        "midi_gen.arpeggio_generation.create_arp", side_effect=fake_create_arp
    ):
        path, result, options = generate_midi_for_style(
            "Philip Glass",
            use_cursor_sdk=False,
            overrides={"bars": 8, "section_role": "bridge", "extend_factor": 2},
            section_role="bridge",
        )
    assert path.endswith("sketch.mid")
    assert result.profile.id == "glass_minimal"
    assert options.get("section_role") == "bridge"
    assert options.get("extend_factor") == 2
    assert options.get("bars") == 8  # stretch happens inside create_arp
    assert captured["options"].get("extend_factor") == 2
    assert captured["options"]["bars"] == 16
    assert captured["options"]["chord_progression"] == resolve_section_recipe(
        get_profile_by_id("glass_minimal"), "bridge"
    ).chord_progression


def test_default_off_chips_leave_generate_behavior_as_today(tmp_path):
    captured = {}

    def fake_create_arp(options):
        captured["options"] = dict(options)
        out = tmp_path / "full.mid"
        out.write_bytes(b"MThd")
        return str(out)

    with mock.patch(
        "midi_gen.arpeggio_generation.create_arp", side_effect=fake_create_arp
    ):
        _path, _result, options = generate_midi_for_style(
            "Philip Glass",
            use_cursor_sdk=False,
            overrides={"bars": 8},
            section_role=None,
        )
    glass = get_profile_by_id("glass_minimal")
    assert options.get("section_role") in (None, glass.section_role)
    assert options.get("extend_factor") in (None, 1)
    assert captured["options"]["bars"] == 8
    assert captured["options"]["chord_progression"] == glass.chord_progression


def test_sticky_override_keys_include_section_and_extend():
    assert "section_role" in LOOKUP_STICKY_OVERRIDE_KEYS
    assert "extend_factor" in LOOKUP_STICKY_OVERRIDE_KEYS
    assert "bars" in LOOKUP_STICKY_OVERRIDE_KEYS
