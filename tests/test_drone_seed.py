"""Drone path must honor options['seed'] (Eno Again / Generate-with-seed)."""

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

from midi_gen.cursor_style_lookup import generate_midi_for_style
from midi_gen.drone_generation import generate_drone_events
from midi_gen.notes import note_str_to_midi


def _drone_options(**extra):
    base = {
        "bpm": 72,
        "bars": 8,
        "mode": "lydian",
        "min_octave": 2,
        "max_octave": 4,
        "drone_base_velocity": 70,
        "drone_variation_interval_bars": 2,
        "drone_min_notes_held": 3,
        "drone_octave_doubling_chance": 0.35,
        "drone_allow_octave_shifts": True,
        "drone_octave_shift_one_note_chance": 0.1,
        "drone_enable_walkdowns": False,
        "mode_color": True,
        "debug": False,
    }
    base.update(extra)
    return base


def _roots():
    return [note_str_to_midi(n) for n in ("C3", "G2", "F3", "D3")]


def _note_on_pitches(path: str) -> list[int]:
    mid = mido.MidiFile(path)
    pitches: list[int] = []
    for track in mid.tracks:
        for msg in track:
            if msg.type == "note_on" and msg.velocity > 0:
                pitches.append(msg.note)
    return pitches


def test_same_seed_reproduces_identical_drone_events():
    opts = _drone_options(seed=42)
    a = generate_drone_events(opts, _roots())
    b = generate_drone_events(opts, _roots())
    assert a == b
    assert len(a) > 0


def test_different_seeds_are_not_guaranteed_identical():
    roots = _roots()
    a = generate_drone_events(_drone_options(seed=1), roots)
    b = generate_drone_events(_drone_options(seed=2), roots)
    # Not guaranteed different for every pair, but these two diverge with
    # octave-shift / doubling enabled on an 8-bar multi-root drone.
    assert a != b


def test_explicit_rng_overrides_options_seed():
    roots = _roots()
    import random

    via_seed = generate_drone_events(_drone_options(seed=99), roots)
    via_rng = generate_drone_events(
        _drone_options(seed=1), roots, rng=random.Random(99)
    )
    assert via_seed == via_rng


def test_eno_generate_midi_for_style_seed_is_deterministic(tmp_path):
    """Again on Eno: same seed → same note-on sequence (clean effects, no tape RNG)."""
    overrides_a = {
        "bars": 4,
        "seed": 12345,
        "effects_preset": "clean",
        "debug": False,
        "filename": str(tmp_path / "eno_a.mid"),
    }
    overrides_b = {
        "bars": 4,
        "seed": 12345,
        "effects_preset": "clean",
        "debug": False,
        "filename": str(tmp_path / "eno_b.mid"),
    }
    path_a, result_a, _ = generate_midi_for_style(
        "Brian Eno", use_cursor_sdk=False, overrides=overrides_a
    )
    path_b, result_b, _ = generate_midi_for_style(
        "Brian Eno", use_cursor_sdk=False, overrides=overrides_b
    )
    assert result_a.profile.generation_type == "drone"
    assert result_b.profile.id == "eno_ambient"
    assert _note_on_pitches(path_a) == _note_on_pitches(path_b)

    overrides_c = {
        "bars": 4,
        "seed": 99999,
        "effects_preset": "clean",
        "debug": False,
        "filename": str(tmp_path / "eno_c.mid"),
    }
    path_c, _, _ = generate_midi_for_style(
        "Brian Eno", use_cursor_sdk=False, overrides=overrides_c
    )
    assert _note_on_pitches(path_a) != _note_on_pitches(path_c)
