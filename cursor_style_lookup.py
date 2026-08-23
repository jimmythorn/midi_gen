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
from typing import Any, Dict, List, Optional, Tuple

from .musician_styles import (
    MusicianStyleProfile,
    find_best_profile,
    find_profiles,
    list_styles,
    profile_from_dict,
)
from .effects_presets import build_effects_config, get_preset


STYLE_PROFILE_JSON_SCHEMA = """
Return ONLY a single JSON object (no markdown) with these keys:
{
  "id": "snake_case_id",
  "name": "Musician or Style Name",
  "styles": ["tag1", "tag2"],
  "description": "one short sentence",
  "generation_type": "arpeggio" or "drone",
  "mode": "major|minor|dorian|phrygian|lydian|mixolydian|locrian",
  "bpm": 40-240,
  "bars": 4-16,
  "root_notes": ["E3", "A3", "D3", "G3"],
  "min_octave": 2-5,
  "max_octave": 3-6,
  "use_chord_tones": true/false,
  "arp_mode": "up|down|up_down|random|order",
  "arp_steps": 4|8|16,
  "range_octaves": 1-3,
  "evolution_rate": 0.0-1.0,
  "repetition_factor": 1-10,
  "effects_preset": "clean|subtle_tape|worn_tape|human_feel|tape_and_human"
}
Choose parameters that evoke the musician's stylistic tendencies as a
sketch for algorithmic MIDI — not a literal transcription.
"""


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


def cursor_sdk_available() -> bool:
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


def lookup_with_cursor_sdk(query: str, timeout_ms: int = 120_000) -> Tuple[Optional[MusicianStyleProfile], Optional[str]]:
    """
    Ask Cursor agent to map a musician/style query to a generation profile.

    Returns (profile_or_none, raw_text_or_none).
    """
    if not cursor_sdk_available():
        return None, None

    from cursor_sdk import Agent, LocalAgentOptions

    catalog_hint = ", ".join(p.name for p in find_profiles(query, limit=3)) or "none"
    known_styles = ", ".join(list_styles()[:20])
    prompt = (
        f"Musician/style query: {query!r}\n"
        f"Closest local catalog hits: {catalog_hint}\n"
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


def lookup_musician_style(
    query: str,
    *,
    use_cursor_sdk: bool = True,
    force_sdk: bool = False,
) -> StyleLookupResult:
    """
    Resolve a musician/style query into a MIDI generation profile.

    Resolution order:
    1. Local catalog match (always attempted)
    2. Optional Cursor SDK enrichment when CURSOR_API_KEY is set
    3. Fallback to best local match or a generic ambient sketch
    """
    query = (query or "").strip()
    candidates = find_profiles(query, limit=5) if query else []
    local_best = candidates[0] if candidates else None

    sdk_profile = None
    raw_sdk = None
    used_sdk = False

    should_try_sdk = use_cursor_sdk and (force_sdk or cursor_sdk_available())
    if should_try_sdk and query:
        sdk_profile, raw_sdk = lookup_with_cursor_sdk(query)
        used_sdk = sdk_profile is not None

    if used_sdk and sdk_profile is not None:
        # If local had a strong name match, keep identity but allow SDK param tweaks
        if local_best and local_best.name.lower() in query.lower():
            merged = profile_from_dict(
                {**local_best.as_dict(), **{
                    k: v for k, v in sdk_profile.as_dict().items()
                    if k not in ("id", "name") and v is not None
                }},
                source="hybrid",
            )
            return StyleLookupResult(
                profile=merged,
                matched_locally=True,
                used_cursor_sdk=True,
                candidates=candidates,
                raw_sdk_text=raw_sdk,
                message=f"Hybrid profile for {merged.name} (catalog + Cursor SDK).",
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
) -> Tuple[str, StyleLookupResult, Dict[str, Any]]:
    """
    Lookup style and generate a MIDI file.

    Returns (midi_path, lookup_result, options_used).
    """
    from .arpeggio_generation import create_arp

    result = lookup_musician_style(query, use_cursor_sdk=use_cursor_sdk)
    options = result.to_options()
    if overrides:
        options.update(overrides)
    # Keep effects in sync if preset overridden
    if overrides and "effects_preset" in overrides:
        options["effects_config"] = build_effects_config(overrides["effects_preset"])
        options["effects_preset"] = overrides["effects_preset"]
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
