"""Interesting-returns A: deepen six catalog recipes into locked A PASS cluster.

A PASS bar (product-locked): generation_type, mode_color, development+progression,
density/vamp. Wrong knobs off unless the identity uses them
(embellish / RV / phase_creep / additive_only).
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[1]
if "midi_gen" not in sys.modules:
    _pkg = types.ModuleType("midi_gen")
    _pkg.__path__ = [str(_ROOT)]  # type: ignore[attr-defined]
    _pkg.__file__ = str(_ROOT / "__init__.py")
    sys.modules["midi_gen"] = _pkg

from midi_gen.musician_styles import MUSICIAN_STYLE_CATALOG, get_profile_by_id

LOCKED_IDS = ("eno_ambient", "glass_minimal", "reich_phase", "coltrane_sheets")
SPARSE_IDS = (
    "debussy_color",
    "monk_angles",
    "aphex_glitch",
    "bach_sequence",
    "satie_neoclassical",
    "frahm_felt",
)

# Identities that honestly use optional wrong-knob flags (locked + Aphex RV).
EMBELLISH_IDS = frozenset({"coltrane_sheets"})
RV_IDS = frozenset({"reich_phase", "coltrane_sheets", "aphex_glitch"})
PHASE_IDS = frozenset({"reich_phase"})
ADDITIVE_IDS = frozenset({"glass_minimal"})


def _mode_color_fingerprint(mode_color: Any) -> Tuple:
    if isinstance(mode_color, dict):
        intervals = mode_color.get("intervals")
        if intervals is not None:
            intervals = tuple(int(x) for x in intervals)
        return (
            "dict",
            bool(mode_color.get("enabled", True)),
            intervals,
            int(mode_color.get("accent_every", 4)),
        )
    return ("bool", bool(mode_color))


def _development_fingerprint(development: Optional[Dict[str, Any]]) -> Tuple:
    assert development is not None
    ops = tuple(development.get("mutate_ops") or ())
    return (
        int(development.get("seed_bars", 1)),
        int(development.get("mutate_every_n", 1)),
        ops,
        bool(development.get("phase_creep", False)),
        bool(development.get("additive_only", False)),
    )


def _recipe_fingerprint(profile) -> Tuple:
    """A PASS bound knobs (+ honest wrong-knob flags) for uniqueness."""
    prog = tuple(profile.chord_progression) if profile.chord_progression else None
    return (
        profile.generation_type,
        profile.mode,
        _mode_color_fingerprint(profile.mode_color),
        _development_fingerprint(profile.development),
        bool(profile.embellish),
        bool(profile.rhythmic_variation),
        prog,
        int(profile.arp_steps),
        float(profile.evolution_rate),
        int(profile.repetition_factor),
    )


def test_catalog_size_unchanged():
    assert len(MUSICIAN_STYLE_CATALOG) == 10
    ids = {p.id for p in MUSICIAN_STYLE_CATALOG}
    assert ids == set(LOCKED_IDS) | set(SPARSE_IDS)


def test_sparse_six_all_set_development_and_progression():
    for pid in SPARSE_IDS:
        profile = get_profile_by_id(pid)
        assert profile is not None, pid
        assert profile.development is not None, f"{pid} must set development"
        assert profile.development.get("enabled") is True
        assert profile.development.get("mutate_ops"), f"{pid} needs mutate_ops"
        assert profile.chord_progression, f"{pid} must set chord_progression / vamp"
        opts = profile.to_options()
        assert "development" in opts
        assert "chord_progression" in opts
        assert opts["development"]["mutate_ops"] == profile.development["mutate_ops"]


def test_wrong_knobs_off_unless_identity_uses_them():
    """embellish / RV / phase_creep / additive_only stay off when identity does not use them."""
    for profile in MUSICIAN_STYLE_CATALOG:
        if profile.id in EMBELLISH_IDS:
            assert profile.embellish is True, profile.id
        else:
            assert profile.embellish is False, f"{profile.id} must not turn on embellish"

        if profile.id in RV_IDS:
            assert profile.rhythmic_variation is True, profile.id
        else:
            assert profile.rhythmic_variation is False, f"{profile.id} must not turn on RV"

        assert profile.development is not None, profile.id
        if profile.id in PHASE_IDS:
            assert profile.development.get("phase_creep") is True, profile.id
        else:
            assert profile.development.get("phase_creep") is not True, profile.id

        if profile.id in ADDITIVE_IDS:
            assert profile.development.get("additive_only") is True, profile.id
        else:
            assert profile.development.get("additive_only") is not True, profile.id


def test_locked_four_development_unchanged():
    """Do not weaken Glass / Reich / Eno / Coltrane locks."""
    glass = get_profile_by_id("glass_minimal")
    assert glass.development == {
        "enabled": True,
        "seed_bars": 2,
        "mutate_every_n": 4,
        "mutate_ops": ["add_attack"],
        "additive_only": True,
        "phase_creep": False,
    }
    assert glass.embellish is False
    assert glass.rhythmic_variation is False
    assert glass.root_notes == ["A3", "A3", "E3", "A3"]

    reich = get_profile_by_id("reich_phase")
    assert reich.development["phase_creep"] is True
    assert reich.development["seed_bars"] == 1
    assert reich.development["mutate_every_n"] == 2
    assert reich.rhythmic_variation is True
    assert reich.chord_progression == ["D3", "A3", "G3", "D3"]

    eno = get_profile_by_id("eno_ambient")
    assert eno.generation_type == "drone"
    assert eno.development["seed_bars"] == 4
    assert eno.development["mutate_every_n"] == 4
    assert eno.development["phase_creep"] is False
    assert eno.development["mutate_ops"] == ["add_attack", "add_rest"]

    coltrane = get_profile_by_id("coltrane_sheets")
    assert coltrane.embellish is True
    assert coltrane.rhythmic_variation is True
    assert coltrane.chord_progression == ["D3", "G3", "D3", "C3"]
    assert coltrane.mode_color == {
        "enabled": True,
        "intervals": [9, 2, 5],
        "accent_every": 4,
    }
    assert coltrane.development == {
        "enabled": True,
        "seed_bars": 1,
        "mutate_every_n": 1,
        "mutate_ops": ["add_attack", "add_rest", "invert", "thin"],
        "phase_creep": False,
        "additive_only": False,
    }


def test_all_ten_recipe_fingerprints_unique():
    fps = {}
    for profile in MUSICIAN_STYLE_CATALOG:
        fp = _recipe_fingerprint(profile)
        key = json.dumps(fp, sort_keys=True, default=str)
        assert key not in fps, (
            f"fingerprint collision: {profile.id} vs {fps[key]} → {fp}"
        )
        fps[key] = profile.id
    assert len(fps) == 10


def test_sparse_six_a_pass_archetypes():
    """A PASS knobs: generation_type, mode_color, development+progression, density/vamp."""
    debussy = get_profile_by_id("debussy_color")
    assert debussy.generation_type == "arpeggio"
    assert debussy.mode == "lydian"
    assert isinstance(debussy.mode_color, dict)
    assert debussy.mode_color["intervals"] == [6, 2, 9]
    assert debussy.chord_progression == ["Db3", "Ab3", "Eb3", "Ab3"]
    assert debussy.development["mutate_ops"] == ["invert", "add_attack", "thin"]
    assert debussy.development["mutate_every_n"] >= 3
    assert debussy.embellish is False
    assert debussy.rhythmic_variation is False

    monk = get_profile_by_id("monk_angles")
    assert monk.arp_mode == "order"
    assert isinstance(monk.mode_color, dict)
    assert monk.mode_color["intervals"] == [1, 6]
    assert monk.chord_progression == ["Bb3", "Eb3", "F3", "Bb3"]
    assert "add_rest" in monk.development["mutate_ops"]
    assert monk.embellish is False
    assert monk.rhythmic_variation is False
    assert monk.effects_preset == "human_feel"

    aphex = get_profile_by_id("aphex_glitch")
    assert aphex.arp_steps == 16
    assert aphex.rhythmic_variation is True  # identity uses RV
    assert aphex.embellish is False
    assert aphex.effects_preset == "worn_tape"
    assert isinstance(aphex.mode_color, dict)
    assert aphex.mode_color["intervals"] == [1]
    assert aphex.development["mutate_every_n"] == 1
    assert aphex.chord_progression == ["E2", "B2", "A2", "E3"]

    bach = get_profile_by_id("bach_sequence")
    assert bach.use_chord_tones is True
    assert bach.effects_preset == "clean"
    assert bach.embellish is False
    assert bach.rhythmic_variation is False
    assert bach.development["mutate_ops"] == ["invert", "add_attack"]
    assert bach.chord_progression == ["A3", "D3", "E3", "A3"]
    assert bach.arp_steps == 16
    assert bach.repetition_factor >= 8

    satie = get_profile_by_id("satie_neoclassical")
    assert satie.mode == "major"
    assert satie.mode_color is True  # triad-clean guard
    assert satie.arp_steps == 4
    assert satie.development["seed_bars"] == 4
    assert satie.development["mutate_every_n"] == 4
    assert satie.development["mutate_ops"] == ["invert"]
    assert satie.chord_progression == ["G3", "D3", "C3", "G3"]
    assert satie.embellish is False
    assert satie.rhythmic_variation is False

    frahm = get_profile_by_id("frahm_felt")
    assert frahm.generation_type == "arpeggio"  # not Eno drone
    assert frahm.effects_preset == "tape_and_human"
    assert isinstance(frahm.mode_color, dict)
    assert frahm.mode_color["intervals"] == [2, 9]
    assert frahm.chord_progression == ["D3", "A3", "G3", "C4"]
    assert frahm.development["mutate_ops"] == ["add_attack", "invert"]
    assert frahm.development["mutate_every_n"] >= 3
    assert frahm.embellish is False
    assert frahm.rhythmic_variation is False


def test_sparse_six_not_fake_glass_or_eno():
    glass = get_profile_by_id("glass_minimal")
    reich = get_profile_by_id("reich_phase")
    coltrane = get_profile_by_id("coltrane_sheets")
    eno = get_profile_by_id("eno_ambient")

    for pid in SPARSE_IDS:
        p = get_profile_by_id(pid)
        assert p.development.get("additive_only") is not True, pid
        assert p.development.get("phase_creep") is not True, pid

    satie = get_profile_by_id("satie_neoclassical")
    assert satie.development["mutate_ops"] != glass.development["mutate_ops"]
    assert satie.arp_steps != glass.arp_steps

    frahm = get_profile_by_id("frahm_felt")
    assert frahm.generation_type != eno.generation_type

    bach = get_profile_by_id("bach_sequence")
    assert "phase_creep" not in bach.development["mutate_ops"]
    assert bach.development["mutate_ops"] != reich.development["mutate_ops"]

    aphex = get_profile_by_id("aphex_glitch")
    assert aphex.mode != coltrane.mode
    assert aphex.mode_color != coltrane.mode_color
    assert aphex.effects_preset != coltrane.effects_preset
    assert aphex.embellish is False  # not Coltrane sheets
