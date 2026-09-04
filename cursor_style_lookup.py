"""
Cursor SDK-backed musician/style lookup.

Looks up (or invents) a generation profile for a musician/style query, then
returns MIDI-ready options. Always falls back to the local catalog so the app
works without an API key.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .artist_gate import ArtistGateAccept, ArtistRejected, require_artist
from .musician_styles import (
    COUSIN_SCORE_FLOOR,
    MUSICIAN_STYLE_CATALOG,
    MusicianStyleProfile,
    cousin_recipe_from_neighbors,
    find_profiles,
    find_progression_bearing_neighbors,
    has_full_recipe_contract,
    is_effects_only_overlay,
    list_styles,
    normalize_section_role,
    parse_section_role_from_text,
    profile_from_dict,
    resolve_section_recipe,
    score_profile,
    sparse_unknown_profile,
)
from .effects_presets import build_effects_config, get_preset


STYLE_PROFILE_JSON_SCHEMA = """
Research the query first. Use your knowledge of the musician's recorded work,
typical harmony, rhythm, texture, tempo range, and studio habits — or, for a
vibe, the genre/feel it names. Closest local catalog hits are hints only; do
not copy them unless the query is that same person.

Honesty (tier B):
- Stick to catalog identity when the query is a known catalog name/alias.
- Cousin / sparse OK for strangers; forbid Glass/Eno wallpaper cosplay.
- Forbid effects-only diffs (preset/BPM paint on a blank recipe).
- Bridge/chorus must include a non-empty chord_progression grounded in the
  artist/genre — never generic pop I–V–vi–IV wallpaper after musical accept.
- When both bridge and chorus are produced, bridge roots must differ from
  chorus roots.

Then return ONLY a single JSON object (no markdown) with these keys:
{
  "id": "snake_case_id",
  "name": "Musician or Style Name",
  "styles": ["tag1", "tag2"],
  "description": "one short sentence",
  "style_notes": "2-4 sentences: the stylistic preferences you found and how they map to these params",
  "likeness_summary": "1-2 sentences: why THIS sketch sounds like the named musician (harmony, motion, texture). Not a biography. Not param jargon.",
  "generation_type": "arpeggio" or "drone",
  "mode": "major|minor|dorian|phrygian|lydian|mixolydian|locrian",
  "bpm": 40-240,
  "bars": 4-16,
  "root_notes": ["E3", "A3", "D3", "G3"],
  "min_octave": 2-5,
  "max_octave": 3-6,
  "use_chord_tones": true/false,
  "mode_color": true/false OR {"enabled": true, "intervals": [2, 9], "accent_every": 4},
  "arp_mode": "up|down|up_down|random|order",
  "arp_steps": 4|8|16,
  "range_octaves": 1-3,
  "evolution_rate": 0.0-1.0,
  "repetition_factor": 1-10,
  "embellish": true/false,
  "rhythmic_variation": true/false,
  "chord_progression": ["D3", "A3", "G3", "D3"] or null,
  "section_role": "bridge"|"chorus"|"verse"|"intro"|"outro"|"pre-chorus"|null,
  "section": {
    "role": "bridge"|"chorus"|"verse"|"intro"|"outro"|"pre-chorus",
    "chord_progression": ["D3", "A3", "G3", "D3"],
    "mode": "dorian",
    "bars": 8
  } or null,
  "sections": [
    {"role": "chorus", "chord_progression": ["D3", "A3", "G3", "D3"], "mode": "dorian", "bars": 8},
    {"role": "bridge", "chord_progression": ["E3", "B3", "A3", "E3"], "mode": "dorian", "bars": 8},
    {"role": "intro", "chord_progression": ["D3", "A3", "D3", "A3"], "mode": "dorian", "bars": 4},
    {"role": "outro", "chord_progression": ["A3", "G3", "D3", "A3"], "mode": "dorian", "bars": 8},
    {"role": "pre-chorus", "chord_progression": ["G3", "D3", "A3", "G3"], "mode": "dorian", "bars": 4}
  ] or null,
  "drone_held": true/false/null,
  "extend_factor": 1-4 or null,
  "development": null OR {
    "enabled": true,
    "seed_bars": 1|2|3|4,
    "mutate_every_n": 1-4,
    "mutate_ops": ["add_attack", "add_rest", "invert", "thin", "phase_creep"],
    "phase_creep": true/false,
    "additive_only": true/false,
    "max_phase": 0-2
  },
  "effects_preset": "clean|subtle_tape|worn_tape|human_feel|tape_and_human"
}
Map researched preferences onto those knobs (tempo, mode, drone vs arp,
repetition, tape vs clean, section progression). This JSON is the generation
recipe. Not a transcription of a specific piece.
"""

# Widget/session keys that may override a researched recipe (loop length / RNG /
# section chip / Extend stretch).
LOOKUP_STICKY_OVERRIDE_KEYS = frozenset(
    {
        "bars",
        "seed",
        "debug",
        "filename",
        "extend_factor",
        "section_role",
        "generation_type",
        "drone_held",
        "chord_count",
    }
)


@dataclass
class StyleLookupResult:
    profile: MusicianStyleProfile
    matched_locally: bool
    used_cursor_sdk: bool
    candidates: List[MusicianStyleProfile]
    raw_sdk_text: Optional[str] = None
    message: str = ""

    def to_options(self, section_role: Optional[str] = None) -> Dict[str, Any]:
        effects = build_effects_config(self.profile.effects_preset)
        role = normalize_section_role(section_role)
        resolved = resolve_section_recipe(self.profile, role) if role else self.profile
        return resolved.to_options(effects_config=effects, section_role=None)


def load_dotenv_if_present(path: Optional[os.PathLike[str] | str] = None) -> None:
    """Load KEY=value lines from .env. Does not override variables already set."""
    env_path = Path(path) if path is not None else Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in {'"', "'"}:
            val = val[1:-1]
        os.environ[key] = val


def cursor_sdk_available() -> bool:
    load_dotenv_if_present()
    if not os.environ.get("CURSOR_API_KEY"):
        return False
    try:
        import cursor_sdk  # noqa: F401
        return True
    except ImportError:
        return False


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Pull the first JSON object out of an agent response."""
    if not text:
        return None
    text = text.strip()
    # Strip markdown fences if present
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            return None
    return None


