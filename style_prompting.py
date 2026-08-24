"""
Thin helpers for stylistic prompting UI.

Keeps named catalog (who) and free-text vibe (feel) as two honest paths.
Featured cards + vibe chips are entry points across the full catalog — not a
closed allow-list, and not limited to any fixed shortlist of musicians.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from .effects_presets import get_preset
from .musician_styles import (
    MUSICIAN_STYLE_CATALOG,
    MusicianStyleProfile,
    find_profiles,
    get_profile_by_id,
)


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
    path: str  # "catalog" | "vibe"
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


def half_bars(bars: int) -> int:
    """Halve sketch length for a shorter playable loop (floor at BARS_MIN)."""
    return clamp_bars(max(BARS_MIN, int(bars) // 2))


def double_bars(bars: int) -> int:
    """Double sketch length for a longer playable loop (cap at BARS_MAX)."""
    return clamp_bars(int(bars) * 2)


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


def format_recipe_one_liner(
    profile: MusicianStyleProfile,
    *,
    effects_preset: Optional[str] = None,
) -> str:
    """
    feel + mode/BPM/arp-vs-drone + effects default.

    Example: "Brian Eno · drone · lydian · 72 BPM · Subtle tape"
    """
    preset_id = effects_preset or profile.effects_preset
    try:
        preset_label = get_preset(preset_id)["label"]
    except Exception:
        preset_label = preset_id
    gen = "drone" if profile.generation_type == "drone" else "arp"
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


# Back-compat alias used by early Fun Now wiring
def format_plain_feel_line(profile: MusicianStyleProfile) -> str:
    return format_plain_feel_match(profile)


def preview_recipe(
    *,
    catalog_name: str,
    vibe_text: str = "",
    effects_preset: Optional[str] = None,
) -> RecipePreview:
    """
    Offline lookup preview (no MIDI). Vibe overrides catalog when non-empty.
    """
    from .cursor_style_lookup import lookup_musician_style

    vibe = (vibe_text or "").strip()
    path = "vibe" if vibe else "catalog"
    query = vibe if vibe else catalog_name
    result = lookup_musician_style(query, use_cursor_sdk=False)
    profile = result.profile
    mtype = _match_type_for_profile(
        profile,
        matched_locally=result.matched_locally,
        used_cursor_sdk=result.used_cursor_sdk,
    )
    # Free-text with no catalog hit → honest generic
    if path == "vibe" and not result.matched_locally:
        mtype = "generic"
    return RecipePreview(
        query=query,
        profile=profile,
        path=path,
        match_type=mtype,
        one_liner=format_recipe_one_liner(profile, effects_preset=effects_preset),
        match_line=format_match_line(
            profile,
            match_type=mtype,
            effects_preset=effects_preset,
            matched_locally=result.matched_locally,
            used_cursor_sdk=result.used_cursor_sdk,
        ),
        plain_feel_line=format_plain_feel_match(profile),
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
    """Vibe (feel) wins when filled; otherwise named catalog (who)."""
    vibe = (vibe_text or "").strip()
    return vibe if vibe else catalog_name
