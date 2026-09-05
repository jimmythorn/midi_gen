"""
MIDI Style Lab — Streamlit UI for style → sketch → Logic.

North star: Pick style → Generate → Play into Logic → Download MIDI.

Launch:
  ./run_ui.sh
  # or
  PYTHONPATH=. streamlit run ui_app.py
"""

from __future__ import annotations

import importlib
import os
import sys
import types
from datetime import timedelta
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
if "midi_gen" not in sys.modules:
    _pkg = types.ModuleType("midi_gen")
    _pkg.__path__ = [str(_ROOT)]  # type: ignore[attr-defined]
    _pkg.__file__ = str(_ROOT / "__init__.py")
    sys.modules["midi_gen"] = _pkg

import streamlit as st

from midi_gen.audio_preview import render_midi_to_wav_bytes
from midi_gen.artist_gate import ArtistRejected
from midi_gen.cursor_style_lookup import cursor_sdk_available, generate_midi_for_style
from midi_gen.effects_presets import (
    EFFECT_PARAM_HELP,
    build_effects_config,
    explain_effects_config,
    list_presets,
    normalize_preset_ids,
    serialize_preset_ids,
)
from midi_gen.note_edit import (
    list_note_events,
    refresh_last_run_after_note_write,
    write_note_events,
)
from midi_gen.note_editor import note_editor
from midi_gen.live_midi import (
    get_shared_player,
    has_iac_port,
    port_looks_like_iac,
    preferred_iac_port,
    refresh_output_ports,
)
from midi_gen.musician_styles import list_musicians, list_styles
from midi_gen.preview import format_summary_text, summarize_midi_file
from midi_gen import style_prompting as _style_prompting

importlib.reload(_style_prompting)
from midi_gen.style_prompting import (
    ARTIST_REJECT_DRIP,
    DEFAULT_GENERATION_MODE,
    DEFAULT_SEARCH_KIND,
    DEFAULT_TIMING_FACTOR,
    GENERATION_MODES,
    SECTION_CHIP_LABELS,
    TIMING_CHIP_LABELS,
    artist_reject_drip_copy,
    DEFAULT_CHORD_COUNT,
    DEFAULT_GENERATION_TYPE,
    DEFAULT_SKETCH_BARS,
    clamp_bars,
    clamp_chord_count,
    clamp_extend_factor,
    clamp_generation_mode,
    clamp_generation_type,
    clamp_search_kind,
    clamp_timing_factor,
    featured_style_cards,
    format_generation_mode_label,
    format_likeness_blurb,
    format_match_line,
    format_plain_feel_match,
    generation_mode_from_type,
    preview_recipe,
    artist_gate_blocks_generate,
    artist_gate_wipes_sketch,
    resolve_artist_gate_for_ui,
    resolve_lookup_inputs,
    session_clears_on_artist_reject,
    surprise_roll,
    toggle_section_chip,
    toggle_timing_factor,
)
from midi_gen.ui_prefs import load_prefs, prefs_for_session, save_prefs

ARP_MODE_LABELS = {
    "up": "Up",
    "down": "Down",
    "up_down": "Up/down",
    "random": "Random",
    "order": "Order",
}
ARP_STEP_CHOICES = [4, 8, 16]
ARP_OCTAVE_CHOICES = [1, 2, 3]
_ARP_KEYS = (
    "arp_mode",
    "arp_steps",
    "arp_range_octaves",
    "arp_evolve",
    "arp_repeat",
    "sketch_bpm",
    "arp_gates",
    "arp_pitches",
)
_FX_SLIDER_SPEC = {
    "wow_rate_hz": (0.05, 2.0, 0.05),
    "wow_depth": (0, 50, 1),
    "flutter_rate_hz": (1.0, 16.0, 0.5),
    "flutter_depth": (0, 16, 1),
    "randomness": (0.0, 1.0, 0.05),
    "humanization_range": (0, 32, 1),
}


def _load_repo_dotenv() -> None:
    """Load .env without importing new names from a possibly stale lookup module."""
    env_path = _ROOT / ".env"
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


_load_repo_dotenv()


def _cursor_api_key_present() -> bool:
    """True when CURSOR_API_KEY is set (dotenv already loaded)."""
    return bool(os.environ.get("CURSOR_API_KEY", "").strip())


def _persist_live_prefs() -> None:
    """Write transport prefs (count-in / loop / soft-click / port) to disk."""
    updates = {
        "live_count_in": bool(st.session_state.get("live_count_in", False)),
        "live_loop": bool(st.session_state.get("live_loop", True)),
        "live_soft_click": bool(st.session_state.get("live_soft_click", False)),
        "live_sync_logic": bool(st.session_state.get("live_sync_logic", False)),
    }
    # Only write port once session has one — avoid wiping a remembered bus
    # before ports are enumerated on first paint.
    if "live_port" in st.session_state:
        updates["live_port"] = st.session_state.get("live_port")
    save_prefs(updates)


def _clear_stuck_logic_lock() -> None:
    """Old default waited for MIDI Start and disabled Play. Unlock once."""
    if st.session_state.get("_logic_lock_off_v1"):
        return
    st.session_state["live_sync_logic"] = False
    st.session_state["_logic_lock_off_v1"] = True
    player = get_shared_player()
    if player.playing or player.phase in ("syncing", "count_in", "playing"):
        player.stop(wait=True)
        st.session_state["live_was_playing"] = False
        st.session_state["live_message"] = (
            "Play streams notes now. Record in Logic is a separate button."
        )
    _persist_live_prefs()


def _seed_transport_bool_prefs() -> None:
    """Seed count-in / loop / soft-click / Logic-lock from disk."""
    if st.session_state.get("_live_bool_prefs_seeded"):
        return
    prefs = load_prefs()
    if "live_count_in" not in st.session_state:
        st.session_state["live_count_in"] = bool(prefs.get("live_count_in", False))
    if "live_loop" not in st.session_state:
        st.session_state["live_loop"] = bool(prefs.get("live_loop", True))
    if "live_soft_click" not in st.session_state:
        st.session_state["live_soft_click"] = bool(prefs.get("live_soft_click", False))
    if "live_sync_logic" not in st.session_state:
        st.session_state["live_sync_logic"] = bool(prefs.get("live_sync_logic", False))
    st.session_state["_live_bool_prefs_seeded"] = True


def _seed_live_port(ports: list[str]) -> None:
    """Apply remembered MIDI port once ports are known (drop stale names)."""
    if "live_port" in st.session_state:
        current = st.session_state.get("live_port")
        if current and ports and current not in ports:
            st.session_state.pop("live_port", None)
        else:
            return
    prefs = prefs_for_session(ports)
    remembered = prefs.get("live_port")
    if remembered and remembered in ports:
        st.session_state["live_port"] = remembered


def _reset_arp_knobs() -> None:
    for key in _ARP_KEYS:
        st.session_state.pop(key, None)
    st.session_state.pop("effects_overrides", None)
    for key in list(st.session_state.keys()):
        if str(key).startswith("fx_lvl_"):
            st.session_state.pop(key, None)


def _on_generate_click() -> None:
    """User Generate — the only home path that writes a sketch."""
    _reset_arp_knobs()
    if st.session_state.get("last_run"):
        st.session_state["_live_param_tweak"] = True
    st.session_state["auto_generate"] = True


def _apply_search_kind(kind: str) -> None:
    kind = clamp_search_kind(kind)
    st.session_state["search_kind"] = kind
    st.session_state["search_kind_tabs"] = "Artist" if kind == "artist" else "Mood"


def _on_search_kind_tabs() -> None:
    label = str(st.session_state.get("search_kind_tabs") or "Artist").strip()
    st.session_state["search_kind"] = "artist" if label == "Artist" else "mood"


def _apply_featured_style(name: str) -> None:
    """Select a featured catalog name. Feel stays layered on."""
    st.session_state["catalog_pick"] = name
    _apply_search_kind("artist")
    _reset_arp_knobs()
    st.session_state.pop("spotify_artist_name", None)
    st.session_state.pop("ui_takeover", None)


def _on_catalog_pick_change() -> None:
    """Artist change keeps the current feel (additive)."""
    _reset_arp_knobs()
    st.session_state.pop("spotify_artist_name", None)


def _render_catalog_selectbox(names: list[str]) -> None:
    if st.session_state.get("catalog_pick") not in names:
        st.session_state["catalog_pick"] = None
    st.selectbox(
        "Style (catalog — who)",
        options=names,
        index=None,
        placeholder="Select an artist…",
        help="Named musician/style profiles from the full curated catalog.",
        key="catalog_pick",
        on_change=_on_catalog_pick_change,
    )
    _render_who_caption()


def _apply_section_chip(role: str) -> None:
    st.session_state["section_role"] = toggle_section_chip(
        st.session_state.get("section_role"), role
    )


def _on_section_select() -> None:
    raw = st.session_state.get("home_section_select")
    st.session_state["section_role"] = raw or None


def _apply_timing_factor(factor: float) -> None:
    st.session_state["timing_factor"] = toggle_timing_factor(
        st.session_state.get("timing_factor", DEFAULT_TIMING_FACTOR), factor
    )


def _on_timing_select() -> None:
    st.session_state["timing_factor"] = clamp_timing_factor(
        st.session_state.get("home_timing_select")
    )


def _apply_generation_mode(mode: str) -> None:
    st.session_state["generation_mode"] = clamp_generation_mode(mode)
    # Keep legacy shape key aligned for Length takeover / sketch layout.
    st.session_state["generation_type"] = (
        "arpeggio" if st.session_state["generation_mode"] == "pattern" else "drone"
    )


def _on_generation_mode_select() -> None:
    _apply_generation_mode(st.session_state.get("home_mode_select"))


# --- One-page chrome: home stays sacred; extras are full-screen takeovers ---
# Browse / Mood / Capture moved onto home (mood chips + Play/Record tab).
TAKEOVER_LABELS = {
    "geek": "Geek",
}
TAKEOVER_TITLES = {
    **TAKEOVER_LABELS,
    "debug": "Debug",
}


def _open_takeover(name: str) -> None:
    st.session_state["ui_takeover"] = name


def _close_takeover() -> None:
    st.session_state.pop("ui_takeover", None)


HOME_TAB_SEARCH = "Search + Preview"
HOME_TAB_PLAY = "Play / Record"


def _queue_play_record_tab() -> None:
    st.session_state["_open_play_tab"] = True


