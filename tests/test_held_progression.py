"""Held progression + extend_factor for the drone engine path."""

from __future__ import annotations

import sys
import types
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if "midi_gen" not in sys.modules:
    _pkg = types.ModuleType("midi_gen")
    _pkg.__path__ = [str(_ROOT)]  # type: ignore[attr-defined]
    _pkg.__file__ = str(_ROOT / "__init__.py")
    sys.modules["midi_gen"] = _pkg

from midi_gen.arpeggio_generation import (
    apply_extend_factor,
    create_arp,
    resolve_drone_held,
    resolve_extend_factor,
)
from midi_gen.drone_generation import generate_drone_events
from midi_gen.notes import note_str_to_midi
from midi_gen.scale import get_scale


TICKS_PER_BAR = 480 * 4

# I–V–vi–IV in C major
PROGRESSION = ["C3", "G3", "A3", "F3"]


def _prog_midi():
    return [note_str_to_midi(n) for n in PROGRESSION]


def _held_opts(**extra):
    base = {
        "bpm": 100,
        "bars": 8,
        "mode": "major",
        "min_octave": 3,
        "max_octave": 5,
        "drone_base_velocity": 70,
        "drone_held": True,
        "drone_variation_interval_bars": 1,
        "drone_octave_doubling_chance": 1.0,
        "drone_allow_octave_shifts": True,
        "drone_enable_walkdowns": True,
        "mode_color": True,
        "seed": 7,
        "debug": False,
    }
    base.update(extra)
    return base


def _events_by_start(events):
    by_start: dict[int, list] = defaultdict(list)
    for note, start, dur, vel in events:
        by_start[start].append((note, start, dur, vel))
    return dict(by_start)


def test_resolve_extend_factor_clamps():
    assert resolve_extend_factor(None) == 1
    assert resolve_extend_factor(2) == 2
    assert resolve_extend_factor(4) == 4
    assert resolve_extend_factor(9) == 4
    assert resolve_extend_factor(0) == 1
    assert resolve_extend_factor("3") == 3
    assert resolve_extend_factor("nope") == 1


def test_apply_extend_factor_multiplies_bars_without_mutating_caller():
    raw = {"bars": 8, "extend_factor": 2}
    out = apply_extend_factor(raw)
    assert raw["bars"] == 8
    assert out["bars"] == 16
    assert out["extend_factor"] == 2


def test_resolve_drone_held_defaults_from_progression():
    assert resolve_drone_held({}, _prog_midi()) is True
    assert resolve_drone_held({}, None) is False
    assert resolve_drone_held({"drone_held": False}, _prog_midi()) is False
    assert resolve_drone_held({"drone_held": True}, None) is True
    assert resolve_drone_held({"held": False}, _prog_midi()) is False


def test_held_one_sustained_voicing_per_segment_on_boundaries():
    roots = _prog_midi()
    bars = 8
    events = generate_drone_events(_held_opts(bars=bars), roots)
    bars_per = bars // len(roots)
    by_start = _events_by_start(events)

    # Changes only at segment boundaries (equal bars; last eats remainder — here exact)
    expected_starts = [i * bars_per * TICKS_PER_BAR for i in range(len(roots))]
    assert sorted(by_start.keys()) == expected_starts

    for i, root in enumerate(roots):
        start = expected_starts[i]
        seg_events = by_start[start]
        pitches = sorted(e[0] for e in seg_events)
        expected_pcs = set(get_scale(root, "major", use_chord_tones=True))
        assert {p % 12 for p in pitches} == expected_pcs
        # Full-segment sustain — no mid-segment restarts
        for _note, _s, dur, _v in seg_events:
            assert dur == bars_per * TICKS_PER_BAR
        # Exactly one voicing stack at the boundary (no wash re-attacks)
        assert len(seg_events) == len(pitches)


def test_held_ignores_wash_knobs():
    """Walkdowns / doubling / color must not fire when held."""
    roots = _prog_midi()
    events = generate_drone_events(
        _held_opts(
            bars=8,
            drone_octave_doubling_chance=1.0,
            drone_enable_walkdowns=True,
            drone_allow_octave_shifts=True,
            mode_color={"enabled": True, "accent_every": 1},
        ),
        roots,
    )
    # 4 chords × 3 triad tones = 12 events (no extras)
    assert len(events) == 12
    starts = {e[1] for e in events}
    assert len(starts) == 4


def test_extend_2x_and_4x_stretches_bars_per_chord_not_changes():
    roots = _prog_midi()
    base_bars = 8
    base = generate_drone_events(_held_opts(bars=base_bars), roots)

    for factor in (2, 4):
        stretched = generate_drone_events(
            _held_opts(bars=base_bars * factor), roots
        )
        by_base = _events_by_start(base)
        by_stretch = _events_by_start(stretched)
        assert len(by_base) == len(by_stretch) == len(roots)
        for i in range(len(roots)):
            b_start = sorted(by_base.keys())[i]
            s_start = sorted(by_stretch.keys())[i]
            b_dur = by_base[b_start][0][2]
            s_dur = by_stretch[s_start][0][2]
            assert s_dur == b_dur * factor
            assert {e[0] for e in by_base[b_start]} == {
                e[0] for e in by_stretch[s_start]
            }


