"""
Curated musician / style profiles that map to MIDI generation options.

This is the offline source of truth. Cursor SDK lookup can refine or invent
profiles, but every result is normalized against this schema.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Union
import re

from .scale import FULL_SCALE_INTERVALS
from .notes import note_str_to_midi


@dataclass(frozen=True)
class MusicianStyleProfile:
    """Generation recipe inspired by a musician or style family."""

    id: str
    name: str
    styles: List[str]
    description: str
    generation_type: str = "arpeggio"  # arpeggio | drone
    mode: str = "minor"
    bpm: int = 110
    bars: int = 8
    root_notes: List[str] = field(default_factory=lambda: ["E3", "A3", "D3", "G3"])
    min_octave: int = 3
    max_octave: int = 5
    use_chord_tones: bool = True
    # bool or dict {"enabled", "intervals", "accent_every"} — bool stays compatible
    mode_color: Any = True
    arp_mode: str = "up_down"
    arp_steps: int = 8
    range_octaves: int = 2
    evolution_rate: float = 0.15
    repetition_factor: int = 7
    repeat_pattern: bool = False
    # Wired arp features (optional; default off = backward compatible)
    embellish: bool = False
    rhythmic_variation: bool = False
    chord_progression: Optional[List[str]] = None  # note names or omitted
    # Pattern development arc (None = tile seed cell statically)
    development: Optional[Dict[str, Any]] = None
    effects_preset: str = "human_feel"
    # Drone knobs (ignored for arpeggio)
    drone_base_velocity: int = 72
    drone_variation_interval_bars: int = 2
    drone_min_notes_held: int = 2
    drone_octave_doubling_chance: float = 0.2
    drone_allow_octave_shifts: bool = True
    drone_enable_walkdowns: bool = True
    drone_walkdown_num_steps: int = 2
    drone_walkdown_step_ticks: int = 240
    source: str = "catalog"  # catalog | cursor_sdk | hybrid

    def to_options(self, effects_config: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Convert profile into options dict consumed by create_arp()."""
        opts: Dict[str, Any] = {
            "generation_type": self.generation_type,
            "root": 0,
            "root_notes": list(self.root_notes),
            "mode": self.mode,
            "min_octave": self.min_octave,
            "max_octave": self.max_octave,
            "bpm": self.bpm,
            "bars": self.bars,
            "filename": f"{self.id}.mid",
            "use_chord_tones": self.use_chord_tones,
            "mode_color": self.mode_color,
            "effects_config": effects_config or [],
            "arp_steps": self.arp_steps,
            "arp_mode": self.arp_mode,
            "range_octaves": self.range_octaves,
            "evolution_rate": self.evolution_rate,
            "repetition_factor": self.repetition_factor,
            "repeat_pattern": self.repeat_pattern,
            "embellish": self.embellish,
            "rhythmic_variation": self.rhythmic_variation,
            "drone_base_velocity": self.drone_base_velocity,
            "drone_variation_interval_bars": self.drone_variation_interval_bars,
            "drone_min_notes_held": self.drone_min_notes_held,
            "drone_octave_doubling_chance": self.drone_octave_doubling_chance,
            "drone_allow_octave_shifts": self.drone_allow_octave_shifts,
            "drone_enable_walkdowns": self.drone_enable_walkdowns,
            "drone_walkdown_num_steps": self.drone_walkdown_num_steps,
            "drone_walkdown_step_ticks": self.drone_walkdown_step_ticks,
            "musician_style_id": self.id,
            "musician_style_name": self.name,
            "musician_styles": list(self.styles),
            "effects_preset": self.effects_preset,
            "style_source": self.source,
        }
        if self.chord_progression:
            opts["chord_progression"] = list(self.chord_progression)
        if self.development:
            opts["development"] = dict(self.development)
        return opts

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Curated baseline profiles — stylistic sketches, not literal transcriptions.
MUSICIAN_STYLE_CATALOG: List[MusicianStyleProfile] = [
    MusicianStyleProfile(
        id="eno_ambient",
        name="Brian Eno",
        styles=[
            "ambient", "drone", "atmospheric", "minimal", "pad",
            "ambient pad", "ambient drone", "slow", "sparse", "space",
            "hypnotic", "wash", "texture",
        ],
        description="Slow-moving drones and soft chord beds. Sparse motion, long tones.",
        generation_type="drone",
        mode="lydian",
        bpm=72,
        bars=8,
        root_notes=["C3", "G2", "F3", "D3"],
        min_octave=2,
        max_octave=4,
        use_chord_tones=True,
        mode_color={"enabled": True, "accent_every": 2},
        effects_preset="subtle_tape",
        drone_variation_interval_bars=2,
        drone_min_notes_held=3,
        drone_octave_doubling_chance=0.35,
        drone_enable_walkdowns=False,
        # Slow sparse voicing drift (no phase). Drone path maps mutate_every_n
        # onto variation interval; not an arp cell tile. seed_bars=4 holds the
        # opening pad longer before sparse mutate (Composer lock).
        development={
            "enabled": True,
            "seed_bars": 4,
            "mutate_every_n": 4,
            "mutate_ops": ["add_attack", "add_rest"],
            "phase_creep": False,
            "additive_only": False,
        },
    ),
    MusicianStyleProfile(
        id="glass_minimal",
        name="Philip Glass",
        styles=[
            "minimalism", "minimal", "pattern", "arpeggio", "repetitive",
            "classical", "hypnotic", "additive", "ostinato", "cell",
            "repeating", "pulse",
        ],
        description="Tight repeating arpeggio cells; additive development over sticky Am–Am–Em–Am.",
        generation_type="arpeggio",
        mode="minor",
        bpm=108,
        bars=16,  # 4 bars per chord × Am/Am/Em/Am
        root_notes=["A3", "A3", "E3", "A3"],  # Am / Am / Em / Am
        min_octave=3,
        max_octave=5,
        arp_mode="up_down",
        arp_steps=8,
        range_octaves=1,
        evolution_rate=0.05,
        repetition_factor=9,
        embellish=False,
        rhythmic_variation=False,
        effects_preset="human_feel",
        # Additive-only: grow attacks only — cell is the event; no phase.
        development={
            "enabled": True,
            "seed_bars": 2,
            "mutate_every_n": 4,  # more hypnotic — hold the cell longer
            "mutate_ops": ["add_attack"],
            "additive_only": True,
            "phase_creep": False,
        },
    ),
    MusicianStyleProfile(
        id="reich_phase",
        name="Steve Reich",
        styles=[
            "minimalism", "minimal", "phase", "phasing", "phase music",
            "pulse", "pattern", "percussion", "hypnotic", "modal vamp",
            "16th", "process",
        ],
        description="Pulse-forward 16th-note cells; phase creep and odd-bar accent flips.",
        generation_type="arpeggio",
        mode="dorian",
        bpm=120,
        bars=8,
        root_notes=["D3", "A3", "G3", "D3"],
        min_octave=3,
        max_octave=5,
        arp_mode="up",
        arp_steps=16,
        range_octaves=1,
        evolution_rate=0.08,
        repetition_factor=8,
        embellish=False,
        rhythmic_variation=True,
        mode_color={"enabled": True, "accent_every": 4},
        chord_progression=["D3", "A3", "G3", "D3"],  # short modal vamp, voice-led
        effects_preset="clean",
        development={
            "enabled": True,
            "seed_bars": 1,
            "mutate_every_n": 2,  # breathe between mutations
            "mutate_ops": ["phase_creep", "add_rest", "add_attack", "thin"],
            "phase_creep": True,
            "max_phase": 2,
            "additive_only": False,
        },
    ),
    MusicianStyleProfile(
        id="debussy_color",
        name="Claude Debussy",
        styles=[
            "impressionist", "impressionism", "color", "modal", "piano",
            "wash", "impressionist wash", "soft", "watery", "whole tone",
            "lush", "pastel",
        ],
        description="Modal color and wider voicings; softer motion, full scale tones.",
        generation_type="arpeggio",
        mode="mixolydian",
        bpm=84,
        bars=8,
        root_notes=["Db3", "Ab3", "Gb3", "Eb3"],
        min_octave=3,
        max_octave=6,
        use_chord_tones=False,
        arp_mode="up_down",
        arp_steps=8,
        range_octaves=2,
        evolution_rate=0.2,
        repetition_factor=5,
        effects_preset="subtle_tape",
    ),
    MusicianStyleProfile(
        id="coltrane_sheets",
        name="John Coltrane",
        styles=[
            "jazz", "sheets of sound", "sheets", "modal jazz", "intense",
            "saxophone", "dense", "dense modal sheets", "modal vamp",
            "fiery", "rapid", "dorian",
        ],
        description="Dense modal density sketch — rapid cells colored with 6/9/11.",
        generation_type="arpeggio",
        mode="dorian",
        bpm=168,
        bars=8,
        # Stickier Dm–G–Dm–C vamp (vs circulating D–G–C–F).
        root_notes=["D3", "G3", "D3", "C3"],
        min_octave=3,
        max_octave=6,
        use_chord_tones=False,
        # Drop #4; emphasize 6 / 9 / 11 (intervals 9, 2, 5).
        mode_color={"enabled": True, "intervals": [9, 2, 5], "accent_every": 4},
        arp_mode="random",
        arp_steps=16,
        range_octaves=2,
        evolution_rate=0.35,
        repetition_factor=4,
        embellish=True,
        rhythmic_variation=True,
        chord_progression=["D3", "G3", "D3", "C3"],
        effects_preset="human_feel",
        development={
            "enabled": True,
            "seed_bars": 1,
            "mutate_every_n": 1,
            "mutate_ops": ["add_attack", "add_rest", "invert", "thin"],
            "phase_creep": False,
            "additive_only": False,
        },
    ),
    MusicianStyleProfile(
        id="monk_angles",
        name="Thelonious Monk",
        styles=[
            "jazz", "angular", "angular jazz", "piano", "spaced", "bebop",
            "quirky", "leaps", "crooked", "dissonant", "stride",
        ],
        description="Angular leaps, quirky order, and humanized touch.",
        generation_type="arpeggio",
        mode="major",
        bpm=112,
        bars=8,
        root_notes=["Bb3", "Eb3", "F3", "Bb3"],
        min_octave=3,
        max_octave=5,
        use_chord_tones=True,
        arp_mode="order",
        arp_steps=8,
        range_octaves=2,
        evolution_rate=0.25,
        repetition_factor=4,
        effects_preset="human_feel",
    ),
    MusicianStyleProfile(
        id="aphex_glitch",
        name="Aphex Twin",
        styles=[
            "electronic", "idm", "glitch", "glitchy idm", "unstable",
            "ambient techno", "worn tape", "wow", "flutter", "broken",
            "jitter", "acid",
        ],
        description="Faster cells with worn-tape pitch instability and velocity jitter.",
        generation_type="arpeggio",
        mode="phrygian",
        bpm=136,
        bars=8,
        root_notes=["E2", "B2", "A2", "E3"],
        min_octave=2,
        max_octave=5,
        use_chord_tones=False,
        arp_mode="random",
        arp_steps=16,
        range_octaves=2,
        evolution_rate=0.4,
        repetition_factor=3,
        effects_preset="worn_tape",
    ),
    MusicianStyleProfile(
        id="bach_sequence",
        name="J.S. Bach",
        styles=[
            "baroque", "sequence", "counterpoint", "classical", "arpeggio",
            "steady pulse", "directional", "voice leading", "fugue",
            "tonal", "motoric",
        ],
        description="Clear directional sequences, chord tones, steady pulse.",
        generation_type="arpeggio",
        mode="minor",
        bpm=96,
        bars=8,
        root_notes=["A3", "D3", "E3", "A3"],
        min_octave=3,
        max_octave=5,
        use_chord_tones=True,
        arp_mode="up_down",
        arp_steps=16,
        range_octaves=2,
        evolution_rate=0.02,
        repetition_factor=9,
        effects_preset="clean",
    ),
    MusicianStyleProfile(
        id="satie_neoclassical",
        name="Erik Satie",
        styles=[
            "ambient", "spare", "piano", "gentle", "neoclassical",
            "spare neoclassical", "gymnopedie", "gymnopédie", "sparse",
            "quiet", "slow piano", "soft",
        ],
        description="Sparse, slow, gently repeating figures with soft humanization.",
        generation_type="arpeggio",
        mode="major",
        bpm=66,
        bars=8,
        root_notes=["G3", "D3", "C3", "G3"],
        min_octave=3,
        max_octave=4,
        use_chord_tones=True,
        arp_mode="up",
        arp_steps=4,
        range_octaves=1,
        evolution_rate=0.05,
        repetition_factor=9,
        effects_preset="human_feel",
    ),
    MusicianStyleProfile(
        id="frahm_felt",
        name="Nils Frahm",
        styles=[
            "modern classical", "piano", "intimate", "ambient", "felt",
            "felt piano", "worn tape piano", "tape", "soft dynamics",
            "mid-tempo", "warm", "neo classical",
        ],
        description="Intimate mid-tempo arpeggios with tape warmth and soft dynamics.",
        generation_type="arpeggio",
        mode="dorian",
        bpm=92,
        bars=8,
        root_notes=["D3", "A3", "G3", "C4"],
        min_octave=3,
        max_octave=5,
        use_chord_tones=True,
        arp_mode="up_down",
        arp_steps=8,
        range_octaves=1,
        evolution_rate=0.12,
        repetition_factor=7,
        effects_preset="tape_and_human",
    ),
]