def _apply_pending_home_tab() -> None:
    if st.session_state.pop("_open_play_tab", False):
        st.session_state["home_tabs"] = HOME_TAB_PLAY


def _toggle_geek() -> None:
    if st.session_state.get("ui_takeover") == "geek":
        st.session_state.pop("ui_takeover", None)
    else:
        st.session_state["ui_takeover"] = "geek"


def _persist_widget_keys() -> None:
    """Streamlit deletes unbound widget keys; mirror them so takeovers don't wipe state."""
    pairs = (
        ("vibe_text", ""),
        ("catalog_pick", None),
        ("search_kind", DEFAULT_SEARCH_KIND),
        ("bars", DEFAULT_SKETCH_BARS),
        ("chord_count", DEFAULT_CHORD_COUNT),
        ("generation_type", DEFAULT_GENERATION_TYPE),
        ("generation_mode", DEFAULT_GENERATION_MODE),
        ("section_role", None),
        ("extend_factor", 1),
        ("timing_factor", DEFAULT_TIMING_FACTOR),
        ("effects_preset", "tape_and_human"),
        ("use_sdk", _cursor_api_key_present()),
        ("sketch_bpm", None),
        ("arp_mode", None),
        ("arp_steps", None),
        ("arp_range_octaves", None),
        ("arp_evolve", None),
        ("arp_repeat", None),
        ("live_count_in", False),
        ("live_loop", True),
        ("live_soft_click", False),
        ("live_sync_logic", False),
        ("live_port", None),
    )
    for key, default in pairs:
        shadow = f"_persist_{key}"
        if key in st.session_state:
            st.session_state[shadow] = st.session_state[key]
        elif shadow in st.session_state:
            st.session_state[key] = st.session_state[shadow]
        elif default is not None:
            st.session_state[key] = default
            st.session_state[shadow] = default
    # Normalize section / timing after mirror (None = chips off).
    # Widget-bound keys (search_kind select) must not be reassigned after instantiate —
    # only refresh their shadow mirrors.
    role = st.session_state.get("section_role")
    if role is not None and not str(role).strip():
        st.session_state["section_role"] = None
        st.session_state["_persist_section_role"] = None
    st.session_state["extend_factor"] = clamp_extend_factor(
        st.session_state.get("extend_factor", 1)
    )
    st.session_state["_persist_extend_factor"] = st.session_state["extend_factor"]
    st.session_state["timing_factor"] = clamp_timing_factor(
        st.session_state.get("timing_factor", DEFAULT_TIMING_FACTOR)
    )
    st.session_state["_persist_timing_factor"] = st.session_state["timing_factor"]
    st.session_state["generation_mode"] = clamp_generation_mode(
        st.session_state.get("generation_mode", DEFAULT_GENERATION_MODE)
    )
    st.session_state["_persist_generation_mode"] = st.session_state["generation_mode"]
    st.session_state["_persist_search_kind"] = clamp_search_kind(
        st.session_state.get("search_kind", DEFAULT_SEARCH_KIND)
    )
    # Map legacy takeover names from older sessions.
    legacy = st.session_state.get("ui_takeover")
    if legacy == "advanced":
        st.session_state["ui_takeover"] = "debug"
    elif legacy in ("browse", "moods", "capture", "more", "length", "effects"):
        st.session_state.pop("ui_takeover", None)


def _render_who_caption() -> None:
    pick = str(st.session_state.get("catalog_pick") or "").strip()
    vibe = str(st.session_state.get("vibe_text") or "").strip()
    spotify_name = str(st.session_state.get("spotify_artist_name") or "").strip()
    if pick and vibe:
        st.caption(f"Selected · **{pick}** + **{vibe}**")
    elif pick:
        st.caption(f"Selected · **{pick}**")
    elif spotify_name:
        if vibe and vibe.lower() != spotify_name.lower():
            st.caption(f"Selected · **{spotify_name}** · {vibe}")
        else:
            st.caption(f"Selected · **{spotify_name}**")
    elif vibe:
        st.caption(f"Selected · **{vibe}**")


