"""Tests for mode color (beyond triads) and bend-aware audio preview."""

from __future__ import annotations

import sys
import types
import wave
from io import BytesIO
from pathlib import Path

import mido
import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[1]
if "midi_gen" not in sys.modules:
    _pkg = types.ModuleType("midi_gen")
    _pkg.__path__ = [str(_ROOT)]  # type: ignore[attr-defined]
    _pkg.__file__ = str(_ROOT / "__init__.py")
    sys.modules["midi_gen"] = _pkg

from midi_gen.arpeggio import create_arpeggio, paint_mode_color
from midi_gen.audio_preview import render_midi_to_wav_bytes
from midi_gen.drone_generation import generate_drone_events
from midi_gen.musician_styles import get_profile_by_id, profile_from_dict
from midi_gen.notes import note_str_to_midi
from midi_gen.scale import get_mode_color_pitch_classes, get_scale


def test_satie_id_and_legacy_alias():
    profile = get_profile_by_id("satie_neoclassical")
    assert profile is not None
    assert profile.name == "Erik Satie"
    assert get_profile_by_id("satt_neoclassical") is profile
    aliased = profile_from_dict({"id": "satt_neoclassical", "name": "Erik Satie"})
    assert aliased.id == "satie_neoclassical"


def test_lydian_arpeggio_includes_sharp_four():
    root = note_str_to_midi("C4")
    triad_pcs = set(get_scale(root, "lydian", use_chord_tones=True))
    color_pcs = set(get_mode_color_pitch_classes(root, "lydian"))
    assert color_pcs == {(root % 12 + 6) % 12}  # F#
    assert color_pcs.isdisjoint(triad_pcs)

    notes = create_arpeggio(
        root=root,
        mode="lydian",
        length=8,
        min_octave=4,
        max_octave=5,
        arp_mode="up",
        range_octaves=1,
        evolution_rate=0.0,
        repetition_factor=10,
        use_chord_tones=True,
        mode_color=True,
    )
    pcs = {n % 12 for n in notes}
    assert color_pcs & pcs, f"expected Lydian #4 in {pcs}"
    # Sparse: approach-only → well under half the cell is color
    color_count = sum(1 for n in notes if (n % 12) in color_pcs)
    assert 1 <= color_count <= 3, f"color density too high: {color_count}/8 in {notes}"


def test_dorian_arpeggio_includes_nat6_or_9():
    root = note_str_to_midi("D3")
    color_pcs = set(get_mode_color_pitch_classes(root, "dorian"))
    notes = create_arpeggio(
        root=root,
        mode="dorian",
        length=8,
        min_octave=3,
        max_octave=5,
        arp_mode="up_down",
        range_octaves=1,
        evolution_rate=0.0,
        repetition_factor=10,
        use_chord_tones=True,
        mode_color=True,
    )
    pcs = {n % 12 for n in notes}
    assert color_pcs & pcs


def test_major_minor_have_no_mode_color_intervals():
    root = note_str_to_midi("C4")
    assert get_mode_color_pitch_classes(root, "major") == []
    assert get_mode_color_pitch_classes(root, "minor") == []
    triad_maj = set(get_scale(root, "major", use_chord_tones=True))
    notes = create_arpeggio(
        root=root,
        mode="major",
        length=8,
        min_octave=4,
        max_octave=5,
        arp_mode="up",
        range_octaves=1,
        evolution_rate=0.0,
        repetition_factor=10,
        use_chord_tones=True,
        mode_color=True,
    )
    assert {n % 12 for n in notes} <= triad_maj


def test_glass_profile_stays_triad_clean():
    from midi_gen.musician_styles import find_best_profile

    glass = find_best_profile("Philip Glass")
    assert glass is not None
    assert glass.mode == "minor"
    assert get_mode_color_pitch_classes(note_str_to_midi(glass.root_notes[0]), glass.mode) == []
    root = note_str_to_midi(glass.root_notes[0])
    triad = set(get_scale(root, glass.mode, use_chord_tones=True))
    notes = create_arpeggio(
        root=root,
        mode=glass.mode,
        length=glass.arp_steps,
        min_octave=glass.min_octave,
        max_octave=glass.max_octave,
        arp_mode=glass.arp_mode,
        range_octaves=glass.range_octaves,
        evolution_rate=0.0,
        repetition_factor=10,
        use_chord_tones=glass.use_chord_tones,
        mode_color=glass.mode_color,
    )
    assert {n % 12 for n in notes} <= triad