# Phrase / token aliases → one or more catalog profile ids.
# Multi-target aliases (e.g. minimalism → reich|glass) boost both; ranking
# still picks the best score, and siblings surface as related candidates.
STYLE_QUERY_ALIASES: Dict[str, tuple[str, ...]] = {
    "gymnopedie": ("satie_neoclassical",),
    "gymnopédie": ("satie_neoclassical",),
    "gymnopedies": ("satie_neoclassical",),
    "sheets of sound": ("coltrane_sheets",),
    "sheets": ("coltrane_sheets",),
    "phase music": ("reich_phase",),
    "phasing": ("reich_phase",),
    "phase": ("reich_phase",),
    "ambient pad": ("eno_ambient",),
    "ambient drone": ("eno_ambient",),
    "ambient": ("eno_ambient", "satie_neoclassical", "frahm_felt"),
    "minimalism": ("reich_phase", "glass_minimal"),
    "minimal pulse": ("reich_phase", "glass_minimal"),
    "minimal": ("glass_minimal", "reich_phase", "eno_ambient"),
    "angular jazz": ("monk_angles",),
    "angular": ("monk_angles",),
    "impressionist wash": ("debussy_color",),
    "impressionist": ("debussy_color",),
    "dense modal sheets": ("coltrane_sheets",),
    "glitchy idm": ("aphex_glitch",),
    "glitch": ("aphex_glitch",),
    "idm": ("aphex_glitch",),
    "worn tape piano": ("frahm_felt", "aphex_glitch"),
    "felt piano": ("frahm_felt",),
    "spare neoclassical": ("satie_neoclassical",),
    "baroque": ("bach_sequence",),
    "counterpoint": ("bach_sequence",),
    "additive cells": ("glass_minimal",),
    "additive": ("glass_minimal",),
    "phase pulse": ("reich_phase",),
    "clear sequence": ("bach_sequence",),
    "modal fire": ("coltrane_sheets",),
}


