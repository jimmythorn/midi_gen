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
    try:
        file_len = float(mid.length)
        if file_len > duration:
            duration = file_len
    except Exception:
        pass
    return schedule, duration


def messages_with_abs_ticks(
    messages: Iterable[mido.Message],
) -> Tuple[List[Tuple[int, mido.Message]], int]:
    """Delta-timed stream → (absolute_tick, message) pairs. Meta omitted."""
    abs_tick = 0
    out: List[Tuple[int, mido.Message]] = []
    for msg in messages:
        delta = getattr(msg, "time", 0) or 0
        if delta:
            abs_tick += int(delta)
        if msg.type == "set_tempo" or msg.is_meta:
            continue
        out.append((abs_tick, msg.copy(time=0)))
    last = out[-1][0] if out else 0
    return out, last


def midi_file_tick_schedule(
    path: str,
) -> Tuple[List[Tuple[int, mido.Message]], int, int]:
    """Flatten a MIDI file to (tick, message) pairs, last tick, ticks_per_beat."""
    mid = mido.MidiFile(path)
    tpb = int(mid.ticks_per_beat or 480)
    schedule, last_tick = messages_with_abs_ticks(mido.merge_tracks(mid.tracks))
    return schedule, last_tick, tpb


def tick_to_seconds(tick: float, bpm: float, ticks_per_beat: int) -> float:
    """Wall-clock seconds for an absolute tick at a constant BPM."""
    tpb = max(1, int(ticks_per_beat or 480))
    safe_bpm = max(1.0, float(bpm or 120.0))
    return float(tick) * 60.0 / safe_bpm / tpb


def seconds_schedule_at_bpm(
    tick_schedule: List[Tuple[int, mido.Message]],
    bpm: float,
    ticks_per_beat: int,
) -> List[Tuple[float, mido.Message]]:
    """Retimed copy so live play follows the requested BPM, not file tempo."""
    return [
        (tick_to_seconds(tick, bpm, ticks_per_beat), msg)
        for tick, msg in tick_schedule
    ]


def spp_to_ticks(pos: int, ticks_per_beat: int) -> int:
    """Song Position Pointer is 16th-notes from start. 4 sixteenths per beat."""
    tpb = max(1, int(ticks_per_beat or 480))
    return int(pos) * (tpb // 4)


def due_index(schedule: List[Tuple[int, mido.Message]], start_i: int, tick: float) -> int:
    """First index in schedule whose tick is > ``tick`` (messages at i..end-1 are due)."""
    i = start_i
    n = len(schedule)
    while i < n and schedule[i][0] <= tick + 1e-9:
        i += 1
    return i


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
