"""
Lightweight audio preview from a MIDI file.

Renders a simple sine+noise instrument to WAV so the UI can play results
without a DAW or soundfont install.
"""

from __future__ import annotations

import base64
import io
import wave
from pathlib import Path
from typing import List, Tuple

import numpy as np

from .midi_tempo import collect_note_spans
from .notes import note_to_name


def _midi_to_hz(note: int) -> float:
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def _collect_notes(path: str) -> Tuple[List[Tuple[float, float, int, int]], float, int]:
    """Returns (notes, duration_sec, bpm_guess)."""
    return collect_note_spans(path)


def render_midi_to_wav_bytes(
    path: str,
    *,
    sample_rate: int = 22050,
    gain: float = 0.22,
) -> bytes:
    """Synthesize a mono 16-bit WAV preview of the MIDI file."""
    notes, duration, _bpm = _collect_notes(path)
    n_samples = max(1, int(duration * sample_rate))
    audio = np.zeros(n_samples, dtype=np.float32)

    for start, end, pitch, velocity in notes:
        i0 = int(start * sample_rate)
        i1 = min(n_samples, int(end * sample_rate))
        if i1 <= i0:
            continue
        t = np.arange(i1 - i0, dtype=np.float32) / sample_rate
        freq = _midi_to_hz(pitch)
        tone = np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(4 * np.pi * freq * t)
        attack = max(1, int(0.01 * sample_rate))
        release = max(1, int(0.08 * sample_rate))
        env = np.ones_like(t)
        a = min(attack, len(env))
        r = min(release, len(env))
        if a > 0:
            env[:a] = np.linspace(0.0, 1.0, a, endpoint=False)
        if r > 0:
            env[-r:] *= np.linspace(1.0, 0.0, r)
        amp = gain * (velocity / 127.0)
        audio[i0:i1] += (tone * env * amp).astype(np.float32)

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
    midi = Path(midi_path)
    out = Path(wav_path) if wav_path else midi.with_suffix(".wav")
    out.write_bytes(render_midi_to_wav_bytes(str(midi)))
    return str(out)


def midi_file_to_base64(path: str) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def describe_preview(path: str) -> str:
    notes, duration, bpm = _collect_notes(path)
    if not notes:
        return "No notes found to preview."
    names = [note_to_name(n[2]) for n in notes[:12]]
    more = "…" if len(notes) > 12 else ""
    return (
        f"Preview synth · {len(notes)} notes · {duration:.1f}s · ~{bpm} BPM · "
        f"{' '.join(names)}{more}"
    )