def lookup_with_cursor_sdk(
    query: str,
    timeout_ms: int = 120_000,
    *,
    identity_name: Optional[str] = None,
    vibe_text: Optional[str] = None,
) -> Tuple[Optional[MusicianStyleProfile], Optional[str]]:
    """
    Ask Cursor agent to map a musician/style query to a generation profile.

    Returns (profile_or_none, raw_text_or_none).
    """
    if not cursor_sdk_available():
        return None, None

    from cursor_sdk import Agent, LocalAgentOptions

    catalog_hint = ", ".join(p.name for p in find_profiles(query, limit=3)) or "none"
    known_styles = ", ".join(list_styles()[:20])
    who = (identity_name or "").strip()
    feel = (vibe_text or "").strip()
    if who and feel:
        head = (
            f"Artist (identity — keep this person): {who!r}\n"
            f"Feel to layer on (additive coloring, not a different artist): {feel!r}\n"
        )
    else:
        head = f"Musician or vibe query: {query!r}\n"
    prompt = (
        f"{head}"
        f"Closest local catalog hits (hints only, do not copy unless same person): {catalog_hint}\n"
        f"Known style tags: {known_styles}\n\n"
        f"{STYLE_PROFILE_JSON_SCHEMA}"
    )

    api_key = os.environ["CURSOR_API_KEY"]
    cwd = os.path.dirname(os.path.abspath(__file__))

    try:
        with Agent.create(
            model="composer-2.5",
            api_key=api_key,
            local=LocalAgentOptions(cwd=cwd),
        ) as agent:
            run = agent.send(prompt)
            # Prefer blocking text() API from docs
            raw = run.text() if hasattr(run, "text") else str(run)
            if callable(raw):
                raw = raw()
    except Exception as exc:  # pragma: no cover - network/runtime dependent
        return None, f"Cursor SDK error: {exc}"

    data = _extract_json_object(str(raw))
    if not data:
        return None, str(raw)
    return profile_from_dict(data, source="cursor_sdk"), str(raw)


