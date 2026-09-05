"""Arp step mask rests even steps when gates say so."""

from __future__ import annotations

import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if "midi_gen" not in sys.modules:
    _pkg = types.ModuleType("midi_gen")
    _pkg.__path__ = [str(_ROOT)]  # type: ignore[attr-defined]
    _pkg.__file__ = str(_ROOT / "__init__.py")
    sys.modules["midi_gen"] = _pkg

from midi_gen.arpeggio_generation import apply_arp_step_mask, create_arp
from midi_gen.note_edit import list_note_events
from midi_gen.note_editor import preview_step_index


def test_apply_arp_step_mask_rests_even_steps():
    assert apply_arp_step_mask(
        [60, 62, 64, 65],
        arp_steps=4,
        gates=[True, False, True, False],
        pitches=None,
    ) == [60, None, 64, None]


def test_create_arp_gates_even_rests(tmp_path):
    path = create_arp(
        {
            "generation_type": "arpeggio",
            "root_notes": ["C4"],
            "mode": "minor",
            "bars": 1,
            "arp_steps": 4,
            "arp_mode": "up",
            "min_octave": 4,
            "max_octave": 5,
            "range_octaves": 1,
            "evolution_rate": 0.0,
            "repetition_factor": 10,
            "repeat_pattern": False,
            "use_chord_tones": True,
            "mode_color": False,
            "effects_config": [],
            "arp_gates": [True, False, True, False],
            "seed": 1,
            "filename": str(tmp_path / "gates.mid"),
            "debug": False,
        }
    )
    starts = [n["start_tick"] for n in list_note_events(path)]
    assert all(not (480 <= t < 960) for t in starts)
    assert all(not (1440 <= t < 1920) for t in starts)


def test_preview_step_index_eighths_wraps_each_bar():
    assert preview_step_index(0.0, 120, 8) == 0
    assert preview_step_index(0.25, 120, 8) == 1
    assert preview_step_index(2.0, 120, 8) == 0
    assert preview_step_index(0.0, 108, 16) == 0
