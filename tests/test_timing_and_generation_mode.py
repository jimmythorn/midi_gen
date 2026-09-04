"""Engine timing_factor + Pattern|Progression generation_mode overrides."""

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

from midi_gen.arpeggio_generation import (
    apply_extend_factor,
    apply_generation_mode,
    apply_timing_factor,
    create_arp,
    resolve_timing_factor,
)
from midi_gen.musician_styles import get_profile_by_id, profile_from_dict


PROGRESSION = ["C3", "G3", "A3", "F3"]  # 4 chords


def test_resolve_timing_factor_discrete_set():
    assert resolve_timing_factor(None) == 1.0
    assert resolve_timing_factor(0.5) == 0.5
    assert resolve_timing_factor(1) == 1.0
    assert resolve_timing_factor(2) == 2.0
    assert resolve_timing_factor(4) == 4.0
    assert resolve_timing_factor("0.5") == 0.5
    assert resolve_timing_factor(3) == 1.0  # not in timing set
    assert resolve_timing_factor(9) == 1.0
    assert resolve_timing_factor("nope") == 1.0


def test_timing_factor_scales_bars_per_chord_chord_count_fixed():
    base = {
        "bars": 8,
        "chord_progression": list(PROGRESSION),
        "timing_factor": 1,
    }
    # Identity
    out1 = apply_timing_factor(base)
    assert out1["bars"] == 8
    assert out1["timing_factor"] == 1.0
    assert len(out1["chord_progression"]) == 4

    # Half time: 2 bars/chord → 4
    out2 = apply_timing_factor({**base, "timing_factor": 2})
    assert out2["bars"] == 16
    assert len(out2["chord_progression"]) == 4
    assert out2["bars"] / 4 == 4  # bars-per-chord

    # Quarter time
    out4 = apply_timing_factor({**base, "timing_factor": 4})
    assert out4["bars"] == 32
    assert len(out4["chord_progression"]) == 4

    # Double time: 2 bars/chord → 1
    out_d = apply_timing_factor({**base, "timing_factor": 0.5})
    assert out_d["bars"] == 4
    assert len(out_d["chord_progression"]) == 4
    assert out_d["bars"] / 4 == 1.0


def test_timing_factor_double_floors_at_half_bar_per_chord():
    # 4 chords × 1 bar = 4 → Double → 0.5 bars/chord → 2 bars total
    out = apply_timing_factor({
        "bars": 4,
        "chord_progression": list(PROGRESSION),
        "timing_factor": 0.5,
    })
    assert out["bars"] == 2
    assert len(out["chord_progression"]) == 4
    assert out["bars"] / 4 == 0.5

    # Already at floor (2 bars / 4 chords = 0.5): Double must not go below
    floored = apply_timing_factor({
        "bars": 2,
        "chord_progression": list(PROGRESSION),
        "timing_factor": 0.5,
    })
    assert floored["bars"] == 2
    assert len(floored["chord_progression"]) == 4


def test_apply_timing_factor_does_not_mutate_caller():
    raw = {"bars": 8, "timing_factor": 2, "chord_progression": list(PROGRESSION)}
    out = apply_timing_factor(raw)
    assert raw["bars"] == 8
    assert out["bars"] == 16


def test_extend_factor_backward_compat_when_timing_unset():
    out = apply_extend_factor({"bars": 8, "extend_factor": 2})
    assert out["bars"] == 16
    assert out["extend_factor"] == 2
    assert out["timing_factor"] == 2.0

    out4 = apply_timing_factor({"bars": 8, "extend_factor": 4})
    assert out4["bars"] == 32

    # timing_factor wins over extend_factor
    prefer = apply_timing_factor({
        "bars": 8,
        "chord_progression": list(PROGRESSION),
        "timing_factor": 0.5,
        "extend_factor": 4,
    })
    assert prefer["bars"] == 4
    assert prefer["timing_factor"] == 0.5