def _render_takeover_header(title: str) -> None:
    st.markdown(
        f"""
        <div class="takeover-shell">
          <div class="takeover-kicker">Full screen</div>
          <h2 class="takeover-title">{title}</h2>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.button(
        "← Back",
        key="takeover_back",
        use_container_width=False,
        on_click=_close_takeover,
        type="primary",
    )


def _render_home_header() -> None:
    """Brand + Debug in the hero header. Debug stays off the chrome row."""
    st.markdown('<div class="hero">', unsafe_allow_html=True)
    brand_col, debug_col = st.columns([6, 1])
    with brand_col:
        st.markdown(
            '<div class="brand-mark">MIDI Style Lab</div>',
            unsafe_allow_html=True,
        )
    with debug_col:
        st.markdown('<div class="header-debug">', unsafe_allow_html=True)
        st.button(
            "Debug",
            key="takeover_debug",
            use_container_width=True,
            on_click=_open_takeover,
            args=("debug",),
        )
        st.markdown("</div>", unsafe_allow_html=True)
    st.markdown(
        "<h1>Pick a style. Generate a sketch. Play it into Logic.</h1>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)


def _render_geek_entry(*, has_sketch: bool) -> None:
    """Geek toggle — Play / Record content stack only."""
    open_geek = st.session_state.get("ui_takeover") == "geek"
    st.markdown('<div class="geek-entry">', unsafe_allow_html=True)
    geek_col, _ = st.columns([1, 4])
    with geek_col:
        st.button(
            f"{'● ' if open_geek else ''}{TAKEOVER_LABELS['geek']}",
            key="takeover_geek",
            use_container_width=True,
            disabled=not has_sketch,
            on_click=_toggle_geek,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def _apply_surprise(name: str, profile_id: str, effects_preset: str) -> None:
    st.session_state["last_surprise_id"] = profile_id
    st.session_state["pending_related_name"] = name
    chosen = list(normalize_preset_ids(effects_preset))
    st.session_state["effects_presets"] = chosen
    st.session_state["effects_preset"] = serialize_preset_ids(chosen)
    _reset_arp_knobs()


def _apply_arp_live() -> None:
    """Rewrite the sketch from arp knobs; keep streaming if already Playing."""
    if not st.session_state.get("last_run"):
        return
    st.session_state["_live_param_tweak"] = True
    st.session_state["auto_generate"] = True
    if get_shared_player().playing:
        st.session_state["pending_replay"] = True


def _parse_fx_lvl_key(key: str) -> tuple[str, str] | None:
    if not str(key).startswith("fx_lvl_"):
        return None
    rest = str(key)[len("fx_lvl_") :]
    for param in _FX_SLIDER_SPEC:
        suffix = "_" + param
        if rest.endswith(suffix):
            return rest[: -len(suffix)], param
    return None


def _apply_effect_level() -> None:
    overrides: dict[str, dict[str, Any]] = {}
    for key in list(st.session_state.keys()):
        parsed = _parse_fx_lvl_key(str(key))
        if not parsed:
            continue
        name, param = parsed
        overrides.setdefault(name, {})[param] = st.session_state[key]
    st.session_state["effects_overrides"] = overrides
    st.session_state["_live_param_tweak"] = True
    st.session_state["auto_generate"] = True
    if get_shared_player().playing:
        st.session_state["pending_replay"] = True


def _commit_note_edits(notes: list) -> None:
    last_run = st.session_state.get("last_run")
    if not last_run:
        return
    refresh_last_run_after_note_write(last_run, notes, dirty=True)
    if get_shared_player().playing:
        st.session_state["pending_replay"] = True


def _reset_generated_notes() -> None:
    last_run = st.session_state.get("last_run")
    if not last_run:
        return
    generated = last_run.get("generated_notes") or []
    refresh_last_run_after_note_write(
        last_run, [dict(n) for n in generated], dirty=False
    )
    if get_shared_player().playing:
        st.session_state["pending_replay"] = True


def _seed_arp_knobs(profile: Any) -> None:
    """Fill arp widgets from the current recipe until the user touches them."""
    mode = getattr(profile, "arp_mode", "up_down")
    if mode not in ARP_MODE_LABELS:
        mode = "up_down"
    steps = int(getattr(profile, "arp_steps", 8) or 8)
    if steps not in ARP_STEP_CHOICES:
        steps = 8
    octaves = int(getattr(profile, "range_octaves", 1) or 1)
    if octaves not in ARP_OCTAVE_CHOICES:
        octaves = 1
    evolve = float(getattr(profile, "evolution_rate", 0.15) or 0.0)
    evolve = max(0.0, min(1.0, evolve))
    lock = int(getattr(profile, "repetition_factor", 7) or 7)
    lock = max(1, min(10, lock))
    bpm = int(getattr(profile, "bpm", 120) or 120)
    bpm = max(40, min(240, bpm))
    if "sketch_bpm" not in st.session_state:
        st.session_state["sketch_bpm"] = bpm
    if "arp_mode" not in st.session_state:
        st.session_state["arp_mode"] = mode
    if "arp_steps" not in st.session_state:
        st.session_state["arp_steps"] = steps
    if "arp_range_octaves" not in st.session_state:
        st.session_state["arp_range_octaves"] = octaves
    if "arp_evolve" not in st.session_state:
        st.session_state["arp_evolve"] = evolve
    if "arp_repeat" not in st.session_state:
        st.session_state["arp_repeat"] = lock


def _knobs_from_profile(profile: Any) -> dict[str, Any]:
    """Session values so live knobs match a researched recipe."""
    mode = getattr(profile, "arp_mode", "up_down")
    if mode not in ARP_MODE_LABELS:
        mode = "up_down"
    steps = int(getattr(profile, "arp_steps", 8) or 8)
    if steps not in ARP_STEP_CHOICES:
        steps = 8
    octaves = int(getattr(profile, "range_octaves", 1) or 1)
    if octaves not in ARP_OCTAVE_CHOICES:
        octaves = 1
    evolve = float(getattr(profile, "evolution_rate", 0.15) or 0.0)
    evolve = max(0.0, min(1.0, evolve))
    lock = int(getattr(profile, "repetition_factor", 7) or 7)
    lock = max(1, min(10, lock))
    bpm = int(getattr(profile, "bpm", 120) or 120)
    bpm = max(40, min(240, bpm))
    fx = str(getattr(profile, "effects_preset", "") or "")
    out: dict[str, Any] = {
        "sketch_bpm": bpm,
        "arp_mode": mode,
        "arp_steps": steps,
        "arp_range_octaves": octaves,
        "arp_evolve": evolve,
        "arp_repeat": lock,
    }
    if fx:
        chosen = list(normalize_preset_ids(fx))
        out["effects_preset"] = serialize_preset_ids(chosen)
        out["effects_presets"] = chosen
    return out


def _render_arp_live(profile: Any) -> None:
    """Play / Record arp knobs when Pattern is selected. BPM lives in Debug."""
    _ = profile
    mode = clamp_generation_mode(
        st.session_state.get("generation_mode")
        or st.session_state.get("home_mode_select")
        or DEFAULT_GENERATION_MODE
    )
    if mode != "pattern":
        return
    st.markdown(
        '<p class="feel-path-label">Arp</p>',
        unsafe_allow_html=True,
    )
    st.caption("Mess with these while Playing — sketch rewrites and keeps streaming.")
    dir_col, step_col, oct_col = st.columns(3)
    with dir_col:
        st.selectbox(
            "Direction",
            options=list(ARP_MODE_LABELS.keys()),
            format_func=lambda key: ARP_MODE_LABELS.get(key, key),
            key="arp_mode",
            on_change=_apply_arp_live,
            help="Note order inside the cell.",
        )
    with step_col:
        st.selectbox(
            "Steps",
            options=ARP_STEP_CHOICES,
            key="arp_steps",
            on_change=_apply_arp_live,
            help="4 = quarters, 8 = 8ths, 16 = 16ths per bar.",
        )
    with oct_col:
        st.selectbox(
            "Octaves",
            options=ARP_OCTAVE_CHOICES,
            key="arp_range_octaves",
            on_change=_apply_arp_live,
            help="How far the pattern climbs from the root.",
        )
    ev_col, lock_col = st.columns(2)
    with ev_col:
        st.slider(
            "Evolve",
            min_value=0.0,
            max_value=1.0,
            step=0.05,
            key="arp_evolve",
            on_change=_apply_arp_live,
            help="Chance the cell mutates as bars pass. 0 = static.",
        )
    with lock_col:
        st.slider(
            "Lock",
            min_value=1,
            max_value=10,
            step=1,
            key="arp_repeat",
            on_change=_apply_arp_live,
            help="How repetitive the cell stays. 10 = most locked.",
        )
    steps = int(st.session_state.get("arp_steps") or 8)
    gates = st.session_state.get("arp_gates")
    if not isinstance(gates, list) or len(gates) != steps:
        prev = list(gates) if isinstance(gates, list) else []
        st.session_state["arp_gates"] = (prev + [True] * steps)[:steps]
    pitches = st.session_state.get("arp_pitches")
    if not isinstance(pitches, list) or len(pitches) != steps:
        prev = list(pitches) if isinstance(pitches, list) else []
        st.session_state["arp_pitches"] = (prev + [None] * steps)[:steps]
    payload = note_editor(
        mode="steps",
        steps=steps,
        gates=list(st.session_state["arp_gates"]),
        pitches=list(st.session_state["arp_pitches"]),
        key="arp_seq",
    )
    if (
        payload
        and payload.get("mode") == "steps"
        and payload != st.session_state.get("_arp_seq_last")
    ):
        st.session_state["_arp_seq_last"] = payload
        st.session_state["arp_gates"] = list(payload.get("gates") or [])
        st.session_state["arp_pitches"] = list(payload.get("pitches") or [])
        _apply_arp_live()


def _render_section_select(*, key: str = "home_section_select") -> None:
    """Intro / Verse / Pre-chorus / Chorus / Bridge / Outro. Off until picked."""
    labels = {role: name for role, name in SECTION_CHIP_LABELS}
    options = [role for role, _ in SECTION_CHIP_LABELS]
    current = str(st.session_state.get("section_role") or "")
    if current not in options:
        current = None
    if key not in st.session_state:
        st.session_state[key] = current
    st.selectbox(
        "Song part",
        options=options,
        format_func=lambda role: labels.get(role, role),
        key=key,
        on_change=_on_section_select,
        help="Sketch a section fingerprint when the catalog has one. Typed “ELO bridge” still works.",
    )


def _render_timing_select(*, key: str = "home_timing_select") -> None:
    """Double / 1× / Half / Quarter → Engine timing_factor."""
    current = clamp_timing_factor(
        st.session_state.get("timing_factor", DEFAULT_TIMING_FACTOR)
    )
    factors = [factor for factor, _ in TIMING_CHIP_LABELS]
    labels = {factor: name for factor, name in TIMING_CHIP_LABELS}
    if key not in st.session_state:
        st.session_state[key] = current
    st.selectbox(
        "Timing",
        options=factors,
        format_func=lambda factor: labels.get(factor, str(factor)),
        key=key,
        on_change=_on_timing_select,
        help=(
            "Double = faster (half bars per chord). "
            "Half / Quarter hold each chord longer. "
            "1× = normal."
        ),
    )


def _render_generation_mode_select(*, key: str = "home_mode_select") -> None:
    """Pattern | Progression → Engine apply_generation_mode."""
    current = clamp_generation_mode(
        st.session_state.get("generation_mode", DEFAULT_GENERATION_MODE)
    )
    if key not in st.session_state:
        st.session_state[key] = current
    st.selectbox(
        "Pattern | Progression",
        options=list(GENERATION_MODES),
        format_func=format_generation_mode_label,
        key=key,
        on_change=_on_generation_mode_select,
        help=(
            "Pattern walks an arpeggio. Progression holds each chord. "
            "Does not rewrite who / fingerprint. "
            "Wash recipes that opt out of held chords still win."
        ),
    )


def _render_part_and_timing_row() -> None:
    """Song part + Timing + Pattern|Progression in one row under Search."""
    st.markdown('<div class="search-control-row">', unsafe_allow_html=True)
    part_col, timing_col, shape_col = st.columns(3, gap="small")
    with part_col:
        _render_section_select(key="home_section_select")
    with timing_col:
        _render_timing_select(key="home_timing_select")
    with shape_col:
        _render_generation_mode_select(key="home_mode_select")
    st.markdown("</div>", unsafe_allow_html=True)


def _render_sketch_layout() -> None:
    """Bars and chord count — both Pattern and Progression."""
    st.markdown(
        '<p class="feel-path-label">Sketch</p>',
        unsafe_allow_html=True,
    )
    bar_col, chord_col = st.columns(2)
    with bar_col:
        st.slider(
            "Bars",
            min_value=2,
            max_value=32,
            step=1,
            key="bars",
            help="Sketch length. 16 bars / 4 chords = 4 bars each. Press Generate to apply.",
        )
    with chord_col:
        st.slider(
            "Chords",
            min_value=1,
            max_value=8,
            step=1,
            key="chord_count",
            help="How many roots in the loop. Press Generate to apply.",
        )
    can_generate = bool(
        str(st.session_state.get("catalog_pick") or "").strip()
        or str(st.session_state.get("vibe_text") or "").strip()
    )
    st.button(
        "Generate",
        key="home_generate",
        use_container_width=True,
        type="primary",
        disabled=not can_generate or bool(st.session_state.get("auto_generate")),
        on_click=_on_generate_click if can_generate else None,
        help="Write a sketch from the search and sketch controls.",
    )


def _render_featured_styles() -> None:
    st.caption("Tap a name to select that catalog profile — not a closed list; full catalog below.")
    feat_cols = st.columns(3)
    for i, card in enumerate(featured_cards):
        with feat_cols[i % 3]:
            selected = st.session_state.get("catalog_pick") == card.name
            st.button(
                f"{'● ' if selected else ''}{card.name}",
                key=f"feat_{card.id}",
                use_container_width=True,
                type="primary" if selected else "secondary",
                on_click=_apply_featured_style,
                args=(card.name,),
            )
            st.markdown(f'<p class="featured-blurb">{card.blurb}</p>', unsafe_allow_html=True)


def _replay_into_logic(player: Any, run: dict, ports: list[str]) -> None:
    """Restart Play after a live arp rewrite. No count-in — keep the stream instant."""
    port = st.session_state.get("live_port")
    if port and ports and port not in ports:
        port = None
    if not port:
        port = preferred_iac_port(ports) or (ports[0] if ports else None)
    if not port:
        st.session_state["live_message"] = "Arp updated — pick a MIDI port to keep playing."
        return
    try:
        opts = run["options"]
        player.play_file(
            run["path"],
            port,
            count_in_bars=0.0,
            bpm=float(opts.get("bpm") or 120),
            bars=float(opts.get("bars") or 8),
            loop=bool(st.session_state.get("live_loop", True)),
            click=False,
            sync="follow" if st.session_state.get("live_sync_logic", False) else "internal",
            send_clock=not bool(st.session_state.get("live_sync_logic", False)),
        )
        st.session_state["live_was_playing"] = True
        st.session_state["live_message"] = f"Streaming to {player.port_name}."
        st.session_state["iac_tip_dismissed"] = True
    except Exception as exc:
        st.session_state["live_message"] = f"Live MIDI failed: {exc}"
        st.session_state["live_was_playing"] = bool(player.playing)


def _apply_effects_preset(pid: str) -> None:
    current = list(
        normalize_preset_ids(
            st.session_state.get("effects_presets")
            or st.session_state.get("effects_preset")
            or "tape_and_human"
        )
    )
    if pid == "clean":
        chosen = ["clean"]
    elif pid in current:
        chosen = [item for item in current if item != pid and item != "clean"]
        if not chosen:
            chosen = ["clean"]
    else:
        chosen = [item for item in current if item != "clean"] + [pid]
    st.session_state["effects_presets"] = chosen
    st.session_state["effects_preset"] = serialize_preset_ids(chosen, default="clean")
    if chosen == ["clean"] or pid == "clean":
        st.session_state["effects_overrides"] = {}
        for key in list(st.session_state.keys()):
            if str(key).startswith("fx_lvl_"):
                st.session_state.pop(key, None)


def _apply_refresh_ports() -> None:
    player = get_shared_player()
    if player.playing:
        return
    st.session_state["refresh_midi_ports"] = True
    refreshed = refresh_output_ports()
    _apply_refreshed_ports(refreshed)
    st.session_state["live_message"] = (
        f"Ports refreshed · {len(refreshed)} available."
        if refreshed
        else "No ports yet — enable IAC, then Refresh again."
    )


st.set_page_config(
    page_title="MIDI Style Lab",
    page_icon="🎛",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Studio-tool look: graphite + acid lime (avoid purple / cream-terracotta defaults)
st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

      :root {
        --ink: #12151a;
        --panel: #1c2129;
        --line: #2c3440;
        --text: #e8edf2;
        --muted: #9aa6b2;
        --accent: #c8f560;
        --accent-ink: #12151a;
      }

      .stApp {
        background:
          radial-gradient(1200px 600px at 10% -10%, #243047 0%, transparent 55%),
          radial-gradient(900px 500px at 100% 0%, #1a2a22 0%, transparent 50%),
          var(--ink);
        color: var(--text);
        font-family: "IBM Plex Sans", sans-serif;
      }

      h1, h2, h3, .brand-mark {
        font-family: "Space Grotesk", sans-serif !important;
        letter-spacing: -0.02em;
      }

      .hero {
        padding: 1.25rem 0 0.5rem 0;
        max-width: 920px;
      }
      .header-debug button {
        font-size: 0.75rem !important;
        min-height: 2rem !important;
        margin-top: 0.05rem !important;
      }
      .brand-mark {
        font-size: 0.85rem;
        font-weight: 700;
        color: var(--accent);
        text-transform: uppercase;
        letter-spacing: 0.14em;
        margin-bottom: 0.65rem;
      }
      .hero h1 {
        font-size: clamp(2.2rem, 5vw, 3.4rem) !important;
        line-height: 1.05 !important;
        margin: 0 0 0.6rem 0 !important;
        color: var(--text) !important;
      }
      .hero p {
        color: var(--muted);
        font-size: 1.05rem;
        max-width: 38rem;
        margin: 0 0 1.25rem 0;
      }

      .tip {
        border-left: 3px solid var(--accent);
        padding: 0.65rem 0.85rem;
        margin: 0.75rem 0 1rem 0;
        background: color-mix(in srgb, var(--panel) 88%, black);
        border-radius: 0 10px 10px 0;
        color: var(--muted);
        font-size: 0.95rem;
        max-width: 40rem;
      }
      .tip strong { color: var(--text); }

      .iac-chip {
        display: inline-block;
        font-size: 0.82rem;
        font-weight: 600;
        letter-spacing: 0.02em;
        padding: 0.28rem 0.65rem;
        border-radius: 6px;
        margin: 0.15rem 0 0.55rem 0;
      }
      .iac-chip.ok {
        background: color-mix(in srgb, var(--accent) 22%, var(--panel));
        color: var(--accent);
      }
      .iac-chip.miss {
        background: color-mix(in srgb, #e07a5f 18%, var(--panel));
        color: #f0b4a4;
      }

      /* Capture / Play context (Audition strip dropped) */
      .audition-capture {
        border: 1px solid var(--line);
        border-radius: 14px;
        background: color-mix(in srgb, var(--panel) 90%, black);
        padding: 0.85rem 1rem 0.95rem 1rem;
        margin: 0.35rem 0 0.65rem 0;
        max-width: 40rem;
      }
      .audition-capture .strip-label {
        color: var(--muted);
        font-size: 0.72rem;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        margin: 0 0 0.55rem 0;
      }
      .audition-capture .pair {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 0.75rem;
        margin: 0 0 0.55rem 0;
      }
      .audition-capture .lane .title {
        font-family: "Space Grotesk", sans-serif;
        font-weight: 600;
        font-size: 1.02rem;
        color: var(--text);
        margin: 0 0 0.15rem 0;
      }
      .audition-capture .lane .sub {
        color: var(--muted);
        font-size: 0.88rem;
        margin: 0;
        line-height: 1.35;
      }
      .audition-capture .order {
        color: var(--muted);
        font-size: 0.88rem;
        margin: 0;
        padding-top: 0.55rem;
        border-top: 1px solid var(--line);
      }
      .audition-capture .order strong { color: var(--text); }

      .play-hero-stack {
        max-width: 16rem;
        margin: 0 0 0.25rem 0;
      }
      @keyframes play-logic-pulse {
        0%, 100% {
          transform: scale(1);
          box-shadow: 0 0 0 1px rgba(18, 21, 26, 0);
        }
        50% {
          transform: scale(1.018);
          box-shadow: 0 0 0 1px rgba(18, 21, 26, 0.1);
        }
      }
      div.st-key-play_logic button,
      div.st-key-play_logic button p,
      div.st-key-play_logic button span {
        font-size: 1.65rem !important;
        font-weight: 700 !important;
        line-height: 1.15 !important;
        white-space: normal !important;
      }
      div.st-key-play_logic button {
        min-height: 7.25rem !important;
        aspect-ratio: 1 / 1;
        border-radius: 14px !important;
        transform-origin: center center;
        animation: play-logic-pulse 2.8s ease-in-out infinite;
      }
      @media (prefers-reduced-motion: reduce) {
        div.st-key-play_logic button {
          animation: none;
        }
      }
      div.st-key-stop_logic button {
        min-height: 2.6rem !important;
        margin-top: 0.4rem !important;
      }

      .silence-check {
        color: var(--muted);
        font-size: 0.86rem;
        margin: 0.45rem 0 0.25rem 0;
        max-width: 40rem;
        line-height: 1.4;
      }
      .silence-check strong { color: var(--text); }

      .metric-row {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 0.75rem;
        margin: 0.75rem 0 1rem 0;
      }
      .metric {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 12px;
        padding: 0.85rem 0.9rem;
      }
      .metric .label {
        color: var(--muted);
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
      }
      .metric .value {
        font-family: "Space Grotesk", sans-serif;
        font-size: 1.35rem;
        font-weight: 700;
        margin-top: 0.2rem;
      }

      .effect-chip {
        border-left: 3px solid var(--accent);
        padding-left: 0.75rem;
        margin-bottom: 0.85rem;
      }
      .effect-chip strong { color: var(--text); }
      .effect-chip span { color: var(--muted); display: block; font-size: 0.92rem; }

      div[data-testid="stSidebar"] {
        background: #0e1116;
        border-right: 1px solid var(--line);
      }

      .stButton > button[kind="primary"] {
        background: var(--accent) !important;
        color: var(--accent-ink) !important;
        border: none !important;
        font-weight: 700 !important;
      }

      .generate-wrap button[kind="primary"] {
        min-height: 3.1rem !important;
        font-size: 1.1rem !important;
        letter-spacing: 0.01em;
        width: 100%;
      }

      .recipe-preview {
        border: 1px solid var(--line);
        border-radius: 12px;
        background: color-mix(in srgb, var(--panel) 92%, black);
        padding: 0.85rem 1rem;
        margin: 0.75rem 0 1rem 0;
        max-width: 40rem;
      }
      .recipe-preview .label {
        color: var(--muted);
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 0.25rem;
      }
      .recipe-preview .line {
        font-family: "Space Grotesk", sans-serif;
        font-size: 1.05rem;
        font-weight: 600;
        color: var(--text);
      }
      .recipe-preview .match {
        color: var(--muted);
        font-size: 0.92rem;
        margin-top: 0.35rem;
      }
      .generate-loading .line::after {
        content: "";
        display: inline-block;
        width: 0.7em;
        height: 0.7em;
        margin-left: 0.55rem;
        border: 2px solid var(--line);
        border-top-color: var(--accent);
        border-radius: 50%;
        vertical-align: -0.1em;
        animation: gen-spin 0.7s linear infinite;
      }
      @keyframes gen-spin {
        to { transform: rotate(360deg); }
      }

      .recipe-preview .feel {
        color: var(--text);
        font-size: 1.0rem;
        margin-top: 0.4rem;
        font-weight: 500;
      }
      .path-hint {
        color: var(--muted);
        font-size: 0.88rem;
        margin: 0.15rem 0 0.65rem 0;
      }
      .feel-path-label {
        font-family: "Space Grotesk", sans-serif;
        font-size: 1.15rem;
        font-weight: 600;
        color: var(--text);
        margin: 0.35rem 0 0.35rem 0;
      }
      div.st-key-vibe_text [data-testid="stTextInputRootElement"] {
        height: auto !important;
        overflow: visible !important;
        width: 100% !important;
      }
      div.st-key-vibe_text [data-testid="stTextInputField"] {
        width: 100% !important;
        box-sizing: border-box !important;
        font-size: 1.35rem !important;
        line-height: 1.4 !important;
        padding: 32px !important;
      }
      .mood-pack-label {
        color: var(--accent);
        font-size: 0.78rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        margin: 0.65rem 0 0.35rem 0;
      }
      .post-feel {
        font-family: "Space Grotesk", sans-serif;
        font-size: 1.15rem;
        font-weight: 600;
        color: var(--text);
        margin: 0 0 0.55rem 0;
      }
      .effect-lite {
        color: var(--muted);
        font-size: 0.82rem;
        margin: 0.15rem 0 0.45rem 0;
      }
      div.st-key-left_controls {
        margin-top: 1.75rem;
        padding-top: 0.35rem;
      }
      div.st-key-left_controls .feel-path-label {
        margin: 0 0 0.9rem 0;
      }
      div.st-key-left_controls .effect-lite {
        margin: 1.6rem 0 0.85rem 0;
      }
      .featured-blurb {
        color: var(--muted);
        font-size: 0.82rem;
        margin: 0.2rem 0 0.55rem 0;
        min-height: 2.2em;
      }
      .bars-chip-row {
        max-width: 40rem;
        margin: 0.25rem 0 0.75rem 0;
      }
      .section-chip-row {
        max-width: 42rem;
        margin: 0.15rem 0 0.65rem 0;
      }
      .extend-chip-row {
        max-width: 28rem;
        margin: 0.15rem 0 0.65rem 0;
      }
      .search-control-row {
        max-width: 52rem;
        margin: 0.35rem 0 0.65rem 0;
      }
      .search-control-row [data-testid="stHorizontalBlock"] {
        align-items: end;
        flex-wrap: nowrap !important;
        gap: 0.65rem;
      }
      .search-control-row [data-testid="column"] {
        min-width: 0 !important;
      }
      .compact-controls {
        max-width: 48rem;
        margin: 0.5rem 0 0.85rem 0;
        padding: 0.55rem 0 0.15rem 0;
        border-top: 1px solid var(--line);
      }
      .compact-controls .feel-path-label {
        font-size: 0.95rem;
        margin: 0.45rem 0 0.25rem 0;
      }

      .geek-entry {
        max-width: 56rem;
        margin: 0 0 0.75rem 0;
      }
      .geek-entry button {
        font-size: 1.05rem !important;
        min-height: 2.85rem !important;
        padding: 0.65rem 1rem !important;
      }
      .takeover-shell {
        max-width: 52rem;
        margin: 0.25rem 0 0.75rem 0;
      }
      .takeover-kicker {
        color: var(--accent);
        font-size: 0.72rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.14em;
        margin: 0 0 0.35rem 0;
      }
      [data-testid="stTabs"] [data-testid="stTab"],
      [data-testid="stTabs"] [data-testid="stTab"] p,
      [data-testid="stTabs"] [data-testid="stTab"] span,
      [data-testid="stTabs"] [data-testid="stTab"] [data-testid="stMarkdownContainer"],
      [data-testid="stTabs"] [data-testid="stTab"] [data-testid="stMarkdownContainer"] p,
      [data-testid="stTabs"] [role="tab"],
      [data-testid="stTabs"] [role="tab"] p,
      [data-testid="stTabs"] [role="tab"] span {
        font-family: "Space Grotesk", sans-serif !important;
        font-size: 1.85rem !important;
        font-weight: 600 !important;
        letter-spacing: -0.02em;
        line-height: 1.2 !important;
      }
      [data-testid="stTabs"] [data-testid="stTab"],
      [data-testid="stTabs"] [role="tab"] {
        padding: 1.35rem 2rem !important;
        min-height: 4.5rem !important;
      }
      [data-testid="stTabs"] [role="tablist"] {
        gap: 0.85rem;
        padding: 0.5rem 0 0.85rem 0;
      }
      [data-testid="stTabPanel"] {
        padding-top: 1.5rem !important;
      }
      div.st-key-search_kind_tabs [data-testid="stTab"],
      div.st-key-search_kind_tabs [data-testid="stTab"] *,
      div.st-key-search_kind_tabs [role="tab"],
      div.st-key-search_kind_tabs [role="tab"] * {
        font-size: 1.15rem !important;
      }
      div.st-key-search_kind_tabs [data-testid="stTab"],
      div.st-key-search_kind_tabs [role="tab"] {
        padding: 0.4rem 0.85rem !important;
        min-height: 2.4rem !important;
      }
      div.st-key-search_kind_tabs [data-testid="stTabPanel"] {
        display: none !important;
        padding: 0 !important;
        min-height: 0 !important;
      }
      div.st-key-kind_tab_row [data-testid="stHorizontalBlock"] {
        align-items: flex-end !important;
      }
      div.st-key-kind_tab_row div.st-key-surprise_me button {
        min-height: 2.4rem !important;
        font-size: 0.95rem !important;
      }

      .takeover-title {
        font-family: "Space Grotesk", sans-serif !important;
        font-size: clamp(1.8rem, 4vw, 2.6rem) !important;
        line-height: 1.05 !important;
        margin: 0 0 0.75rem 0 !important;
        color: var(--text) !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)
st.html(
    """
    <style>
      [data-testid="stTabs"] [data-testid="stTab"],
      [data-testid="stTabs"] [data-testid="stTab"] *,
      [data-testid="stTabs"] [role="tab"],
      [data-testid="stTabs"] [role="tab"] * {
        font-family: "Space Grotesk", sans-serif !important;
        font-size: 1.85rem !important;
        font-weight: 600 !important;
        letter-spacing: -0.02em !important;
        line-height: 1.2 !important;
      }
      [data-testid="stTabs"] [data-testid="stTab"],
      [data-testid="stTabs"] [role="tab"] {
        padding: 1.35rem 2rem !important;
        min-height: 4.5rem !important;
      }
      div.st-key-search_kind_tabs [data-testid="stTab"],
      div.st-key-search_kind_tabs [data-testid="stTab"] *,
      div.st-key-search_kind_tabs [role="tab"],
      div.st-key-search_kind_tabs [role="tab"] * {
        font-size: 1.15rem !important;
      }
      div.st-key-search_kind_tabs [data-testid="stTab"],
      div.st-key-search_kind_tabs [role="tab"] {
        padding: 0.4rem 0.85rem !important;
        min-height: 2.4rem !important;
      }
      div.st-key-search_kind_tabs [data-testid="stTabPanel"] {
        display: none !important;
        padding: 0 !important;
        min-height: 0 !important;
      }
      @keyframes play-logic-pulse {
        0%, 100% {
          transform: scale(1);
          box-shadow: 0 0 0 1px rgba(18, 21, 26, 0);
        }
        50% {
          transform: scale(1.018);
          box-shadow: 0 0 0 1px rgba(18, 21, 26, 0.1);
        }
      }
      div.st-key-play_logic button,
      div.st-key-play_logic button p,
      div.st-key-play_logic button span {
        font-size: 1.65rem !important;
        font-weight: 700 !important;
        line-height: 1.15 !important;
        white-space: normal !important;
      }
      div.st-key-play_logic button {
        min-height: 7.25rem !important;
        aspect-ratio: 1 / 1;
        border-radius: 14px !important;
        transform-origin: center center;
        animation: play-logic-pulse 2.8s ease-in-out infinite;
      }
      @media (prefers-reduced-motion: reduce) {
        div.st-key-play_logic button {
          animation: none;
        }
      }
    </style>
    """
)

musicians = list_musicians()
musician_names = sorted({m.name for m in musicians})
presets = list_presets()
preset_ids = [p["id"] for p in presets]
preset_labels = {p["id"]: f"{p['label']} — {p['summary']}" for p in presets}
featured_cards = featured_style_cards()

IAC_FIRST_RUN_TIP = """
<div class="tip">
  <strong>One-time Mac setup for Logic</strong><br/>
  Audio MIDI Setup → MIDI Studio → IAC Driver → enable <em>Device is online</em>.
  In Logic, set a Software Instrument track’s MIDI In to that IAC bus.
  After that, Play into Logic is one click.
</div>
"""

MULTI_PORT_HELP = (
    "Prefer an IAC Driver bus. In Logic, set the track’s MIDI In to the "
    "same IAC bus you pick here — mismatched ports mean silence."
)

# Light context — denser opts live in Play / Record + Debug.
# Audition strip dropped (UI Simplify); Play / Record tab carries the path.
AUDITION_CAPTURE_STRIP_HTML = ""

SILENCE_CHECKLIST_HTML = """
<p class="silence-check"><strong>Hearing nothing?</strong>
MIDI In matches the port · track hears input · instrument loaded.</p>
"""


def _show_iac_tip() -> None:
    """First-run IAC tip; hidden after a successful Play (session)."""
    if st.session_state.get("iac_tip_dismissed"):
        return
    st.markdown(IAC_FIRST_RUN_TIP, unsafe_allow_html=True)


def _render_iac_status_chip(ports: list[str]) -> None:
    """Compact found/missing chip — preferred over tip-only homework."""
    if has_iac_port(ports):
        name = preferred_iac_port(ports) or "IAC"
        st.markdown(
            f'<span class="iac-chip ok">IAC found · {name}</span>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<span class="iac-chip miss">IAC missing — enable Device is online, then Refresh</span>',
            unsafe_allow_html=True,
        )


def _apply_refreshed_ports(ports: list[str]) -> None:
    """Prefer IAC after a mid-session refresh; drop stale selections."""
    preferred = preferred_iac_port(ports)
    current = st.session_state.get("live_port")
    if preferred and (not current or current not in ports or not port_looks_like_iac(current)):
        st.session_state["live_port"] = preferred
    elif current and current not in ports:
        st.session_state.pop("live_port", None)
        if preferred:
            st.session_state["live_port"] = preferred


# --- Session defaults + pending actions (before chrome) ---
_apply_pending_home_tab()
_persist_widget_keys()
if "catalog_pick" not in st.session_state:
    st.session_state["catalog_pick"] = None
    st.session_state["_persist_catalog_pick"] = None
if "vibe_text" not in st.session_state:
    st.session_state["vibe_text"] = ""
if "search_kind" not in st.session_state:
    st.session_state["search_kind"] = DEFAULT_SEARCH_KIND
if "bars" not in st.session_state:
    st.session_state["bars"] = DEFAULT_SKETCH_BARS
if "chord_count" not in st.session_state:
    st.session_state["chord_count"] = DEFAULT_CHORD_COUNT
if "generation_type" not in st.session_state:
    st.session_state["generation_type"] = DEFAULT_GENERATION_TYPE
if "generation_mode" not in st.session_state:
    st.session_state["generation_mode"] = generation_mode_from_type(
        st.session_state.get("generation_type", DEFAULT_GENERATION_TYPE)
    )
if "timing_factor" not in st.session_state:
    st.session_state["timing_factor"] = DEFAULT_TIMING_FACTOR
if "effects_preset" not in st.session_state and "effects_presets" not in st.session_state:
    st.session_state["effects_preset"] = "tape_and_human"
    st.session_state["effects_presets"] = ["tape_and_human"]
if "use_sdk" not in st.session_state:
    st.session_state["use_sdk"] = _cursor_api_key_present()

# Transport prefs (count-in / loop / soft-click) before widgets bind.
_seed_transport_bool_prefs()
_persist_widget_keys()

# Pending related-style regenerate (Random / named identity jump)
_pending_related = st.session_state.pop("pending_related_name", None)
if _pending_related:
    if _pending_related in musician_names:
        st.session_state["catalog_pick"] = _pending_related
        _apply_search_kind("artist")
    else:
        st.session_state["vibe_text"] = _pending_related
        _apply_search_kind("mood")

has_sketch = bool(st.session_state.get("last_run"))
takeover = st.session_state.get("ui_takeover")
if takeover not in TAKEOVER_TITLES:
    takeover = None
    st.session_state.pop("ui_takeover", None)

# --- Shared recipe / gate (session state; no widgets yet) ---
_fx_raw = st.session_state.get("effects_presets") or st.session_state.get(
    "effects_preset"
) or "tape_and_human"
_fx_ids = normalize_preset_ids(_fx_raw)
st.session_state["effects_presets"] = list(_fx_ids)
effects_preset = serialize_preset_ids(_fx_ids)
st.session_state["effects_preset"] = effects_preset

_catalog_who = str(st.session_state.get("catalog_pick") or "").strip()
_vibe_now = str(st.session_state.get("vibe_text") or "").strip()
_has_style_intent = bool(_catalog_who or _vibe_now)
_gate = (
    resolve_artist_gate_for_ui(
        _catalog_who,
        _vibe_now,
        search_kind=st.session_state.get("search_kind", DEFAULT_SEARCH_KIND),
    )
    if _has_style_intent
    else None
)
_gate_ok = bool(getattr(_gate, "accepted", False))
_generating = bool(st.session_state.get("auto_generate"))
_artist_rejected = bool(
    _has_style_intent
    and artist_gate_wipes_sketch(
        blocks_generate=artist_gate_blocks_generate(
            _gate, cursor_available=_cursor_api_key_present()
        ),
        generating=_generating,
        has_sketch=bool(st.session_state.get("last_run")),
    )
)
if _artist_rejected:
    _had_last_run = bool(st.session_state.get("last_run"))
    st.session_state["artist_reject_reason"] = getattr(_gate, "reason", None)
    for _key in session_clears_on_artist_reject():
        st.session_state.pop(_key, None)
    st.session_state["generate_error"] = artist_reject_drip_copy(
        st.session_state.get("artist_reject_reason")
    )
    st.session_state.pop("auto_generate", None)
    st.session_state.pop("pending_replay", False)
    st.session_state.pop("spotify_artist_name", None)
    if _had_last_run:
        st.rerun()
elif _gate_ok:
    st.session_state.pop("artist_reject_reason", None)
    if st.session_state.get("generate_error") == ARTIST_REJECT_DRIP:
        st.session_state.pop("generate_error", None)
    _spotify_hit = getattr(_gate, "spotify_artist", None) if _gate is not None else None
    _agent_name = str(getattr(_gate, "agent_name", "") or "").strip() if _gate is not None else ""
    if getattr(_gate, "source", None) == "spotify" and _spotify_hit is not None:
        st.session_state["spotify_artist_name"] = _spotify_hit.name
    elif getattr(_gate, "source", None) == "agent" and _agent_name:
        st.session_state["spotify_artist_name"] = _agent_name
    else:
        st.session_state.pop("spotify_artist_name", None)

# Identity pin: feel layers on who; Spotify/agent/other-catalog artists unpin.
if _has_style_intent:
    query, identity_name = resolve_lookup_inputs(
        st.session_state.get("catalog_pick") or "",
        st.session_state.get("vibe_text") or "",
        gate_accept=_gate if _gate_ok else None,
    )
else:
    query, identity_name = "", None

st.session_state["bars"] = clamp_bars(int(st.session_state.get("bars", DEFAULT_SKETCH_BARS)))
st.session_state["chord_count"] = clamp_chord_count(
    st.session_state.get("chord_count", DEFAULT_CHORD_COUNT)
)
st.session_state["generation_type"] = clamp_generation_type(
    st.session_state.get("generation_type", DEFAULT_GENERATION_TYPE)
)
st.session_state["generation_mode"] = clamp_generation_mode(
    st.session_state.get(
        "generation_mode",
        generation_mode_from_type(st.session_state.get("generation_type")),
    )
)
st.session_state["extend_factor"] = clamp_extend_factor(
    st.session_state.get("extend_factor", 1)
)
st.session_state["timing_factor"] = clamp_timing_factor(
    st.session_state.get("timing_factor", DEFAULT_TIMING_FACTOR)
)
st.session_state["search_kind"] = clamp_search_kind(
    st.session_state.get("search_kind", DEFAULT_SEARCH_KIND)
)
_section_role = st.session_state.get("section_role")
if _section_role is not None and not str(_section_role).strip():
    _section_role = None
    st.session_state["section_role"] = None

recipe = (
    preview_recipe(
        catalog_name=st.session_state.get("catalog_pick") or "",
        vibe_text=st.session_state.get("vibe_text") or "" if not _artist_rejected else "",
        effects_preset=effects_preset,
        gate_accept=_gate if _gate_ok else None,
        section_role=_section_role,
    )
    if _has_style_intent and not _artist_rejected
    else None
)

_pending_knobs = st.session_state.pop("_pending_profile_knobs", None)
if isinstance(_pending_knobs, dict):
    st.session_state.update(_pending_knobs)
_seed_arp_knobs(recipe.profile if recipe else None)

player = get_shared_player()
_clear_stuck_logic_lock()
_force_refresh = st.session_state.pop("refresh_midi_ports", False)
if _force_refresh and player.playing:
    _force_refresh = False
live = player.status(refresh=_force_refresh)
ports = live.ports
if _force_refresh:
    _apply_refreshed_ports(ports)
_seed_live_port(ports)
default_port = preferred_iac_port(ports) or (ports[0] if ports else None)
if "live_port" not in st.session_state and default_port:
    st.session_state["live_port"] = default_port

run = st.session_state.get("last_run")
if run and st.session_state.pop("pending_replay", False):
    _replay_into_logic(player, run, ports)

_transport_busy = bool(player.playing)
generate = False


def _render_random_button() -> None:
    last_run_for_surprise = st.session_state.get("last_run")
    last_result = (
        last_run_for_surprise.get("result") if last_run_for_surprise else None
    )
    previous_id = st.session_state.get("last_surprise_id")
    surprise_roll_pick = surprise_roll(
        current=recipe.profile if recipe else None,
        vibe_hint=query,
        last_result=last_result,
        previous_id=previous_id,
        avoid_effects=effects_preset,
    )
    surprise_pick = surprise_roll_pick[0] if surprise_roll_pick else None
    surprise_fx = surprise_roll_pick[1] if surprise_roll_pick else ""
    st.button(
        "Random",
        use_container_width=True,
        key="surprise_me",
        disabled=surprise_pick is None,
        help="Pick a catalog artist and a different effects preset. Press Generate.",
        on_click=_apply_surprise if surprise_pick is not None else None,
        args=(
            (surprise_pick.name, surprise_pick.id, surprise_fx)
            if surprise_pick is not None
            else ()
        ),
    )


def _render_search_query(kind: str) -> None:
    placeholder = (
        "e.g. classic rock, ambient, jazz…"
        if kind == "mood"
        else "e.g. Philip Glass, Nils Frahm, Brian Eno…"
    )
    st.text_input(
        "Vibe (feel)",
        placeholder=placeholder,
        help="Mood = genre feel. Artist = musician name. Press Generate when ready.",
        key="vibe_text",
        label_visibility="collapsed",
        width="stretch",
    )
    _render_part_and_timing_row()


def _render_search_feel() -> None:
    kind = clamp_search_kind(st.session_state.get("search_kind"))
    default_label = "Artist" if kind == "artist" else "Mood"
    if "search_kind_tabs" not in st.session_state:
        st.session_state["search_kind_tabs"] = default_label
    with st.container(key="kind_tab_row"):
        kind_col, random_col = st.columns([5, 1], vertical_alignment="bottom")
        with kind_col:
            tab_mood, tab_artist = st.tabs(
                ["Mood", "Artist"],
                default=default_label,
                key="search_kind_tabs",
                on_change=_on_search_kind_tabs,
            )
        with random_col:
            _render_random_button()
    label = str(st.session_state.get("search_kind_tabs") or default_label).strip()
    if tab_artist.open is True or label == "Artist":
        st.session_state["search_kind"] = "artist"
    elif tab_mood.open is True or label == "Mood":
        st.session_state["search_kind"] = "mood"
    kind = clamp_search_kind(st.session_state.get("search_kind"))
    _render_search_query(kind)


GENERATE_BUSY_COPY = "Resolving style and writing MIDI…"


def _render_generate_loading() -> None:
    """Original Generating callout. Replaces Play / Clear IAC while busy."""
    st.markdown(
        f"""
        <div class="recipe-preview generate-loading">
          <div class="label">Generating</div>
          <div class="line">{GENERATE_BUSY_COPY}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_listen(run_data: dict) -> None:
    """In-browser piano preview — Search + Preview hero."""
    st.markdown("### Preview")
    if run_data.get("wav_bytes"):
        st.audio(run_data["wav_bytes"], format="audio/wav")
    else:
        st.caption("No preview audio for this sketch.")


def _render_play_hero(run_data: dict) -> None:
    """Sacred Play / Clear IAC — Play / Record tab (and sticky if playing elsewhere)."""
    result = run_data["result"]
    options = run_data["options"]
    path = run_data["path"]
    profile = result.profile

    if "live_count_in" not in st.session_state:
        st.session_state["live_count_in"] = False
    if "live_loop" not in st.session_state:
        st.session_state["live_loop"] = True
    if "live_sync_logic" not in st.session_state:
        st.session_state["live_sync_logic"] = False

    st.markdown("### Play in Logic")
    # Honest: live stream ≠ region. Record setup lives in this same tab.
    st.caption(
        "Play sends MMC Record + MIDI Start. One click starts the take. "
        "Logic must Listen to MMC Input and MIDI Clock on this IAC bus. "
        "Arm the track. Re-Play restarts from the top."
    )
    if not live.available:
        st.warning(
            live.error
            or "No MIDI ports available. Enable IAC Driver, then Refresh ports below."
        )
    else:
        port_now = st.session_state.get("live_port") or (ports[0] if ports else None)
        if port_now:
            st.caption(f"Port · **{port_now}**")

        _gen_lock = bool(st.session_state.get("auto_generate"))
        if _gen_lock:
            _render_generate_loading()
        else:
            st.markdown('<div class="play-hero-stack">', unsafe_allow_html=True)
            if st.button(
                "Re-Play" if player.phase == "playing" else "Play in Logic",
                type="primary",
                use_container_width=True,
                key="play_logic",
            ):
                try:
                    sketch_bpm = float(options.get("bpm") or 120)
                    count_in = bool(st.session_state.get("live_count_in", False))
                    loop_play = bool(st.session_state.get("live_loop", True))
                    use_click = bool(st.session_state.get("live_soft_click", False))
                    lock_logic = bool(st.session_state.get("live_sync_logic", False))
                    player.play_file(
                        path,
                        st.session_state.get("live_port"),
                        count_in_bars=0.0 if lock_logic else (1.0 if count_in else 0.0),
                        bpm=sketch_bpm,
                        bars=float(options.get("bars") or 8),
                        loop=loop_play,
                        click=False if lock_logic else (use_click if count_in else False),
                        sync="follow" if lock_logic else "internal",
                        send_clock=not lock_logic,
                    )
                    bits = [f"Streaming to {player.port_name}"]
                    if lock_logic:
                        bits.append("waiting for Logic Play")
                    else:
                        bits.append("MIDI Start + clock")
                        if count_in:
                            bits.append(
                                "1-bar count-in + soft click"
                                if use_click
                                else "1-bar count-in"
                            )
                    if loop_play:
                        bits.append("loops until Stop")
                    st.session_state["live_message"] = " · ".join(bits) + "."
                    st.session_state["live_was_playing"] = True
                    st.session_state["iac_tip_dismissed"] = True
                    _persist_live_prefs()
                    st.rerun()
                except Exception as exc:
                    st.session_state["live_message"] = f"Live MIDI failed: {exc}"
                    st.session_state["live_was_playing"] = bool(player.playing)
            clear_port = st.session_state.get("live_port") or player.port_name
            if st.button(
                "Clear IAC",
                use_container_width=True,
                disabled=not bool(clear_port),
                key="stop_logic",
                help="Stop the stream, flush hanging notes, and stop Logic "
                "(MMC Stop + MIDI Stop). Works while Playing or idle.",
            ):
                player.stop(wait=True, port_name=clear_port)
                st.session_state["live_was_playing"] = False
                st.session_state["live_message"] = (
                    f"Cleared IAC · Logic stopped ({clear_port})."
                )
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        if player.playing or st.session_state.get("live_was_playing"):

            @st.fragment(run_every=timedelta(milliseconds=400))
            def _playback_status_poll() -> None:
                err = player.last_error
                if player.playing:
                    active = player.port_name
                    ports_now = refresh_output_ports()
                    if active and ports_now is not None and active not in ports_now:
                        player.stop(wait=False)
                        st.session_state["live_was_playing"] = False
                        st.session_state["live_message"] = (
                            "MIDI port lost — Refresh ports."
                        )
                        st.rerun()
                        return
                    st.session_state["live_was_playing"] = True
                    label = player.transport_caption()
                    loop_tag = " · loops until Stop" if player.looping else ""
                    st.caption(f"{label} → **{player.port_name}**{loop_tag}")
                    return
                if st.session_state.pop("live_was_playing", False):
                    if err:
                        st.session_state["live_message"] = err
                    else:
                        st.session_state["live_message"] = "Finished."
                    st.rerun()

            _playback_status_poll()
        elif st.session_state.get("live_message") == "Stopped.":
            st.caption("Stopped.")
        elif str(st.session_state.get("live_message") or "").startswith("All notes off"):
            st.caption("All notes off.")

        if not _transport_busy:
            _persist_live_prefs()

        if player.last_error and not player.playing:
            if st.session_state.get("live_message") != player.last_error:
                st.session_state["live_message"] = player.last_error
            st.session_state["live_was_playing"] = False

        live_msg = st.session_state.get("live_message")
        if live_msg:
            if "port lost" in live_msg.lower() or "failed" in live_msg.lower() or (
                player.last_error and live_msg == player.last_error
            ):
                st.error(live_msg)
            else:
                st.info(live_msg)
        elif player.last_error:
            st.error(player.last_error)

    # Silence for unused locals when Play path short-circuits
    _ = (profile,)


def _render_download(run_data: dict) -> None:
    path = run_data["path"]
    midi_bytes = Path(path).read_bytes()
    st.markdown("### Download")
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            "Download MIDI",
            data=midi_bytes,
            file_name=Path(path).name,
            mime="audio/midi",
            use_container_width=True,
        )
    with dl2:
        st.download_button(
            "Download WAV preview",
            data=run_data.get("wav_bytes") or b"",
            file_name=Path(path).with_suffix(".wav").name,
            mime="audio/wav",
            use_container_width=True,
            disabled=not bool(run_data.get("wav_bytes")),
        )


