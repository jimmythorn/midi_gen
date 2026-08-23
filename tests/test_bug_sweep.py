"""Regression tests from the bug sweep."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import mido
import pytest

_ROOT = Path(__file__).resolve().parents[1]
if "midi_gen" not in sys.modules:
    _pkg = types.ModuleType("midi_gen")
    _pkg.__path__ = [str(_ROOT)]  # type: ignore[attr-defined]
    _pkg.__file__ = str(_ROOT / "__init__.py")
    sys.modules["midi_gen"] = _pkg

from midi_gen.arpeggio import create_arpeggio
from midi_gen.arpeggio_generation import create_arp
from midi_gen.cursor_style_lookup import generate_midi_for_style
from midi_gen.drone_generation import generate_drone_events
from midi_gen.midi_ordering import sort_midi_instructions
from midi_gen.midi_tempo import midi_file_schedule
from midi_gen.musician_styles import profile_from_dict
from midi_gen.notes import note_str_to_midi, note_to_name
from midi_gen.preview import summarize_midi_file


def _assert_non_negative_deltas(path: str) -> None:
    mid = mido.MidiFile(path)
    for track in mid.tracks:
        for msg in track:
            assert msg.time >= 0, msg


def test_eno_clean_drone_writes_without_crash():
    path, result, _options = generate_midi_for_style(
        "Brian Eno",
        use_cursor_sdk=False,
        overrides={"bars": 4, "effects_preset": "clean", "debug": False},
    )
    assert result.profile.generation_type == "drone"
    assert Path(path).exists()
    _assert_non_negative_deltas(path)
    summary = summarize_midi_file(path)
    assert summary["note_on_count"] > 0


def test_sort_midi_instructions_orders_overlapping_voices():
    events = [
        ("note_on", 100, 60, 80, 0),
        ("note_off", 50, 62, 0, 0),
        ("note_on", 50, 64, 80, 0),
        ("control_change", 0, 101, 0, 0),
    ]
    ordered = sort_midi_instructions(events)
    ticks = [e[1] for e in ordered]
    assert ticks == sorted(ticks)
    # at tick 50, note_off before note_on
    at_50 = [e for e in ordered if e[1] == 50]
    assert at_50[0][0] == "note_off"
    assert at_50[1][0] == "note_on"


def test_tempo_map_schedule_accumulates_deltas(tmp_path):
    path = tmp_path / "tempo.mid"
    mid = mido.MidiFile()
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0))
    track.append(mido.Message("note_on", note=60, velocity=90, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, time=480))  # 0.5s
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(60), time=0))
    track.append(mido.Message("note_on", note=62, velocity=90, time=0))
    track.append(mido.Message("note_off", note=62, velocity=0, time=480))  # +1.0s → 1.5
    mid.save(path)

    schedule, duration = midi_file_schedule(str(path))
    times = [round(t, 3) for t, _ in schedule]
    assert times[0] == 0.0
    assert times[1] == 0.5
    assert times[2] == 0.5
    assert times[3] == 1.5
    assert round(duration, 3) == 1.5


def test_drone_doubling_without_walkdowns():
    options = {
        "bpm": 90,
        "bars": 2,
        "mode": "lydian",
        "min_octave": 3,
        "max_octave": 5,
        "drone_base_velocity": 70,
        "drone_variation_interval_bars": 2,
        "drone_min_notes_held": 2,
        "drone_octave_doubling_chance": 1.0,
        "drone_allow_octave_shifts": False,
        "drone_enable_walkdowns": False,
        "debug": False,
    }
    roots = [note_str_to_midi("C3")]
    events = generate_drone_events(options, roots)
    pitches = [e[0] for e in events]
    # With forced doubling, expect at least one pitch an octave away from a base tone
    assert any(abs(a - b) == 12 for a in pitches for b in pitches)


def test_arpeggio_respects_max_octave():
    notes = create_arpeggio(
        root=note_str_to_midi("C4"),
        mode="major",
        length=16,
        min_octave=4,
        max_octave=4,
        arp_mode="up",
        range_octaves=5,  # would sprawl without max clamp
        evolution_rate=0.0,
        repetition_factor=10,
        use_chord_tones=True,
    )
    assert notes
    assert max(notes) <= note_str_to_midi("B4")
    assert min(notes) >= note_str_to_midi("C4")


def test_create_arp_rejects_bad_generation_type():
    with pytest.raises(ValueError, match="generation_type"):
        create_arp({"generation_type": "banana", "bars": 1, "root_notes": ["C4"]})


def test_create_arp_rejects_zero_arp_steps():
    with pytest.raises(ValueError, match="arp_steps"):
        create_arp({
            "generation_type": "arpeggio",
            "bars": 1,
            "root_notes": ["C4"],
            "arp_steps": 0,
            "effects_config": [],
        })


def test_profile_from_dict_clamps_invalid_mode_and_roots():
    profile = profile_from_dict({
        "name": "Weird",
        "mode": "blues",
        "root_notes": ["C4", "not-a-note", "G4"],
        "generation_type": "arpeggio",
    })
    assert profile.mode == "minor"
    assert profile.root_notes == ["C4", "G4"]