def list_styles() -> List[str]:
    """Unique style tags across the catalog, sorted."""
    tags = {tag.lower() for profile in MUSICIAN_STYLE_CATALOG for tag in profile.styles}
    return sorted(tags)


def list_musicians() -> List[MusicianStyleProfile]:
    return list(MUSICIAN_STYLE_CATALOG)


def get_profile_by_id(profile_id: str) -> Optional[MusicianStyleProfile]:
    needle = profile_id.strip().lower()
    # Historical typo alias
    if needle == "satt_neoclassical":
        needle = "satie_neoclassical"
    for profile in MUSICIAN_STYLE_CATALOG:
        if profile.id == needle:
            return profile
    return None


_PROFILE_ID_ALIASES = {
    "satt_neoclassical": "satie_neoclassical",
}


def _tokenize(text: str) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


def _normalize_query(query: str) -> str:
    """Lowercase, fold common diacritics used in vibe aliases."""
    q = (query or "").strip().lower()
    # Fold é → e so gymnopédie matches gymnopedie alias keys
    for src, dst in (("é", "e"), ("è", "e"), ("ê", "e"), ("ü", "u"), ("ö", "o")):
        q = q.replace(src, dst)
    return q


def alias_target_ids(query: str) -> List[str]:
    """
    Resolve STYLE_QUERY_ALIASES hits for a free-text query.

    Longer phrase keys win first; returns unique profile ids in alias order.
    """
    q = _normalize_query(query)
    if not q:
        return []
    # Also index folded alias keys (gymnopédie → gymnopedie)
    folded_aliases = {
        _normalize_query(k): v for k, v in STYLE_QUERY_ALIASES.items()
    }
    hits: List[str] = []
    seen: set[str] = set()
    # Longest phrase first so "sheets of sound" beats "sheets"
    for phrase in sorted(folded_aliases.keys(), key=len, reverse=True):
        if phrase == q or f" {phrase} " in f" {q} ":
            for pid in folded_aliases[phrase]:
                if pid not in seen:
                    hits.append(pid)
                    seen.add(pid)
    return hits