def _render_result_row(run_data: dict) -> None:
    """Feel + Preview on the left; arp + seasoning under them; Play on the right."""
    result = run_data["result"]
    options = run_data["options"]
    profile = result.profile
    main_col, play_col = st.columns([10, 4], gap="large")
    with main_col:
        aside_col, preview_col = st.columns(2, gap="large")
        with aside_col:
            plain = run_data.get("plain_feel_line") or format_plain_feel_match(profile)
            st.markdown(f'<p class="post-feel">{plain}</p>', unsafe_allow_html=True)
            st.caption(
                f"{options.get('mode')} · {options.get('bpm')} BPM · "
                f"{options.get('bars')} bars · "
                f"{len(options.get('chord_progression') or [])} chords · "
                f"{format_generation_mode_label(options.get('generation_mode') or generation_mode_from_type(options.get('generation_type')))}"
            )
            likeness = run_data.get("likeness_blurb")
            if not likeness:
                likeness = format_likeness_blurb(
                    profile, used_cursor_sdk=bool(result.used_cursor_sdk)
                )
            if likeness:
                label, body = likeness
                st.markdown(f"**{label}**")
                st.write(body)
        with preview_col:
            _render_listen(run_data)
            _render_download(run_data)
        with st.container(key="left_controls"):
            if takeover != "geek":
                _render_arp_live(profile)
                _render_effects_chips(run_data)
    with play_col:
        _render_play_hero(run_data)


