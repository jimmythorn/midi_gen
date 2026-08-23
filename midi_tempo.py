"""
Shared MIDI tempo-map timing.

Absolute tick → seconds must accumulate per-delta with the tempo in force for
that span. Using tick2second(abs_tick, tempo_now) is wrong after tempo changes.
"""

from __future__ import annotations

from typing import Iterable, List, Tuple

import mido


def messages_with_abs_seconds(
    messages: Iterable[mido.Message],
    ticks_per_beat: int,
    initial_tempo: int = 500000,
) -> List[Tuple[float, mido.Message]]:
    """
    Convert a delta-timed message stream into (absolute_seconds, message) pairs.

    Tempo meta messages update the map and are omitted from the result.
    Other meta messages are omitted. Channel/sysex messages are included with
    time=0 copies suitable for live send or analysis.
    """
    tempo = initial_tempo
    abs_tick = 0
    abs_seconds = 0.0
    out: List[Tuple[float, mido.Message]] = []

    tpb = ticks_per_beat or 480
    for msg in messages:
        delta = getattr(msg, "time", 0) or 0
        if delta:
            abs_seconds += mido.tick2second(delta, tpb, tempo)
            abs_tick += delta
        if msg.type == "set_tempo":
            tempo = msg.tempo
            continue
        if msg.is_meta:
            continue
        out.append((abs_seconds, msg.copy(time=0)))
    return out


def midi_file_schedule(path: str) -> Tuple[List[Tuple[float, mido.Message]], float]:
    """Flatten a MIDI file to an absolute-second schedule and duration."""
    mid = mido.MidiFile(path)
    schedule = messages_with_abs_seconds(
        mido.merge_tracks(mid.tracks),
        mid.ticks_per_beat or 480,
    )
    duration = schedule[-1][0] if schedule else 0.0
    return schedule, duration


def collect_note_spans(
    path: str,
) -> Tuple[List[Tuple[float, float, int, int]], float, int]:
    """
    Return (spans, duration_sec, bpm_at_end).

    Each span: (start_sec, end_sec, pitch, velocity).
    """
    mid = mido.MidiFile(path)
    tpb = mid.ticks_per_beat or 480
    tempo = 500000
    abs_tick = 0
    abs_seconds = 0.0
    active: dict = {}
    notes: List[Tuple[float, float, int, int]] = []

    for msg in mido.merge_tracks(mid.tracks):
        delta = getattr(msg, "time", 0) or 0
        if delta:
            abs_seconds += mido.tick2second(delta, tpb, tempo)
            abs_tick += delta
        if msg.type == "set_tempo":
            tempo = msg.tempo
            continue
        if msg.type == "note_on" and msg.velocity > 0:
            active[msg.note] = (abs_seconds, msg.velocity)
        elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            if msg.note in active:
                start, vel = active.pop(msg.note)
                end = abs_seconds if abs_seconds > start else start + 0.05
                notes.append((start, end, msg.note, vel))

    duration = max((n[1] for n in notes), default=1.0) + 0.15
    bpm = int(round(mido.tempo2bpm(tempo)))
    notes.sort(key=lambda n: n[0])
    return notes, duration, bpm