def test_create_arp_timing_factor_half(tmp_path):
    from midi_gen import arpeggio_generation as ag

    captured = {}
    real = ag.generate_drone_events

    def spy(options, roots, rng=None):
        captured["bars"] = options.get("bars")
        captured["roots"] = list(roots)
        return real(options, roots, rng=rng)

    ag.generate_drone_events = spy  # type: ignore[assignment]
    try:
        create_arp({
            "generation_type": "drone",
            "mode": "major",
            "bars": 8,
            "timing_factor": 2,
            "chord_progression": PROGRESSION,
            "min_octave": 3,
            "max_octave": 5,
            "seed": 11,
            "filename": str(tmp_path / "timing_half.mid"),
            "effects_config": [],
        })
    finally:
        ag.generate_drone_events = real  # type: ignore[assignment]

    assert captured["bars"] == 16
    assert len(captured["roots"]) == 4


def test_create_arp_timing_factor_double(tmp_path):
    from midi_gen import arpeggio_generation as ag

    captured = {}
    real = ag.generate_drone_events

    def spy(options, roots, rng=None):
        captured["bars"] = options.get("bars")
        captured["roots"] = list(roots)
        return real(options, roots, rng=rng)

    ag.generate_drone_events = spy  # type: ignore[assignment]
    try:
        create_arp({
            "generation_type": "drone",
            "mode": "major",
            "bars": 8,
            "timing_factor": 0.5,
            "chord_progression": PROGRESSION,
            "min_octave": 3,
            "max_octave": 5,
            "seed": 11,
            "filename": str(tmp_path / "timing_double.mid"),
            "effects_config": [],
        })
    finally:
        ag.generate_drone_events = real  # type: ignore[assignment]

    assert captured["bars"] == 4
    assert len(captured["roots"]) == 4


def test_progression_override_sets_drone_held():
    opts = {
        "generation_type": "arpeggio",
        "chord_progression": list(PROGRESSION),
        "bars": 8,
    }
    out = apply_generation_mode(opts, "progression")
    assert out["generation_type"] == "drone"
    assert out["drone_held"] is True
    assert out["chord_progression"] == PROGRESSION
    assert opts["generation_type"] == "arpeggio"  # no mutate caller


def test_progression_override_wash_opt_out_wins():
    eno = get_profile_by_id("eno_ambient")
    assert eno is not None
    opts = eno.to_options()
    assert opts.get("drone_held") is False
    out = apply_generation_mode(opts, "progression")
    assert out["generation_type"] == "drone"
    assert out["drone_held"] is False
    # Fingerprint fields untouched
    assert out.get("chord_progression") == opts.get("chord_progression")
    assert out.get("development") == opts.get("development")


def test_pattern_override_sets_arpeggio():
    opts = {
        "generation_type": "drone",
        "drone_held": True,
        "chord_progression": list(PROGRESSION),
    }
    out = apply_generation_mode(opts, "pattern")
    assert out["generation_type"] == "arpeggio"
    assert out["drone_held"] is True  # left alone
    assert out["chord_progression"] == PROGRESSION


def test_generation_mode_none_is_noop():
    opts = {"generation_type": "drone", "drone_held": False, "bars": 8}
    out = apply_generation_mode(opts, None)
    assert out == opts or (
        out["generation_type"] == "drone"
        and out["drone_held"] is False
        and out["bars"] == 8
    )


def test_to_options_emits_timing_factor_when_set():
    profile = profile_from_dict(
        {
            "name": "Timing Sketch",
            "styles": ["drone"],
            "generation_type": "drone",
            "chord_progression": ["C3", "G2", "F3", "D3"],
            "drone_held": False,
            "timing_factor": 0.5,
            "development": {
                "enabled": True,
                "seed_bars": 2,
                "mutate_every_n": 2,
                "mutate_ops": ["add_attack"],
            },
        },
        source="cursor_sdk",
    )
    opts = profile.to_options()
    assert opts["timing_factor"] == 0.5
    assert opts["drone_held"] is False
