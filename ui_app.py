"""
MIDI Style Lab — Streamlit UI for style → sketch → Logic.

North star: Pick style → Generate → Play into Logic → Download MIDI.

Launch:
  ./run_ui.sh
  # or
  PYTHONPATH=. streamlit run ui_app.py
"""

from __future__ import annotations

import sys
import types
from datetime import timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if "midi_gen" not in sys.modules:
    _pkg = types.ModuleType("midi_gen")
    _pkg.__path__ = [str(_ROOT)]  # type: ignore[attr-defined]
    _pkg.__file__ = str(_ROOT / "__init__.py")
    sys.modules["midi_gen"] = _pkg

import streamlit as st

from midi_gen.audio_preview import describe_preview, render_midi_to_wav_bytes
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
    featured_style_cards,
    format_match_line,
    preview_recipe,
    related_from_lookup_result,
    resolve_happy_path_query,
    vibe_chips,
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

      /* Audition → Capture: one visual unit; live stream ≠ region */
      .audition-capture {
        border: 1px solid var(--line);
        border-bottom: none;
        border-radius: 14px 14px 0 0;
        background: color-mix(in srgb, var(--panel) 90%, black);
        padding: 0.85rem 1rem 0.35rem 1rem;
        margin: 0.35rem 0 0 0;
        max-width: 40rem;
      }
      .audition-capture-bottom {
        border: 1px solid var(--line);
        border-top: none;
        border-radius: 0 0 14px 14px;
        background: color-mix(in srgb, var(--panel) 90%, black);
        padding: 0.15rem 1rem 0.95rem 1rem;
        margin: 0 0 0.85rem 0;
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
        margin: 0 0 0.35rem 0;
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
      .audition-capture-bottom .order {
        color: var(--muted);
        font-size: 0.88rem;
        margin: 0;
        padding-top: 0.45rem;
        border-top: 1px solid var(--line);
      }
      .audition-capture-bottom .order strong { color: var(--text); }
      /* Count-in / Loop sit inside the strip unit (denser than a separate block) */
      .audition-capture .strip-opts-label {
        color: var(--muted);
        font-size: 0.72rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin: 0.45rem 0 0 0;
        padding-top: 0.45rem;
        border-top: 1px solid var(--line);
      }
      /* Bridge Streamlit checkbox row into the strip chrome */
      div[data-testid="stHorizontalBlock"]:has(div[data-testid="stCheckbox"]) {
        max-width: 40rem;
        margin: 0 !important;
        padding: 0.15rem 1rem 0.25rem 1rem;
        border-left: 1px solid var(--line);
        border-right: 1px solid var(--line);
        background: color-mix(in srgb, var(--panel) 90%, black);
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

      /* Bigger primary Generate CTA */
      div[data-testid="stVerticalBlock"] > div:has(> div > button[kind="primary"][data-testid="baseButton-primary"]) button[kind="primary"] {
        min-height: 3rem;
        font-size: 1.05rem !important;
        padding: 0.65rem 1.25rem !important;
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
      .path-hint {
        color: var(--muted);
        font-size: 0.88rem;
        margin: 0.15rem 0 0.65rem 0;
      }
      .featured-blurb {
        color: var(--muted);
        font-size: 0.82rem;
        margin: 0.2rem 0 0.55rem 0;
        min-height: 2.2em;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

musicians = list_musicians()
musician_names = [m.name for m in musicians]
presets = list_presets()
preset_ids = [p["id"] for p in presets]
preset_labels = {p["id"]: f"{p['label']} — {p['summary']}" for p in presets}
featured_cards = featured_style_cards()
vibe_examples = vibe_chips()

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

# Split so Count-in / Loop widgets sit inside the same visual strip unit.
AUDITION_CAPTURE_STRIP_TOP_HTML = """
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
  <div class="strip-opts-label">Before Record / Capture (optional)</div>
</div>
"""

AUDITION_CAPTURE_STRIP_BOTTOM_HTML = """
<div class="audition-capture-bottom">
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
      <p>Named catalog (who) or free-text vibe (feel) — then Generate, audition in Logic, download.</p>
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

# Pending related-style regenerate (Try instead)
_pending_related = st.session_state.pop("pending_related_name", None)
if _pending_related:
    # Named catalog hit → who path; otherwise leave as feel override
    if _pending_related in musician_names:
        st.session_state["catalog_pick"] = _pending_related
        st.session_state["vibe_text"] = ""
    else:
        st.session_state["vibe_text"] = _pending_related
    st.session_state["auto_generate"] = True

# --- Featured style cards (entry points across full catalog) ---
st.markdown("#### Featured styles")
st.caption("Tap a name to select that catalog profile — not a closed list; full catalog below.")
feat_cols = st.columns(3)
for i, card in enumerate(featured_cards):
    with feat_cols[i % 3]:
        if st.button(card.name, key=f"feat_{card.id}", use_container_width=True):
            st.session_state["catalog_pick"] = card.name
            st.session_state["vibe_text"] = ""
            st.rerun()
        st.markdown(f'<p class="featured-blurb">{card.blurb}</p>', unsafe_allow_html=True)

# --- Catalog (who) ---
if st.session_state["catalog_pick"] not in musician_names:
    st.session_state["catalog_pick"] = musician_names[0]
catalog = st.selectbox(
    "Style (catalog — who)",
    options=musician_names,
    help="Named musician/style profiles from the full curated catalog.",
    key="catalog_pick",
)
# --- Free-text vibe (feel) — first-class, not a thin alias ---
st.text_input(
    "Or type a vibe (feel)",
    placeholder="e.g. ambient drone, gymnopédie, sheets of sound, anything…",
    help=(
        "First-class path: type any feel. Soft-matches the catalog (aliases + tags), "
        "optional SDK enrich, or an honest generic sketch — chips below are examples only."
    ),
    key="vibe_text",
)
st.markdown(
    '<p class="path-hint">Chips teach the language — you can always type beyond them.</p>',
    unsafe_allow_html=True,
)
chip_rows = [vibe_examples[i : i + 4] for i in range(0, len(vibe_examples), 4)]
for row_i, row in enumerate(chip_rows):
    cols = st.columns(4)
    for j, chip in enumerate(row):
        with cols[j]:
            if st.button(chip, key=f"vibe_chip_{row_i}_{j}", use_container_width=True):
                st.session_state["vibe_text"] = chip
                st.rerun()

query = resolve_happy_path_query(st.session_state["catalog_pick"], st.session_state["vibe_text"])

effects_preset = st.selectbox(
    "Effects",
    options=preset_ids,
    format_func=lambda i: preset_labels[i],
    index=preset_ids.index("tape_and_human"),
    help="Seasoning after notes are written — not a substitute for style pick.",
)

# --- Recipe preview + match transparency (pre-Generate, no MIDI write) ---
recipe = preview_recipe(
    catalog_name=st.session_state["catalog_pick"],
    vibe_text=st.session_state["vibe_text"],
    effects_preset=effects_preset,
)
path_note = (
    "feel path (vibe overrides catalog)"
    if recipe.path == "vibe"
    else "who path (named catalog)"
)
st.markdown(
    f"""
    <div class="recipe-preview">
      <div class="label">About to generate · {path_note}</div>
      <div class="line">{recipe.one_liner}</div>
      <div class="match">{recipe.match_line}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.expander("Advanced"):
    bars = st.slider(
        "Bars",
        2,
        32,
        int(st.session_state.get("bars", 8)),
        help="Defaults to the catalog profile length when left alone.",
    )
    use_sdk = st.toggle(
        "Cursor SDK enrichment",
        value=False,
        help="Uses CURSOR_API_KEY when set; otherwise catalog only. Enrich-this-vibe, not a rewrite.",
    )
    st.caption(
        "SDK: " + ("ready" if cursor_sdk_available() else "offline — catalog only")
    )
    bpm_override = st.number_input(
        "BPM override (0 = profile tempo)",
        min_value=0,
        max_value=240,
        value=0,
    )

st.markdown('<div class="generate-wrap">', unsafe_allow_html=True)
generate = st.button("Generate", type="primary", use_container_width=True)
st.markdown("</div>", unsafe_allow_html=True)
if st.session_state.pop("auto_generate", False):
    generate = True

# --- Generate ---
if generate:
    with st.spinner("Resolving style and writing MIDI…"):
        overrides = {
            "effects_preset": effects_preset,
            "bars": int(bars),
            "debug": False,
        }
        if bpm_override:
            overrides["bpm"] = int(bpm_override)
        try:
            path, result, options = generate_midi_for_style(
                query,
                use_cursor_sdk=use_sdk,
                overrides=overrides,
            )
            summary = summarize_midi_file(path)
            wav_bytes = render_midi_to_wav_bytes(path)
            st.session_state["last_run"] = {
                "path": path,
                "result": result,
                "options": options,
                "summary": summary,
                "query": query,
                "wav_bytes": wav_bytes,
                "preview_caption": describe_preview(path),
                "match_line": format_match_line(
                    result.profile,
                    effects_preset=options.get("effects_preset") or effects_preset,
                    matched_locally=result.matched_locally,
                    used_cursor_sdk=result.used_cursor_sdk,
                ),
            }
            st.session_state.pop("generate_error", None)
            st.session_state.pop("live_message", None)
        except Exception as exc:
            st.session_state["generate_error"] = str(exc)

if st.session_state.get("generate_error"):
    st.error(f"Generation failed: {st.session_state['generate_error']}")

run = st.session_state.get("last_run")
player = get_shared_player()
# Honor an explicit mid-session Refresh request before painting status.
_force_refresh = st.session_state.pop("refresh_midi_ports", False)
live = player.status(refresh=_force_refresh)
ports = live.ports
if _force_refresh:
    _apply_refreshed_ports(ports)
default_port = preferred_iac_port(ports) or (ports[0] if ports else None)
if "live_port" not in st.session_state and default_port:
    st.session_state["live_port"] = default_port

# First-run / empty-state IAC tip (not buried; dismiss after successful Play)
if not run:
    _show_iac_tip()
    st.info("Pick a style or type a vibe, then Generate.")
else:
    result = run["result"]
    options = run["options"]
    summary = run["summary"]
    path = run["path"]
    profile = result.profile
    midi_bytes = Path(path).read_bytes()

    st.success(result.message)
    st.caption(run.get("match_line") or format_match_line(profile))
    st.caption(
        f"{profile.name} · {options.get('mode')} · {options.get('bpm')} BPM · "
        f"{options.get('bars')} bars · {profile.generation_type}"
    )

    # --- Try instead / related (flexibility lever; full-catalog related) ---
    related = related_from_lookup_result(
        result, limit=3, vibe_hint=run.get("query") or ""
    )
    if related:
        st.markdown("#### Try instead")
        st.caption("Adjacent feels from the full catalog — regenerates without resetting the form.")
        rel_cols = st.columns(min(3, len(related)))
        for i, rel in enumerate(related[:3]):
            with rel_cols[i]:
                if st.button(
                    rel.name,
                    key=f"related_{rel.id}",
                    use_container_width=True,
                ):
                    st.session_state["pending_related_name"] = rel.name
                    st.rerun()

    # --- Primary CTA: Audition → Capture (Play into Logic) ---
    st.markdown("### Play into Logic")

    chip_col, refresh_col = st.columns([3, 1])
    with chip_col:
        _render_iac_status_chip(ports)
    with refresh_col:
        if st.button("Refresh ports", use_container_width=True, key="refresh_ports"):
            st.session_state["refresh_midi_ports"] = True
            refreshed = refresh_output_ports()
            _apply_refreshed_ports(refreshed)
            st.session_state["live_message"] = (
                f"Ports refreshed · {len(refreshed)} available."
                if refreshed
                else "No ports yet — enable IAC, then Refresh again."
            )
            st.rerun()

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

        # Audition→Capture strip: lanes + Count-in/Loop (opt-in) + capture order.
        # Instant audition by default — count-in is OFF until the user opts in.
        if "live_count_in" not in st.session_state:
            st.session_state["live_count_in"] = False
        if "live_loop" not in st.session_state:
            st.session_state["live_loop"] = False
        st.markdown(AUDITION_CAPTURE_STRIP_TOP_HTML, unsafe_allow_html=True)
        opt_a, opt_b = st.columns(2)
        with opt_a:
            count_in = st.checkbox(
                "Count-in (1 silent bar)",
                key="live_count_in",
                help="Opt in before Record/Capture for time after Arm→Record. "
                "Off by default for instant audition. Silent (no metronome MIDI).",
            )
        with opt_b:
            loop_play = st.checkbox(
                "Loop sketch",
                key="live_loop",
                help="Repeat until Stop — useful if you miss the first pass.",
            )
        st.markdown(AUDITION_CAPTURE_STRIP_BOTTOM_HTML, unsafe_allow_html=True)

        play_col, stop_col = st.columns([2, 1])
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
                    player.play_file(
                        path,
                        st.session_state.get("live_port"),
                        count_in_bars=1.0 if count_in else 0.0,
                        bpm=sketch_bpm,
                        loop=bool(loop_play),
                    )
                    bits = [f"Streaming to {player.port_name}"]
                    if count_in:
                        bits.append("1-bar count-in")
                    if loop_play:
                        bits.append("looping")
                    st.session_state["live_message"] = " · ".join(bits) + "."
                    st.session_state["live_was_playing"] = True
                    # Hide first-run tip after a successful Play
                    st.session_state["iac_tip_dismissed"] = True
                    st.rerun()
                except Exception as exc:
                    st.session_state["live_message"] = f"Live MIDI failed: {exc}"
                    st.session_state["live_was_playing"] = False
        with stop_col:
            if st.button(
                "Stop",
                use_container_width=True,
                disabled=not player.playing,
                key="stop_logic",
            ):
                player.stop(wait=True)
                st.session_state["live_was_playing"] = False
                st.session_state["live_message"] = "Stopped."
                st.rerun()

        # Honest Playing caption: poll while active; clear when thread ends
        # or when the MIDI port disappears / send fails mid-play.
        if player.playing or st.session_state.get("live_was_playing"):

            @st.fragment(run_every=timedelta(milliseconds=400))
            def _playback_status_poll() -> None:
                err = player.last_error
                if player.playing:
                    # Port vanished from enumeration while still "playing".
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
                    phase = player.phase
                    label = "Count-in" if phase == "count_in" else "Playing"
                    loop_tag = " · looping" if player.looping else ""
                    st.caption(f"{label} → **{player.port_name}**{loop_tag}")
                    return
                # Worker finished (natural end, Stop, or port/send failure).
                if st.session_state.pop("live_was_playing", False):
                    if err:
                        st.session_state["live_message"] = err
                    else:
                        msg = st.session_state.get("live_message") or ""
                        if msg.startswith("Streaming"):
                            st.session_state["live_message"] = "Finished."
                    st.rerun()

            _playback_status_poll()
        elif st.session_state.get("live_message") == "Stopped.":
            st.caption("Stopped.")

        st.markdown(SILENCE_CHECKLIST_HTML, unsafe_allow_html=True)

        live_msg = st.session_state.get("live_message")
        if live_msg:
            if "port lost" in live_msg.lower() or (
                player.last_error and "port lost" in (player.last_error or "").lower()
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

    st.markdown("### Listen")
    st.caption(
        "Quick sine preview — Play into Logic for real feel. "
        + (run.get("preview_caption") or "")
    )
    if run.get("wav_bytes"):
        st.audio(run["wav_bytes"], format="audio/wav")

    # --- Geek / Debug (collapsed lab chrome) ---
    with st.expander("Geek / Debug"):
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