def test_mode_color_can_be_disabled():
    root = note_str_to_midi("C4")
    color_pcs = set(get_mode_color_pitch_classes(root, "lydian"))
    notes = create_arpeggio(
        root=root,
        mode="lydian",
        length=8,
        min_octave=4,
        max_octave=4,
        arp_mode="up",
        range_octaves=0,
        evolution_rate=0.0,
        repetition_factor=10,
        use_chord_tones=True,
        mode_color=False,
    )
    pcs = {n % 12 for n in notes}
    assert not (color_pcs & pcs)
    assert pcs <= set(get_scale(root, "lydian", use_chord_tones=True))


def test_paint_mode_color_approach_only_sparse():
    root = note_str_to_midi("C4")
    triad = get_scale(root, "mixolydian", use_chord_tones=True)
    color_pcs = set(get_mode_color_pitch_classes(root, "mixolydian"))
    # Fabricate a triad-only 8-step cell
    pattern = [
        note_str_to_midi("C4"),
        note_str_to_midi("E4"),
        note_str_to_midi("G4"),
        note_str_to_midi("E4"),
        note_str_to_midi("C4"),
        note_str_to_midi("E4"),
        note_str_to_midi("G4"),
        note_str_to_midi("E4"),
    ]
    painted = paint_mode_color(pattern, root, "mixolydian", 4, 5, accent_every=4)
    # Strong beats 0,4 remain chord tones
    assert painted[0] % 12 in triad
    assert painted[4] % 12 in triad
    # Mid-weak slots (1, 2, 5, 6) stay triad — only approach (3, 7) paint
    assert painted[1] % 12 in triad
    assert painted[2] % 12 in triad
    assert painted[5] % 12 in triad
    assert painted[6] % 12 in triad
    assert painted[3] % 12 in color_pcs
    assert painted[7] % 12 in color_pcs
    color_count = sum(1 for n in painted if (n % 12) in color_pcs)
    assert color_count == 2, f"expected 2 approach accents, got {color_count}: {painted}"


def test_paint_force_one_if_missing_when_no_approach():
    """Short cell with no approach slot still gets one forced color hit."""
    root = note_str_to_midi("C4")
    color_pcs = set(get_mode_color_pitch_classes(root, "lydian"))
    # length 1 has no approach before a strong beat under period=4
    painted = paint_mode_color(
        [note_str_to_midi("C4")],
        root,
        "lydian",
        4,
        5,
        accent_every=4,
    )
    assert painted[0] % 12 in color_pcs



def test_drone_lydian_includes_color_tone():
    options = {
        "bpm": 72,
        "bars": 4,
        "mode": "lydian",
        "min_octave": 3,
        "max_octave": 4,
        "drone_base_velocity": 70,
        "drone_variation_interval_bars": 2,
        "drone_min_notes_held": 2,
        "drone_octave_doubling_chance": 0.0,
        "drone_allow_octave_shifts": False,
        "drone_enable_walkdowns": False,
        "mode_color": True,
        "debug": False,
    }
    root = note_str_to_midi("C3")
    color_pcs = set(get_mode_color_pitch_classes(root, "lydian"))
    events = generate_drone_events(options, [root])
    pitches = {e[0] % 12 for e in events}
    assert color_pcs & pitches


def _write_bent_midi(path: Path, bend_depth: int = 4000) -> None:
    """One long note with oscillating pitch bend (tape-like)."""
    mid = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0))
    track.append(mido.Message("note_on", note=60, velocity=100, time=0))
    # Sweep bend up and down over 1 beat (480 ticks), many steps
    steps = 24
    step_ticks = 480 // steps
    current = 0
    for i in range(steps):
        # triangle: 0 → +depth → 0 → −depth → 0
        phase = i / steps
        if phase < 0.25:
            bend = int(bend_depth * (phase / 0.25))
        elif phase < 0.5:
            bend = int(bend_depth * (1 - (phase - 0.25) / 0.25))
        elif phase < 0.75:
            bend = int(-bend_depth * ((phase - 0.5) / 0.25))
        else:
            bend = int(-bend_depth * (1 - (phase - 0.75) / 0.25))
        delta = step_ticks
        track.append(mido.Message("pitchwheel", pitch=bend, time=delta))
        current += delta
    # hold a bit then off
    track.append(mido.Message("pitchwheel", pitch=0, time=240))
    track.append(mido.Message("note_off", note=60, velocity=0, time=0))
    mid.save(path)