def _render_effects_chips(run_data: dict | None) -> None:
    st.markdown(
        '<p class="effect-lite">Effects seasoning</p>',
        unsafe_allow_html=True,
    )
    current_ids = set(
        normalize_preset_ids(
            st.session_state.get("effects_presets")
            or st.session_state.get("effects_preset")
            or effects_preset
        )
    )
    fx_cols = st.columns(min(5, len(preset_ids)))
    for i, pid in enumerate(preset_ids):
        with fx_cols[i % len(fx_cols)]:
            label = presets[i]["label"] if i < len(presets) else pid
            is_on = pid in current_ids
            st.button(
                f"{'● ' if is_on else ''}{label}",
                key=f"fx_chip_{pid}",
                use_container_width=True,
                help=preset_labels.get(pid, pid),
                on_click=_apply_effects_preset,
                args=(pid,),
            )
    cfg = build_effects_config(
        current_ids,
        overrides=st.session_state.get("effects_overrides"),
    )
    for effect in cfg:
        name = str(effect.get("name") or "")
        if not name:
            continue
        for param, spec in _FX_SLIDER_SPEC.items():
            if param not in effect:
                continue
            lo, hi, step = spec
            key = f"fx_lvl_{name}_{param}"
            current = effect.get(param, lo)
            if isinstance(step, float):
                lo, hi, step = float(lo), float(hi), float(step)
                current = float(current)
            else:
                lo, hi, step = int(lo), int(hi), int(step)
                current = int(current)
            if key not in st.session_state:
                st.session_state[key] = current
            st.slider(
                param.replace("_", " "),
                min_value=lo,
                max_value=hi,
                step=step,
                key=key,
                help=EFFECT_PARAM_HELP.get(param, param),
                on_change=_apply_effect_level,
            )
    last_run = run_data or st.session_state.get("last_run") or {}
    if last_run.get("notes_dirty"):
        st.caption("Recipe rewrite replaces piano-roll edits.")
        st.caption(
            "Piano-roll edits will be replaced if you change Arp, Steps grid, or Effects."
        )
    st.button(
        "Reset to generated",
        key="reset_generated_notes",
        disabled=not last_run.get("notes_dirty"),
        on_click=_reset_generated_notes,
    )