def test_create_arp_extend_factor_doubles_bars_via_options(tmp_path):
    opts = {
        "generation_type": "drone",
        "mode": "major",
        "bars": 8,
        "extend_factor": 2,
        "chord_progression": PROGRESSION,
        "root_notes": ["C3"],  # must be ignored in favor of progression
        "min_octave": 3,
        "max_octave": 5,
        "seed": 11,
        "filename": str(tmp_path / "held_ext.mid"),
        "effects_config": [],
    }
    # Spy via generate_drone_events through create_arp — inspect MIDI length via events
    from midi_gen import arpeggio_generation as ag

    captured = {}
    real = ag.generate_drone_events

    def spy(options, roots, rng=None):
        captured["bars"] = options.get("bars")
        captured["held"] = options.get("drone_held")
        captured["roots"] = list(roots)
        return real(options, roots, rng=rng)

    ag.generate_drone_events = spy  # type: ignore[assignment]
    try:
        create_arp(opts)
    finally:
        ag.generate_drone_events = real  # type: ignore[assignment]

    assert captured["bars"] == 16
    assert captured["held"] is True
    assert captured["roots"] == _prog_midi()


def test_create_arp_extend_4x(tmp_path):
    from midi_gen import arpeggio_generation as ag

    captured = {}
    real = ag.generate_drone_events

    def spy(options, roots, rng=None):
        captured["bars"] = options.get("bars")
        return real(options, roots, rng=rng)

    ag.generate_drone_events = spy  # type: ignore[assignment]
    try:
        create_arp({
            "generation_type": "drone",
            "mode": "major",
            "bars": 8,
            "extend_factor": 4,
            "chord_progression": PROGRESSION,
            "min_octave": 3,
            "max_octave": 5,
            "seed": 3,
            "filename": str(tmp_path / "held_x4.mid"),
            "effects_config": [],
        })
    finally:
        ag.generate_drone_events = real  # type: ignore[assignment]

    assert captured["bars"] == 32


def test_non_held_wash_path_still_available():
    roots = _prog_midi()
    wash = generate_drone_events(
        _held_opts(
            drone_held=False,
            bars=8,
            drone_variation_interval_bars=1,
            drone_octave_doubling_chance=1.0,
            drone_enable_walkdowns=False,
            drone_allow_octave_shifts=False,
            mode_color=False,
        ),
        roots,
    )
    held = generate_drone_events(_held_opts(bars=8), roots)
    # Wash with interval=1 and forced doubling produces more / different events
    assert len(wash) > len(held)
    # Wash re-attacks inside segments (starts not only on boundaries)
    wash_starts = {e[1] for e in wash}
    boundary_starts = {i * 2 * TICKS_PER_BAR for i in range(4)}
    assert wash_starts != boundary_starts or len(wash) > 12


def test_held_seed_determinism():
    roots = _prog_midi()
    a = generate_drone_events(_held_opts(seed=42), roots)
    b = generate_drone_events(_held_opts(seed=42), roots)
    assert a == b


def test_progression_default_held_without_explicit_flag(tmp_path):
    """chord_progression alone → held True (recipe default)."""
    from midi_gen import arpeggio_generation as ag

    captured = {}
    real = ag.generate_drone_events

    def spy(options, roots, rng=None):
        captured["held"] = options.get("drone_held")
        captured["roots"] = list(roots)
        return real(options, roots, rng=rng)

    ag.generate_drone_events = spy  # type: ignore[assignment]
    try:
        create_arp({
            "generation_type": "drone",
            "mode": "major",
            "bars": 8,
            "chord_progression": PROGRESSION,
            "root_notes": ["E2", "E2"],
            "min_octave": 3,
            "max_octave": 5,
            "seed": 1,
            "filename": str(tmp_path / "default_held.mid"),
            "effects_config": [],
        })
    finally:
        ag.generate_drone_events = real  # type: ignore[assignment]

    assert captured["held"] is True
    assert captured["roots"] == _prog_midi()


def test_explicit_non_held_with_progression(tmp_path):
    from midi_gen import arpeggio_generation as ag

    captured = {}
    real = ag.generate_drone_events

    def spy(options, roots, rng=None):
        captured["held"] = options.get("drone_held")
        return real(options, roots, rng=rng)

    ag.generate_drone_events = spy  # type: ignore[assignment]
    try:
        create_arp({
            "generation_type": "drone",
            "mode": "lydian",
            "bars": 4,
            "chord_progression": PROGRESSION,
            "drone_held": False,
            "min_octave": 2,
            "max_octave": 4,
            "seed": 5,
            "filename": str(tmp_path / "wash_prog.mid"),
            "effects_config": [],
        })
    finally:
        ag.generate_drone_events = real  # type: ignore[assignment]

    assert captured["held"] is False


def test_eno_wash_catalog_opts_out_of_held():
    """Ambient pad recipe must not flip to held when progression is present."""
    from midi_gen.musician_styles import get_profile_by_id

    eno = get_profile_by_id("eno_ambient")
    assert eno is not None
    assert eno.drone_held is False
    opts = eno.to_options()
    assert opts.get("drone_held") is False
    # Even if FULL-contract / cousin attaches a progression later:
    assert resolve_drone_held(
        opts, [note_str_to_midi(n) for n in ("C3", "G2", "F3", "D3")]
    ) is False


def test_wash_catalog_drones_all_opt_out():
    from midi_gen.musician_styles import MUSICIAN_STYLE_CATALOG

    wash = [
        p
        for p in MUSICIAN_STYLE_CATALOG
        if p.generation_type == "drone"
        and any(
            t in p.styles
            for t in ("wash", "ambient", "ambient pad", "ambient drone", "pad", "texture")
        )
    ]
    assert wash, "expected at least eno_ambient"
    for profile in wash:
        assert profile.drone_held is False, profile.id
        assert profile.to_options().get("drone_held") is False, profile.id