def _wav_rms_diff(a: bytes, b: bytes) -> float:
    def pcm(data: bytes) -> np.ndarray:
        with wave.open(BytesIO(data), "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            return np.frombuffer(frames, dtype=np.int16).astype(np.float32)

    x, y = pcm(a), pcm(b)
    n = min(len(x), len(y))
    if n == 0:
        return 0.0
    return float(np.sqrt(np.mean((x[:n] - y[:n]) ** 2)))


def _midi_bend_rms(path: str) -> float:
    """RMS of pitchwheel values — strength metric that ignores WAV peak-normalize."""
    bends: list[float] = []
    mid = mido.MidiFile(path)
    for track in mid.tracks:
        for msg in track:
            if msg.type == "pitchwheel":
                bends.append(float(msg.pitch))
    if not bends:
        return 0.0
    arr = np.asarray(bends, dtype=np.float64)
    return float(np.sqrt(np.mean(arr * arr)))


def _wobble_only_from_preset(preset_id: str, *, randomness: float = 0.0) -> list:
    """Tape wobble knobs only — strip humanize so velocity can't confound."""
    from midi_gen.effects_presets import get_preset

    out = []
    for conf in get_preset(preset_id)["effects"]:
        if conf.get("name") != "tape_wobble":
            continue
        wobble = dict(conf)
        wobble["randomness"] = randomness
        out.append(wobble)
    return out


def _write_drone_with_effects(tmp_path: Path, name: str, effect_confs: list) -> Path:
    """Same fixed drone MIDI notes, with optional wobble-only effects. Returns path."""
    import random

    from midi_gen.effects import EffectRegistry
    from midi_gen.midi import create_midi_file

    # 2 bars of a sustained C major triad (shared across clean/subtle/worn)
    ticks = 480 * 4 * 2
    events = [
        (60, 0, ticks, 90),
        (64, 0, ticks, 90),
        (67, 0, ticks, 90),
    ]
    path = tmp_path / f"{name}.mid"
    options = {
        "generation_type": "drone",
        "bpm": 120,
        "filename": str(path),
        "debug": False,
    }
    effects = []
    for conf in effect_confs:
        effect = EffectRegistry.create_effect(conf)
        assert effect is not None, conf
        effects.append(effect)
    # Seed so note-sync contour direction matches across variants
    random.seed(42)
    create_midi_file(events, options, effects)
    return path


def test_audio_preview_honors_pitch_bend(tmp_path):
    bent = tmp_path / "bent.mid"
    flat = tmp_path / "flat.mid"
    _write_bent_midi(bent, bend_depth=5000)

    # Flat twin: same note, no bends
    mid = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0))
    track.append(mido.Message("note_on", note=60, velocity=100, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, time=480 + 240))
    mid.save(flat)

    wav_bent = render_midi_to_wav_bytes(str(bent))
    wav_flat = render_midi_to_wav_bytes(str(flat))
    assert wav_bent[:4] == b"RIFF"
    # Pitch modulation must audibly change the waveform vs unbent
    assert _wav_rms_diff(wav_bent, wav_flat) > 500.0


def test_tape_wobble_preview_differs_from_clean_same_midi(tmp_path):
    """Wobble-only on identical notes — velocity humanize cannot confound."""
    subtle_conf = _wobble_only_from_preset("subtle_tape")
    worn_conf = _wobble_only_from_preset("worn_tape")
    assert len(subtle_conf) == 1 and subtle_conf[0]["name"] == "tape_wobble"
    assert len(worn_conf) == 1 and worn_conf[0]["name"] == "tape_wobble"
    assert not any(c.get("name") == "humanize_velocity" for c in subtle_conf + worn_conf)

    path_clean = _write_drone_with_effects(tmp_path, "clean", [])
    path_subtle = _write_drone_with_effects(tmp_path, "subtle", subtle_conf)
    path_worn = _write_drone_with_effects(tmp_path, "worn", worn_conf)

    wav_clean = render_midi_to_wav_bytes(str(path_clean))
    wav_subtle = render_midi_to_wav_bytes(str(path_subtle))
    wav_worn = render_midi_to_wav_bytes(str(path_worn))

    assert _wav_rms_diff(wav_clean, wav_subtle) > 100.0
    assert _wav_rms_diff(wav_clean, wav_worn) > 100.0
    # Strength via bend magnitude (WAV peak-normalize can invert RMS ordering)
    subtle_bend = _midi_bend_rms(str(path_subtle))
    worn_bend = _midi_bend_rms(str(path_worn))
    assert subtle_bend > 0.0
    assert worn_bend > subtle_bend, (
        f"worn wobble should exceed subtle ({worn_bend:.1f} vs {subtle_bend:.1f})"
    )
