"""
Lightweight local preference store for Style Lab transport options.

Persists count-in / loop / soft-click / last MIDI port across Streamlit
session restarts. No cloud sync — JSON under the user config directory
(or a project-local fallback if home is unwritable).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

# Sensible first-run defaults (instant silent audition).
DEFAULT_PREFS: Dict[str, Any] = {
    "live_count_in": False,
    "live_loop": False,
    "live_soft_click": False,
    "live_sync_logic": True,
    "live_port": None,
}

_BOOL_KEYS = ("live_count_in", "live_loop", "live_soft_click", "live_sync_logic")


def prefs_path() -> Path:
    """Prefer ``~/.midi_gen/ui_prefs.json``; fall back to project-local."""
    home = Path.home() / ".midi_gen" / "ui_prefs.json"
    try:
        home.parent.mkdir(parents=True, exist_ok=True)
        # Probe writability without leaving junk.
        probe = home.parent / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return home
    except OSError:
        return Path(__file__).resolve().parent / ".midi_gen_ui_prefs.json"


def load_prefs(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load prefs merged over defaults. Corrupt / missing → defaults."""
    target = path or prefs_path()
    out = dict(DEFAULT_PREFS)
    try:
        if not target.is_file():
            return out
        raw = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return out
        for key in _BOOL_KEYS:
            if key in raw:
                out[key] = bool(raw[key])
        port = raw.get("live_port")
        out["live_port"] = str(port) if port else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return dict(DEFAULT_PREFS)
    return out


def save_prefs(updates: Dict[str, Any], path: Optional[Path] = None) -> Path:
    """
    Merge ``updates`` into on-disk prefs and write atomically.

    Unknown keys are ignored. Returns the path written.
    """
    target = path or prefs_path()
    current = load_prefs(target)
    for key in _BOOL_KEYS:
        if key in updates:
            current[key] = bool(updates[key])
    if "live_port" in updates:
        port = updates["live_port"]
        current["live_port"] = str(port) if port else None
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(current, indent=2, sort_keys=True) + "\n"
    # Atomic replace so a crash mid-write does not corrupt the store.
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, target)
    return target


def prefs_for_session(ports: Optional[list] = None) -> Dict[str, Any]:
    """
    Prefs suitable for seeding ``st.session_state``.

    Drops a remembered port that is no longer in ``ports`` (when provided).
    """
    prefs = load_prefs()
    port = prefs.get("live_port")
    if ports is not None and port and port not in ports:
        prefs["live_port"] = None
    return prefs
