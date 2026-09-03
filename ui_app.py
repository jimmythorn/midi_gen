"""
MIDI Style Lab — Streamlit UI for style → sketch → Logic.

North star: Pick style → Generate → Play into Logic → Download MIDI.

Launch:
  ./run_ui.sh
  # or
  PYTHONPATH=. streamlit run ui_app.py
"""

from __future__ import annotations

import os
import random
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

from midi_gen.audio_preview import describe_preview, render_midi_to_wav_bytes
from midi_gen.artist_gate import ArtistGateReject, ArtistRejected
from midi_gen.cursor_style_lookup import cursor_sdk_available, generate_midi_for_style
from midi_gen.effects_presets import EFFECT_PARAM_HELP, explain_effects_config, list_presets
from midi_gen.live_midi import (
    get_shared_player,
    has_iac_port,
    port_looks_like_iac,
    preferred_iac_port,
    refresh_output_ports,
)
from midi_gen.musician_styles import list_musicians, list_styles
from midi_gen.preview import events_to_roll_rows, format_summary_text, summarize_midi_file
from midi_gen.style_prompting import (
    ARTIST_REJECT_DRIP,
    artist_reject_drip_copy,
    clamp_bars,
    double_bars,
    featured_style_cards,
    format_match_line,
    format_plain_feel_match,
    half_bars,
    mood_chip_packs,
    preview_recipe,
    related_from_lookup_result,
    resolve_artist_gate_for_ui,
    resolve_happy_path_query,
    session_clears_on_artist_reject,
    surprise_related_profile,
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
)


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


def _persist_live_prefs() -> None:
    """Write transport prefs (count-in / loop / soft-click / port) to disk."""
    updates = {
        "live_count_in": bool(st.session_state.get("live_count_in", False)),
        "live_loop": bool(st.session_state.get("live_loop", False)),
        "live_soft_click": bool(st.session_state.get("live_soft_click", False)),
        "live_sync_logic": bool(st.session_state.get("live_sync_logic", True)),
    }
    # Only write port once session has one — avoid wiping a remembered bus
    # before ports are enumerated on first paint.
    if "live_port" in st.session_state:
        updates["live_port"] = st.session_state.get("live_port")
    save_prefs(updates)


def _seed_transport_bool_prefs() -> None:
    """Seed count-in / loop / soft-click / Logic-lock from disk."""
    if st.session_state.get("_live_bool_prefs_seeded"):
        return
    prefs = load_prefs()
    if "live_count_in" not in st.session_state:
        st.session_state["live_count_in"] = bool(prefs.get("live_count_in", False))
    if "live_loop" not in st.session_state:
        st.session_state["live_loop"] = bool(prefs.get("live_loop", False))
    if "live_soft_click" not in st.session_state:
        st.session_state["live_soft_click"] = bool(prefs.get("live_soft_click", False))
    if "live_sync_logic" not in st.session_state:
        st.session_state["live_sync_logic"] = bool(prefs.get("live_sync_logic", True))
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


def _apply_vibe_text(chip: str) -> None:
    """Set vibe from a chip. Must run as on_click (before the text_input binds)."""
    st.session_state["vibe_text"] = chip
    _reset_arp_knobs()


def _apply_featured_style(name: str) -> None:
    """Select a featured catalog name. Feel stays layered on."""
    st.session_state["catalog_pick"] = name
    _reset_arp_knobs()


def _on_catalog_pick_change() -> None:
    """Artist change keeps the current feel (additive)."""
    _reset_arp_knobs()


def _render_catalog_selectbox(names: list[str]) -> None:
    if st.session_state["catalog_pick"] not in names:
        st.session_state["catalog_pick"] = names[0]
    st.selectbox(
        "Style (catalog — who)",
        options=names,
        help="Named musician/style profiles from the full curated catalog.",
        key="catalog_pick",
        on_change=_on_catalog_pick_change,
    )
    pick = st.session_state["catalog_pick"]
    vibe = str(st.session_state.get("vibe_text") or "").strip()
    if vibe:
        st.caption(f"Selected · **{pick}** + **{vibe}**")
    else:
        st.caption(f"Selected · **{pick}**")