def _catalog_identity(name: Optional[str]) -> Optional[MusicianStyleProfile]:
    """Exact catalog name match so a feel cannot steal the selected artist."""
    n = (name or "").strip().lower()
    if not n:
        return None
    for profile in MUSICIAN_STYLE_CATALOG:
        if profile.name.lower() == n:
            return profile
    return None


def _name_token_overlap(query: str, profile: MusicianStyleProfile) -> bool:
    """True when query shares a token with the musician name or id."""
    def tokens(text: str) -> set:
        return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t}

    q_tokens = tokens(query)
    if not q_tokens:
        return False
    name_tokens = tokens(profile.name) | tokens(profile.id.replace("_", " "))
    return bool(q_tokens & name_tokens)


def _strong_local_identity(
    query: str,
    profile: MusicianStyleProfile,
) -> bool:
    """
    Catalog stick only on identity-strength hits (name / high score / alias).

    Weak description-only keyword scores (e.g. \"jazz\" in a stranger name)
    must not steal the recipe into Coltrane/Glass — those go cousin/sparse.
    """
    if score_profile(query, profile) >= 5.0:
        return True
    if _name_token_overlap(query, profile):
        return True
    return False


def _spotify_genre_styles(gate: Optional[ArtistGateAccept]) -> List[str]:
    if gate is None or gate.spotify_artist is None:
        return []
    return list(gate.spotify_artist.genres)


def _cousin_seed_query(
    query: str,
    gate: Optional[ArtistGateAccept],
) -> str:
    """Build find_profiles seed from accepted-artist genres + name + query."""
    parts: List[str] = []
    if gate is not None and gate.spotify_artist is not None:
        artist = gate.spotify_artist
        parts.extend(artist.genres)
        if artist.name:
            parts.append(artist.name)
    q = (query or "").strip()
    if q:
        parts.append(q)
    return " ".join(parts).strip() or q


def _nearest_cousins(
    query: str,
    gate: Optional[ArtistGateAccept],
    *,
    limit: int = 3,
) -> List[MusicianStyleProfile]:
    seed = _cousin_seed_query(query, gate)
    if not seed:
        return []
    # Prefer progression/section-bearing neighbors (same habit, not BPM alone).
    bearing = find_progression_bearing_neighbors(seed, limit=limit)
    if bearing:
        return bearing
    return find_profiles(seed, limit=limit)


def _cousin_is_strong(
    query: str,
    cousin: MusicianStyleProfile,
    gate: Optional[ArtistGateAccept],
) -> bool:
    seed = _cousin_seed_query(query, gate)
    return score_profile(seed, cousin) >= COUSIN_SCORE_FLOOR


def _style_notes_from_gate(gate: Optional[ArtistGateAccept]) -> str:
    if gate is None or gate.spotify_artist is None:
        return ""
    artist = gate.spotify_artist
    genres = ", ".join(artist.genres) if artist.genres else "(no genres)"
    followers = artist.followers_total
    return (
        f"Spotify accept: {artist.name}; genres=[{genres}]; "
        f"followers.total={followers}"
    )


