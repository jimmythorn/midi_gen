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


SECTION_ROLES = frozenset(
    {"bridge", "chorus", "verse", "intro", "outro", "pre-chorus"}
)
# pre-chorus / prechorus before chorus so "pre-chorus" does not match chorus.
_SECTION_CUE_RE = re.compile(
    r"\b(pre[-\s]?chorus|prechorus|bridge|chorus|verse|intro|outro)\b",
    re.IGNORECASE,
)


def _canonical_section_token(token: str) -> Optional[str]:
    """Map a matched cue token onto a SECTION_ROLES value."""
    text = str(token or "").strip().lower().replace("_", "-").replace(" ", "-")
    if text in ("prechorus", "pre-chorus"):
        return "pre-chorus"
    if text in SECTION_ROLES:
        return text
    return None


def normalize_section_role(raw: Optional[Any]) -> Optional[str]:
    """Clamp free-text / option values to known section roles."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        raw = raw.get("role")
    text = str(raw or "").strip().lower()
    if not text:
        return None
    exact = _canonical_section_token(text)
    if exact is not None:
        return exact
    match = _SECTION_CUE_RE.search(text)
    if not match:
        return None
    return _canonical_section_token(match.group(1))


def parse_section_role_from_text(text: Optional[str]) -> Optional[str]:
    """Light free-text cue parse — first known section token wins."""
    if not text:
        return None
    match = _SECTION_CUE_RE.search(str(text))
    if not match:
        return None
    return _canonical_section_token(match.group(1))


def progression_pitch_classes(prog: Optional[List[str]]) -> Optional[tuple]:
    """Root pitch-class tuple for bridge≠chorus checks."""
    if not prog:
        return None
    pcs = []
    for note in prog:
        try:
            pcs.append(note_str_to_midi(str(note)) % 12)
        except (ValueError, IndexError, TypeError):
            continue
    return tuple(pcs) if pcs else None


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
    # None = omit (create_arp defaults held when chord_progression set).
    # Wash/ambient pad recipes must set False so progression does not flip them held.
    drone_held: Optional[bool] = None
    # Optional Engine stretch (1–4); omit → create_arp default 1.
    extend_factor: Optional[int] = None
    # Active section after resolve (verse|chorus|bridge|intro|outro|pre-chorus);
    # None = top-level recipe.
    section_role: Optional[str] = None
    # Catalog fingerprints: [{role, chord_progression, mode?, bars?, generation_type?}, ...]
    sections: Optional[List[Dict[str, Any]]] = None
    source: str = "catalog"  # catalog | cursor_sdk | hybrid
    # Research notes from Cursor SDK (empty for catalog-only profiles)
    style_notes: str = ""
    # Listener-facing 1–2 sentences: why this sketch sounds like the musician.
    likeness_summary: str = ""

    def to_options(
        self,
        effects_config: Optional[List[Dict[str, Any]]] = None,
        *,
        section_role: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Convert profile into flat options dict consumed by create_arp()."""
        role = normalize_section_role(section_role)
        if role is None:
            role = normalize_section_role(self.section_role)
        if role:
            resolved = resolve_section_recipe(self, role)
            if resolved is not self:
                # Already flattened — do not re-enter with a role hint.
                return resolved.to_options(effects_config=effects_config, section_role=None)

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
        if self.drone_held is not None:
            opts["drone_held"] = bool(self.drone_held)
        if self.extend_factor is not None:
            try:
                opts["extend_factor"] = max(1, min(4, int(self.extend_factor)))
            except (TypeError, ValueError):
                opts["extend_factor"] = 1
        if self.chord_progression:
            opts["chord_progression"] = list(self.chord_progression)
        if self.development:
            opts["development"] = dict(self.development)
        if self.section_role:
            opts["section_role"] = self.section_role
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
        # Wash / ambient pad — keep voicing drift; do not flip to held when
        # FULL-contract or cousin paths attach a chord_progression.
        drone_held=False,
        # Sparse pad bed (not pop I–V–vi–IV); chorus default for section resolve.
        chord_progression=["C3", "G2", "F3", "D3"],
        sections=[
            {
                "role": "chorus",
                "chord_progression": ["C3", "G2", "F3", "D3"],
                "mode": "lydian",
                "bars": 8,
            },
            {
                # Sparse departure — still ambient drone, different roots.
                "role": "bridge",
                "chord_progression": ["F3", "C3", "Bb2", "F3"],
                "mode": "lydian",
                "bars": 8,
            },
            {
                # Soft pad open — shorter bed, not chorus wallpaper.
                "role": "intro",
                "chord_progression": ["C3", "G2", "C3", "G2"],
                "mode": "lydian",
                "bars": 4,
            },
            {
                # Fade settle — different roots from intro/chorus/bridge.
                "role": "outro",
                "chord_progression": ["D3", "F3", "G2", "C3"],
                "mode": "lydian",
                "bars": 8,
            },
            {
                # Lift into chorus wash — not a chorus clone.
                "role": "pre-chorus",
                "chord_progression": ["G2", "D3", "F3", "C3"],
                "mode": "lydian",
                "bars": 4,
            },
        ],
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
        # Sticky Am family — chorus identity; not Reich phase / Eno wash.
        chord_progression=["A3", "A3", "E3", "A3"],
        sections=[
            {
                "role": "chorus",
                "chord_progression": ["A3", "A3", "E3", "A3"],
                "mode": "minor",
                "bars": 16,
            },
            {
                "role": "verse",
                "chord_progression": ["A3", "E3", "A3", "E3"],
                "mode": "minor",
                "bars": 8,
            },
            {
                # Depart roots; stay additive minor cell family — not phase vamp.
                "role": "bridge",
                "chord_progression": ["C3", "G3", "F3", "C3"],
                "mode": "minor",
                "bars": 8,
            },
            {
                # Sparse cell open — shorter than verse/chorus.
                "role": "intro",
                "chord_progression": ["A3", "E3", "A3", "A3"],
                "mode": "minor",
                "bars": 4,
            },
            {
                # Resolve settle — not verse or chorus wallpaper.
                "role": "outro",
                "chord_progression": ["E3", "A3", "E3", "A3"],
                "mode": "minor",
                "bars": 8,
            },
            {
                # Lift toward sticky Am chorus — different roots + short bars.
                "role": "pre-chorus",
                "chord_progression": ["E3", "C3", "G3", "E3"],
                "mode": "minor",
                "bars": 4,
            },
        ],
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
        sections=[
            {
                "role": "chorus",
                "chord_progression": ["D3", "A3", "G3", "D3"],
                "mode": "dorian",
                "bars": 8,
            },
            {
                # Same modal-vamp habit; different roots from chorus.
                "role": "bridge",
                "chord_progression": ["E3", "B3", "A3", "E3"],
                "mode": "dorian",
                "bars": 8,
            },
            {
                "role": "intro",
                "chord_progression": ["D3", "A3", "D3", "A3"],
                "mode": "dorian",
                "bars": 4,
            },
            {
                "role": "outro",
                "chord_progression": ["A3", "G3", "D3", "A3"],
                "mode": "dorian",
                "bars": 8,
            },
            {
                "role": "pre-chorus",
                "chord_progression": ["G3", "D3", "A3", "G3"],
                "mode": "dorian",
                "bars": 4,
            },
        ],
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
        description="Lydian color wash: wide voicings, #4/9/6 accents, floating vamp, slow invert/thin evolve.",
        generation_type="arpeggio",
        mode="lydian",
        bpm=84,
        bars=8,
        root_notes=["Db3", "Ab3", "Gb3", "Eb3"],
        min_octave=3,
        max_octave=6,
        use_chord_tones=False,
        # Full-scale wash + explicit color paint (#4 / 9 / 6) — not a Glass triad cell.
        mode_color={"enabled": True, "intervals": [6, 2, 9], "accent_every": 2},
        arp_mode="up_down",
        arp_steps=8,
        range_octaves=2,
        evolution_rate=0.12,
        repetition_factor=5,
        embellish=False,  # color via mode_color, not Coltrane neighbor density
        rhythmic_variation=False,
        chord_progression=["Db3", "Ab3", "Eb3", "Ab3"],  # floating modal vamp
        sections=[
            {
                "role": "chorus",
                "chord_progression": ["Db3", "Ab3", "Eb3", "Ab3"],
                "mode": "lydian",
                "bars": 8,
            },
            {
                "role": "bridge",
                "chord_progression": ["Gb3", "Db3", "Ab3", "Eb3"],
                "mode": "lydian",
                "bars": 8,
            },
            {
                "role": "intro",
                "chord_progression": ["Db3", "Ab3", "Db3", "Ab3"],
                "mode": "lydian",
                "bars": 4,
            },
            {
                "role": "outro",
                "chord_progression": ["Ab3", "Eb3", "Db3", "Ab3"],
                "mode": "lydian",
                "bars": 8,
            },
            {
                "role": "pre-chorus",
                "chord_progression": ["Eb3", "Ab3", "Gb3", "Db3"],
                "mode": "lydian",
                "bars": 4,
            },
        ],
        effects_preset="subtle_tape",
        # Slow wash: hold seed, rare soft mutate — not additive cells, not phase.
        development={
            "enabled": True,
            "seed_bars": 2,
            "mutate_every_n": 3,
            "mutate_ops": ["invert", "add_attack", "thin"],
            "phase_creep": False,
            "additive_only": False,
        },
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
        sections=[
            {
                "role": "chorus",
                "chord_progression": ["D3", "G3", "D3", "C3"],
                "mode": "dorian",
                "bars": 8,
            },
            {
                # Borrow/color inside sheets family — not Glass additive cells.
                "role": "bridge",
                "chord_progression": ["D3", "Bb3", "A3", "C3"],
                "mode": "dorian",
                "bars": 8,
            },
            {
                "role": "intro",
                "chord_progression": ["D3", "G3", "D3", "G3"],
                "mode": "dorian",
                "bars": 4,
            },
            {
                "role": "outro",
                "chord_progression": ["C3", "D3", "G3", "D3"],
                "mode": "dorian",
                "bars": 8,
            },
            {
                "role": "pre-chorus",
                "chord_progression": ["G3", "C3", "D3", "A3"],
                "mode": "dorian",
                "bars": 4,
            },
        ],
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
        description="Angular order leaps, dissonant color accents, crooked rest/invert mutate.",
        generation_type="arpeggio",
        mode="major",
        bpm=112,
        bars=8,
        root_notes=["Bb3", "Eb3", "F3", "Bb3"],
        min_octave=3,
        max_octave=5,
        use_chord_tones=True,
        # Angular dissonance (b2 / #4) — not Coltrane 6/9/11 sheets.
        mode_color={"enabled": True, "intervals": [1, 6], "accent_every": 2},
        arp_mode="order",
        arp_steps=8,
        range_octaves=2,
        evolution_rate=0.25,
        repetition_factor=4,
        embellish=False,
        rhythmic_variation=False,  # rests from crooked development, not RV
        chord_progression=["Bb3", "Eb3", "F3", "Bb3"],
        sections=[
            {
                "role": "chorus",
                "chord_progression": ["Bb3", "Eb3", "F3", "Bb3"],
                "mode": "major",
                "bars": 8,
            },
            {
                "role": "bridge",
                "chord_progression": ["Eb3", "Ab3", "Bb3", "F3"],
                "mode": "major",
                "bars": 8,
            },
            {
                "role": "intro",
                "chord_progression": ["Bb3", "F3", "Bb3", "F3"],
                "mode": "major",
                "bars": 4,
            },
            {
                "role": "outro",
                "chord_progression": ["F3", "Bb3", "Eb3", "Bb3"],
                "mode": "major",
                "bars": 8,
            },
            {
                "role": "pre-chorus",
                "chord_progression": ["Eb3", "F3", "Bb3", "Ab3"],
                "mode": "major",
                "bars": 4,
            },
        ],
        effects_preset="human_feel",
        # Crooked: rests and contour flips — not phase creep.
        development={
            "enabled": True,
            "seed_bars": 1,
            "mutate_every_n": 2,
            "mutate_ops": ["add_rest", "invert", "thin", "add_attack"],
            "phase_creep": False,
            "additive_only": False,
        },
    ),
    MusicianStyleProfile(
        id="aphex_glitch",
        name="Aphex Twin",
        styles=[
            "electronic", "idm", "glitch", "glitchy idm", "unstable",
            "ambient techno", "worn tape", "wow", "flutter", "broken",
            "jitter", "acid",
        ],
        description="Unstable 16ths, phrygian b2 accents, RV rests, worn-tape jitter mutate.",
        generation_type="arpeggio",
        mode="phrygian",
        bpm=136,
        bars=8,
        root_notes=["E2", "B2", "A2", "E3"],
        min_octave=2,
        max_octave=5,
        use_chord_tones=False,
        mode_color={"enabled": True, "intervals": [1], "accent_every": 2},  # b2 bite
        arp_mode="random",
        arp_steps=16,
        range_octaves=2,
        evolution_rate=0.4,
        repetition_factor=3,
        embellish=False,  # instability via RV + mutate, not neighbor embellish
        rhythmic_variation=True,  # Aphex identity: unstable rhythm cells
        chord_progression=["E2", "B2", "A2", "E3"],
        sections=[
            {
                "role": "chorus",
                "chord_progression": ["E2", "B2", "A2", "E3"],
                "mode": "phrygian",
                "bars": 8,
            },
            {
                "role": "bridge",
                "chord_progression": ["A2", "E3", "F2", "B2"],
                "mode": "phrygian",
                "bars": 8,
            },
            {
                "role": "intro",
                "chord_progression": ["E2", "B2", "E2", "B2"],
                "mode": "phrygian",
                "bars": 4,
            },
            {
                "role": "outro",
                "chord_progression": ["B2", "A2", "E3", "B2"],
                "mode": "phrygian",
                "bars": 8,
            },
            {
                "role": "pre-chorus",
                "chord_progression": ["B2", "A2", "F2", "E2"],
                "mode": "phrygian",
                "bars": 4,
            },
        ],
        effects_preset="worn_tape",
        # Jittery every-bar mutate — not a clean sequence, not Reich phase.
        development={
            "enabled": True,
            "seed_bars": 1,
            "mutate_every_n": 1,
            "mutate_ops": ["add_rest", "add_attack", "thin", "invert"],
            "phase_creep": False,
            "additive_only": False,
        },
    ),
    MusicianStyleProfile(
        id="bach_sequence",
        name="J.S. Bach",
        styles=[
            "baroque", "sequence", "counterpoint", "classical", "arpeggio",
            "steady pulse", "directional", "voice leading", "fugue",
            "tonal", "motoric",
        ],
        description="Directional 16th sequences on chord tones; invert/add_attack sequence arc, clean.",
        generation_type="arpeggio",
        mode="minor",
        bpm=96,
        bars=8,
        root_notes=["A3", "D3", "E3", "A3"],
        min_octave=3,
        max_octave=5,
        use_chord_tones=True,
        mode_color=True,  # minor triad = identity
        arp_mode="up_down",
        arp_steps=16,
        range_octaves=2,
        evolution_rate=0.02,
        repetition_factor=9,
        embellish=False,
        rhythmic_variation=False,
        chord_progression=["A3", "D3", "E3", "A3"],  # i–iv–V–i
        sections=[
            {
                "role": "chorus",
                "chord_progression": ["A3", "D3", "E3", "A3"],
                "mode": "minor",
                "bars": 8,
            },
            {
                "role": "bridge",
                "chord_progression": ["D3", "G3", "A3", "E3"],
                "mode": "minor",
                "bars": 8,
            },
            {
                "role": "intro",
                "chord_progression": ["A3", "E3", "A3", "E3"],
                "mode": "minor",
                "bars": 4,
            },
            {
                "role": "outro",
                "chord_progression": ["E3", "A3", "D3", "A3"],
                "mode": "minor",
                "bars": 8,
            },
            {
                "role": "pre-chorus",
                "chord_progression": ["D3", "E3", "A3", "G3"],
                "mode": "minor",
                "bars": 4,
            },
        ],
        effects_preset="clean",
        # Sequence-like: contour invert + densify — no phase_creep, no Glass additive_only.
        development={
            "enabled": True,
            "seed_bars": 1,
            "mutate_every_n": 2,
            "mutate_ops": ["invert", "add_attack"],
            "phase_creep": False,
            "additive_only": False,
        },
    ),
    MusicianStyleProfile(
        id="satie_neoclassical",
        name="Erik Satie",
        styles=[
            "ambient", "spare", "piano", "gentle", "neoclassical",
            "spare neoclassical", "gymnopedie", "gymnopédie", "sparse",
            "quiet", "slow piano", "soft",
        ],
        description="Sparse 4-step piano figures; long seed, rare invert — almost static.",
        generation_type="arpeggio",
        mode="major",
        bpm=66,
        bars=8,
        root_notes=["G3", "D3", "C3", "G3"],
        min_octave=3,
        max_octave=4,
        use_chord_tones=True,
        mode_color=True,  # major triad lock (must stay bool True for triad-clean guard)
        arp_mode="up",
        arp_steps=4,
        range_octaves=1,
        evolution_rate=0.05,
        repetition_factor=9,
        embellish=False,
        rhythmic_variation=False,
        chord_progression=["G3", "D3", "C3", "G3"],
        sections=[
            {
                "role": "chorus",
                "chord_progression": ["G3", "D3", "C3", "G3"],
                "mode": "major",
                "bars": 8,
            },
            {
                "role": "bridge",
                "chord_progression": ["C3", "G3", "A3", "E3"],
                "mode": "major",
                "bars": 8,
            },
            {
                "role": "intro",
                "chord_progression": ["G3", "D3", "G3", "D3"],
                "mode": "major",
                "bars": 4,
            },
            {
                "role": "outro",
                "chord_progression": ["D3", "C3", "G3", "D3"],
                "mode": "major",
                "bars": 8,
            },
            {
                "role": "pre-chorus",
                "chord_progression": ["C3", "D3", "G3", "A3"],
                "mode": "major",
                "bars": 4,
            },
        ],
        effects_preset="human_feel",
        # Almost-static: long seed, rare mutate — not Glass additive cells.
        development={
            "enabled": True,
            "seed_bars": 4,
            "mutate_every_n": 4,
            "mutate_ops": ["invert"],
            "phase_creep": False,
            "additive_only": False,
        },
    ),
    MusicianStyleProfile(
        id="frahm_felt",
        name="Nils Frahm",
        styles=[
            "modern classical", "piano", "intimate", "ambient", "felt",
            "felt piano", "worn tape piano", "tape", "soft dynamics",
            "mid-tempo", "warm", "neo classical",
        ],
        description="Intimate mid-tempo felt-piano arp; soft dorian 6/9 color, gentle evolve — not a drone.",
        generation_type="arpeggio",
        mode="dorian",
        bpm=92,
        bars=8,
        root_notes=["D3", "A3", "G3", "C4"],
        min_octave=3,
        max_octave=5,
        use_chord_tones=True,
        mode_color={"enabled": True, "intervals": [2, 9], "accent_every": 4},
        arp_mode="up_down",
        arp_steps=8,
        range_octaves=1,
        evolution_rate=0.12,
        repetition_factor=7,
        embellish=False,
        rhythmic_variation=False,
        chord_progression=["D3", "A3", "G3", "C4"],
        sections=[
            {
                "role": "chorus",
                "chord_progression": ["D3", "A3", "G3", "C4"],
                "mode": "dorian",
                "bars": 8,
            },
            {
                "role": "bridge",
                "chord_progression": ["G3", "D3", "C4", "A3"],
                "mode": "dorian",
                "bars": 8,
            },
            {
                "role": "intro",
                "chord_progression": ["D3", "A3", "D3", "A3"],
                "mode": "dorian",
                "bars": 4,
            },
            {
                "role": "outro",
                "chord_progression": ["A3", "G3", "D3", "C4"],
                "mode": "dorian",
                "bars": 8,
            },
            {
                "role": "pre-chorus",
                "chord_progression": ["A3", "G3", "C4", "D3"],
                "mode": "dorian",
                "bars": 4,
            },
        ],
        effects_preset="tape_and_human",
        # Gentle evolve — keep arpeggio (not Eno drone); not Coltrane sheets.
        development={
            "enabled": True,
            "seed_bars": 2,
            "mutate_every_n": 3,
            "mutate_ops": ["add_attack", "invert"],
            "phase_creep": False,
            "additive_only": False,
        },
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


# Honest sparse blank — NEVER MUSICIAN_STYLE_CATALOG[0] (eno_ambient).
# Wallpaper leak: custom_query / SDK normalize used to overlay onto Eno.
NEUTRAL_SPARSE_DEFAULTS: Dict[str, Any] = {
    "id": "sparse_unknown",
    "name": "Unknown",
    "styles": [],
    "description": "Honest sparse unknown — not a catalog identity.",
    "generation_type": "arpeggio",
    "mode": "minor",
    "bpm": 100,
    "bars": 8,
    "root_notes": ["E3", "A3", "D3", "G3"],
    "min_octave": 3,
    "max_octave": 5,
    "use_chord_tones": True,
    "mode_color": True,  # triad-clean — not Eno accent dict, not Glass additive
    "arp_mode": "up_down",
    "arp_steps": 8,
    "range_octaves": 2,
    "evolution_rate": 0.1,
    "repetition_factor": 6,
    "repeat_pattern": False,
    "embellish": False,
    "rhythmic_variation": False,
    "chord_progression": ["E3", "B2", "A3", "E3"],
    "development": {
        "enabled": True,
        "seed_bars": 2,
        "mutate_every_n": 2,
        "mutate_ops": ["invert", "thin"],
        "phase_creep": False,
        "additive_only": False,
        "max_phase": 2,
    },
    "effects_preset": "human_feel",
    "drone_base_velocity": 72,
    "drone_variation_interval_bars": 2,
    "drone_min_notes_held": 2,
    "drone_octave_doubling_chance": 0.2,
    "drone_allow_octave_shifts": True,
    "drone_enable_walkdowns": True,
    "drone_walkdown_num_steps": 2,
    "drone_walkdown_step_ticks": 240,
    "drone_held": None,
    "extend_factor": None,
    "section_role": None,
    "sections": None,
    "source": "sparse",
    "style_notes": "",
    "likeness_summary": "",
}

# Structural contract for cousin few-shot (create_arp already binds these).
# Soft steers (bpm / density / effects) may bend in-band; these must not be
# effects-only overlays onto a blank catalog fallback.
FULL_RECIPE_CONTRACT_KEYS: tuple[str, ...] = (
    "generation_type",
    "mode",
    "mode_color",
    "development",
    "chord_progression",
    "embellish",
    "rhythmic_variation",
    "arp_mode",
    "arp_steps",
    "range_octaves",
    "evolution_rate",
    "repetition_factor",
    "use_chord_tones",
    "root_notes",
    "min_octave",
    "max_octave",
)

# Soft-steer band keys — Composer may bend these inside a cousin style band.
SOFT_STEER_KEYS: tuple[str, ...] = (
    "bpm",
    "arp_steps",
    "evolution_rate",
    "repetition_factor",
    "effects_preset",
)

# Minimum score_profile hit to treat a catalog neighbor as a real cousin.
COUSIN_SCORE_FLOOR = 2.0


def _clean_progression_notes(raw: Any) -> Optional[List[str]]:
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        return None
    cleaned: List[str] = []
    for note in raw:
        try:
            if isinstance(note, int):
                from .notes import note_to_name
                cleaned.append(note_to_name(int(note)))
            else:
                note_str_to_midi(str(note))
                cleaned.append(str(note))
        except (ValueError, IndexError, TypeError):
            continue
    return cleaned or None


def _normalize_section_entry(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    role = normalize_section_role(raw.get("role"))
    prog = _clean_progression_notes(raw.get("chord_progression"))
    if not role or not prog:
        return None
    entry: Dict[str, Any] = {
        "role": role,
        "chord_progression": prog,
    }
    mode = str(raw.get("mode") or "").strip().lower()
    if mode in FULL_SCALE_INTERVALS:
        entry["mode"] = mode
    if raw.get("bars") is not None:
        try:
            entry["bars"] = int(max(1, min(64, int(raw["bars"]))))
        except (TypeError, ValueError):
            pass
    gen = str(raw.get("generation_type") or "").strip().lower()
    if gen in ("arpeggio", "drone"):
        entry["generation_type"] = gen
    return entry


def _normalize_sections(raw: Any) -> Optional[List[Dict[str, Any]]]:
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        return None
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        entry = _normalize_section_entry(item)
        if entry is None or entry["role"] in seen:
            continue
        seen.add(entry["role"])
        out.append(entry)
    return out or None


def find_section_entry(
    profile: MusicianStyleProfile,
    section_role: Optional[str],
) -> Optional[Dict[str, Any]]:
    role = normalize_section_role(section_role)
    if not role or not profile.sections:
        return None
    for entry in profile.sections:
        if normalize_section_role(entry.get("role")) == role:
            return entry
    return None


def resolve_section_recipe(
    profile: MusicianStyleProfile,
    section_role: Optional[str] = None,
) -> MusicianStyleProfile:
    """
    who + section → flat recipe (progression / mode / bars) for Engine options.

    If ``profile.sections`` has the role, use that fingerprint. Else keep
    top-level ``chord_progression`` / mode / bars and stamp ``section_role``.
    """
    role = normalize_section_role(section_role)
    if role is None:
        role = normalize_section_role(profile.section_role)
    if role is None:
        return profile

    entry = find_section_entry(profile, role)
    if entry is None:
        if profile.section_role == role:
            return profile
        data = profile.as_dict()
        data["section_role"] = role
        return profile_from_dict(data, source=profile.source)

    want_prog = list(entry["chord_progression"])
    want_mode = entry.get("mode")
    want_bars = entry.get("bars")
    want_gen = entry.get("generation_type")
    already = (
        profile.section_role == role
        and profile.chord_progression == want_prog
        and (want_mode is None or profile.mode == want_mode)
        and (want_bars is None or profile.bars == int(want_bars))
        and (want_gen is None or profile.generation_type == want_gen)
    )
    if already:
        return profile

    data = profile.as_dict()
    data["section_role"] = role
    data["chord_progression"] = want_prog
    # Keep segment roots aligned with the resolved progression.
    data["root_notes"] = list(want_prog)
    if want_mode is not None:
        data["mode"] = want_mode
    if want_bars is not None:
        data["bars"] = int(want_bars)
    if want_gen is not None:
        data["generation_type"] = want_gen
    # Preserve wash opt-out (Eno) and other profile-level Engine knobs.
    return profile_from_dict(data, source=profile.source)


def find_progression_bearing_neighbors(
    query: str,
    *,
    limit: int = 3,
    exclude_ids: Optional[set] = None,
) -> List[MusicianStyleProfile]:
    """
    Few-shot neighbors that carry real chord_progression / sections.

    Prefers same harmonic habit over BPM-only hits. Never invents wallpaper.
    """
    if limit <= 0:
        return []
    exclude = {str(x) for x in (exclude_ids or set())}
    ranked = find_profiles(query, limit=max(limit * 4, 8))
    # Fall back to full-catalog score order when local hits are thin.
    if len(ranked) < limit * 2:
        scored = sorted(
            MUSICIAN_STYLE_CATALOG,
            key=lambda p: score_profile(query, p),
            reverse=True,
        )
        seen_ids = {p.id for p in ranked}
        for profile in scored:
            if profile.id in seen_ids:
                continue
            ranked.append(profile)
            seen_ids.add(profile.id)

    out: List[MusicianStyleProfile] = []
    for profile in ranked:
        if profile.id in exclude:
            continue
        has_prog = bool(profile.chord_progression)
        has_sections = bool(
            profile.sections
            and any(s.get("chord_progression") for s in profile.sections)
        )
        if not (has_prog or has_sections):
            continue
        out.append(profile)
        if len(out) >= limit:
            break
    return out


def recipe_structure_fingerprint(profile: MusicianStyleProfile) -> tuple:
    """Fingerprint of bound knobs (not effects-only). Used to reject wallpaper."""
    prog = tuple(profile.chord_progression) if profile.chord_progression else None
    dev = profile.development
    if isinstance(dev, dict):
        dev_fp = (
            int(dev.get("seed_bars", 1)),
            int(dev.get("mutate_every_n", 1)),
            tuple(dev.get("mutate_ops") or ()),
            bool(dev.get("phase_creep", False)),
            bool(dev.get("additive_only", False)),
        )
    else:
        dev_fp = None
    mc = profile.mode_color
    if isinstance(mc, dict):
        intervals = mc.get("intervals")
        mc_fp = (
            "dict",
            bool(mc.get("enabled", True)),
            tuple(int(x) for x in intervals) if intervals is not None else None,
            int(mc.get("accent_every", 4)),
        )
    else:
        mc_fp = ("bool", bool(mc))
    return (
        profile.generation_type,
        profile.mode,
        mc_fp,
        dev_fp,
        bool(profile.embellish),
        bool(profile.rhythmic_variation),
        prog,
        int(profile.arp_steps),
        float(profile.evolution_rate),
        int(profile.repetition_factor),
    )


def is_effects_only_overlay(
    profile: MusicianStyleProfile,
    reference: MusicianStyleProfile,
) -> bool:
    """True when only soft-steer fields differ — reject as incomplete few-shot."""
    return recipe_structure_fingerprint(profile) == recipe_structure_fingerprint(reference)


def has_full_recipe_contract(profile: MusicianStyleProfile) -> bool:
    """FULL contract: development + progression present and enabled."""
    if not profile.chord_progression:
        return False
    dev = profile.development
    if not isinstance(dev, dict):
        return False
    if dev.get("enabled") is False:
        return False
    if not dev.get("mutate_ops"):
        return False
    return True


def sparse_unknown_profile(
    query: str,
    *,
    styles: Optional[List[str]] = None,
    style_notes: str = "",
) -> MusicianStyleProfile:
    """Honest sparse unknown — never CATALOG[0] / eno_ambient / glass_minimal."""
    q = (query or "").strip() or "Unknown"
    tokens = [t for t in re.split(r"[^a-z0-9]+", q.lower()) if t][:6]
    data = dict(NEUTRAL_SPARSE_DEFAULTS)
    data["id"] = "custom_query"
    data["name"] = q
    data["styles"] = [s.lower() for s in (styles or tokens or ["sparse"])]
    data["description"] = (
        f"Honest sparse unknown for {q!r} — no catalog identity fallback."
    )
    data["style_notes"] = (style_notes or "").strip()[:800]
    data["source"] = "sparse"
    # Ambient/drone query token may soft-pick drone generation_type only —
    # still not Eno's development / mode_color fingerprint.
    joined = " ".join(data["styles"])
    if "drone" in joined or "ambient" in joined:
        data["generation_type"] = "drone"
        # Sparse ambient/drone is wash-intent, not held progression.
        data["drone_held"] = False
    return profile_from_dict(data, source="sparse")


def cousin_recipe_from_neighbors(
    query: str,
    neighbors: List[MusicianStyleProfile],
    *,
    styles: Optional[List[str]] = None,
    style_notes: str = "",
    followers_total: Optional[int] = None,
) -> Optional[MusicianStyleProfile]:
    """
    Few-shot FULL contract from 2–3 nearest local catalog recipes.

    Primary cousin supplies generation_type / mode_color / development /
    progression / embellish / RV / density. Soft steers (bpm / effects /
    density) may bend from secondary cousins in-band. Effects-only overlay
    is rejected (returns None → caller uses sparse unknown).
    """
    if not neighbors:
        return None
    primary = neighbors[0]
    data = primary.as_dict()

    # Guarantee development + progression from the neighbor set (FULL contract).
    if not data.get("development"):
        for other in neighbors[1:]:
            if other.development:
                data["development"] = dict(other.development)
                break
    if not data.get("chord_progression"):
        for other in neighbors[1:]:
            if other.chord_progression:
                data["chord_progression"] = list(other.chord_progression)
                break

    # Soft steers from secondary cousins (in-band bends only).
    if len(neighbors) > 1:
        bpms = [n.bpm for n in neighbors[:3]]
        data["bpm"] = int(round(sum(bpms) / len(bpms)))
        # Prefer a non-primary effects preset only when second cousin differs.
        if neighbors[1].effects_preset and neighbors[1].effects_preset != primary.effects_preset:
            # Keep primary effects unless follower mass suggests tape warmth.
            if followers_total is not None and followers_total >= 100_000:
                data["effects_preset"] = neighbors[1].effects_preset

    q = (query or "").strip() or primary.name
    tokens = [t for t in re.split(r"[^a-z0-9]+", q.lower()) if t][:6]
    data["id"] = "custom_query"
    data["name"] = q
    data["styles"] = [s.lower() for s in (styles or tokens or list(primary.styles[:4]))]
    cousin_names = ", ".join(n.name for n in neighbors[:3])
    data["description"] = (
        f"Cousin fingerprint from local recipes ({cousin_names}) for {q!r}."
    )
    notes = (style_notes or "").strip()
    if followers_total is not None:
        notes = (notes + f" followers.total={followers_total}").strip()
    data["style_notes"] = notes[:800]
    data["source"] = "cousin"

    profile = profile_from_dict(data, source="cousin")
    if not has_full_recipe_contract(profile):
        return None
    # Reject effects-only relative to neutral sparse (incomplete few-shot).
    neutral = profile_from_dict(dict(NEUTRAL_SPARSE_DEFAULTS), source="sparse")
    if is_effects_only_overlay(profile, neutral):
        return None
    return profile


def profile_from_dict(data: Dict[str, Any], source: str = "cursor_sdk") -> MusicianStyleProfile:
    """Normalize arbitrary dict (e.g. SDK JSON) into a valid profile."""
    # Neutral sparse blank — never CATALOG[0] (eno_ambient wallpaper).
    base = dict(NEUTRAL_SPARSE_DEFAULTS)
    incoming = dict(data or {})

    # Nested section block → flat role + progression/mode/bars (SDK convenience).
    raw_section = incoming.pop("section", None)
    if isinstance(raw_section, dict):
        role = normalize_section_role(raw_section.get("role"))
        if role:
            incoming["section_role"] = role
        sec_prog = _clean_progression_notes(raw_section.get("chord_progression"))
        if sec_prog:
            incoming["chord_progression"] = sec_prog
        mode = str(raw_section.get("mode") or "").strip().lower()
        if mode in FULL_SCALE_INTERVALS:
            incoming["mode"] = mode
        if raw_section.get("bars") is not None:
            incoming["bars"] = raw_section["bars"]
        gen = str(raw_section.get("generation_type") or "").strip().lower()
        if gen in ("arpeggio", "drone"):
            incoming["generation_type"] = gen

    # Prefer matching catalog musician when name is known
    name = str(incoming.get("name") or incoming.get("musician") or "").strip()
    if name:
        existing = find_best_profile(name)
        if existing and score_profile(name, existing) >= 5:
            base = existing.as_dict()

    allowed = set(base.keys())
    for key, value in incoming.items():
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
    if base.get("drone_held") is None:
        base["drone_held"] = None
    else:
        base["drone_held"] = bool(base.get("drone_held"))

    if base.get("extend_factor") is None:
        base["extend_factor"] = None
    else:
        try:
            base["extend_factor"] = max(1, min(4, int(base.get("extend_factor"))))
        except (TypeError, ValueError):
            base["extend_factor"] = None

    base["section_role"] = normalize_section_role(base.get("section_role"))
    # Prefer explicit sections from incoming; keep catalog sections when name-matched
    # and incoming omitted them or sent null (do not wipe identity fingerprints).
    if incoming.get("sections") is not None:
        base["sections"] = _normalize_sections(incoming.get("sections"))
    else:
        base["sections"] = _normalize_sections(base.get("sections"))

    raw_prog = base.get("chord_progression")
    if raw_prog is None:
        base["chord_progression"] = None
    elif isinstance(raw_prog, (list, tuple)):
        base["chord_progression"] = _clean_progression_notes(raw_prog)
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
    base["style_notes"] = str(base.get("style_notes") or "").strip()[:800]
    base["likeness_summary"] = str(base.get("likeness_summary") or "").strip()[:400]
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