def score_profile(query: str, profile: MusicianStyleProfile) -> float:
    """Keyword + alias score for offline matching across the full catalog."""
    q = _normalize_query(query)
    tokens = set(_tokenize(q))
    if not tokens and not q:
        return 0.0

    haystack = set(_tokenize(profile.name)) | set(_tokenize(profile.id))
    for style in profile.styles:
        haystack |= set(_tokenize(style))
    haystack |= set(_tokenize(profile.description))

    overlap = tokens & haystack
    score = 0.0
    if overlap:
        score += float(len(overlap))

    # Exact name / id boosts
    name_tokens = set(_tokenize(profile.name))
    if name_tokens and name_tokens.issubset(tokens):
        score += 5.0
    if profile.id in q.replace(" ", "_"):
        score += 4.0

    # Multi-word style tag phrase hits (e.g. "felt piano", "modal vamp")
    style_hits = 0
    for style in profile.styles:
        style_norm = _normalize_query(style)
        style_toks = set(_tokenize(style_norm))
        if style_norm and (style_norm == q or f" {style_norm} " in f" {q} "):
            score += 3.0
            style_hits += 1
        elif style_toks and style_toks.issubset(tokens):
            score += 1.5
            style_hits += 1
        elif style_toks & tokens:
            score += 0.75
            style_hits += 1

    # Alias / synonym boost — free-text maps to the right catalog id(s)
    alias_ids = alias_target_ids(q)
    if profile.id in alias_ids:
        # Primary alias target gets a stronger bump; later siblings still boost
        rank = alias_ids.index(profile.id)
        score += 6.0 if rank == 0 else 3.5

    if score <= 0 and not overlap and profile.id not in alias_ids:
        return 0.0
    return score