def _enrich_sdk_with_cousin_contract(
    sdk_profile: MusicianStyleProfile,
    *,
    query: str,
    gate: Optional[ArtistGateAccept],
) -> Optional[MusicianStyleProfile]:
    """
    Incomplete SDK recipe → cousin FULL contract + SDK soft steers in-band.

    Soft steers may bend bpm/density/effects; must not discard SDK
    generation_type / mode when set. Reject effects-only results.
    """
    cousins = _nearest_cousins(query, gate, limit=3)
    genres = _spotify_genre_styles(gate)
    notes = _style_notes_from_gate(gate)
    followers = (
        gate.spotify_artist.followers_total
        if gate is not None and gate.spotify_artist is not None
        else None
    )
    base_neighbors = cousins
    if not base_neighbors or not _cousin_is_strong(query, base_neighbors[0], gate):
        # No strong cousin — pad sparse FULL contract under SDK soft steers.
        sparse = sparse_unknown_profile(
            sdk_profile.name or query,
            styles=genres or list(sdk_profile.styles) or None,
            style_notes=notes or sdk_profile.style_notes,
        )
        base_neighbors = [sparse]

    primary = base_neighbors[0]
    data = primary.as_dict()
    # FULL structural from cousin/sparse; overlay SDK soft + identity fields.
    sdk_data = sdk_profile.as_dict()
    for key in (
        "name",
        "styles",
        "description",
        "style_notes",
        "likeness_summary",
        "generation_type",
        "mode",
        "mode_color",
        "bpm",
        "arp_steps",
        "evolution_rate",
        "repetition_factor",
        "effects_preset",
        "arp_mode",
        "range_octaves",
    ):
        if sdk_data.get(key) is not None and sdk_data.get(key) != "":
            data[key] = sdk_data[key]
    # Prefer SDK development/progression when already FULL; else keep cousin.
    if sdk_profile.development and sdk_profile.chord_progression:
        data["development"] = sdk_data["development"]
        data["chord_progression"] = sdk_data["chord_progression"]
    elif cousins and _cousin_is_strong(query, cousins[0], gate):
        for other in cousins:
            if other.development and not data.get("development"):
                data["development"] = dict(other.development)
            if other.chord_progression and not data.get("chord_progression"):
                data["chord_progression"] = list(other.chord_progression)
    data["id"] = "custom_query"
    data["source"] = "hybrid"
    if followers is not None and "followers.total" not in (data.get("style_notes") or ""):
        data["style_notes"] = (
            f"{(data.get('style_notes') or '').strip()} followers.total={followers}"
        ).strip()[:800]
    profile = profile_from_dict(data, source="hybrid")
    if not has_full_recipe_contract(profile):
        return None
    if is_effects_only_overlay(profile, sparse_unknown_profile(query)):
        return None
    return profile


def _resolve_stranger_or_sparse(
    query: str,
    *,
    gate: Optional[ArtistGateAccept],
    candidates: List[MusicianStyleProfile],
    raw_sdk: Optional[str],
) -> StyleLookupResult:
    """
    No local catalog identity — cousin fingerprint or honest sparse unknown.

    Never CATALOG[0] / eno_ambient wallpaper. Genres/followers from require_artist
    drive the few-shot seed when present.
    """
    cousins = _nearest_cousins(query, gate, limit=3)
    genres = _spotify_genre_styles(gate)
    notes = _style_notes_from_gate(gate)
    followers = (
        gate.spotify_artist.followers_total
        if gate is not None and gate.spotify_artist is not None
        else None
    )

    if cousins and _cousin_is_strong(query, cousins[0], gate):
        cousin_profile = cousin_recipe_from_neighbors(
            (gate.spotify_artist.name if gate and gate.spotify_artist else query),
            cousins,
            styles=genres or None,
            style_notes=notes,
            followers_total=followers,
        )
        if (
            cousin_profile is not None
            and has_full_recipe_contract(cousin_profile)
            and not is_effects_only_overlay(
                cousin_profile,
                sparse_unknown_profile(query),
            )
        ):
            return StyleLookupResult(
                profile=cousin_profile,
                matched_locally=False,
                used_cursor_sdk=False,
                candidates=cousins,
                raw_sdk_text=raw_sdk,
                message=(
                    f"Cousin fingerprint from {[c.name for c in cousins[:3]]} "
                    f"for {cousin_profile.name}."
                ),
            )

    sparse = sparse_unknown_profile(
        (gate.spotify_artist.name if gate and gate.spotify_artist else query),
        styles=genres or None,
        style_notes=notes or "Honest sparse unknown — no strong local cousin.",
    )
    return StyleLookupResult(
        profile=sparse,
        matched_locally=False,
        used_cursor_sdk=False,
        candidates=cousins or candidates,
        raw_sdk_text=raw_sdk,
        message="No catalog match. Using honest sparse unknown (not catalog[0]).",
    )