def _render_capture_setup() -> None:
    """Count-in / loop, IAC tip, Refresh, silence checklist (Play / Record tab)."""
    st.markdown("### Settings")
    port_col, record_col = st.columns(2, gap="large")
    with port_col:
        _show_iac_tip()
        _render_iac_status_chip(ports)
        st.button(
            "Refresh ports",
            use_container_width=True,
            key="refresh_ports",
            disabled=_transport_busy,
            help="Disabled while Playing — Stop first.",
            on_click=_apply_refresh_ports,
        )
        if not live.available:
            st.warning(
                live.error
                or "No MIDI ports available. Enable IAC Driver, then Refresh ports."
            )
        elif len(ports) > 1:
            st.selectbox(
                "MIDI output port",
                options=ports,
                key="live_port",
                help=MULTI_PORT_HELP,
                disabled=_transport_busy,
            )
            st.caption("Logic MIDI In must match the IAC bus chosen above.")
            selected = st.session_state.get("live_port") or ""
            if selected and not port_looks_like_iac(selected) and has_iac_port(ports):
                st.warning(
                    "Selected port is not IAC — prefer an IAC Driver bus before Play "
                    "(mismatched MIDI In usually means silence)."
                )
        elif ports:
            st.caption(f"Port: **{ports[0]}**")
            st.session_state["live_port"] = ports[0]
            if not port_looks_like_iac(ports[0]):
                st.caption("Prefer enabling IAC Driver for Logic — then Refresh ports.")
        st.markdown(SILENCE_CHECKLIST_HTML, unsafe_allow_html=True)
    with record_col:
        st.markdown("#### Record")
        st.caption(
            "Arm the track in Logic. Play here punches MMC Record + Start. "
            "Lock to Logic: transmit MIDI Clock from Logic to this IAC bus, "
            "then Play here, then Play in Logic. Notes fire on Logic’s downbeat."
        )
        st.checkbox(
            "Lock to Logic clock",
            key="live_sync_logic",
            disabled=_transport_busy,
            help="Wait for MIDI Start from Logic, then chase incoming clock. "
            "Logic must transmit MIDI Clock to this IAC bus.",
        )
        st.checkbox(
            "Count-in (1 silent bar)",
            key="live_count_in",
            disabled=_transport_busy,
            help="Internal wall-clock only (ignored while Lock to Logic is On).",
        )
        st.checkbox(
            "Loop sketch",
            key="live_loop",
            disabled=_transport_busy,
            help="On by default — loops until Stop. Turn off for a one-shot pass.",
        )
        if st.session_state.get("live_soft_click"):
            st.caption(
                "Soft click is On (Debug) — click MIDI will be captured "
                "if Logic is recording."
            )
    if not _transport_busy:
        _persist_live_prefs()


