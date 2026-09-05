"""
Plain-language effect presets.

The tape/humanize controls are musically useful but opaque (Hz, cents, randomness).
These presets expose intent first; advanced knobs stay available underneath.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


EFFECT_PRESETS: Dict[str, Dict[str, Any]] = {
    "clean": {
        "id": "clean",
        "label": "Clean",
        "summary": "No processing — exactly the generated notes.",
        "what_you_hear": "Steady digital pitch and even velocities. Good for inspecting raw patterns.",
        "effects": [],
    },
    "human_feel": {
        "id": "human_feel",
        "label": "Human feel",
        "summary": "Small loudness variation so notes don't sound machine-perfect.",
        "what_you_hear": "Some notes a bit louder/softer. Pitch stays locked.",
        "effects": [
            {
                "name": "humanize_velocity",
                "humanization_range": 10,
            }
        ],
    },
    "subtle_tape": {
        "id": "subtle_tape",
        "label": "Subtle tape",
        "summary": "Gentle wow — slow pitch drift like a well-kept cassette.",
        "what_you_hear": "Soft floating pitch. Feels warmer and less rigid, especially on drones/pads.",
        "effects": [
            {
                "name": "tape_wobble",
                "wow_rate_hz": 0.35,
                "wow_depth": 12,
                "flutter_rate_hz": 5.0,
                "flutter_depth": 2,
                "randomness": 0.25,
                "depth_units": "cents",
            }
        ],
    },
    "worn_tape": {
        "id": "worn_tape",
        "label": "Worn tape",
        "summary": "Stronger wow + flutter — unstable vintage deck.",
        "what_you_hear": "Noticeable slow sway plus quicker shimmer. Useful for lo-fi / IDM edges.",
        "effects": [
            {
                "name": "tape_wobble",
                "wow_rate_hz": 0.6,
                "wow_depth": 30,
                "flutter_rate_hz": 9.0,
                "flutter_depth": 6,
                "randomness": 0.55,
                "depth_units": "cents",
            },
            {
                "name": "humanize_velocity",
                "humanization_range": 14,
            },
        ],
    },
    "tape_and_human": {
        "id": "tape_and_human",
        "label": "Tape + human",
        "summary": "Mild pitch drift plus natural velocity — default 'musical' polish.",
        "what_you_hear": "Slight cassette motion and uneven touch. Usually the most musical default.",
        "effects": [
            {
                "name": "tape_wobble",
                "wow_rate_hz": 0.45,
                "wow_depth": 18,
                "flutter_rate_hz": 7.0,
                "flutter_depth": 3,
                "randomness": 0.35,
                "depth_units": "cents",
            },
            {
                "name": "humanize_velocity",
                "humanization_range": 10,
            },
        ],
    },
}


EFFECT_PARAM_HELP = {
    "wow_rate_hz": "How fast the slow pitch sway moves (cycles per second). Lower = lazier drift.",
    "wow_depth": "How far the slow sway bends pitch. In cents: 100 cents = 1 semitone.",
    "flutter_rate_hz": "How fast the quick shimmer moves. Higher = busier instability.",
    "flutter_depth": "How far the quick shimmer bends pitch (usually smaller than wow).",
    "randomness": "Extra organic variation in the wobble phase (0 = steady, 1 = more unpredictable).",
    "humanization_range": "Max velocity bump up/down so notes aren't all the same loudness.",
    "depth_units": "Measure for wow/flutter depth: cents (recommended) or semitones.",
}


def list_presets() -> List[Dict[str, Any]]:
    return [EFFECT_PRESETS[key] for key in EFFECT_PRESETS]


def get_preset(preset_id: str) -> Dict[str, Any]:
    return EFFECT_PRESETS.get(preset_id, EFFECT_PRESETS["clean"])


def normalize_preset_ids(
    raw: Any,
    *,
    default: str = "tape_and_human",
) -> Tuple[str, ...]:
    """Accept one id, a comma string, or a sequence. Drop unknown ids."""
    if raw is None:
        parts: List[str] = []
    elif isinstance(raw, (list, tuple, set)):
        parts = [str(p).strip() for p in raw]
    else:
        parts = [
            p.strip()
            for p in str(raw).replace(";", ",").split(",")
            if p.strip()
        ]
    seen: List[str] = []
    for pid in parts:
        if pid in EFFECT_PRESETS and pid not in seen:
            seen.append(pid)
    if "clean" in seen and len(seen) > 1:
        seen = [pid for pid in seen if pid != "clean"]
    if not seen:
        fallback = default if default in EFFECT_PRESETS else "tape_and_human"
        return (fallback,)
    return tuple(seen)


def serialize_preset_ids(raw: Any, *, default: str = "tape_and_human") -> str:
    return ",".join(normalize_preset_ids(raw, default=default))


def format_preset_labels(raw: Any, *, default: str = "tape_and_human") -> str:
    ids = normalize_preset_ids(raw, default=default)
    return " + ".join(str(EFFECT_PRESETS[pid]["label"]) for pid in ids)


def build_effects_config(
    preset_id: Union[str, Sequence[str]],
    overrides: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Build effects_config list for create_arp / EffectRegistry.

    preset_id may be one id, a comma-joined string, or several ids.
    Same-named effects later in the list replace earlier ones.

    overrides can tweak numeric fields on matching effect names, e.g.
    {"tape_wobble": {"wow_depth": 20}}.
    """
    ids = normalize_preset_ids(preset_id, default="clean")
    merged: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for pid in ids:
        if pid == "clean":
            continue
        for effect in get_preset(pid)["effects"]:
            conf = dict(effect)
            name = str(conf.get("name") or "")
            if not name:
                continue
            if overrides and name in overrides:
                conf.update(overrides[name])
            if name not in merged:
                order.append(name)
            merged[name] = conf
    return [merged[name] for name in order]


def explain_effects_config(effects_config: List[Dict[str, Any]]) -> List[str]:
    """Human-readable bullet lines for a concrete effects_config."""
    if not effects_config:
        return ["Clean: no pitch or velocity processing."]

    lines: List[str] = []
    for conf in effects_config:
        name = conf.get("name")
        if name == "tape_wobble":
            lines.append(
                "Tape wobble: slow sway "
                f"{conf.get('wow_rate_hz', '?')} Hz / {conf.get('wow_depth', '?')} "
                f"{conf.get('depth_units', 'cents')}, "
                f"quick shimmer {conf.get('flutter_rate_hz', '?')} Hz / "
                f"{conf.get('flutter_depth', '?')} "
                f"{conf.get('depth_units', 'cents')} "
                f"(randomness {conf.get('randomness', '?')})."
            )
        elif name == "humanize_velocity":
            lines.append(
                f"Human feel: velocity varies by about ±{conf.get('humanization_range', 10) // 2} "
                "so attacks aren't identical."
            )
        else:
            lines.append(f"{name}: {conf}")
    return lines