def lookup_musician_style(
    query: str,
    *,
    use_cursor_sdk: bool = True,
    force_sdk: bool = False,
    identity_name: Optional[str] = None,
    vibe_text: Optional[str] = None,
    skip_artist_gate: bool = False,
    gate_accept: Optional[ArtistGateAccept] = None,
) -> StyleLookupResult:
    """
    Resolve a musician/style query into a MIDI generation profile.

    Resolution order:
    1. Artist gate (catalog/alias, else Spotify type=artist) — fail closed
    2. Local catalog match (identity pin or scored hit)
    3. Optional Cursor SDK enrichment when CURSOR_API_KEY is set
    4. Cousin few-shot from 2–3 nearest catalog recipes (genres/followers bind)
    5. Honest sparse unknown — never CATALOG[0] / eno_ambient wallpaper

    ``identity_name`` pins the catalog artist so a feel cannot replace them.
    Do not pass the UI who-chip when the typed vibe is the accepted artist.
    Raises ``ArtistRejected`` when the gate fails (no create_arp / SDK after).
    """
    query = (query or "").strip()
    feel = (vibe_text or "").strip() or None
    gate: Optional[ArtistGateAccept] = gate_accept
    if not skip_artist_gate:
        # Reject before any Cursor SDK enrich or generic invent-a-sketch path.
        gate = require_artist(
            query,
            identity_name=identity_name,
            force_spotify=bool(feel),
        )
    identity = _catalog_identity(identity_name)
    candidates = find_profiles(query, limit=5) if query else []
    if identity is not None:
        local_best = identity
    elif candidates and _strong_local_identity(query, candidates[0]):
        local_best = candidates[0]
    else:
        # Weak keyword overlap only — keep candidates for cousin few-shot.
        local_best = None

    sdk_profile = None
    raw_sdk = None
    used_sdk = False

    should_try_sdk = use_cursor_sdk and (force_sdk or cursor_sdk_available())
    if should_try_sdk and query:
        sdk_profile, raw_sdk = lookup_with_cursor_sdk(
            query,
            identity_name=identity_name,
            vibe_text=feel,
        )
        used_sdk = sdk_profile is not None

    if used_sdk and sdk_profile is not None:
        # Keep catalog identity when pinned or when the name is in the query.
        keep_who = identity is not None or (
            local_best is not None and local_best.name.lower() in query.lower()
        )
        if keep_who and local_best is not None:
            sdk_data = sdk_profile.as_dict()
            sdk_data["id"] = local_best.id
            sdk_data["name"] = local_best.name
            sdk_data["source"] = "hybrid"
            # Catalog identity owns section fingerprints unless SDK authored some.
            if not sdk_data.get("sections") and local_best.sections:
                sdk_data["sections"] = [
                    dict(s) for s in local_best.sections
                ]
            if (
                not sdk_data.get("chord_progression")
                and local_best.chord_progression
            ):
                sdk_data["chord_progression"] = list(local_best.chord_progression)
            # Preserve wash opt-out (Eno) — do not let SDK flip drone_held.
            if local_best.drone_held is not None and sdk_data.get("drone_held") is None:
                sdk_data["drone_held"] = local_best.drone_held
            merged = profile_from_dict(sdk_data, source="hybrid")
            return StyleLookupResult(
                profile=merged,
                matched_locally=True,
                used_cursor_sdk=True,
                candidates=candidates,
                raw_sdk_text=raw_sdk,
                message=f"Researched params for {merged.name} (catalog name + Cursor SDK recipe).",
            )
        # SDK stranger: FULL contract required. Effects-only → reject into few-shot.
        if (
            has_full_recipe_contract(sdk_profile)
            and not is_effects_only_overlay(
                sdk_profile, sparse_unknown_profile(query)
            )
        ):
            return StyleLookupResult(
                profile=sdk_profile,
                matched_locally=local_best is not None,
                used_cursor_sdk=True,
                candidates=candidates,
                raw_sdk_text=raw_sdk,
                message=f"Cursor SDK profile for {sdk_profile.name}.",
            )
        # Incomplete SDK recipe: bind cousin FULL contract, keep SDK soft steers.
        enriched = _enrich_sdk_with_cousin_contract(
            sdk_profile,
            query=query,
            gate=gate,
        )
        if enriched is not None:
            return StyleLookupResult(
                profile=enriched,
                matched_locally=False,
                used_cursor_sdk=True,
                candidates=candidates,
                raw_sdk_text=raw_sdk,
                message=(
                    f"Cursor SDK soft steers + cousin FULL contract for {enriched.name}."
                ),
            )

    if local_best is not None:
        return StyleLookupResult(
            profile=local_best,
            matched_locally=True,
            used_cursor_sdk=False,
            candidates=candidates,
            raw_sdk_text=raw_sdk,
            message=(
                f"Local catalog match: {local_best.name}."
                + (
                    " Cursor SDK unavailable — set CURSOR_API_KEY to enrich."
                    if use_cursor_sdk and not cursor_sdk_available()
                    else ""
                )
            ),
        )

    return _resolve_stranger_or_sparse(
        query,
        gate=gate,
        candidates=candidates,
        raw_sdk=raw_sdk,
    )


