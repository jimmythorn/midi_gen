"""Tests for note-event I/O and last_run refresh."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import mido

_ROOT = Path(__file__).resolve().parents[1]
if "midi_gen" not in sys.modules:
    _pkg = types.ModuleType("midi_gen")
    _pkg.__path__ = [str(_ROOT)]  # type: ignore[attr-defined]
    _pkg.__file__ = str(_ROOT / "__init__.py")
    sys.modules["midi_gen"] = _pkg

from midi_gen.note_edit import (
    list_note_events,
    refresh_last_run_after_note_write,
    write_note_events,
)
from midi_gen.preview import summarize_midi_file


def _fields(notes):
    return [
        {
            "start_tick": n["start_tick"],
            "duration_tick": n["duration_tick"],
            "note": n["note"],
            "velocity": n["velocity"],
            "channel": n["channel"],
        }
        for n in notes
    ]


def test_list_note_events_overlap_durations(tmp_path):
    path = tmp_path / "overlap.mid"
    mid = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120)))
    track.append(mido.Message("note_on", note=60, velocity=80, time=0))
    track.append(mido.Message("note_on", note=64, velocity=90, time=240))
    track.append(mido.Message("note_off", note=60, velocity=80, time=240))
    track.append(mido.Message("note_off", note=64, velocity=90, time=240))
    mid.save(path)

    notes = list_note_events(str(path))
    assert [n["duration_tick"] for n in notes] == [480, 480]
    assert [n["id"] for n in notes] == [0, 1]
    assert notes[0]["note"] == 60
    assert notes[1]["note"] == 64
    assert notes[0]["start_tick"] == 0
    assert notes[1]["start_tick"] == 240


def test_write_note_events_roundtrip_after_mutate(tmp_path):
    path = tmp_path / "round.mid"
    write_note_events(
        str(path),
        [
            {
                "id": 0,
                "start_tick": 0,
                "duration_tick": 480,
                "note": 60,
                "velocity": 80,
                "channel": 0,
            },
            {
                "id": 1,
                "start_tick": 240,
                "duration_tick": 480,
                "note": 64,
                "velocity": 90,
                "channel": 0,
            },
        ],
        bpm=120,
        ticks_per_beat=480,
    )
    notes = list_note_events(str(path))
    notes[0]["note"] = 72
    notes[0]["start_tick"] = 120
    write_note_events(str(path), notes, bpm=100, ticks_per_beat=480)
    again = list_note_events(str(path))
    assert [n["id"] for n in again] == [0, 1]
    assert _fields(again) == _fields(notes)


def test_write_empty_notes_is_valid_empty_file(tmp_path):
    path = tmp_path / "empty.mid"
    write_note_events(str(path), [], bpm=120, ticks_per_beat=480)
    assert path.is_file()
    mid = mido.MidiFile(str(path))
    ons = [
        msg
        for track in mid.tracks
        for msg in track
        if msg.type == "note_on" and msg.velocity > 0
    ]
    assert ons == []
    assert list_note_events(str(path)) == []


def test_write_note_events_clamps(tmp_path):
    path = tmp_path / "clamp.mid"
    write_note_events(
        str(path),
        [
            {
                "start_tick": 0,
                "duration_tick": 0,
                "note": 200,
                "velocity": 0,
                "channel": 99,
            }
        ],
        bpm=120,
        ticks_per_beat=480,
    )
    notes = list_note_events(str(path))
    assert len(notes) == 1
    assert notes[0]["note"] == 127
    assert notes[0]["velocity"] == 1
    assert notes[0]["duration_tick"] == 1
    assert notes[0]["channel"] == 15


def test_refresh_last_run_after_note_write_changes_pitch(tmp_path):
    path = tmp_path / "refresh.mid"
    write_note_events(
        str(path),
        [
            {
                "id": 0,
                "start_tick": 0,
                "duration_tick": 480,
                "note": 60,
                "velocity": 80,
                "channel": 0,
            }
        ],
        bpm=120,
        ticks_per_beat=480,
    )
    last_run = {
        "path": str(path),
        "options": {"bpm": 120},
        "summary": {"ticks_per_beat": 480},
    }
    notes = list_note_events(str(path))
    notes[0]["note"] = 72
    refresh_last_run_after_note_write(last_run, notes, dirty=True)
    listed = list_note_events(str(path))
    assert listed[0]["note"] == 72
    assert summarize_midi_file(str(path))["note_preview"][0]["note"] == 72
    assert last_run["notes_dirty"] is True
    assert last_run["edit_notes"][0]["note"] == 72
    assert last_run["wav_bytes"]


def test_reset_restores_generated_notes(tmp_path):
    path = tmp_path / "reset.mid"
    generated = [
        {
            "id": 0,
            "start_tick": 0,
            "duration_tick": 480,
            "note": 60,
            "velocity": 80,
            "channel": 0,
        }
    ]
    write_note_events(str(path), generated, bpm=120, ticks_per_beat=480)
    last_run = {
        "path": str(path),
        "options": {"bpm": 120},
        "summary": {"ticks_per_beat": 480},
        "generated_notes": [dict(n) for n in generated],
    }
    edited = [dict(generated[0])]
    edited[0]["note"] = 72
    refresh_last_run_after_note_write(last_run, edited, dirty=True)
    assert list_note_events(str(path))[0]["note"] == 72
    refresh_last_run_after_note_write(
        last_run,
        [dict(n) for n in last_run["generated_notes"]],
        dirty=False,
    )
    assert last_run["notes_dirty"] is False
    assert _fields(list_note_events(str(path))) == _fields(last_run["generated_notes"])
