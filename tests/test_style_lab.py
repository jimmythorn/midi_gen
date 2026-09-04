"""Tests for musician-style lookup, effects presets, and MIDI generation."""

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

from midi_gen.arpeggio import create_arpeggio
from midi_gen.cursor_style_lookup import (
    lookup_musician_style,
    generate_midi_for_style,
    load_dotenv_if_present,
)
from midi_gen.effects_presets import build_effects_config, explain_effects_config, get_preset
from midi_gen.musician_styles import find_best_profile, list_styles, profile_from_dict
from midi_gen.notes import note_str_to_midi, note_to_name
from midi_gen.preview import summarize_midi_file


def test_note_flats_and_sharps():
    assert note_str_to_midi("C4") == 60
    assert note_str_to_midi("Db4") == note_str_to_midi("C#4")
    assert note_str_to_midi("Bb3") == note_str_to_midi("A#3")
    assert note_to_name(60) == "C4"


def test_catalog_style_match():
    profile = find_best_profile("ambient drone")
    assert profile is not None
    assert "ambient" in profile.styles or profile.generation_type == "drone"

    glass = find_best_profile("Philip Glass")
    assert glass is not None
    assert glass.id == "glass_minimal"
    assert list_styles()


def test_lookup_offline_no_sdk():
    result = lookup_musician_style("Steve Reich phase", use_cursor_sdk=False)
    assert result.matched_locally
    assert result.profile.id == "reich_phase"
    assert not result.used_cursor_sdk
    options = result.to_options()
    assert options["generation_type"] == "arpeggio"
    assert isinstance(options["effects_config"], list)


def test_feel_does_not_replace_pinned_artist():
    result = lookup_musician_style(
        "Philip Glass — ambient drone",
        use_cursor_sdk=False,
        identity_name="Philip Glass",
        vibe_text="ambient drone",
    )
    assert result.profile.id == "glass_minimal"
    feel_only = lookup_musician_style("ambient drone", use_cursor_sdk=False)
    assert feel_only.profile.id == "eno_ambient"


def test_load_dotenv_if_present_fills_missing_only(monkeypatch, tmp_path):
    import os

    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text("CURSOR_API_KEY=crsr_test_only\n", encoding="utf-8")
    load_dotenv_if_present(env_path)
    assert os.environ["CURSOR_API_KEY"] == "crsr_test_only"
    monkeypatch.setenv("CURSOR_API_KEY", "keep_me")
    env_path.write_text("CURSOR_API_KEY=other\n", encoding="utf-8")
    load_dotenv_if_present(env_path)
    assert os.environ["CURSOR_API_KEY"] == "keep_me"


def test_effects_presets_plain_language():
    preset = get_preset("worn_tape")
    assert "hear" in preset["what_you_hear"].lower() or "Noticeable" in preset["what_you_hear"]
    config = build_effects_config("tape_and_human")
    names = {c["name"] for c in config}
    assert "tape_wobble" in names
    assert "humanize_velocity" in names
    lines = explain_effects_config(config)
    assert any("Tape" in line or "Human" in line for line in lines)


def test_arpeggio_respects_written_octave():
    from midi_gen.notes import note_str_to_midi, note_to_name
    notes = create_arpeggio(
        root=note_str_to_midi("A3"),
        mode="minor",
        length=8,
        min_octave=3,
        max_octave=5,
        arp_mode="up_down",
        range_octaves=1,
        evolution_rate=0.0,
        repetition_factor=9,
        use_chord_tones=True,
    )
    assert len(notes) == 8
    assert min(notes) >= note_str_to_midi("C3")
    assert max(notes) <= note_str_to_midi("B4")
    assert "A3" in [note_to_name(n) for n in notes] or "A4" in [note_to_name(n) for n in notes]


def test_generate_midi_for_style(tmp_path, monkeypatch):
    # Keep output under package generated/ but ensure it writes a real file
    path, result, options = generate_midi_for_style(
        "Bach sequence",
        use_cursor_sdk=False,
        overrides={"bars": 4, "effects_preset": "clean", "debug": False},
    )
    assert Path(path).exists()
    assert result.profile.id == "bach_sequence"
    summary = summarize_midi_file(path)
    assert summary["note_on_count"] > 0
    assert summary["unique_pitches"] >= 1


