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
from midi_gen.cursor_style_lookup import lookup_musician_style, generate_midi_for_style
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
        },
        source="cursor_sdk",
    )
    assert profile.source == "cursor_sdk"
    assert profile.arp_steps == 8
    assert profile.bpm == 140
