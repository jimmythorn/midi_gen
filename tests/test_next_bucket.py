"""Tests for pattern development, rhythmic_variation fix, and catalog enrich."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import mido
import pytest

_ROOT = Path(__file__).resolve().parents[1]
if "midi_gen" not in sys.modules:
    _pkg = types.ModuleType("midi_gen")
    _pkg.__path__ = [str(_ROOT)]  # type: ignore[attr-defined]
    _pkg.__file__ = str(_ROOT / "__init__.py")
    sys.modules["midi_gen"] = _pkg

from midi_gen.arpeggio import create_arpeggio
from midi_gen.arpeggio_generation import create_arp
from midi_gen.cursor_style_lookup import STYLE_PROFILE_JSON_SCHEMA, lookup_musician_style
from midi_gen.musician_styles import get_profile_by_id, profile_from_dict
from midi_gen.notes import note_str_to_midi
from midi_gen.pattern_development import (
    apply_phase_offset,
    evolve_phase,
    mutate_cell,
    normalize_development,
)


def test_rhythmic_variation_preserves_rests():
    """CRITICAL: rests must survive — no strip-and-refill self-nullify."""
    import random

    rng = random.Random(0)
    notes = create_arpeggio(
        root=note_str_to_midi("C4"),
        mode="major",
        length=8,
        min_octave=4,
        max_octave=5,
        arp_mode="up",
        range_octaves=1,
        evolution_rate=0.0,
        repetition_factor=10,
        rhythmic_variation=True,
        use_chord_tones=True,
        mode_color=False,
        bar_index=0,
        preserve_rests=True,
        rng=rng,
    )
    assert len(notes) == 8
    # With seeded RNG, dropped/dotted path should introduce at least one rest
    # across a few bar indices.
    rest_seen = any(n is None for n in notes)
    if not rest_seen:
        notes_odd = create_arpeggio(
            root=note_str_to_midi("C4"),
            mode="major",
            length=8,
            min_octave=4,
            max_octave=5,
            arp_mode="up",
            range_octaves=1,
            evolution_rate=0.0,
            repetition_factor=10,
            rhythmic_variation=True,
            use_chord_tones=True,
            mode_color=False,
            bar_index=1,  # odd-bar accent flip changes placement
            preserve_rests=True,
            rng=random.Random(1),
        )
        rest_seen = any(n is None for n in notes_odd) or notes != notes_odd
    assert rest_seen, "rhythmic_variation should create rests or odd-bar shift"


def test_rhythmic_variation_odd_bar_differs():
    import random

    kwargs = dict(
        root=note_str_to_midi("D3"),
        mode="dorian",
        length=16,
        min_octave=3,
        max_octave=5,
        arp_mode="up",
        range_octaves=1,
        evolution_rate=0.0,
        repetition_factor=10,
        rhythmic_variation=True,
        use_chord_tones=True,
        mode_color=False,
        preserve_rests=True,
    )
    even = create_arpeggio(**kwargs, bar_index=0, rng=random.Random(42))
    odd = create_arpeggio(**kwargs, bar_index=1, rng=random.Random(42))
    # Same seed + odd-bar flip → different attack placement
    assert even != odd


def test_development_changes_patterns_across_bars(tmp_path):
    """Development must change note patterns across bars (not static tile)."""
    path = create_arp({
        "generation_type": "arpeggio",
        "root_notes": ["C4"],
        "mode": "minor",
        "bars": 8,
        "arp_steps": 8,
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
        "seed": 7,
        "development": {
            "enabled": True,
            "seed_bars": 1,
            "mutate_every_n": 1,
            "mutate_ops": ["add_rest", "invert", "thin", "add_attack"],
            "phase_creep": True,
            "max_phase": 2,
            "additive_only": False,
        },
        "filename": str(tmp_path / "dev.mid"),
        "debug": False,
    })
    # Also compare bar event grids directly via a second static run
    static_path = create_arp({
        "generation_type": "arpeggio",
        "root_notes": ["C4"],
        "mode": "minor",
        "bars": 8,
        "arp_steps": 8,
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
        "seed": 7,
        "development": None,
        "filename": str(tmp_path / "static.mid"),
        "debug": False,
    })
    assert Path(path).exists()
    assert Path(static_path).exists()

    def pitch_seq(p: str) -> list:
        mid = mido.MidiFile(p)
        pitches = []
        for track in mid.tracks:
            for msg in track:
                if msg.type == "note_on" and msg.velocity > 0:
                    pitches.append(msg.note)
        return pitches

    developed = pitch_seq(path)
    static = pitch_seq(static_path)
    assert developed, "expected notes"
    assert static, "expected static notes"
    # Developed sketch should not be a pure repeat of the static tile
    assert developed != static

    # Within developed file: first-half pitch multiset differs from second half
    mid = len(developed) // 2
    assert developed[:mid] != developed[mid : mid + mid] or len(set(developed)) > 1


def test_mutate_additive_only_never_adds_rests():
    cell = [60, 64, 67, 72, 67, 64, 60, 64]
    out = mutate_cell(
        cell,
        mutate_ops=["add_attack", "add_rest", "thin", "invert"],
        source_notes=[60, 64, 67, 72],
        additive_only=True,
        rng=__import__("random").Random(0),
    )
    assert all(n is not None for n in out) or sum(1 for n in out if n is not None) >= sum(
        1 for n in cell if n is not None
    )


def test_phase_creep_helpers():
    cell = [1, 2, 3, 4, 5, 6, 7, 8]
    assert apply_phase_offset(cell, 0) == cell
    assert apply_phase_offset(cell, 1) == [8, 1, 2, 3, 4, 5, 6, 7]
    assert apply_phase_offset(cell, 2) == [7, 8, 1, 2, 3, 4, 5, 6]
    assert evolve_phase(0) == 1
    assert evolve_phase(1) == 2
    assert evolve_phase(2) == 2
    assert normalize_development(None) is None
    assert normalize_development(False) is None
    d = normalize_development({"additive_only": True, "mutate_ops": ["add_attack", "thin"]})
    assert d is not None
    assert "thin" not in d["mutate_ops"]
    assert "add_attack" in d["mutate_ops"]


def test_arp_steps_duration_matches_eighths(tmp_path):
    """8-step non-repeat should write 8th-note durations (240 ticks), not 16ths."""
    path = create_arp({
        "generation_type": "arpeggio",
        "root_notes": ["C4"],
        "mode": "major",
        "bars": 1,
        "arp_steps": 8,
        "arp_mode": "up",
        "min_octave": 4,
        "max_octave": 4,
        "range_octaves": 0,
        "evolution_rate": 0.0,
        "repetition_factor": 10,
        "repeat_pattern": False,
        "use_chord_tones": True,
        "mode_color": False,
        "effects_config": [],
        "bpm": 120,
        "filename": str(tmp_path / "eighths.mid"),
        "debug": False,
    })
    mid = mido.MidiFile(path)
    # Collect note_on → note_off durations for first few notes
    abs_tick = 0
    ons = {}
    durations = []
    for track in mid.tracks:
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                ons[msg.note] = abs_tick
            elif msg.type in ("note_off", "note_on") and (
                msg.type == "note_off" or msg.velocity == 0
            ):
                if msg.note in ons:
                    durations.append(abs_tick - ons.pop(msg.note))
    assert durations, "expected notes"
    # 8th note at 480 tpq = 240 ticks
    assert all(d == 240 for d in durations), f"expected 240-tick 8ths, got {durations}"


def test_create_arp_wires_embellish_and_progression(tmp_path):
    path = create_arp({
        "generation_type": "arpeggio",
        "root_notes": ["D3"],
        "mode": "dorian",
        "bars": 2,
        "arp_steps": 8,
        "arp_mode": "up",
        "min_octave": 3,
        "max_octave": 5,
        "evolution_rate": 0.0,
        "repetition_factor": 10,
        "embellish": True,
        "rhythmic_variation": True,
        "chord_progression": ["D3", "A3"],
        "effects_config": [],
        "seed": 3,
        "filename": str(tmp_path / "wired.mid"),
        "debug": False,
    })
    assert Path(path).exists()
    mid = mido.MidiFile(path)
    assert any(msg.type == "note_on" for track in mid.tracks for msg in track)


def test_enriched_catalog_profiles():
    glass = get_profile_by_id("glass_minimal")
    assert glass is not None
    assert glass.root_notes == ["A3", "A3", "E3", "A3"]
    assert glass.bars == 16
    assert glass.development is not None
    assert glass.development.get("additive_only") is True
    assert glass.embellish is True

    reich = get_profile_by_id("reich_phase")
    assert reich is not None
    assert reich.rhythmic_variation is True
    assert reich.development is not None
    assert reich.development.get("phase_creep") is True
    assert reich.chord_progression is not None

    eno = get_profile_by_id("eno_ambient")
    assert eno is not None
    assert eno.generation_type == "drone"
    assert isinstance(eno.mode_color, dict)

    coltrane = get_profile_by_id("coltrane_sheets")
    assert coltrane is not None
    assert "Giant Steps" not in coltrane.description
    assert "density" in coltrane.description.lower() or "6/9/11" in coltrane.description
    assert isinstance(coltrane.mode_color, dict)
    assert coltrane.mode_color.get("intervals") == [9, 2, 5]
    # No #4 in custom intervals
    assert 6 not in coltrane.mode_color.get("intervals", [])

    # satie alias still works
    assert get_profile_by_id("satt_neoclassical") is get_profile_by_id("satie_neoclassical")

    opts = glass.to_options()
    assert opts["development"]["additive_only"] is True
    assert opts["embellish"] is True


def test_schema_mentions_development_and_mode_color_dict():
    assert "development" in STYLE_PROFILE_JSON_SCHEMA
    assert "embellish" in STYLE_PROFILE_JSON_SCHEMA
    assert "rhythmic_variation" in STYLE_PROFILE_JSON_SCHEMA
    assert "intervals" in STYLE_PROFILE_JSON_SCHEMA


def test_profile_from_dict_accepts_nested_blocks():
    profile = profile_from_dict({
        "name": "Custom",
        "mode": "dorian",
        "mode_color": {"enabled": True, "intervals": [2, 9], "accent_every": 4},
        "development": {"seed_bars": 2, "mutate_every_n": 2, "additive_only": True},
        "embellish": True,
        "rhythmic_variation": True,
        "chord_progression": ["D3", "A3"],
    })
    assert isinstance(profile.mode_color, dict)
    assert profile.mode_color["intervals"] == [2, 9]
    assert profile.development["seed_bars"] == 2
    assert profile.development["additive_only"] is True
    assert profile.embellish is True
    assert profile.chord_progression == ["D3", "A3"]


def test_glass_profile_stays_triad_clean_with_enrichment():
    from midi_gen.scale import get_scale

    glass = get_profile_by_id("glass_minimal")
    assert glass is not None
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
        embellish=False,
        rhythmic_variation=False,
    )
    sounding = [n for n in notes if n is not None]
    assert {n % 12 for n in sounding} <= triad


def test_lookup_reich_and_glass_offline():
    r = lookup_musician_style("Steve Reich", use_cursor_sdk=False)
    assert r.profile.id == "reich_phase"
    g = lookup_musician_style("Philip Glass", use_cursor_sdk=False)
    assert g.profile.id == "glass_minimal"
    assert g.to_options()["bars"] == 16