def _render_advanced_takeover() -> None:
    if _artist_rejected or recipe is None:
        st.caption("Matched: —")
    else:
        st.caption(recipe.match_line)
    st.number_input(
        "BPM",
        min_value=40,
        max_value=240,
        step=1,
        key="sketch_bpm",
        on_change=_apply_arp_live,
        help="Sketch tempo for Generate. Lock to Logic clock follows Logic’s MIDI Start, not this number.",
    )
    st.toggle(
        "Cursor SDK enrichment",
        key="use_sdk",
        help="Research the artist and write a short home blurb: why this sketch sounds like them. Requires CURSOR_API_KEY.",
    )
    use_sdk = bool(st.session_state.get("use_sdk", _cursor_api_key_present()))
    if not use_sdk:
        sdk_line = "SDK: off — catalog only"
    elif cursor_sdk_available():
        sdk_line = "SDK: ready"
    else:
        sdk_line = "SDK: on, but CURSOR_API_KEY missing — catalog only"
    st.caption(sdk_line)
    soft_click = st.checkbox(
        "Soft click during count-in",
        key="live_soft_click",
        help="Sends metronome notes on the same MIDI port during count-in. "
        "Off by default — count-in stays truly silent. "
        "Count-in itself is under Record near Play.",
    )
    if soft_click:
        st.caption(
            "Warning: click MIDI will be captured if Logic is recording "
            "(same IAC bus as the sketch)."
        )
    else:
        st.caption("When Off, count-in stays truly silent (no click notes).")
    _persist_live_prefs()
    st.divider()
    st.caption("Catalog pin (optional)")
    _render_featured_styles()
    _render_catalog_selectbox(musician_names)


