"""User sketch layout: bars, chord count, drone (held) shape."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
if "midi_gen" not in sys.modules:
    _pkg = types.ModuleType("midi_gen")
    _pkg.__path__ = [str(_ROOT)]  # type: ignore[attr-defined]
    _pkg.__file__ = str(_ROOT / "__init__.py")
    sys.modules["midi_gen"] = _pkg

from midi_gen.cursor_style_lookup import (
    LOOKUP_STICKY_OVERRIDE_KEYS,
    generate_midi_for_style,
)
from midi_gen.notes import shift_midi_by_octaves, shift_note_name_octave
from midi_gen.style_prompting import (
    DEFAULT_CHORD_COUNT,
    DEFAULT_GENERATION_TYPE,
    DEFAULT_PROGRESSION,
    DEFAULT_SKETCH_BARS,
    apply_octave_shift,
    apply_user_sketch_layout,
    clamp_chord_count,
    clamp_generation_type,
    clamp_octave_shift,
    format_shape_label,
    resize_chord_progression,
    shift_progression_octave,
)


def test_clamp_chord_count_and_generation_type():
    assert clamp_chord_count(4) == 4
    assert clamp_chord_count(1) == 1
    assert clamp_chord_count(8) == 8
    assert clamp_chord_count(0) == 1
    assert clamp_chord_count(99) == 8
    assert clamp_chord_count("nope") == DEFAULT_CHORD_COUNT
    assert clamp_generation_type("drone") == "drone"
    assert clamp_generation_type("progression") == "drone"
    assert clamp_generation_type("arpeggio") == "arpeggio"
    assert clamp_generation_type("banana") == DEFAULT_GENERATION_TYPE
    assert format_shape_label("drone") == "Progression"
    assert format_shape_label("progression") == "Progression"
    assert format_shape_label("arpeggio") == "Arpeggio"
    assert DEFAULT_SKETCH_BARS == 16
    assert DEFAULT_CHORD_COUNT == 4
    assert DEFAULT_GENERATION_TYPE == "drone"


def test_resize_chord_progression_trim_cycle_and_fallback():
    assert resize_chord_progression(["C3", "G3", "A3", "F3"], 2) == ["C3", "G3"]
    assert resize_chord_progression(["C3", "G3"], 4) == ["C3", "G3", "C3", "G3"]
    assert resize_chord_progression([], 4) == list(DEFAULT_PROGRESSION)
    assert resize_chord_progression(None, 4) == list(DEFAULT_PROGRESSION)


def test_apply_user_sketch_layout_held_drone_and_resize():
    out = apply_user_sketch_layout(
        {
            "generation_type": "drone",
            "chord_count": 2,
            "chord_progression": ["D3", "A3", "G3", "D3"],
            "root_notes": ["D3", "A3", "G3", "D3"],
        }
    )
    assert out["generation_type"] == "drone"
    assert out["drone_held"] is True
    assert out["chord_progression"] == ["D3", "A3"]
    assert out["root_notes"] == ["D3", "A3"]
    assert out["chord_count"] == 2


def test_apply_user_sketch_layout_noop_without_user_knobs():
    raw = {"generation_type": "arpeggio", "chord_progression": ["A3", "E3"]}
    assert apply_user_sketch_layout(raw) == raw


def test_shift_note_name_and_midi_octave():
    assert shift_note_name_octave("C3", 1) == "C4"
    assert shift_note_name_octave("C4", -1) == "C3"
    assert shift_midi_by_octaves(60, 1) == 72
    assert shift_midi_by_octaves(127, 1) == 127
    assert shift_midi_by_octaves(1, -1) == 1
    assert shift_progression_octave(["C3", "G3"], 1) == ["C4", "G4"]
    assert shift_progression_octave([48, 55], 1) == [60, 67]
    assert clamp_octave_shift(9) == 3
    assert clamp_octave_shift("nope") == 0


def test_apply_octave_shift_moves_roots_and_window():
    out = apply_octave_shift(
        {
            "chord_progression": ["C3", "G3"],
            "root_notes": ["C3", "G3"],
            "min_octave": 3,
            "max_octave": 5,
        },
        1,
    )
    assert out["chord_progression"] == ["C4", "G4"]
    assert out["root_notes"] == ["C4", "G4"]
    assert out["min_octave"] == 4
    assert out["max_octave"] == 6


def test_apply_user_sketch_layout_octave_shift_after_resize():
    out = apply_user_sketch_layout(
        {
            "chord_count": 2,
            "chord_progression": ["C3", "G3", "A3", "F3"],
            "min_octave": 3,
            "max_octave": 5,
            "octave_shift": 1,
        }
    )
    assert out["chord_progression"] == ["C4", "G4"]
    assert out["root_notes"] == ["C4", "G4"]
    assert out["min_octave"] == 4
    assert out["max_octave"] == 6
    assert out["octave_shift"] == 1


def test_generate_honors_held_drone_16_bars_4_chords(tmp_path):
    captured = {}

    def fake_create_arp(options):
        captured["options"] = dict(options)
        out = tmp_path / "held.mid"
        out.write_bytes(b"MThd")
        return str(out)

    with mock.patch(
        "midi_gen.arpeggio_generation.create_arp", side_effect=fake_create_arp
    ):
        _path, _result, options = generate_midi_for_style(
            "Philip Glass",
            use_cursor_sdk=False,
            overrides={
                "bars": 16,
                "chord_count": 4,
                "generation_type": "drone",
                "drone_held": True,
            },
        )
    assert options["generation_type"] == "drone"
    assert options["drone_held"] is True
    assert options["bars"] == 16
    assert options["chord_count"] == 4
    assert len(options["chord_progression"]) == 4
    assert captured["options"]["generation_type"] == "drone"
    assert captured["options"]["drone_held"] is True
    assert captured["options"]["chord_progression"] == options["chord_progression"]


def test_sticky_keys_include_sketch_layout():
    assert "generation_type" in LOOKUP_STICKY_OVERRIDE_KEYS
    assert "drone_held" in LOOKUP_STICKY_OVERRIDE_KEYS
    assert "chord_count" in LOOKUP_STICKY_OVERRIDE_KEYS
    assert "octave_shift" in LOOKUP_STICKY_OVERRIDE_KEYS


def test_generate_honors_octave_shift(tmp_path):
    captured = {}

    def fake_create_arp(options):
        captured["options"] = dict(options)
        out = tmp_path / "shifted.mid"
        out.write_bytes(b"MThd")
        return str(out)

    with mock.patch(
        "midi_gen.arpeggio_generation.create_arp", side_effect=fake_create_arp
    ):
        _path, _result, base = generate_midi_for_style(
            "Philip Glass",
            use_cursor_sdk=False,
            overrides={"generation_mode": "progression"},
        )
        _path, _result, options = generate_midi_for_style(
            "Philip Glass",
            use_cursor_sdk=False,
            overrides={"octave_shift": 1, "generation_mode": "progression"},
        )
    assert options["min_octave"] == int(base["min_octave"]) + 1
    assert options["max_octave"] == int(base["max_octave"]) + 1
    assert options["chord_progression"] == shift_progression_octave(
        base["chord_progression"], 1
    )
    assert captured["options"]["min_octave"] == options["min_octave"]
    assert captured["options"]["chord_progression"] == options["chord_progression"]


def test_ui_wires_sketch_layout_knobs():
    src = (_ROOT / "ui_app.py").read_text(encoding="utf-8")
    assert "def _render_sketch_layout" in src
    assert "_render_sketch_layout()" in src
    assert 'key="chord_count"' in src
    assert 'key="home_generate"' in src
    assert '"chord_count": int(chord_count)' in src
    # UI Simplify: Pattern|Progression → generation_mode (wash opt-out via Engine)
    assert '"generation_mode": generation_mode' in src
    assert "apply_generation_mode" in (_ROOT / "cursor_style_lookup.py").read_text(
        encoding="utf-8"
    )
    assert "Timing" in src
    assert "Song part" in src
    assert "Drone (held)" not in src
    assert "Extend (drone)" not in src
    assert "_render_timing_chips" in src
    assert "_render_generation_mode_toggle" in src
    assert "_render_section_chips" in src
    assert "_render_timing_select" not in src
    assert "_render_generation_mode_select" not in src