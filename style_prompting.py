"""
Thin helpers for stylistic prompting UI.

Keeps named catalog (who) plus optional free-text vibe (feel) as layers.
Feel is additive — it does not replace the selected artist.
Featured cards + vibe chips are entry points across the full catalog — not a
closed allow-list, and not limited to any fixed shortlist of musicians.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .arpeggio_generation import resolve_extend_factor
from .effects_presets import get_preset, list_presets
from .musician_styles import (
    MUSICIAN_STYLE_CATALOG,
    MusicianStyleProfile,
    SECTION_ROLES,
    find_profiles,
    get_profile_by_id,
    normalize_section_role,
    resolve_section_recipe,
)

# Home section chips — default off (None) = full sketch as today.
SECTION_CHIP_ROLES: tuple[str, ...] = (
    "verse",
    "chorus",
    "bridge",
    "intro",
    "outro",
    "pre-chorus",
)
SECTION_CHIP_LABELS: tuple[tuple[str, str], ...] = (
    ("verse", "Verse"),
    ("chorus", "Chorus"),
    ("bridge", "Bridge"),
    ("intro", "Intro"),
    ("outro", "Outro"),
    ("pre-chorus", "Pre-chorus"),
)
# Extend stretch factors shown next to Half/Double (1 = off).
EXTEND_CHIP_FACTORS: tuple[int, ...] = (2, 4)


# Curated subset spanning the FULL catalog (not only recently enriched profiles).
# Order is presentation order; ids must exist in MUSICIAN_STYLE_CATALOG.
FEATURED_STYLE_IDS: tuple[str, ...] = (
    "eno_ambient",
    "glass_minimal",
    "debussy_color",
    "monk_angles",
    "aphex_glitch",
    "frahm_felt",
)

# Short poetic lines for featured cards (feel, not parameter dump).
FEATURED_BLURBS: Dict[str, str] = {
    "eno_ambient": "Slow air — pads that barely move",
    "glass_minimal": "Tight cells that bloom by addition",
    "reich_phase": "Pulse that slips against itself",
    "debussy_color": "Wash of modal color, soft edges",
    "coltrane_sheets": "Dense sheets of modal fire",
    "monk_angles": "Spaced leaps, crooked charm",
    "aphex_glitch": "Unstable cells, worn-tape jitter",
    "bach_sequence": "Clear sequences, steady pulse",
    "satie_neoclassical": "Spare piano figures, quiet room",
    "frahm_felt": "Intimate mid-tempo, felt warmth",
}

# Example vibes that teach the language — resolve via lookup to ANY catalog hit
# (or SDK / generic fallback). Not tied to a fixed musician shortlist.
VIBE_CHIPS: tuple[str, ...] = (
    "ambient drone",
    "angular jazz",
    "worn tape piano",
    "minimal pulse",
    "impressionist wash",
    "dense modal sheets",
    "glitchy idm",
    "spare neoclassical",
)

# Playful packs spanning the full catalog — entry points, not a closed set.
# Each chip soft-matches via lookup (aliases + tags), not locked musician IDs.
MOOD_CHIP_PACKS: tuple[dict, ...] = (
    {
        "id": "soft_sparse",
        "label": "Soft & sparse",
        "chips": [
            "ambient drone",
            "spare neoclassical",
            "impressionist wash",
            "worn tape piano",
        ],
    },
    {
        "id": "pulse_phase",
        "label": "Pulse & phase",
        "chips": [
            "minimal pulse",
            "additive cells",
            "phase pulse",
            "clear sequence",
        ],
    },
    {
        "id": "jazz_grit",
        "label": "Jazz & grit",
        "chips": [
            "angular jazz",
            "dense modal sheets",
            "glitchy idm",
            "modal fire",
        ],
    },
)

# Sketch length bounds (match Advanced slider / create_arp clamps).
BARS_MIN = 2
BARS_MAX = 32
CHORD_COUNT_MIN = 1
CHORD_COUNT_MAX = 8
DEFAULT_SKETCH_BARS = 16
DEFAULT_CHORD_COUNT = 4
DEFAULT_GENERATION_TYPE = "drone"
DEFAULT_PROGRESSION: tuple[str, ...] = ("C3", "G3", "A3", "F3")
GENERATION_TYPES: tuple[str, ...] = ("drone", "arpeggio")
SHAPE_LABELS: Dict[str, str] = {
    "drone": "Progression",
    "arpeggio": "Arpeggio",
}

# Plain-feel vocabulary (happy-path line, not geek match type).
_FEEL_PREF: tuple[str, ...] = (
    "ambient",
    "phase",
    "modal",
    "angular",
    "glitch",
    "impressionist",
    "spare",
    "felt",
    "baroque",
    "minimal",
    "sequence",
)
_SHAPE_PREF: tuple[str, ...] = (
    "additive",
    "sheets",
    "glitch",
    "pulse",
    "phase",
    "angular",
    "sequence",
    "wash",
    "ostinato",
)


@dataclass(frozen=True)
class FeaturedStyleCard:
    id: str
    name: str
    blurb: str


@dataclass(frozen=True)
class RecipePreview:
    """One-liner preview of what Generate will produce (no MIDI write)."""

    query: str
    profile: MusicianStyleProfile
    path: str  # "catalog" | "vibe" | "both"
    match_type: str  # catalog | sdk | hybrid | generic
    one_liner: str
    match_line: str
    plain_feel_line: str


def featured_style_cards(
    ids: Optional[Sequence[str]] = None,
) -> List[FeaturedStyleCard]:
    """4–6 featured cards from the full catalog (curated ids, skip missing)."""
    chosen = list(ids) if ids is not None else list(FEATURED_STYLE_IDS)
    cards: List[FeaturedStyleCard] = []
    for pid in chosen:
        profile = get_profile_by_id(pid)
        if profile is None:
            continue
        blurb = FEATURED_BLURBS.get(pid) or _fallback_blurb(profile)
        cards.append(FeaturedStyleCard(id=profile.id, name=profile.name, blurb=blurb))
    return cards


def vibe_chips() -> List[str]:
    return list(VIBE_CHIPS)


@dataclass(frozen=True)
class MoodChipPack:
    id: str
    label: str
    chips: tuple[str, ...]


def mood_chip_packs() -> List[MoodChipPack]:
    """2–3 playful packs; chips remain examples, free-text stays first-class."""
    out: List[MoodChipPack] = []
    for raw in MOOD_CHIP_PACKS:
        chips = tuple(str(c) for c in raw.get("chips") or ())
        if not chips:
            continue
        out.append(
            MoodChipPack(
                id=str(raw.get("id") or raw.get("label") or "pack"),
                label=str(raw.get("label") or raw.get("id") or "Pack"),
                chips=chips,
            )
        )
    return out


def clamp_bars(bars: int) -> int:
    return max(BARS_MIN, min(BARS_MAX, int(bars)))


def clamp_chord_count(raw: Any) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = DEFAULT_CHORD_COUNT
    return max(CHORD_COUNT_MIN, min(CHORD_COUNT_MAX, n))


def clamp_generation_type(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    if s in ("progression", "progressions", "held"):
        return "drone"
    return s if s in GENERATION_TYPES else DEFAULT_GENERATION_TYPE


def format_shape_label(raw: Any) -> str:
    """User-facing shape: held drone is Progression."""
    key = clamp_generation_type(raw)
    return SHAPE_LABELS.get(key, SHAPE_LABELS[DEFAULT_GENERATION_TYPE])


def resize_chord_progression(
    roots: Optional[Sequence[Any]],
    count: int,
) -> List[str]:
    """Trim or cycle roots to ``count``. Empty source → I–V–vi–IV."""
    n = clamp_chord_count(count)
    src = [str(r).strip() for r in (roots or []) if str(r).strip()]
    if not src:
        src = list(DEFAULT_PROGRESSION)
    return [src[i % len(src)] for i in range(n)]


def apply_user_sketch_layout(options: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply user bars/chords/shape knobs onto Engine options.

    ``chord_count`` resizes ``chord_progression`` / ``root_notes``.
    User ``drone`` without an explicit held flag becomes held chords.
    No-op when those keys are absent.
    """
    out = dict(options)
    if "generation_type" in out:
        out["generation_type"] = clamp_generation_type(out.get("generation_type"))
        if out["generation_type"] == "drone" and out.get("drone_held") is None:
            out["drone_held"] = True
    if "chord_count" in out and out["chord_count"] is not None:
        count = clamp_chord_count(out["chord_count"])
        src = out.get("chord_progression") or out.get("root_notes")
        resized = resize_chord_progression(src, count)
        out["chord_progression"] = resized
        out["root_notes"] = list(resized)
        out["chord_count"] = count
    return out


