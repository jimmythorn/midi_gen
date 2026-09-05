"""
Lightweight audio preview from a MIDI file.

Renders a piano-like additive voice to WAV so the UI can play results
without a DAW or soundfont install. Honors pitch-bend events so tape
wow/flutter is audible in the quick preview.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import mido

from .midi_types import MIDI_PITCH_BEND_CENTER, SEMITONES_PER_BEND
from .notes import note_to_name

# (start_sec, end_sec, pitch, velocity, channel)
NoteEvent = Tuple[float, float, int, int, int]
# (time_sec, bend_value)  bend in mido range −8192…8191
BendPoint = Tuple[float, int]


def _midi_to_hz(note: int) -> float:
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def _bend_to_cents(bend: int, semitones: float = float(SEMITONES_PER_BEND)) -> float:
    """Map MIDI pitch-bend to cents relative to center (0)."""
    return (bend / 8192.0) * semitones * 100.0


def _collect_timeline(
    path: str,
) -> Tuple[List[NoteEvent], Dict[int, List[BendPoint]], float, int]:
    """
    Returns (notes, bends_by_channel, duration_sec, bpm_guess).
    Each note: (start_sec, end_sec, pitch, velocity, channel)
    """
    mid = mido.MidiFile(path)
    ticks_per_beat = mid.ticks_per_beat or 480
    tempo = 500000  # default 120 bpm
    notes: List[NoteEvent] = []
    bends_by_channel: Dict[int, List[BendPoint]] = {}

    # Flatten first tracks with tempo awareness
    for track in mid.tracks:
        abs_tick = 0
        active: Dict[Tuple[int, int], Tuple[int, int]] = {}  # (ch, note) -> (tick, vel)
        for msg in track:
            abs_tick += msg.time
            if msg.type == "set_tempo":
                tempo = msg.tempo
            elif msg.type == "pitchwheel":
                ch = int(getattr(msg, "channel", 0))
                t = mido.tick2second(abs_tick, ticks_per_beat, tempo)
                bends_by_channel.setdefault(ch, []).append((t, int(msg.pitch)))
            elif msg.type == "note_on" and msg.velocity > 0:
                ch = int(msg.channel)
                active[(ch, msg.note)] = (abs_tick, msg.velocity)
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                ch = int(getattr(msg, "channel", 0))
                key = (ch, msg.note)
                if key in active:
                    start_tick, vel = active.pop(key)
                    start = mido.tick2second(start_tick, ticks_per_beat, tempo)
                    end = mido.tick2second(abs_tick, ticks_per_beat, tempo)
                    if end <= start:
                        end = start + 0.05
                    notes.append((start, end, msg.note, vel, ch))

    # Ensure each channel has a center bend at t=0 for lookup
    for ch, points in list(bends_by_channel.items()):
        points.sort(key=lambda p: p[0])
        if not points or points[0][0] > 0.0:
            bends_by_channel[ch] = [(0.0, MIDI_PITCH_BEND_CENTER)] + points

    duration = max((n[1] for n in notes), default=1.0)
    # Also cover trailing bend automation after last note-off
    for points in bends_by_channel.values():
        if points:
            duration = max(duration, points[-1][0])
    bpm = int(round(mido.tempo2bpm(tempo)))
    notes.sort(key=lambda n: n[0])
    return notes, bends_by_channel, duration + 0.15, bpm


def _bend_cents_series(
    start: float,
    n_samples: int,
    sample_rate: int,
    bend_points: List[BendPoint],
) -> np.ndarray:
    """Piecewise-constant bend → cents for each sample of a note."""
    if n_samples <= 0:
        return np.zeros(0, dtype=np.float32)
    if not bend_points:
        return np.zeros(n_samples, dtype=np.float32)

    times = np.array([p[0] for p in bend_points], dtype=np.float64)
    values = np.array([p[1] for p in bend_points], dtype=np.float64)
    sample_times = start + (np.arange(n_samples, dtype=np.float64) / sample_rate)
    # Rightmost bend event at or before each sample (step hold)
    idx = np.searchsorted(times, sample_times, side="right") - 1
    idx = np.clip(idx, 0, len(values) - 1)
    bends = values[idx]
    return (_bend_to_cents(bends)).astype(np.float32)


def _collect_notes(path: str) -> Tuple[List[Tuple[float, float, int, int]], float, int]:
    """Back-compat helper used by describe_preview / older callers."""
    notes, _bends, duration, bpm = _collect_timeline(path)
    simple = [(s, e, p, v) for s, e, p, v, _ch in notes]
    return simple, duration, bpm


def _piano_voice(
    phase: np.ndarray,
    *,
    sample_rate: int,
    velocity: int,
    pitch: int,
) -> np.ndarray:
    """Hammer click + decaying partials. No soundfont."""
    n = int(phase.shape[0])
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    t = np.arange(n, dtype=np.float64) / float(sample_rate)
    vel = max(0.05, min(1.0, velocity / 127.0))
    amps = np.array([1.00, 0.62, 0.38, 0.22, 0.14, 0.08, 0.04], dtype=np.float64)
    amps[1:] *= 0.35 + 0.65 * vel
    decays = np.array([1.8, 3.2, 5.0, 7.5, 10.0, 13.0, 16.0], dtype=np.float64)
    decays *= 1.0 + max(0, pitch - 60) / 80.0
    tone = np.zeros(n, dtype=np.float64)
    for k, (amp, dec) in enumerate(zip(amps, decays), start=1):
        tone += amp * np.sin(k * phase) * np.exp(-dec * t)
    rng = np.random.RandomState((int(pitch) * 31 + int(velocity)) & 0xFFFF)
    hammer_n = max(1, int(0.006 * sample_rate))
    take = min(hammer_n, n)
    hammer = np.zeros(n, dtype=np.float64)
    hammer[:take] = rng.randn(take) * (0.18 * vel)
    hammer[:take] *= np.linspace(1.0, 0.0, take)
    return (tone + hammer).astype(np.float32)


def render_midi_to_wav_bytes(
    path: str,
    *,
    sample_rate: int = 22050,
    gain: float = 0.20,
) -> bytes:
    """Synthesize a mono 16-bit piano WAV preview (pitch-bend aware)."""
    notes, bends_by_channel, duration, _bpm = _collect_timeline(path)
    n_samples = max(1, int(duration * sample_rate))
    audio = np.zeros(n_samples, dtype=np.float32)

    for start, end, pitch, velocity, channel in notes:
        i0 = int(start * sample_rate)
        i1 = min(n_samples, int(end * sample_rate))
        if i1 <= i0:
            continue
        n = i1 - i0
        bend_pts = bends_by_channel.get(channel) or bends_by_channel.get(0, [])
        cents = _bend_cents_series(start, n, sample_rate, bend_pts)
        freq = _midi_to_hz(pitch) * (2.0 ** (cents / 1200.0))
        phase = np.cumsum(2.0 * np.pi * freq / sample_rate, dtype=np.float64)
        tone = _piano_voice(
            phase, sample_rate=sample_rate, velocity=velocity, pitch=pitch
        )
        attack = max(1, int(0.004 * sample_rate))
        release = max(1, int(0.22 * sample_rate))
        env = np.ones(n, dtype=np.float32)
        a = min(attack, n)
        r = min(release, n)
        if a > 0:
            env[:a] = np.linspace(0.0, 1.0, a, endpoint=False)
        if r > 0:
            env[-r:] *= np.linspace(1.0, 0.0, r)
        amp = gain * (velocity / 127.0)
        audio[i0:i1] += (tone * env * amp).astype(np.float32)

    # Soft clip / normalize
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 0.95:
        audio *= 0.95 / peak

    pcm = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def write_wav_preview(midi_path: str, wav_path: str | None = None) -> str:
    """Write a WAV next to the MIDI (or to wav_path) and return the path."""
    midi = Path(midi_path)
    out = Path(wav_path) if wav_path else midi.with_suffix(".wav")
    out.write_bytes(render_midi_to_wav_bytes(str(midi)))
    return str(out)


def midi_file_to_base64(path: str) -> str:
    import base64

    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def describe_preview(path: str) -> str:
    notes, duration, bpm = _collect_notes(path)
    _notes_full, bends_by_channel, _, _ = _collect_timeline(path)
    bend_count = sum(max(0, len(pts) - 1) for pts in bends_by_channel.values())
    if not notes:
        return "No notes found to preview."
    names = [note_to_name(n[2]) for n in notes[:12]]
    more = "…" if len(notes) > 12 else ""
    bend_bit = f" · {bend_count} bends" if bend_count else ""
    return (
        f"Preview piano · {len(notes)} notes · {duration:.1f}s · ~{bpm} BPM"
        f"{bend_bit} · {' '.join(names)}{more}"
    )
