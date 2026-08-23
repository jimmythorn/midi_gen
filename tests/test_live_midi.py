"""Tests for live MIDI / IAC playback helpers."""

from __future__ import annotations

import sys
import types
import time
from pathlib import Path

import mido
import pytest

_ROOT = Path(__file__).resolve().parents[1]
if "midi_gen" not in sys.modules:
    _pkg = types.ModuleType("midi_gen")
    _pkg.__path__ = [str(_ROOT)]  # type: ignore[attr-defined]
    _pkg.__file__ = str(_ROOT / "__init__.py")
    sys.modules["midi_gen"] = _pkg

from midi_gen.live_midi import (
    LiveMidiPlayer,
    _midi_file_to_schedule,
    preferred_iac_port,
    rtmidi_available,
)


def _write_tiny_midi(path: Path) -> None:
    mid = mido.MidiFile()
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120)))
    track.append(mido.Message("note_on", note=60, velocity=90, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, time=240))
    track.append(mido.Message("note_on", note=64, velocity=80, time=0))
    track.append(mido.Message("note_off", note=64, velocity=0, time=240))
    mid.save(path)


def test_preferred_iac_port_prefers_iac_name():
    assert preferred_iac_port(["USB Midi", "IAC Driver Bus 1", "Other"]) == "IAC Driver Bus 1"
    assert preferred_iac_port(["Foo", "Bar"]) == "Foo"
    assert preferred_iac_port([]) is None


def test_midi_file_schedule_orders_events(tmp_path):
    path = tmp_path / "tiny.mid"
    _write_tiny_midi(path)
    schedule, duration = _midi_file_to_schedule(str(path))
    assert len(schedule) >= 4
    times = [t for t, _ in schedule]
    assert times == sorted(times)
    assert duration >= times[-1]
    assert all(msg.time == 0 for _, msg in schedule)


def test_player_status_reports_backend():
    player = LiveMidiPlayer()
    status = player.status()
    assert status.backend == ("mido+rtmidi" if rtmidi_available() else None)
    assert isinstance(status.ports, list)
    assert status.playing is False


def test_play_file_missing_raises(tmp_path):
    player = LiveMidiPlayer()
    with pytest.raises(FileNotFoundError):
        player.play_file(str(tmp_path / "nope.mid"), port_name="missing")


def test_play_and_stop_with_virtual_port(tmp_path):
    """
    If the environment has no MIDI outs, skip.
    On Mac with IAC (or any virtual port), smoke-test start/stop.
    """
    player = LiveMidiPlayer()
    status = player.status()
    if not status.available:
        pytest.skip(status.error or "no MIDI ports")

    path = tmp_path / "tiny.mid"
    _write_tiny_midi(path)
    port = preferred_iac_port(status.ports) or status.ports[0]
    player.play_file(str(path), port)
    assert player.playing
    time.sleep(0.05)
    player.stop(wait=True)
    assert not player.playing