def test_effect_registry_maps_wow_flutter_knobs():
    from midi_gen.effects import EffectRegistry, TapeWobbleEffect
    effect = EffectRegistry.create_effect(
        {
            "name": "tape_wobble",
            "wow_rate_hz": 0.4,
            "wow_depth": 18,
            "flutter_rate_hz": 9.0,
            "flutter_depth": 4,
            "randomness": 0.3,
            "depth_units": "cents",
        }
    )
    assert isinstance(effect, TapeWobbleEffect)
    assert effect.config.wow_rate_hz == 0.4
    assert effect.config.wow_depth_cents == 18
    assert effect.config.flutter_rate_hz == 9.0
    assert effect.config.flutter_depth_cents == 4
    assert effect.config.pitch_bend_update_rate >= 30.0


def test_wav_preview_renders(tmp_path):
    from midi_gen.audio_preview import describe_preview, render_midi_to_wav_bytes
    from midi_gen.cursor_style_lookup import generate_midi_for_style

    path, _result, _options = generate_midi_for_style(
        "Bach sequence",
        use_cursor_sdk=False,
        overrides={"bars": 2, "effects_preset": "clean", "debug": False},
    )
    wav = render_midi_to_wav_bytes(path)
    assert wav[:4] == b"RIFF"
    assert len(wav) > 1000
    assert "notes" in describe_preview(path)


def test_sdk_research_prompt_asks_for_style_notes():
    from midi_gen.cursor_style_lookup import STYLE_PROFILE_JSON_SCHEMA

    assert "Research the query first" in STYLE_PROFILE_JSON_SCHEMA
    assert "style_notes" in STYLE_PROFILE_JSON_SCHEMA
    assert "likeness_summary" in STYLE_PROFILE_JSON_SCHEMA
    assert "why THIS sketch sounds like" in STYLE_PROFILE_JSON_SCHEMA
    assert "hints only" in STYLE_PROFILE_JSON_SCHEMA


def test_sdk_recipe_wins_over_widget_overrides(monkeypatch, tmp_path):
    """Researched params must reach MIDI options; bars/seed still apply."""
    from midi_gen.artist_gate import ArtistGateAccept
    from midi_gen.cursor_style_lookup import generate_midi_for_style
    from midi_gen.musician_styles import profile_from_dict

    researched = profile_from_dict(
        {
            "name": "Custom Research",
            "styles": ["ambient"],
            "generation_type": "drone",
            "mode": "lydian",
            "bpm": 64,
            "arp_steps": 4,
            "effects_preset": "subtle_tape",
            "style_notes": "Long tones, slow pulse, lydian color.",
        },
        source="cursor_sdk",
    )

    monkeypatch.setattr(
        "midi_gen.cursor_style_lookup.require_artist",
        lambda query, identity_name=None, **_kwargs: ArtistGateAccept(
            query=query,
            source="spotify",
            message="test accept",
        ),
    )
    monkeypatch.setattr(
        "midi_gen.cursor_style_lookup.cursor_sdk_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "midi_gen.cursor_style_lookup.lookup_with_cursor_sdk",
        lambda query, timeout_ms=120_000, **_kwargs: (researched, '{"bpm":64}'),
    )
    path, result, options = generate_midi_for_style(
        "zzzz-unknown-vibe-no-catalog-hit",
        use_cursor_sdk=True,
        overrides={
            "bpm": 180,
            "arp_steps": 16,
            "effects_preset": "clean",
            "bars": 4,
            "debug": False,
        },
        live_tweak=False,
    )
    assert result.used_cursor_sdk
    assert options["bpm"] == 64
    assert options["effects_preset"] == "subtle_tape"
    assert options["mode"] == "lydian"
    assert options["bars"] == 4
    assert researched.style_notes.startswith("Long tones")
    assert Path(path).exists()

    _, _, tweaked = generate_midi_for_style(
        "zzzz-unknown-vibe-no-catalog-hit",
        use_cursor_sdk=True,
        overrides={"bpm": 180, "effects_preset": "clean", "bars": 4, "debug": False},
        live_tweak=True,
    )
    assert tweaked["bpm"] == 180
    assert tweaked["effects_preset"] == "clean"


def test_profile_from_sdk_shaped_dict():
    profile = profile_from_dict(
        {
            "name": "Custom Jazz",
            "styles": ["jazz", "modal"],
            "generation_type": "arpeggio",
            "mode": "dorian",
            "bpm": 140,
            "arp_steps": 12,  # invalid -> clamped to 8
            "effects_preset": "human_feel",
            "style_notes": "Modal vamps, walking inner voices.",
            "likeness_summary": "Dorian vamps and walking inner voices, like a mid-tempo modal date.",
        },
        source="cursor_sdk",
    )
    assert profile.source == "cursor_sdk"
    assert profile.arp_steps == 8
    assert profile.bpm == 140
    assert "Modal vamps" in profile.style_notes
    assert "Dorian vamps" in profile.likeness_summary