def _render_geek_takeover(run_data: dict) -> None:
    result = run_data["result"]
    options = run_data["options"]
    summary = run_data["summary"]
    path = run_data["path"]
    profile = result.profile

    st.markdown("#### Live MIDI")
    st.caption(
        "Live options rewrite the sketch and keep streaming."
    )
    _render_arp_live(profile)
    _render_effects_chips(run_data)
    st.markdown("#### Save")
    _render_download(run_data)
    st.divider()

    st.caption(run_data.get("match_line") or format_match_line(profile))
    st.markdown(
        f"""
        <div class="metric-row">
          <div class="metric"><div class="label">Notes</div><div class="value">{summary['note_on_count']}</div></div>
          <div class="metric"><div class="label">Pitches</div><div class="value">{summary['unique_pitches']}</div></div>
          <div class="metric"><div class="label">Range</div><div class="value">{summary['pitch_range']['min']}–{summary['pitch_range']['max']}</div></div>
          <div class="metric"><div class="label">Bends</div><div class="value">{summary['pitch_bend_events']}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f"**{profile.name}** · `{profile.source}` · {profile.generation_type}")
    st.write(profile.description)
    st.write(
        f"Mode **{options.get('mode')}** · "
        f"arp `{profile.arp_mode}` / {profile.arp_steps} steps · "
        f"mode_color `{options.get('mode_color', True)}`"
    )
    st.markdown("**Effects applied**")
    for line in explain_effects_config(options.get("effects_config") or []):
        st.write(f"- {line}")
    if result.candidates:
        st.caption("Also considered: " + ", ".join(c.name for c in result.candidates))

    st.code(format_summary_text(summary))
    payload = note_editor(
        notes=run_data.get("edit_notes") or [],
        mode="roll",
        ticks_per_beat=int((run_data.get("summary") or {}).get("ticks_per_beat") or 480),
        key="geek_roll",
    )
    if payload and payload.get("mode") == "roll" and payload.get("notes") is not None:
        if payload != st.session_state.get("_geek_roll_last"):
            st.session_state["_geek_roll_last"] = payload
            _commit_note_edits(list(payload["notes"]))

    st.markdown("**Raw generator options**")
    st.json(options)

    st.caption("Style tags: " + ", ".join(list_styles()))
    st.caption("CLI (`python -m midi_gen`) remains available for power/dev use.")
    _ = path


# --- Takeover OR home (single Streamlit page; no multipage routes) ---
generate = False
if takeover == "debug":
    _render_takeover_header(TAKEOVER_TITLES[takeover])
    # Keep Clear IAC reachable if a stream is active while buried in a takeover.
    if run and (player.playing or st.session_state.get("live_was_playing")):
        _render_play_hero(run)
    _render_advanced_takeover()
else:
    # --- HOME: Search + Preview | Play / Record (Logic stack wrapped, not rewritten) ---
    _render_home_header()

    tab_search, tab_play = st.tabs(
        [HOME_TAB_SEARCH, HOME_TAB_PLAY],
        key="home_tabs",
    )
    with tab_search:
        _render_search_feel()
        _render_sketch_layout()

    with tab_play:
        _gen_busy = bool(st.session_state.get("auto_generate"))
        _render_geek_entry(has_sketch=bool(run) and not _gen_busy)
        if takeover == "geek":
            if run:
                _render_geek_takeover(run)
            else:
                st.info("Generate a sketch first.")
        if _gen_busy and not run:
            _render_generate_loading()
        if run:
            _render_result_row(run)
        if st.session_state.get("generate_error") and not run:
            _reject = st.session_state.get("artist_reject_reason")
            if _reject or st.session_state["generate_error"] == ARTIST_REJECT_DRIP:
                st.error(artist_reject_drip_copy(_reject))
            else:
                st.error(f"Generation failed: {st.session_state['generate_error']}")
        if not run and not _gen_busy:
            st.info("Generate a sketch first, then Play in Logic / Record.")
        elif run:
            _render_capture_setup()

# Auto-generate from Random / live tweaks / effects chips
if st.session_state.pop("auto_generate", False):
    generate = False if _artist_rejected or not _has_style_intent else True

bars = clamp_bars(int(st.session_state.get("bars", DEFAULT_SKETCH_BARS)))
chord_count = clamp_chord_count(st.session_state.get("chord_count", DEFAULT_CHORD_COUNT))
generation_mode = clamp_generation_mode(
    st.session_state.get("generation_mode", DEFAULT_GENERATION_MODE)
)
use_sdk = bool(st.session_state.get("use_sdk", _cursor_api_key_present()))
section_role = st.session_state.get("section_role")
if section_role is not None and not str(section_role).strip():
    section_role = None
timing_factor = clamp_timing_factor(
    st.session_state.get("timing_factor", DEFAULT_TIMING_FACTOR)
)

# --- Generate pipeline ---
if generate:
    player.stop(wait=True)
    st.session_state["live_was_playing"] = False
    with st.spinner(GENERATE_BUSY_COPY):
        overrides = {
            "effects_preset": effects_preset,
            "bars": int(bars),
            "chord_count": int(chord_count),
            "generation_mode": generation_mode,
            "debug": False,
        }
        if section_role:
            overrides["section_role"] = section_role
        if abs(timing_factor - 1.0) > 1e-9:
            overrides["timing_factor"] = float(timing_factor)
        if st.session_state.get("arp_mode") in ARP_MODE_LABELS:
            overrides["arp_mode"] = st.session_state["arp_mode"]
        if st.session_state.get("arp_steps") in ARP_STEP_CHOICES:
            overrides["arp_steps"] = int(st.session_state["arp_steps"])
        if st.session_state.get("arp_range_octaves") in ARP_OCTAVE_CHOICES:
            overrides["range_octaves"] = int(st.session_state["arp_range_octaves"])
        if "arp_evolve" in st.session_state:
            overrides["evolution_rate"] = float(st.session_state["arp_evolve"])
        if "arp_repeat" in st.session_state:
            overrides["repetition_factor"] = int(st.session_state["arp_repeat"])
        if "sketch_bpm" in st.session_state:
            overrides["bpm"] = int(st.session_state["sketch_bpm"])
        if "arp_gates" in st.session_state:
            overrides["arp_gates"] = list(st.session_state["arp_gates"])
        if "arp_pitches" in st.session_state:
            overrides["arp_pitches"] = list(st.session_state["arp_pitches"])
        if st.session_state.get("effects_overrides"):
            overrides["effects_overrides"] = dict(st.session_state["effects_overrides"])
        if "gen_seed" in st.session_state:
            overrides["seed"] = int(st.session_state.pop("gen_seed"))
        live_tweak = bool(st.session_state.pop("_live_param_tweak", False))
        try:
            path, result, options = generate_midi_for_style(
                query,
                use_cursor_sdk=use_sdk,
                overrides=overrides,
                live_tweak=live_tweak,
                identity_name=identity_name,
                vibe_text=str(st.session_state.get("vibe_text") or "").strip() or None,
                section_role=section_role,
            )
            summary = summarize_midi_file(path)
            wav_bytes = render_midi_to_wav_bytes(path)
            notes = list_note_events(path)
            plain = format_plain_feel_match(result.profile)
            likeness = format_likeness_blurb(
                result.profile, used_cursor_sdk=bool(result.used_cursor_sdk)
            )
            st.session_state["last_run"] = {
                "path": path,
                "result": result,
                "options": options,
                "summary": summary,
                "query": query,
                "wav_bytes": wav_bytes,
                "plain_feel_line": plain,
                "likeness_blurb": likeness,
                "edit_notes": notes,
                "generated_notes": [dict(n) for n in notes],
                "notes_dirty": False,
                "match_line": format_match_line(
                    result.profile,
                    effects_preset=options.get("effects_preset") or effects_preset,
                    matched_locally=result.matched_locally,
                    used_cursor_sdk=result.used_cursor_sdk,
                ),
            }
            if result.used_cursor_sdk and not live_tweak:
                st.session_state["_pending_profile_knobs"] = _knobs_from_profile(
                    result.profile
                )
            st.session_state.pop("generate_error", None)
            st.session_state.pop("artist_reject_reason", None)
            st.session_state.pop("live_message", None)
            _queue_play_record_tab()
            st.rerun()
        except ArtistRejected as exc:
            st.session_state["artist_reject_reason"] = exc.result.reason
            for _key in session_clears_on_artist_reject():
                st.session_state.pop(_key, None)
            st.session_state["generate_error"] = artist_reject_drip_copy(
                exc.result.reason
            )
            st.session_state.pop("pending_replay", False)
            st.rerun()
        except Exception as exc:
            st.session_state.pop("artist_reject_reason", None)
            st.session_state["generate_error"] = str(exc)
            st.session_state.pop("pending_replay", False)
            st.rerun()

if st.session_state.get("generate_error") and run and not takeover:
    _reject = st.session_state.get("artist_reject_reason")
    if _reject or st.session_state["generate_error"] == ARTIST_REJECT_DRIP:
        st.error(artist_reject_drip_copy(_reject))
    else:
        st.error(f"Generation failed: {st.session_state['generate_error']}")

# End-of-run mirror so takeover unmounts don't wipe sacred / prefs keys.
_persist_widget_keys()
