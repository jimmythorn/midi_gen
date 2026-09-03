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

from .artist_gate import ArtistRejected, require_artist
from .musician_styles import (
    MUSICIAN_STYLE_CATALOG,
    MusicianStyleProfile,
    find_best_profile,
    find_profiles,
    list_styles,
    profile_from_dict,
)
from .effects_presets import build_effects_config, get_preset


STYLE_PROFILE_JSON_SCHEMA = """
Research the query first. Use your knowledge of the musician's recorded work,
typical harmony, rhythm, texture, tempo range, and studio habits — or, for a
vibe, the genre/feel it names. Closest local catalog hits are hints only; do
not copy them unless the query is that same person.

Then return ONLY a single JSON object (no markdown) with these keys:
{
  "id": "snake_case_id",
  "name": "Musician or Style Name",
  "styles": ["tag1", "tag2"],
  "description": "one short sentence",
  "style_notes": "2-4 sentences: the stylistic preferences you found and how they map to these params",
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
repetition, tape vs clean). This JSON is the generation recipe. Not a
transcription of a specific piece.
"""

# Widget/session keys that may override a researched recipe (loop length / RNG only).
LOOKUP_STICKY_OVERRIDE_KEYS = frozenset({"bars", "seed", "debug", "filename"})


@dataclass
class StyleLookupResult:
    profile: MusicianStyleProfile
    matched_locally: bool
    used_cursor_sdk: bool
    candidates: List[MusicianStyleProfile]
    raw_sdk_text: Optional[str] = None
    message: str = ""

    def to_options(self) -> Dict[str, Any]:
        effects = build_effects_config(self.profile.effects_preset)
        return self.profile.to_options(effects_config=effects)


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


def lookup_musician_style(
    query: str,
    *,
    use_cursor_sdk: bool = True,
    force_sdk: bool = False,
    identity_name: Optional[str] = None,
    vibe_text: Optional[str] = None,
    skip_artist_gate: bool = False,
) -> StyleLookupResult:
    """
    Resolve a musician/style query into a MIDI generation profile.

    Resolution order:
    1. Artist gate (catalog/alias, else Spotify type=artist) — fail closed
    2. Local catalog match
    3. Optional Cursor SDK enrichment when CURSOR_API_KEY is set
    4. Fallback to best local match or a generic ambient sketch

    ``identity_name`` pins the catalog artist so a feel cannot replace them.
    Raises ``ArtistRejected`` when the gate fails (no create_arp / SDK after).
    """
    query = (query or "").strip()
    feel = (vibe_text or "").strip() or None
    if not skip_artist_gate:
        # Reject before any Cursor SDK enrich or generic invent-a-sketch path.
        require_artist(query, identity_name=identity_name)
    identity = _catalog_identity(identity_name)
    candidates = find_profiles(query, limit=5) if query else []
    local_best = identity or (candidates[0] if candidates else None)

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
            merged = profile_from_dict(sdk_data, source="hybrid")
            return StyleLookupResult(
                profile=merged,
                matched_locally=True,
                used_cursor_sdk=True,
                candidates=candidates,
                raw_sdk_text=raw_sdk,
                message=f"Researched params for {merged.name} (catalog name + Cursor SDK recipe).",
            )
        return StyleLookupResult(
            profile=sdk_profile,
            matched_locally=local_best is not None,
            used_cursor_sdk=True,
            candidates=candidates,
            raw_sdk_text=raw_sdk,
            message=f"Cursor SDK profile for {sdk_profile.name}.",
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
                + (" Cursor SDK unavailable — set CURSOR_API_KEY to enrich." if use_cursor_sdk and not cursor_sdk_available() else "")
            ),
        )

    # Last resort generic sketch from the query tokens
    fallback = profile_from_dict(
        {
            "id": "custom_query",
            "name": query or "Custom",
            "styles": [t for t in re.split(r"[^a-z0-9]+", query.lower()) if t][:4] or ["ambient"],
            "description": "Generic sketch derived from the query; refine with Cursor SDK or catalog picks.",
            "generation_type": "drone" if "drone" in query.lower() or "ambient" in query.lower() else "arpeggio",
            "mode": "minor",
            "bpm": 100,
            "effects_preset": "subtle_tape",
        },
        source="catalog",
    )
    return StyleLookupResult(
        profile=fallback,
        matched_locally=False,
        used_cursor_sdk=False,
        candidates=[],
        raw_sdk_text=raw_sdk,
        message="No catalog match. Using a generic sketch.",
    )


def generate_midi_for_style(
    query: str,
    *,
    use_cursor_sdk: bool = True,
    overrides: Optional[Dict[str, Any]] = None,
    live_tweak: bool = False,
    identity_name: Optional[str] = None,
    vibe_text: Optional[str] = None,
) -> Tuple[str, StyleLookupResult, Dict[str, Any]]:
    """
    Lookup style and generate a MIDI file.

    Artist gate runs first (catalog/alias or Spotify type=artist). Rejects
    raise ``ArtistRejected`` before ``create_arp`` or Cursor SDK lookup.

    When the Cursor SDK returns a recipe, widget overrides are ignored except
    loop length / seed / debug — unless ``live_tweak`` (user moved a live knob).

    Returns (midi_path, lookup_result, options_used).
    """
    # Fail closed before create_arp / SDK — shared gate with lookup.
    require_artist(query, identity_name=identity_name)

    from .arpeggio_generation import create_arp

    result = lookup_musician_style(
        query,
        use_cursor_sdk=use_cursor_sdk,
        identity_name=identity_name,
        vibe_text=vibe_text,
        skip_artist_gate=True,  # already gated above
    )
    options = result.to_options()
    if overrides:
        to_apply = dict(overrides)
        if result.used_cursor_sdk and not live_tweak:
            to_apply = {
                k: v for k, v in to_apply.items() if k in LOOKUP_STICKY_OVERRIDE_KEYS
            }
        options.update(to_apply)
        # Keep effects in sync if preset overridden
        if "effects_preset" in to_apply:
            options["effects_config"] = build_effects_config(to_apply["effects_preset"])
            options["effects_preset"] = to_apply["effects_preset"]
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
