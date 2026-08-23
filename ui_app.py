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
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if "midi_gen" not in sys.modules:
    _pkg = types.ModuleType("midi_gen")
    _pkg.__path__ = [str(_ROOT)]  # type: ignore[attr-defined]
    _pkg.__file__ = str(_ROOT / "__init__.py")
    sys.modules["midi_gen"] = _pkg

import streamlit as st

from midi_gen.cursor_style_lookup import cursor_sdk_available, generate_midi_for_style
from midi_gen.effects_presets import EFFECT_PARAM_HELP, explain_effects_config, list_presets
from midi_gen.musician_styles import list_musicians, list_styles
from midi_gen.preview import events_to_roll_rows, format_summary_text, summarize_midi_file
from midi_gen.audio_preview import describe_preview, render_midi_to_wav_bytes
from midi_gen.live_midi import get_shared_player, preferred_iac_port


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

      .record-note {
        color: var(--muted);
        font-size: 0.92rem;
        margin: 0.35rem 0 0.85rem 0;
      }

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
    </style>
    """,
    unsafe_allow_html=True,
)

musicians = list_musicians()
musician_names = [m.name for m in musicians]
presets = list_presets()
preset_ids = [p["id"] for p in presets]
preset_labels = {p["id"]: f"{p['label']} — {p['summary']}" for p in presets}

IAC_FIRST_RUN_TIP = """
<div class="tip">
  <strong>One-time Mac setup for Logic</strong><br/>
  Audio MIDI Setup → MIDI Studio → IAC Driver → enable <em>Device is online</em>.
  In Logic, set a Software Instrument track’s MIDI In to that IAC bus.
  After that, Play into Logic is one click.
</div>
"""

# --- Hero: brand + one job ---
st.markdown(
    """
    <div class="hero">
      <div class="brand-mark">MIDI Style Lab</div>
      <h1>Pick a style. Generate a sketch. Play it into Logic.</h1>
      <p>Starting sketches, not finished compositions — generate MIDI, audition in Logic, then download.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# --- Pre-generate: catalog primary, vibe secondary ---
catalog = st.selectbox(
    "Style",
    options=musician_names,
    index=musician_names.index("Philip Glass") if "Philip Glass" in musician_names else 0,
    help="Curated catalog profiles.",
)
vibe = st.text_input(
    "Or type a vibe",
    value="",
    placeholder="e.g. ambient drone, angular jazz, Aphex Twin",
    help="Overrides the catalog pick when filled.",
)
query = vibe.strip() if vibe.strip() else catalog

effects_preset = st.selectbox(
    "Effects",
    options=preset_ids,
    format_func=lambda i: preset_labels[i],
    index=preset_ids.index("tape_and_human"),
    help="Plain-language processing applied after notes are written.",
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
        help="Uses CURSOR_API_KEY when set; otherwise catalog only.",
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
            }
            st.session_state.pop("generate_error", None)
            st.session_state.pop("live_message", None)
        except Exception as exc:
            st.session_state["generate_error"] = str(exc)

if st.session_state.get("generate_error"):
    st.error(f"Generation failed: {st.session_state['generate_error']}")

run = st.session_state.get("last_run")
player = get_shared_player()
live = player.status()
ports = live.ports
default_port = preferred_iac_port(ports) or (ports[0] if ports else None)
if "live_port" not in st.session_state and default_port:
    st.session_state["live_port"] = default_port

# First-run / empty-state IAC tip (not buried)
if not run:
    st.markdown(IAC_FIRST_RUN_TIP, unsafe_allow_html=True)
    st.info("Pick a style and Generate to get a sketch.")
else:
    result = run["result"]
    options = run["options"]
    summary = run["summary"]
    path = run["path"]
    profile = result.profile
    midi_bytes = Path(path).read_bytes()

    st.success(result.message)
    st.caption(
        f"{profile.name} · {options.get('mode')} · {options.get('bpm')} BPM · "
        f"{options.get('bars')} bars · {profile.generation_type}"
    )

    # --- Primary CTA: Play into Logic ---
    st.markdown("### Play into Logic")
    if not live.available:
        st.markdown(IAC_FIRST_RUN_TIP, unsafe_allow_html=True)
        st.warning(
            live.error
            or "No MIDI ports available. Enable IAC Driver, then relaunch this app."
        )
    else:
        if len(ports) > 1:
            st.selectbox(
                "MIDI output port",
                options=ports,
                key="live_port",
                help="Prefer an IAC Driver bus.",
            )
        else:
            st.caption(f"Port: **{ports[0]}**")
            st.session_state["live_port"] = ports[0]

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
                    player.play_file(path, st.session_state.get("live_port"))
                    st.session_state["live_message"] = f"Streaming to {player.port_name}."
                except Exception as exc:
                    st.session_state["live_message"] = f"Live MIDI failed: {exc}"
        with stop_col:
            if st.button(
                "Stop",
                use_container_width=True,
                disabled=not player.playing,
                key="stop_logic",
            ):
                player.stop(wait=False)
                st.session_state["live_message"] = "Stopped."

        st.markdown(
            '<p class="record-note"><strong>Record in Logic to capture</strong> — '
            "live stream alone never writes a region. Arm the track and hit Record "
            "while this plays.</p>",
            unsafe_allow_html=True,
        )
        if player.playing:
            st.caption(f"Playing → **{player.port_name}**")
        if st.session_state.get("live_message"):
            st.info(st.session_state["live_message"])
        if player.last_error:
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