def find_profiles(query: str, limit: int = 5) -> List[MusicianStyleProfile]:
    """Rank catalog profiles for a musician/style query (aliases + tags)."""
    ranked = sorted(
        ((score_profile(query, profile), profile) for profile in MUSICIAN_STYLE_CATALOG),
        key=lambda item: item[0],
        reverse=True,
    )
    return [profile for score, profile in ranked if score > 0][:limit]


def find_best_profile(query: str) -> Optional[MusicianStyleProfile]:
    matches = find_profiles(query, limit=1)
    return matches[0] if matches else None


def profile_from_dict(data: Dict[str, Any], source: str = "cursor_sdk") -> MusicianStyleProfile:
    """Normalize arbitrary dict (e.g. SDK JSON) into a valid profile."""
    base = MUSICIAN_STYLE_CATALOG[0].as_dict()
    # Prefer matching catalog musician when name is known
    name = str(data.get("name") or data.get("musician") or "").strip()
    if name:
        existing = find_best_profile(name)
        if existing and score_profile(name, existing) >= 5:
            base = existing.as_dict()

    allowed = set(base.keys())
    for key, value in data.items():
        if key in allowed and value is not None:
            base[key] = value

    base["source"] = source
    base["styles"] = [str(s).lower() for s in (base.get("styles") or [])]
    if not base.get("id"):
        slug = re.sub(r"[^a-z0-9]+", "_", str(base.get("name", "custom")).lower()).strip("_")
        base["id"] = slug or "custom_style"

    # Clamp / coerce critical fields
    base["generation_type"] = "drone" if str(base.get("generation_type")).lower() == "drone" else "arpeggio"
    mode = str(base.get("mode", "minor")).lower()
    if mode not in FULL_SCALE_INTERVALS:
        mode = "minor"
    base["mode"] = mode
    # Optional schema fields stay backward compatible
    raw_mode_color = base.get("mode_color", True)
    if isinstance(raw_mode_color, dict):
        normalized_mc: Dict[str, Any] = {
            "enabled": bool(raw_mode_color.get("enabled", True)),
        }
        if raw_mode_color.get("intervals") is not None:
            try:
                normalized_mc["intervals"] = [int(x) for x in raw_mode_color["intervals"]]
            except (TypeError, ValueError):
                pass
        if raw_mode_color.get("accent_every") is not None:
            try:
                normalized_mc["accent_every"] = max(2, int(raw_mode_color["accent_every"]))
            except (TypeError, ValueError):
                normalized_mc["accent_every"] = 4
        base["mode_color"] = normalized_mc
    else:
        base["mode_color"] = bool(raw_mode_color)

    base["embellish"] = bool(base.get("embellish", False))
    base["rhythmic_variation"] = bool(base.get("rhythmic_variation", False))

    raw_prog = base.get("chord_progression")
    if raw_prog is None:
        base["chord_progression"] = None
    elif isinstance(raw_prog, (list, tuple)):
        cleaned_prog = []
        for note in raw_prog:
            try:
                if isinstance(note, int):
                    from .notes import note_to_name
                    cleaned_prog.append(note_to_name(int(note)))
                else:
                    note_str_to_midi(str(note))
                    cleaned_prog.append(str(note))
            except (ValueError, IndexError, TypeError):
                continue
        base["chord_progression"] = cleaned_prog or None
    else:
        base["chord_progression"] = None

    raw_dev = base.get("development")
    if raw_dev is None or raw_dev is False:
        base["development"] = None
    elif raw_dev is True:
        base["development"] = {
            "enabled": True,
            "seed_bars": 1,
            "mutate_every_n": 1,
            "mutate_ops": ["add_attack", "add_rest", "invert", "thin", "phase_creep"],
            "phase_creep": True,
        }
    elif isinstance(raw_dev, dict):
        if raw_dev.get("enabled") is False:
            base["development"] = None
        else:
            ops = raw_dev.get("mutate_ops") or [
                "add_attack", "add_rest", "invert", "thin", "phase_creep"
            ]
            if isinstance(ops, str):
                ops = [ops]
            base["development"] = {
                "enabled": True,
                "seed_bars": max(1, min(4, int(raw_dev.get("seed_bars", 1)))),
                "mutate_every_n": max(1, int(raw_dev.get("mutate_every_n", 1))),
                "mutate_ops": [str(o).lower() for o in ops],
                "phase_creep": bool(raw_dev.get("phase_creep", False)),
                "additive_only": bool(raw_dev.get("additive_only", False)),
                "max_phase": int(raw_dev.get("max_phase", 2)),
            }
    else:
        base["development"] = None

    raw_id = str(base.get("id", "")).strip().lower()
    if raw_id in _PROFILE_ID_ALIASES:
        base["id"] = _PROFILE_ID_ALIASES[raw_id]
    base["bpm"] = int(max(40, min(240, int(base.get("bpm", 110)))))
    base["bars"] = int(max(1, min(64, int(base.get("bars", 8)))))
    base["arp_steps"] = int(base.get("arp_steps", 8))
    if base["arp_steps"] not in (4, 8, 16):
        base["arp_steps"] = 8
    base["evolution_rate"] = float(max(0.0, min(1.0, float(base.get("evolution_rate", 0.15)))))
    base["repetition_factor"] = int(max(1, min(10, int(base.get("repetition_factor", 7)))))
    if not isinstance(base.get("root_notes"), list) or not base["root_notes"]:
        base["root_notes"] = ["E3", "A3", "D3", "G3"]
    else:
        cleaned_roots = []
        for note in base["root_notes"]:
            try:
                note_str_to_midi(str(note))
                cleaned_roots.append(str(note))
            except (ValueError, IndexError, TypeError):
                continue
        base["root_notes"] = cleaned_roots or ["E3", "A3", "D3", "G3"]
    return MusicianStyleProfile(**base)


def merge_profile(
    base: MusicianStyleProfile,
    overrides: Optional[Dict[str, Any]] = None,
    source: Optional[str] = None,
) -> MusicianStyleProfile:
    data = base.as_dict()
    if overrides:
        data.update({k: v for k, v in overrides.items() if v is not None})
    if source:
        data["source"] = source
    return profile_from_dict(data, source=data.get("source", base.source))
