"""Note-level MIDI I/O that does not re-run EffectRegistry."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Tuple

import mido


def list_note_events(path: str) -> List[Dict[str, Any]]:
    """Pair note_on / note_off per track into timed note dicts."""
    mid = mido.MidiFile(path)
    raw: List[Dict[str, Any]] = []
    for track in mid.tracks:
        stacks: Dict[Tuple[int, int], List[Tuple[int, int]]] = defaultdict(list)
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                stacks[(msg.note, msg.channel)].append((abs_tick, msg.velocity))
            elif msg.type == "note_off" or (
                msg.type == "note_on" and msg.velocity == 0
            ):
                key = (msg.note, msg.channel)
                if not stacks[key]:
                    continue
                start, velocity = stacks[key].pop()
                raw.append(
                    {
                        "start_tick": int(start),
                        "duration_tick": max(1, int(abs_tick - start)),
                        "note": int(msg.note),
                        "velocity": int(velocity),
                        "channel": int(msg.channel),
                    }
                )
    raw.sort(key=lambda n: (n["start_tick"], n["note"], n["channel"]))
    for index, note in enumerate(raw):
        note["id"] = index
    return raw


def _clamp_note(value: Any) -> int:
    return max(0, min(127, int(value)))


def _clamp_velocity(value: Any) -> int:
    return max(1, min(127, int(value)))


def _clamp_channel(value: Any) -> int:
    if value is None:
        return 0
    return max(0, min(15, int(value)))


def write_note_events(
    path: str,
    notes: List[Dict[str, Any]],
    *,
    bpm: float,
    ticks_per_beat: int,
) -> None:
    """Write one-track MIDI from note dicts. No EffectRegistry."""
    mid = mido.MidiFile(ticks_per_beat=int(ticks_per_beat))
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(float(bpm))))

    events: List[Tuple[int, int, int, int, int]] = []
    for note in notes:
        pitch = _clamp_note(note.get("note", 0))
        velocity = _clamp_velocity(note.get("velocity", 64))
        channel = _clamp_channel(note.get("channel", 0))
        start = int(note.get("start_tick", 0) or 0)
        duration = max(1, int(note.get("duration_tick", 1) or 1))
        events.append((start, 0, pitch, velocity, channel))
        events.append((start + duration, 1, pitch, velocity, channel))
    events.sort(key=lambda item: (item[0], item[1], item[2], item[4]))

    last_tick = 0
    for tick, kind, pitch, velocity, channel in events:
        delta = max(0, tick - last_tick)
        if kind == 0:
            track.append(
                mido.Message(
                    "note_on",
                    note=pitch,
                    velocity=velocity,
                    channel=channel,
                    time=delta,
                )
            )
        else:
            track.append(
                mido.Message(
                    "note_off",
                    note=pitch,
                    velocity=velocity,
                    channel=channel,
                    time=delta,
                )
            )
        last_tick = tick
    mid.save(path)


def refresh_last_run_after_note_write(
    last_run: Dict[str, Any],
    notes: List[Dict[str, Any]],
    *,
    dirty: bool,
) -> None:
    """Write notes to last_run path and refresh preview fields."""
    from .audio_preview import render_midi_to_wav_bytes
    from .preview import summarize_midi_file

    options = last_run.get("options") or {}
    summary = last_run.get("summary") or {}
    bpm = int(options.get("bpm") or 120)
    ticks_per_beat = int(summary.get("ticks_per_beat") or 480)
    write_note_events(
        last_run["path"],
        notes,
        bpm=bpm,
        ticks_per_beat=ticks_per_beat,
    )
    last_run["edit_notes"] = list(notes)
    last_run["notes_dirty"] = dirty
    last_run["summary"] = summarize_midi_file(last_run["path"])
    last_run["wav_bytes"] = render_midi_to_wav_bytes(last_run["path"])