def _apply_half_bars() -> None:
    st.session_state["bars"] = half_bars(int(st.session_state.get("bars", 8)))


def _apply_double_bars() -> None:
    st.session_state["bars"] = double_bars(int(st.session_state.get("bars", 8)))


def _apply_again() -> None:
    st.session_state["pending_again"] = True


def _apply_related(name: str) -> None:
    st.session_state["pending_related_name"] = name
    _reset_arp_knobs()


def _apply_surprise(name: str, profile_id: str) -> None:
    st.session_state["last_surprise_id"] = profile_id
    st.session_state["pending_related_name"] = name
    _reset_arp_knobs()


def _apply_arp_live() -> None:
    """Rewrite the sketch from arp knobs; keep streaming if already Playing."""
    if not st.session_state.get("last_run"):
        return
    st.session_state["_live_param_tweak"] = True
    st.session_state["auto_generate"] = True
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
        out["effects_preset"] = fx
    return out


def _render_arp_live(profile: Any) -> None:
    st.markdown(
        '<p class="feel-path-label">Arp</p>',
        unsafe_allow_html=True,
    )
    st.caption("Mess with these while Playing — sketch rewrites and keeps streaming.")
    st.number_input(
        "BPM",
        min_value=40,
        max_value=240,
        step=1,
        key="sketch_bpm",
        on_change=_apply_arp_live,
        help="Sketch tempo for Generate. Lock to Logic clock follows Logic’s MIDI Start, not this number.",
    )
    if getattr(profile, "generation_type", "arpeggio") != "arpeggio":
        st.caption("Drone sketch — arp knobs hide (they would not change the pad).")
        return
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
            loop=bool(st.session_state.get("live_loop", False)),
            click=False,
            sync="follow" if st.session_state.get("live_sync_logic", True) else "internal",
            send_clock=False,
        )
        st.session_state["live_was_playing"] = True
        st.session_state["live_message"] = f"Streaming to {player.port_name}."
        st.session_state["iac_tip_dismissed"] = True
    except Exception as exc:
        st.session_state["live_message"] = f"Live MIDI failed: {exc}"
        st.session_state["live_was_playing"] = bool(player.playing)