def generate_midi_for_style(
    query: str,
    *,
    use_cursor_sdk: bool = True,
    overrides: Optional[Dict[str, Any]] = None,
    live_tweak: bool = False,
    identity_name: Optional[str] = None,
    vibe_text: Optional[str] = None,
    section_role: Optional[str] = None,
) -> Tuple[str, StyleLookupResult, Dict[str, Any]]:
    """
    Lookup style and generate a MIDI file.

    Artist gate runs first (catalog/alias or Spotify type=artist). Rejects
    raise ``ArtistRejected`` before ``create_arp`` or Cursor SDK lookup.

    When the Cursor SDK returns a recipe, widget overrides are ignored except
    loop length / seed / debug — unless ``live_tweak`` (user moved a live knob).

    Optional ``section_role`` (or free-text intro/verse/pre-chorus/chorus/bridge/outro
    in the query) resolves catalog ``sections[]`` into flat Engine chord_progression before
    ``create_arp``.

    Returns (midi_path, lookup_result, options_used).
    """
    # Fail closed before create_arp / SDK — shared gate with lookup.
    # Bind accept (genres / followers) into few-shot / sparse path.
    gate = require_artist(
        query,
        identity_name=identity_name,
        force_spotify=bool((vibe_text or "").strip()),
    )

    from .arpeggio_generation import create_arp

    result = lookup_musician_style(
        query,
        use_cursor_sdk=use_cursor_sdk,
        identity_name=identity_name,
        vibe_text=vibe_text,
        skip_artist_gate=True,  # already gated above
        gate_accept=gate,
    )
    role = normalize_section_role(section_role)
    if role is None and overrides:
        role = normalize_section_role(overrides.get("section_role"))
        if role is None:
            role = normalize_section_role(overrides.get("section"))
    if role is None:
        role = parse_section_role_from_text(query) or parse_section_role_from_text(vibe_text)

    options = result.to_options(section_role=role)
    if overrides:
        to_apply = dict(overrides)
        if result.used_cursor_sdk and not live_tweak:
            to_apply = {
                k: v for k, v in to_apply.items() if k in LOOKUP_STICKY_OVERRIDE_KEYS
            }
        # section_role already applied via resolve; do not let raw overrides
        # re-stamp a nested section blob into create_arp.
        to_apply.pop("section", None)
        to_apply.pop("sections", None)
        options.update(to_apply)
        # Keep effects in sync if preset overridden
        if "effects_preset" in to_apply:
            options["effects_config"] = build_effects_config(to_apply["effects_preset"])
            options["effects_preset"] = to_apply["effects_preset"]
        # Re-apply section if override carried a role after sticky filter.
        override_role = normalize_section_role(to_apply.get("section_role"))
        if override_role and override_role != role:
            options = result.to_options(section_role=override_role)
            sticky = {
                k: v for k, v in to_apply.items()
                if k not in ("section_role", "section", "sections")
            }
            options.update(sticky)
    from .style_prompting import apply_user_sketch_layout

    options = apply_user_sketch_layout(options)
    path = create_arp(options)
    return path, result, options


def describe_effects_for_profile(profile: MusicianStyleProfile) -> Dict[str, Any]:
    preset = get_preset(profile.effects_preset)
    return {
        "id": preset["id"],
        "label": preset["label"],
        "summary": preset["summary"],
        "what_you_hear": preset["what_you_hear"],
        "parameters": preset["effects"],
    }