def half_bars(bars: int) -> int:
    """Halve sketch length for a shorter playable loop (floor at BARS_MIN)."""
    return clamp_bars(max(BARS_MIN, int(bars) // 2))


def double_bars(bars: int) -> int:
    """Double sketch length for a longer playable loop (cap at BARS_MAX)."""
    return clamp_bars(int(bars) * 2)


def clamp_extend_factor(raw: Any) -> int:
    """UI/session extend_factor — 1 (off) through 4."""
    return resolve_extend_factor(raw)


def toggle_section_chip(current: Optional[str], clicked: str) -> Optional[str]:
    """
    Section chip toggle: click active chip → off; else select that role.

    Default off (None) leaves full-sketch behavior as today.
    """
    role = normalize_section_role(clicked)
    if role is None or role not in SECTION_ROLES:
        return normalize_section_role(current)
    cur = normalize_section_role(current)
    return None if cur == role else role


def toggle_extend_factor(current: Any, clicked: int) -> int:
    """Extend chip toggle: click active factor → 1 (off); else set 2 or 4."""
    factor = clamp_extend_factor(clicked)
    if factor not in EXTEND_CHIP_FACTORS:
        return clamp_extend_factor(current)
    cur = clamp_extend_factor(current)
    return 1 if cur == factor else factor


def surprise_related_profile(
    profile: MusicianStyleProfile,
    *,
    vibe_hint: str = "",
    also_considered: Optional[Sequence[MusicianStyleProfile]] = None,
    last_result: Any = None,
    previous_id: Optional[str] = None,
) -> Optional[MusicianStyleProfile]:
    """
    Surprise me → related[0] named identity jump (Matching Next parked).

    related = related_from_lookup_result(last_result) if last lookup
    else related_profiles(current). Take related[0]; if that equals previous,
    take related[1] when available. Empty → find_profiles on styles, skip self.
    """
    if last_result is not None:
        related = related_from_lookup_result(
            last_result,
            limit=2,
            vibe_hint=vibe_hint,
        )
    else:
        related = related_profiles(
            profile,
            limit=2,
            also_considered=also_considered,
            vibe_hint=vibe_hint,
        )
    if not related:
        seed = vibe_hint.strip() or " ".join(list(profile.styles[:8])) or profile.name
        related = [
            p for p in find_profiles(seed, limit=4) if p.id != profile.id
        ]
    if not related:
        return None
    pick = related[0]
    if previous_id and pick.id == previous_id and len(related) > 1:
        pick = related[1]
    if pick.id == profile.id:
        return related[1] if len(related) > 1 else None
    return pick


def surprise_effects_preset(
    *,
    avoid: str = "",
    rng: Optional[random.Random] = None,
) -> str:
    """Pick an effects preset; skip the current one when others exist."""
    ids = [str(p["id"]) for p in list_presets() if p.get("id")]
    if not ids:
        return "tape_and_human"
    pool = [i for i in ids if i != (avoid or "").strip()] or ids
    picker = rng if rng is not None else random
    return picker.choice(pool)


def surprise_catalog_profile(
    *,
    previous_id: Optional[str] = None,
    rng: Optional[random.Random] = None,
) -> Optional[MusicianStyleProfile]:
    """Random catalog artist, skipping the last Surprise pick when possible."""
    catalog = list(MUSICIAN_STYLE_CATALOG)
    if not catalog:
        return None
    skip = (previous_id or "").strip()
    pool = [p for p in catalog if p.id != skip] or catalog
    picker = rng if rng is not None else random
    return picker.choice(pool)


def surprise_roll(
    *,
    current: Optional[MusicianStyleProfile] = None,
    last_result: Any = None,
    previous_id: Optional[str] = None,
    vibe_hint: str = "",
    avoid_effects: str = "",
    rng: Optional[random.Random] = None,
) -> Optional[Tuple[MusicianStyleProfile, str]]:
    """
    Surprise me: populate a named artist plus a varied effects preset.

    Empty start → random catalog artist. After a pick → related identity jump.
    Effects always re-roll away from the current preset when possible.
    """
    profile: Optional[MusicianStyleProfile] = None
    if current is not None:
        profile = surprise_related_profile(
            current,
            vibe_hint=vibe_hint,
            last_result=last_result,
            previous_id=previous_id,
        )
    if profile is None:
        profile = surprise_catalog_profile(previous_id=previous_id, rng=rng)
    if profile is None:
        return None
    return profile, surprise_effects_preset(avoid=avoid_effects, rng=rng)


def _fallback_blurb(profile: MusicianStyleProfile) -> str:
    desc = (profile.description or "").strip()
    if not desc:
        return ", ".join(profile.styles[:3]) or profile.generation_type
    # First clause / short sentence
    cut = desc.split(".")[0].strip()
    return cut if len(cut) <= 56 else cut[:53].rstrip() + "…"


def _match_type_for_profile(
    profile: MusicianStyleProfile,
    *,
    matched_locally: bool = True,
    used_cursor_sdk: bool = False,
) -> str:
    source = (profile.source or "catalog").lower()
    if used_cursor_sdk or source in ("cursor_sdk", "sdk"):
        return "sdk" if source != "hybrid" else "hybrid"
    if source == "hybrid":
        return "hybrid"
    if not matched_locally or profile.id == "custom_query":
        return "generic"
    return "catalog"


def _section_drip_shape(profile: MusicianStyleProfile) -> str:
    """Section sketch shape — progression unless wash opts out."""
    if profile.drone_held is False:
        return "drone" if profile.generation_type == "drone" else "arp"
    if profile.chord_progression or profile.drone_held is True:
        return "progression"
    return "drone" if profile.generation_type == "drone" else "arp"


def format_recipe_one_liner(
    profile: MusicianStyleProfile,
    *,
    effects_preset: Optional[str] = None,
    section_role: Optional[str] = None,
) -> str:
    """
    feel + mode/BPM/arp-vs-drone + effects default.

    Example: "Brian Eno · drone · lydian · 72 BPM · Subtle tape"

    When ``section_role`` is set (chip or resolved profile), name the section
    so the drip is not an ambient wash: e.g. ``Philip Glass · bridge · progression``.
    """
    role = normalize_section_role(section_role) or normalize_section_role(
        getattr(profile, "section_role", None)
    )
    if role:
        return f"{profile.name} · {role} · {_section_drip_shape(profile)}"
    preset_id = effects_preset or profile.effects_preset
    try:
        preset_label = get_preset(preset_id)["label"]
    except Exception:
        preset_label = preset_id
    if profile.generation_type == "drone":
        gen = "drone" if profile.drone_held is False else "progression"
    else:
        gen = "arp"
    return (
        f"{profile.name} · {gen} · {profile.mode} · "
        f"{profile.bpm} BPM · {preset_label}"
    )


def format_match_line(
    profile: MusicianStyleProfile,
    *,
    match_type: Optional[str] = None,
    effects_preset: Optional[str] = None,
    matched_locally: bool = True,
    used_cursor_sdk: bool = False,
) -> str:
    """Geek match transparency — Advanced only. Matched: name · type · mode · effects"""
    mtype = match_type or _match_type_for_profile(
        profile,
        matched_locally=matched_locally,
        used_cursor_sdk=used_cursor_sdk,
    )
    preset_id = effects_preset or profile.effects_preset
    try:
        preset_label = get_preset(preset_id)["label"]
    except Exception:
        preset_label = preset_id
    return (
        f"Matched: {profile.name} · {mtype} · {profile.mode} · {preset_label}"
    )


def _style_token_bag(profile: MusicianStyleProfile) -> set[str]:
    bag: set[str] = set()
    for raw in profile.styles:
        s = (raw or "").lower().strip()
        if not s:
            continue
        bag.add(s)
        bag.update(s.replace("-", " ").split())
    return bag


def format_plain_feel_match(profile: MusicianStyleProfile) -> str:
    """
    Plain-feel clarity for happy path (not geek match type).

    ``Sounds like {name} ({feel} · {shape})``
    - feel = first useful styles[] tag (curated preference)
    - shape = drone if generation_type==drone else style shape word, else pulse

    Examples: Eno ambient·drone; Glass minimal·additive; Reich phase·pulse;
    Coltrane modal·sheets.
    """
    bag = _style_token_bag(profile)
    feel = next((w for w in _FEEL_PREF if w in bag), None)
    if feel is None:
        if profile.styles:
            feel = str(profile.styles[0]).lower().replace("-", " ").split()[0]
        else:
            feel = "sketch"
    if profile.generation_type == "drone":
        shape = "drone"
    else:
        shape = next((w for w in _SHAPE_PREF if w in bag), "pulse")
    return f"Sounds like {profile.name} ({feel} · {shape})"


def _usable_likeness_prose(text: str, *, limit: int = 400) -> str:
    """Drop Spotify gate residue so the home blurb stays listener-facing."""
    raw = (text or "").strip()
    if not raw:
        return ""
    words = [
        part
        for part in raw.split()
        if not part.startswith("followers.total=")
    ]
    out = " ".join(words).strip()
    if out.lower().startswith("spotify accept"):
        return ""
    return out[:limit]


def format_likeness_blurb(
    profile: MusicianStyleProfile,
    *,
    used_cursor_sdk: bool = False,
) -> Optional[Tuple[str, str]]:
    """
    Home blurb: Cursor likeness when SDK ran; else catalog description.

    Returns ``(label, body)`` or None.
    """
    summary = _usable_likeness_prose(getattr(profile, "likeness_summary", "") or "")
    notes = _usable_likeness_prose(getattr(profile, "style_notes", "") or "")
    if used_cursor_sdk and (summary or notes):
        return (f"Why it sounds like {profile.name}", summary or notes)
    desc = (profile.description or "").strip()
    if desc:
        return (f"Why this sketch · {profile.name}", desc)
    return None


# Back-compat alias used by early Fun Now wiring
def format_plain_feel_line(profile: MusicianStyleProfile) -> str:
    return format_plain_feel_match(profile)


def preview_recipe(
    *,
    catalog_name: str,
    vibe_text: str = "",
    effects_preset: Optional[str] = None,
    gate_accept: Any = None,
    section_role: Optional[str] = None,
) -> RecipePreview:
    """
    Offline lookup preview (no MIDI).

    Feel language layers on catalog who. Different artist identity (other catalog
    musician or Spotify stranger ≠ who) unpins the who-chip. Empty vibe sticks.
    Optional ``gate_accept`` binds Spotify genres/followers into cousin few-shot.
    Optional ``section_role`` resolves catalog ``sections[]`` for drip + knobs.
    """
    from .cursor_style_lookup import lookup_musician_style

    identity = (catalog_name or "").strip()
    vibe = (vibe_text or "").strip()
    query, identity_name = resolve_lookup_inputs(
        identity, vibe, gate_accept=gate_accept
    )
    different_artist = vibe_is_different_artist_identity(
        identity, vibe, gate_accept=gate_accept
    )
    if identity and vibe and not different_artist:
        path = "both"
    elif vibe:
        path = "vibe"
    else:
        path = "catalog"
    result = lookup_musician_style(
        query,
        use_cursor_sdk=False,
        identity_name=identity_name,
        skip_artist_gate=True,  # UI / caller already gated
        gate_accept=gate_accept if different_artist else None,
    )
    role = normalize_section_role(section_role)
    profile = (
        resolve_section_recipe(result.profile, role) if role else result.profile
    )
    mtype = _match_type_for_profile(
        profile,
        matched_locally=result.matched_locally,
        used_cursor_sdk=result.used_cursor_sdk,
    )
    if path == "vibe" and not result.matched_locally:
        mtype = "generic"
    plain = format_plain_feel_match(profile)
    if path == "both" and vibe:
        plain = f"{plain} · feel {vibe}"
    return RecipePreview(
        query=query,
        profile=profile,
        path=path,
        match_type=mtype,
        one_liner=format_recipe_one_liner(
            profile, effects_preset=effects_preset, section_role=role
        ),
        match_line=format_match_line(
            profile,
            match_type=mtype,
            effects_preset=effects_preset,
            matched_locally=result.matched_locally,
            used_cursor_sdk=result.used_cursor_sdk,
        ),
        plain_feel_line=plain,
    )


def related_profiles(
    profile: MusicianStyleProfile,
    *,
    limit: int = 3,
    also_considered: Optional[Sequence[MusicianStyleProfile]] = None,
    vibe_hint: str = "",
) -> List[MusicianStyleProfile]:
    """
    2–3 adjacent styles from the FULL catalog via find_profiles / candidates.

    Never a hardcoded shortlist of 4. Prefers lookup candidates, then
    find_profiles on the profile's tags (+ optional vibe hint).
    """
    limit = max(0, int(limit))
    if limit == 0:
        return []

    out: List[MusicianStyleProfile] = []
    seen = {profile.id}

    if also_considered:
        for cand in also_considered:
            if cand.id in seen:
                continue
            out.append(cand)
            seen.add(cand.id)
            if len(out) >= limit:
                return out[:limit]

    # Prefer existing find_profiles across the whole catalog
    seed = vibe_hint.strip() or " ".join(
        [profile.name] + list(profile.styles[:6]) + [profile.generation_type]
    )
    for other in find_profiles(seed, limit=limit + 4):
        if other.id in seen:
            continue
        out.append(other)
        seen.add(other.id)
        if len(out) >= limit:
            break

    # Soft fill: shared style tags if find_profiles was thin
    if len(out) < limit:
        ranked: List[tuple[float, MusicianStyleProfile]] = []
        my_tags = {s.lower() for s in profile.styles}
        for other in MUSICIAN_STYLE_CATALOG:
            if other.id in seen:
                continue
            shared = my_tags & {s.lower() for s in other.styles}
            if not shared:
                continue
            score = float(len(shared))
            if profile.generation_type == other.generation_type:
                score += 0.5
            ranked.append((score, other))
        ranked.sort(key=lambda item: item[0], reverse=True)
        for _score, other in ranked:
            out.append(other)
            seen.add(other.id)
            if len(out) >= limit:
                break

    return out[:limit]


def related_from_lookup_result(
    result: Any,
    *,
    limit: int = 3,
    vibe_hint: str = "",
) -> List[MusicianStyleProfile]:
    """Convenience: related chips from a StyleLookupResult."""
    profile = result.profile
    candidates = getattr(result, "candidates", None) or []
    also = [c for c in candidates if c.id != profile.id]
    return related_profiles(
        profile,
        limit=limit,
        also_considered=also,
        vibe_hint=vibe_hint,
    )


def resolve_happy_path_query(catalog_name: str, vibe_text: str = "") -> str:
    """Catalog artist plus optional feel. Feel layers on; it does not replace who."""
    who = (catalog_name or "").strip()
    vibe = (vibe_text or "").strip()
    if who and vibe:
        if who.lower() in vibe.lower():
            return vibe
        return f"{who} — {vibe}"
    return who or vibe


def _catalog_musician_named(vibe: str, *, excluding: str = "") -> Optional[str]:
    """
    Return catalog musician name when vibe names that identity (not style/alias).

    Excludes the selected who. Style aliases like \"ambient drone\" do not count.
    """
    from .musician_styles import (
        MUSICIAN_STYLE_CATALOG,
        alias_target_ids,
        score_profile,
    )

    v = (vibe or "").strip()
    if not v:
        return None
    # Feel aliases / mood language are never a musician-name swap.
    if alias_target_ids(v):
        return None
    excl = (excluding or "").strip().lower()
    v_lower = v.lower()
    for profile in MUSICIAN_STYLE_CATALOG:
        if profile.name.lower() == excl:
            continue
        if profile.name.lower() == v_lower:
            return profile.name
        # Strong name identity: all name tokens present + high score.
        name_toks = {t for t in profile.name.lower().split() if t}
        vibe_toks = {t for t in v_lower.replace("-", " ").split() if t}
        if name_toks and name_toks.issubset(vibe_toks) and score_profile(v, profile) >= 5.0:
            return profile.name
    return None


def _vibe_is_feel_language(vibe: str) -> bool:
    """Alias keys, vibe chips, mood-pack chips — layer on who, never replace."""
    from .musician_styles import alias_target_ids

    v = (vibe or "").strip()
    if not v:
        return False
    if alias_target_ids(v):
        return True
    v_lower = v.lower()
    if v_lower in {c.lower() for c in VIBE_CHIPS}:
        return True
    for pack in MOOD_CHIP_PACKS:
        for chip in pack.get("chips") or ():
            if str(chip).lower() == v_lower:
                return True
    return False


def vibe_is_different_artist_identity(
    catalog_name: str,
    vibe_text: str,
    *,
    gate_accept: Any = None,
) -> bool:
    """
    True when typed vibe is a *different artist identity* than the who-chip.

    Different artist =
      - Spotify type=artist accept whose name is not the who-chip, or
      - catalog musician *name* hit that is not the who-chip.

    Style aliases / mood chips stay pinned only when Spotify did not return
    a different artist (genre queries resolve to the Spotify artist).
    """
    who = (catalog_name or "").strip()
    vibe = (vibe_text or "").strip()
    if not vibe:
        return False
    if who and vibe.lower() == who.lower():
        return False
    if gate_accept is not None and getattr(gate_accept, "accepted", False):
        if getattr(gate_accept, "source", None) == "spotify":
            artist = getattr(gate_accept, "spotify_artist", None)
            if artist is not None and (artist.type or "") == "artist":
                artist_name = (artist.name or "").strip()
                if artist_name and artist_name.lower() != who.lower():
                    return True
    if _vibe_is_feel_language(vibe):
        return False
    other = _catalog_musician_named(vibe, excluding=who)
    return other is not None


def resolve_lookup_inputs(
    catalog_name: str,
    vibe_text: str = "",
    *,
    gate_accept: Any = None,
) -> tuple[str, Optional[str]]:
    """
    Query + identity_name for lookup / Generate.

    Empty vibe → catalog who (catalog stick).
    Feel language / unknown feel → who+feel query, identity stays (Fun Now).
    Different artist identity (other catalog musician or Spotify stranger ≠ who)
    → vibe is the query, identity unpinned (no Glass wallpaper).
    """
    vibe = (vibe_text or "").strip()
    who = (catalog_name or "").strip()
    if not vibe:
        return who, (who or None)
    if vibe_is_different_artist_identity(who, vibe, gate_accept=gate_accept):
        if gate_accept is not None and getattr(gate_accept, "source", None) == "spotify":
            artist = getattr(gate_accept, "spotify_artist", None)
            artist_name = (getattr(artist, "name", None) or "").strip()
            if artist_name:
                return artist_name, None
        return vibe, None
    # Feel layers on selected artist.
    return resolve_happy_path_query(who, vibe), (who or None)


# Sample Musician reject drip — plain copy only (never raw reason enums in UI).
ARTIST_REJECT_DRIP = "Not finding a musician…"


def artist_gate_query_for_ui(catalog_name: str, vibe_text: str = "") -> str:
    """
    Pre-Generate gate query for Sample Musician drip.

    Typed vibe/feel is gated as the artist query (no catalog identity pin) so
    Ted Bundy-class names reject instead of showing the pinned catalog recipe.
    Empty vibe falls back to the selected catalog who.
    """
    vibe = (vibe_text or "").strip()
    if vibe:
        return vibe
    return (catalog_name or "").strip()


def resolve_artist_gate_for_ui(
    catalog_name: str,
    vibe_text: str = "",
    *,
    spotify_search=None,
):
    """
    Run ``resolve_artist_query`` for pre-Generate drip.

    Typed Search / feel always hits Spotify (force_spotify).
    Empty vibe pins the catalog who so Browse picks stay local.
    """
    from .artist_gate import resolve_artist_query

    vibe = (vibe_text or "").strip()
    who = (catalog_name or "").strip()
    if vibe:
        return resolve_artist_query(
            vibe,
            identity_name=None,
            spotify_search=spotify_search,
            force_spotify=True,
        )
    return resolve_artist_query(
        who,
        identity_name=who or None,
        spotify_search=spotify_search,
    )


def artist_reject_drip_copy(reason: str | None = None) -> str:
    """Visible reject drip — always Sample's plain words; reason stays for tests."""
    _ = reason  # session may store enum; UI never surfaces it
    return ARTIST_REJECT_DRIP


def session_clears_on_artist_reject() -> tuple[str, ...]:
    """Session keys cleared when the gate rejects (no stale recipe / sketch)."""
    return ("last_run", "match_line", "generate_error")