def _apply_effects_preset(pid: str) -> None:
    st.session_state["effects_preset"] = pid
    st.session_state["_live_param_tweak"] = True
    st.session_state["auto_generate"] = True


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

      /* Audition → Capture: light context unit; Play stays the hero below */
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

      /* Play is the hero CTA; Stop + compact Panic sit beside it */
      .play-hero-row {
        max-width: 40rem;
        margin: 0 0 0.25rem 0;
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
        margin: 0.35rem 0 0.55rem 0;
      }
      .effect-lite {
        color: var(--muted);
        font-size: 0.82rem;
        margin: 0.15rem 0 0.45rem 0;
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
    </style>
    """,
    unsafe_allow_html=True,
)

musicians = list_musicians()
musician_names = sorted({m.name for m in musicians})
presets = list_presets()
preset_ids = [p["id"] for p in presets]
preset_labels = {p["id"]: f"{p['label']} — {p['summary']}" for p in presets}
featured_cards = featured_style_cards()
mood_packs = mood_chip_packs()

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

# Light Audition→Capture context — denser opts live collapsed under Advanced.
AUDITION_CAPTURE_STRIP_HTML = """
<div class="audition-capture">
  <div class="strip-label">Audition → Capture</div>
  <div class="pair">
    <div class="lane">
      <p class="title">Play (live)</p>
      <p class="sub">Hear the sketch in Logic — stream only, nothing written.</p>
    </div>
    <div class="lane">
      <p class="title">Record in Logic</p>
      <p class="sub">Keep a region — live stream alone never writes the project.</p>
    </div>
  </div>
  <p class="order"><strong>Capture order:</strong> Arm → Record in Logic → Play here.</p>
</div>
"""

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


# --- Hero: brand + one job ---
st.markdown(
    """
    <div class="hero">
      <div class="brand-mark">MIDI Style Lab</div>
      <h1>Pick a style. Generate a sketch. Play it into Logic.</h1>
      <p>Named catalog (who) plus optional feel — then Generate, audition in Logic, download.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Session defaults for honest who / feel paths
if "catalog_pick" not in st.session_state:
    st.session_state["catalog_pick"] = (
        "Philip Glass" if "Philip Glass" in musician_names else musician_names[0]
    )
if "vibe_text" not in st.session_state:
    st.session_state["vibe_text"] = ""
if "bars" not in st.session_state:
    st.session_state["bars"] = 8
if "effects_preset" not in st.session_state:
    st.session_state["effects_preset"] = "tape_and_human"

# Transport prefs (count-in / loop / soft-click) before Advanced widgets bind.
_seed_transport_bool_prefs()

# Pending related-style regenerate (Try instead / Surprise me — named identity jump)
_pending_related = st.session_state.pop("pending_related_name", None)
if _pending_related:
    # Named catalog hit → who path; otherwise leave as feel override
    if _pending_related in musician_names:
        st.session_state["catalog_pick"] = _pending_related
    else:
        st.session_state["vibe_text"] = _pending_related
    st.session_state["auto_generate"] = True

# Again: same recipe, new take/seed (not an identity jump)
_pending_again = st.session_state.pop("pending_again", False)
if _pending_again:
    st.session_state["gen_seed"] = random.randint(1, 2_147_483_646)
    st.session_state["auto_generate"] = True

has_sketch = bool(st.session_state.get("last_run"))

# --- Featured style cards (entry points; collapse after first successful Generate) ---
with st.expander(
    "Featured styles",
    expanded=not has_sketch,
):
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

_render_catalog_selectbox(musician_names)

# --- Empty-state feel path: bigger type-a-feel / tap-a-chip; hide geek chrome ---
if not has_sketch:
    st.markdown(
        '<p class="feel-path-label">Type a feel or tap a chip</p>',
        unsafe_allow_html=True,
    )
    st.text_input(
        "Vibe (feel)",
        placeholder="e.g. ambient drone, gymnopédie, sheets of sound, anything…",
        help=(
            "Layers on the selected artist. Does not replace them. "
            "Packs below are examples only."
        ),
        key="vibe_text",
        label_visibility="collapsed",
    )
    st.markdown(
        '<p class="path-hint">Mood packs teach the language — you can always type beyond them.</p>',
        unsafe_allow_html=True,
    )
    for pack in mood_packs:
        st.markdown(
            f'<p class="mood-pack-label">{pack.label}</p>',
            unsafe_allow_html=True,
        )
        cols = st.columns(max(2, len(pack.chips)))
        for j, chip in enumerate(pack.chips):
            with cols[j]:
                st.button(
                    f"{'● ' if st.session_state.get('vibe_text') == chip else ''}{chip}",
                    key=f"mood_{pack.id}_{j}",
                    use_container_width=True,
                    type="primary" if st.session_state.get("vibe_text") == chip else "secondary",
                    on_click=_apply_vibe_text,
                    args=(chip,),
                )
else:
    # Post-gen: vibe remains editable; packs stay available but quieter
    st.text_input(
        "Or type a vibe (feel)",
        placeholder="e.g. ambient drone, gymnopédie, sheets of sound, anything…",
        help=(
            "Layers on the selected artist. Does not replace them. "
            "Soft-matches tags; SDK research (if on) keeps the artist and applies this feel."
        ),
        key="vibe_text",
    )
    with st.expander("Mood packs", expanded=False):
        st.caption("Examples only — free-text stays first-class.")
        for pack in mood_packs:
            st.markdown(
                f'<p class="mood-pack-label">{pack.label}</p>',
                unsafe_allow_html=True,
            )
            cols = st.columns(max(2, len(pack.chips)))
            for j, chip in enumerate(pack.chips):
                with cols[j]:
                    st.button(
                        f"{'● ' if st.session_state.get('vibe_text') == chip else ''}{chip}",
                        key=f"mood_post_{pack.id}_{j}",
                        use_container_width=True,
                        type="primary" if st.session_state.get("vibe_text") == chip else "secondary",
                        on_click=_apply_vibe_text,
                        args=(chip,),
                    )

query = resolve_happy_path_query(st.session_state["catalog_pick"], st.session_state["vibe_text"])
effects_preset = st.session_state.get("effects_preset") or "tape_and_human"
if effects_preset not in preset_ids:
    effects_preset = "tape_and_human"
    st.session_state["effects_preset"] = effects_preset

# --- Pre-Generate artist drip (as user types / on lookup; not only on Generate) ---
_gate = resolve_artist_gate_for_ui(
    str(st.session_state.get("catalog_pick") or ""),
    str(st.session_state.get("vibe_text") or ""),
)
_artist_rejected = isinstance(_gate, ArtistGateReject) or not getattr(_gate, "accepted", False)
if _artist_rejected:
    # Blank recipe / stale sketch; store reason for tests; plain drip for humans.
    _had_last_run = bool(st.session_state.get("last_run"))
    st.session_state["artist_reject_reason"] = getattr(_gate, "reason", None)
    for _key in session_clears_on_artist_reject():
        st.session_state.pop(_key, None)
    st.session_state["generate_error"] = artist_reject_drip_copy(
        st.session_state.get("artist_reject_reason")
    )
    st.session_state.pop("auto_generate", None)
    st.session_state.pop("pending_replay", False)
    if _had_last_run:
        # Refresh featured / empty-state chrome after wiping last_run.
        st.rerun()
else:
    st.session_state.pop("artist_reject_reason", None)
    if st.session_state.get("generate_error") == ARTIST_REJECT_DRIP:
        st.session_state.pop("generate_error", None)

# --- Half / Double bars (real bars knob; no settings sprawl) ---
st.session_state["bars"] = clamp_bars(int(st.session_state.get("bars", 8)))
st.markdown('<div class="bars-chip-row">', unsafe_allow_html=True)
bars_label, half_col, double_col = st.columns([2, 1, 1])
with bars_label:
    st.caption(f"Loop length · **{st.session_state['bars']} bars**")
with half_col:
    st.button(
        "½ Half",
        use_container_width=True,
        key="bars_half",
        disabled=st.session_state["bars"] <= 2,
        help="Halve sketch length for a shorter playable loop.",
        on_click=_apply_half_bars,
    )
with double_col:
    st.button(
        "2× Double",
        use_container_width=True,
        key="bars_double",
        disabled=st.session_state["bars"] >= 32,
        help="Double sketch length for a longer playable loop.",
        on_click=_apply_double_bars,
    )
st.markdown("</div>", unsafe_allow_html=True)

# --- Recipe preview + plain-feel clarity (pre-Generate, no MIDI write) ---
# Reject: blank panel / drip only — never a fake catalog "About to generate" recipe.
recipe = preview_recipe(
    catalog_name=st.session_state["catalog_pick"],
    vibe_text=st.session_state["vibe_text"] if not _artist_rejected else "",
    effects_preset=effects_preset,
)
if _artist_rejected:
    st.markdown(
        f"""
        <div class="recipe-preview">
          <div class="label">Artist gate</div>
          <div class="line">{ARTIST_REJECT_DRIP}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    path_note = (
        "artist + feel (feel layers on)"
        if recipe.path == "both"
        else ("feel only" if recipe.path == "vibe" else "who path (named catalog)")
    )
    st.markdown(
        f"""
        <div class="recipe-preview">
          <div class="label">About to generate · {path_note}</div>
          <div class="line">{recipe.one_liner}</div>
          <div class="feel">{recipe.plain_feel_line}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

_pending_knobs = st.session_state.pop("_pending_profile_knobs", None)
if isinstance(_pending_knobs, dict):
    st.session_state.update(_pending_knobs)
_seed_arp_knobs(recipe.profile)
_render_arp_live(recipe.profile)

# Geek chrome (match type, SDK, soft-click, bars slider) — Advanced only
if "use_sdk" not in st.session_state:
    st.session_state["use_sdk"] = False
with st.expander("Advanced", expanded=False):
    if _artist_rejected:
        st.caption("Matched: —")
    else:
        st.caption(recipe.match_line)
    st.slider(
        "Bars",
        2,
        32,
        help="Defaults to the catalog profile length when left alone.",
        key="bars",
    )
    use_sdk = st.toggle(
        "Cursor SDK enrichment",
        key="use_sdk",
        help="Research the selected artist or vibe and drive sketch params from that. Requires CURSOR_API_KEY.",
    )
    if not use_sdk:
        sdk_line = "SDK: off — catalog only"
    elif cursor_sdk_available():
        sdk_line = "SDK: ready"
    else:
        sdk_line = "SDK: on, but CURSOR_API_KEY missing — catalog only"
    st.caption(sdk_line)
    # Soft click is opt-in and Off by default — tucked here so primary audition stays clean.
    soft_click = st.checkbox(
        "Soft click during count-in",
        key="live_soft_click",
        help="Sends metronome notes on the same MIDI port during count-in. "
        "Off by default — count-in stays truly silent. "
        "Count-in itself is under Before Record / Capture near Play.",
    )
    if soft_click:
        st.caption(
            "Warning: click MIDI will be captured if Logic is recording "
            "(same IAC bus as the sketch)."
        )
    else:
        st.caption("When Off, count-in stays truly silent (no click notes).")
    # Persist soft-click even before a sketch exists.
    _persist_live_prefs()

bars = clamp_bars(int(st.session_state.get("bars", 8)))

# --- Generate + Surprise me (adjacent; Surprise = named related jump, then generate) ---
st.markdown('<div class="generate-wrap">', unsafe_allow_html=True)
gen_col, surprise_col = st.columns([3, 1])
with gen_col:
    generate = st.button(
        "Generate",
        type="primary",
        use_container_width=True,
        disabled=_artist_rejected,
        help=ARTIST_REJECT_DRIP if _artist_rejected else None,
    )
with surprise_col:
    last_run_for_surprise = st.session_state.get("last_run")
    last_result = (
        last_run_for_surprise.get("result") if last_run_for_surprise else None
    )
    # Skip bouncing straight back to the last Surprise target when possible.
    previous_id = st.session_state.get("last_surprise_id")
    surprise_pick = (
        None
        if _artist_rejected
        else surprise_related_profile(
            recipe.profile,
            vibe_hint=query,
            last_result=last_result,
            previous_id=previous_id,
        )
    )
    st.button(
        "Surprise me",
        use_container_width=True,
        key="surprise_me",
        disabled=surprise_pick is None or _artist_rejected,
        help="Dice into a related named style from the full catalog, then generate.",
        on_click=_apply_surprise if surprise_pick is not None else None,
        args=(surprise_pick.name, surprise_pick.id) if surprise_pick is not None else (),
    )
st.markdown("</div>", unsafe_allow_html=True)
if st.session_state.pop("auto_generate", False):
    generate = False if _artist_rejected else True

player = get_shared_player()

# --- Generate ---
if generate:
    # Stop any in-flight clip before writing a new sketch (no old stream over new MIDI).
    player.stop(wait=True)
    st.session_state["live_was_playing"] = False
    with st.spinner("Resolving style and writing MIDI…"):
        overrides = {
            "effects_preset": effects_preset,
            "bars": int(bars),
            "debug": False,
        }
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
        # Again / explicit seed → new take; otherwise leave RNG unbound
        if "gen_seed" in st.session_state:
            overrides["seed"] = int(st.session_state.pop("gen_seed"))
        live_tweak = bool(st.session_state.pop("_live_param_tweak", False))
        try:
            path, result, options = generate_midi_for_style(
                query,
                use_cursor_sdk=use_sdk,
                overrides=overrides,
                live_tweak=live_tweak,
                identity_name=str(st.session_state.get("catalog_pick") or "").strip() or None,
                vibe_text=str(st.session_state.get("vibe_text") or "").strip() or None,
            )
            summary = summarize_midi_file(path)
            wav_bytes = render_midi_to_wav_bytes(path)
            plain = format_plain_feel_match(result.profile)
            st.session_state["last_run"] = {
                "path": path,
                "result": result,
                "options": options,
                "summary": summary,
                "query": query,
                "wav_bytes": wav_bytes,
                "preview_caption": describe_preview(path),
                "plain_feel_line": plain,
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
            # Refresh layout (collapse featured, show post-gen chrome)
            st.rerun()
        except ArtistRejected as exc:
            # Sample Musician drip: store reason for tests; plain copy only in UI.
            st.session_state["artist_reject_reason"] = exc.result.reason
            for _key in session_clears_on_artist_reject():
                st.session_state.pop(_key, None)
            st.session_state["generate_error"] = artist_reject_drip_copy(
                exc.result.reason
            )
            st.session_state.pop("pending_replay", False)
        except Exception as exc:
            st.session_state.pop("artist_reject_reason", None)
            st.session_state["generate_error"] = str(exc)
            st.session_state.pop("pending_replay", False)

if st.session_state.get("generate_error"):
    _reject = st.session_state.get("artist_reject_reason")
    if _reject or st.session_state["generate_error"] == ARTIST_REJECT_DRIP:
        # Never show "Rejected (not_a_musician)" / raw enums — Sample's plain drip.
        st.error(artist_reject_drip_copy(_reject))
    else:
        st.error(f"Generation failed: {st.session_state['generate_error']}")

run = st.session_state.get("last_run")
# Honor an explicit mid-session Refresh request before painting status.
_force_refresh = st.session_state.pop("refresh_midi_ports", False)
if _force_refresh and player.playing:
    # Don't refresh / clobber Streaming status while a clip is active.
    _force_refresh = False
live = player.status(refresh=_force_refresh)
ports = live.ports
if _force_refresh:
    _apply_refreshed_ports(ports)
# Seed remembered port once ports are known; else prefer IAC / first.
_seed_live_port(ports)
default_port = preferred_iac_port(ports) or (ports[0] if ports else None)
if "live_port" not in st.session_state and default_port:
    st.session_state["live_port"] = default_port

if run and st.session_state.pop("pending_replay", False):
    _replay_into_logic(player, run, ports)

# Freeze transport chrome while count-in / playing (Play is already disabled).
_transport_busy = bool(player.playing)

# First-run / empty-state IAC tip (not buried; dismiss after successful Play)
if not run:
    _show_iac_tip()
    st.info("Type a feel or tap a chip, then Generate — or Surprise me.")
else:
    result = run["result"]
    options = run["options"]
    summary = run["summary"]
    path = run["path"]
    profile = result.profile
    midi_bytes = Path(path).read_bytes()

    st.success(result.message)
    # Plain-feel clarity on happy path; geek match type stays in Advanced only
    plain = run.get("plain_feel_line") or format_plain_feel_match(profile)
    st.markdown(f'<p class="post-feel">{plain}</p>', unsafe_allow_html=True)
    st.caption(
        f"{options.get('mode')} · {options.get('bpm')} BPM · "
        f"{options.get('bars')} bars"
    )
    notes = str(getattr(profile, "style_notes", "") or "").strip()
    if notes:
        st.caption(notes)

    # --- Again + Try instead (hero-level with Play; above the fold) ---
    related = related_from_lookup_result(
        result, limit=3, vibe_hint=run.get("query") or ""
    )
    st.button(
        "Again",
        use_container_width=True,
        key="again_take",
        help="Same recipe, new take/seed.",
        on_click=_apply_again,
    )
    if related:
        st.markdown("#### Try instead")
        st.caption("Adjacent feels from the full catalog — regenerates without resetting the form.")
        rel_cols = st.columns(min(3, len(related)))
        for i, rel in enumerate(related[:3]):
            with rel_cols[i]:
                st.button(
                    rel.name,
                    key=f"related_{rel.id}",
                    use_container_width=True,
                    on_click=_apply_related,
                    args=(rel.name,),
                )

    # --- Primary CTA: Audition → Capture (Play into Logic) ---
    st.markdown("### Play into Logic")

    chip_col, refresh_col = st.columns([3, 1])
    with chip_col:
        _render_iac_status_chip(ports)
    with refresh_col:
        st.button(
            "Refresh ports",
            use_container_width=True,
            key="refresh_ports",
            disabled=_transport_busy,
            help="Disabled while Playing — Stop first.",
            on_click=_apply_refresh_ports,
        )

    if not live.available:
        _show_iac_tip()
        st.warning(
            live.error
            or "No MIDI ports available. Enable IAC Driver, then Refresh ports."
        )
    else:
        # Tip until first successful Play; chip is the always-on status signal.
        _show_iac_tip()

        if len(ports) > 1:
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
        else:
            st.caption(f"Port: **{ports[0]}**")
            st.session_state["live_port"] = ports[0]
            if not port_looks_like_iac(ports[0]):
                st.caption("Prefer enabling IAC Driver for Logic — then Refresh ports.")

        # Sample Musician bar: Play is the hero; instant audition by default.
        # Count-in / Loop / soft-click stay collapsed (Advanced / expander) — not strip chrome.
        if "live_count_in" not in st.session_state:
            st.session_state["live_count_in"] = False
        if "live_loop" not in st.session_state:
            st.session_state["live_loop"] = False
        if "live_sync_logic" not in st.session_state:
            st.session_state["live_sync_logic"] = True
        st.markdown(AUDITION_CAPTURE_STRIP_HTML, unsafe_allow_html=True)

        # Hero CTA row: Play dominates; Stop + compact Panic beside it.
        st.markdown('<div class="play-hero-row">', unsafe_allow_html=True)
        play_col, stop_col, panic_col = st.columns([4, 1, 1])
        with play_col:
            if st.button(
                "Play into Logic",
                type="primary",
                use_container_width=True,
                disabled=player.playing,
                key="play_logic",
            ):
                try:
                    sketch_bpm = float(options.get("bpm") or 120)
                    count_in = bool(st.session_state.get("live_count_in", False))
                    loop_play = bool(st.session_state.get("live_loop", False))
                    # Soft click only from Advanced (Off by default → silent count-in).
                    use_click = bool(st.session_state.get("live_soft_click", False))
                    lock_logic = bool(st.session_state.get("live_sync_logic", True))
                    player.play_file(
                        path,
                        st.session_state.get("live_port"),
                        count_in_bars=0.0 if lock_logic else (1.0 if count_in else 0.0),
                        bpm=sketch_bpm,
                        bars=float(options.get("bars") or 8),
                        loop=loop_play,
                        click=False if lock_logic else (use_click if count_in else False),
                        sync="follow" if lock_logic else "internal",
                        send_clock=False,
                    )
                    bits = [f"Streaming to {player.port_name}"]
                    if lock_logic:
                        bits.append("waiting for Logic Play")
                    elif count_in:
                        bits.append(
                            "1-bar count-in + soft click"
                            if use_click
                            else "1-bar count-in"
                        )
                    if loop_play:
                        bits.append("looping")
                    st.session_state["live_message"] = " · ".join(bits) + "."
                    st.session_state["live_was_playing"] = True
                    st.session_state["iac_tip_dismissed"] = True
                    _persist_live_prefs()
                    st.rerun()
                except Exception as exc:
                    st.session_state["live_message"] = f"Live MIDI failed: {exc}"
                    st.session_state["live_was_playing"] = bool(player.playing)
        with stop_col:
            stop_enabled = player.playing or bool(
                st.session_state.get("live_was_playing")
            )
            if st.button(
                "Stop",
                use_container_width=True,
                disabled=not stop_enabled,
                key="stop_logic",
            ):
                player.stop(wait=True)
                st.session_state["live_was_playing"] = False
                st.session_state["live_message"] = "Stopped."
                st.rerun()
        with panic_col:
            # Compact Panic near Stop — all-notes-off, not fake transport.
            panic_port = st.session_state.get("live_port") or player.port_name
            if st.button(
                "Panic",
                use_container_width=True,
                disabled=not bool(panic_port),
                key="panic_logic",
                help="All notes off (CC123) on the selected port. "
                "Works while Playing or idle. Does not Stop.",
            ):
                player.panic(panic_port)
                st.session_state["live_message"] = (
                    f"All notes off (CC123) on {panic_port}."
                )
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

        # Caption-only countdown / Playing / Finished — no big chrome.
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
                    loop_tag = " · looping" if player.looping else ""
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

        st.markdown(SILENCE_CHECKLIST_HTML, unsafe_allow_html=True)

        # Denser extras collapsed — count-in / loop off primary strip; soft click in Advanced.
        with st.expander("Before Record / Capture", expanded=False):
            st.caption(
                "Lock to Logic: transmit MIDI Clock from Logic to this IAC bus, "
                "then Play here, then Play in Logic. Notes fire on Logic’s downbeat."
            )
            opt_a, opt_b, opt_c = st.columns(3)
            with opt_a:
                st.checkbox(
                    "Lock to Logic clock",
                    key="live_sync_logic",
                    disabled=_transport_busy,
                    help="Wait for MIDI Start from Logic, then chase incoming clock. "
                    "Logic must transmit MIDI Clock to this IAC bus.",
                )
            with opt_b:
                st.checkbox(
                    "Count-in (1 silent bar)",
                    key="live_count_in",
                    disabled=_transport_busy,
                    help="Internal wall-clock only (ignored while Lock to Logic is On).",
                )
            with opt_c:
                st.checkbox(
                    "Loop sketch",
                    key="live_loop",
                    disabled=_transport_busy,
                    help="Repeat until Stop — useful if you miss the first pass.",
                )
            if st.session_state.get("live_soft_click"):
                st.caption(
                    "Soft click is On (Advanced) — click MIDI will be captured "
                    "if Logic is recording."
                )

        # Invisible prefs persistence (no settings UI).
        if not _transport_busy:
            _persist_live_prefs()

        # If the worker exited with last_error outside the poll, still surface it.
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

    # --- Secondary: Download first, then Listen preview ---
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
            data=run.get("wav_bytes") or b"",
            file_name=Path(path).with_suffix(".wav").name,
            mime="audio/wav",
            use_container_width=True,
            disabled=not bool(run.get("wav_bytes")),
        )

    # Effects as light post-gen chips only (no Effects panel / deep studio)
    st.markdown(
        '<p class="effect-lite">Effects seasoning</p>',
        unsafe_allow_html=True,
    )
    current_fx = options.get("effects_preset") or effects_preset
    fx_cols = st.columns(min(5, len(preset_ids)))
    for i, pid in enumerate(preset_ids):
        with fx_cols[i % len(fx_cols)]:
            label = presets[i]["label"] if i < len(presets) else pid
            is_on = pid == current_fx
            st.button(
                f"{'● ' if is_on else ''}{label}",
                key=f"fx_chip_{pid}",
                use_container_width=True,
                help=preset_labels.get(pid, pid),
                on_click=_apply_effects_preset if pid != current_fx else None,
                args=(pid,) if pid != current_fx else (),
            )

    st.markdown("### Listen")
    st.caption(
        "Quick sine preview — Play into Logic for real feel. "
        + (run.get("preview_caption") or "")
    )
    if run.get("wav_bytes"):
        st.audio(run["wav_bytes"], format="audio/wav")

    # --- Geek / Debug (collapsed lab chrome) ---
    with st.expander("Geek / Debug"):
        st.caption(run.get("match_line") or format_match_line(profile))
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
        roll = events_to_roll_rows(summary)
        if roll:
            st.scatter_chart(
                {
                    "beat": [r["beat"] for r in roll],
                    "midi": [r["midi"] for r in roll],
                },
                x="beat",
                y="midi",
                height=280,
            )
            st.dataframe(roll, use_container_width=True, hide_index=True, height=240)

        st.markdown("**Raw generator options**")
        st.json(options)

        st.markdown("**Effects glossary**")
        for preset in presets:
            st.markdown(
                f"""
                <div class="effect-chip">
                  <strong>{preset['label']}</strong>
                  <span>{preset['summary']} — {preset['what_you_hear']}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        for key, help_text in EFFECT_PARAM_HELP.items():
            st.markdown(f"**{key}** — {help_text}")

        st.caption("Style tags: " + ", ".join(list_styles()))
        st.caption("CLI (`python -m midi_gen`) remains available for power/dev use.")
