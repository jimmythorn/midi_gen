"""
MIDI Style Lab — Streamlit UI with musician/style lookup and test output.

Launch:
  ./run_ui.sh
  # or
  PYTHONPATH=/tmp/py streamlit run ui_app.py
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

      .panel {
        background: color-mix(in srgb, var(--panel) 92%, black);
        border: 1px solid var(--line);
        border-radius: 14px;
        padding: 1rem 1.1rem;
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
    </style>
    """,
    unsafe_allow_html=True,
)

musicians = list_musicians()
presets = list_presets()
preset_ids = [p["id"] for p in presets]
preset_labels = {p["id"]: f"{p['label']} — {p['summary']}" for p in presets}

# --- Hero: brand + one job ---
st.markdown(
    """
    <div class="hero">
      <div class="brand-mark">MIDI Style Lab</div>
      <h1>MIDI in the shape of a musician’s style.</h1>
      <p>Look up a player or vibe, generate a sketch, and inspect the test output before you export.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

query_col, action_col = st.columns([3, 1], vertical_alignment="bottom")
with query_col:
    query = st.text_input(
        "Musician or style",
        value=st.session_state.get("query", "Philip Glass minimalism"),
        placeholder="e.g. Brian Eno, angular jazz, ambient drone, Aphex Twin",
        label_visibility="collapsed",
        key="query_input",
    )
with action_col:
    generate = st.button("Generate MIDI", type="primary", use_container_width=True)

# Compact controls under the hero (one secondary strip — not a dashboard)
c1, c2, c3, c4 = st.columns([1.2, 1.4, 1, 1])
with c1:
    pick = st.selectbox(
        "Catalog musician",
        options=["(from query)"] + [m.name for m in musicians],
        help="Optional shortcut into the curated catalog.",
    )
with c2:
    effects_preset = st.selectbox(
        "Effects",
        options=preset_ids,
        format_func=lambda i: preset_labels[i],
        index=preset_ids.index("tape_and_human"),
        help="Plain-language processing applied after notes are written.",
    )
with c3:
    bars = st.slider("Bars", 2, 32, int(st.session_state.get("bars", 8)))
with c4:
    use_sdk = st.toggle("Cursor SDK", value=True, help="Uses CURSOR_API_KEY when set; otherwise catalog only.")
    st.caption("SDK: " + ("ready" if cursor_sdk_available() else "offline"))

if pick != "(from query)":
    query = pick

bpm_override = st.number_input(
    "BPM override (0 keeps the profile tempo)",
    min_value=0,
    max_value=240,
    value=0,
)

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

# --- Test output (persists across reruns) ---
run = st.session_state.get("last_run")
if not run:
    st.info("Enter a musician or style, then generate to see test output here.")
else:
    result = run["result"]
    options = run["options"]
    summary = run["summary"]
    path = run["path"]
    profile = result.profile

    st.markdown("### Test output")
    st.success(result.message)

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

    left, right = st.columns([1.05, 1.2], gap="large")
    with left:
        st.markdown("#### Profile")
        st.markdown(f"**{profile.name}** · `{profile.source}` · {profile.generation_type}")
        st.write(profile.description)
        st.write(
            f"Mode **{options.get('mode')}** · "
            f"{options.get('bpm')} BPM · "
            f"{options.get('bars')} bars · "
            f"arp `{profile.arp_mode}` / {profile.arp_steps} steps"
        )
        st.markdown("#### Effects applied")
        for line in explain_effects_config(options.get("effects_config") or []):
            st.write(f"- {line}")
        if result.candidates:
            st.caption("Also considered: " + ", ".join(c.name for c in result.candidates))

        midi_bytes = Path(path).read_bytes()
        st.markdown("#### Listen")
        st.caption(run.get("preview_caption") or "Simple synth preview (not a DAW instrument).")
        if run.get("wav_bytes"):
            st.audio(run["wav_bytes"], format="audio/wav")
        st.download_button(
            "Download MIDI",
            data=midi_bytes,
            file_name=Path(path).name,
            mime="audio/midi",
            use_container_width=True,
        )
        st.download_button(
            "Download WAV preview",
            data=run.get("wav_bytes") or b"",
            file_name=Path(path).with_suffix(".wav").name,
            mime="audio/wav",
            use_container_width=True,
            disabled=not bool(run.get("wav_bytes")),
        )
        st.code(format_summary_text(summary))

    with right:
        st.markdown("#### Note preview")
        roll = events_to_roll_rows(summary)
        if roll:
            st.scatter_chart(
                {
                    "beat": [r["beat"] for r in roll],
                    "midi": [r["midi"] for r in roll],
                },
                x="beat",
                y="midi",
                height=320,
            )
            st.dataframe(roll, use_container_width=True, hide_index=True, height=280)

    with st.expander("Raw generator options"):
        st.json(options)

# --- Effects explainer (below the fold; one purpose) ---
st.markdown("---")
st.markdown("### Effects, in plain language")
st.caption("These reshape the finished note stream. Pick a preset above — details live here.")
effect_cols = st.columns(len(presets))
for col, preset in zip(effect_cols, presets):
    with col:
        st.markdown(
            f"""
            <div class="effect-chip">
              <strong>{preset['label']}</strong>
              <span>{preset['summary']}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.expander("What you hear"):
            st.write(preset["what_you_hear"])

with st.expander("Parameter glossary (wow, flutter, cents…)"):
    for key, help_text in EFFECT_PARAM_HELP.items():
        st.markdown(f"**{key}** — {help_text}")

st.caption("Style tags: " + ", ".join(list_styles()))
