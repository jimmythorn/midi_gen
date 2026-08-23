"""
Streamlit UI for testing musician-style MIDI generation.

Run:
  PYTHONPATH=.. streamlit run midi_gen/ui_app.py
or from this repo (workspace = package root):
  python -m streamlit run ui_app.py
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

# Bootstrap: allow `midi_gen.*` imports when this folder is the repo root.
_ROOT = Path(__file__).resolve().parent
if "midi_gen" not in sys.modules:
    _pkg = types.ModuleType("midi_gen")
    _pkg.__path__ = [str(_ROOT)]  # type: ignore[attr-defined]
    _pkg.__file__ = str(_ROOT / "__init__.py")
    sys.modules["midi_gen"] = _pkg

import streamlit as st

from midi_gen.cursor_style_lookup import (
    cursor_sdk_available,
    generate_midi_for_style,
)
from midi_gen.effects_presets import (
    EFFECT_PARAM_HELP,
    explain_effects_config,
    list_presets,
)
from midi_gen.musician_styles import list_musicians, list_styles
from midi_gen.preview import events_to_roll_rows, format_summary_text, summarize_midi_file


st.set_page_config(page_title="MIDI Gen · Style Lab", page_icon="🎹", layout="wide")

st.title("MIDI Style Lab")
st.caption(
    "Look up a musician or style, map it to generation settings "
    "(local catalog and optional Cursor SDK), then inspect test MIDI output."
)

with st.sidebar:
    st.header("Lookup")
    query = st.text_input(
        "Musician or style",
        value="Philip Glass minimalism",
        help="Examples: Brian Eno, jazz angular, ambient drone, Aphex Twin",
    )
    use_sdk = st.toggle(
        "Use Cursor SDK when available",
        value=True,
        help="Requires CURSOR_API_KEY. Falls back to the local catalog otherwise.",
    )
    sdk_ready = cursor_sdk_available()
    st.write("Cursor SDK:", "ready" if sdk_ready else "offline (catalog only)")

    st.header("Catalog")
    musicians = list_musicians()
    pick = st.selectbox(
        "Or pick a catalog musician",
        options=["(use query)"] + [m.name for m in musicians],
    )
    if pick != "(use query)":
        query = pick

    st.header("Overrides")
    presets = list_presets()
    preset_ids = [p["id"] for p in presets]
    preset_labels = {p["id"]: p["label"] for p in presets}
    effects_preset = st.selectbox(
        "Effects preset",
        options=preset_ids,
        format_func=lambda i: preset_labels[i],
        index=preset_ids.index("tape_and_human") if "tape_and_human" in preset_ids else 0,
    )
    bars = st.slider("Bars", 2, 32, 8)
    bpm_override = st.number_input("BPM override (0 = use profile)", min_value=0, max_value=240, value=0)

    generate = st.button("Generate MIDI", type="primary", use_container_width=True)

# Effects explainer — always visible so the feature is understandable
st.subheader("Effects (plain language)")
cols = st.columns(len(presets))
for col, preset in zip(cols, presets):
    with col:
        st.markdown(f"**{preset['label']}**")
        st.write(preset["summary"])
        with st.expander("What you hear"):
            st.write(preset["what_you_hear"])
            for effect in preset["effects"]:
                st.code(effect, language="json")

with st.expander("Parameter glossary"):
    for key, help_text in EFFECT_PARAM_HELP.items():
        st.markdown(f"**{key}** — {help_text}")

st.subheader("Known style tags")
st.write(", ".join(list_styles()))

if generate:
    with st.spinner("Looking up style and generating MIDI…"):
        overrides = {
            "effects_preset": effects_preset,
            "bars": bars,
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

    st.success(result.message)
    left, right = st.columns([1, 1])
    with left:
        st.markdown("### Profile")
        profile = result.profile
        st.write(
            {
                "name": profile.name,
                "id": profile.id,
                "styles": profile.styles,
                "source": profile.source,
                "generation_type": profile.generation_type,
                "mode": profile.mode,
                "bpm": options.get("bpm"),
                "bars": options.get("bars"),
                "arp_mode": profile.arp_mode,
                "arp_steps": profile.arp_steps,
                "effects_preset": options.get("effects_preset"),
                "used_cursor_sdk": result.used_cursor_sdk,
            }
        )
        st.write(profile.description)
        st.markdown("### Effects applied")
        for line in explain_effects_config(options.get("effects_config") or []):
            st.write(f"- {line}")
        if result.candidates:
            st.markdown("### Other catalog candidates")
            st.write([c.name for c in result.candidates])

    with right:
        st.markdown("### Test output")
        st.code(format_summary_text(summary))
        midi_bytes = Path(path).read_bytes()
        st.download_button(
            "Download MIDI",
            data=midi_bytes,
            file_name=Path(path).name,
            mime="audio/midi",
            use_container_width=True,
        )
        roll = events_to_roll_rows(summary)
        if roll:
            st.markdown("### Note preview")
            st.dataframe(roll, use_container_width=True, hide_index=True)
            st.scatter_chart(
                {
                    "beat": [r["beat"] for r in roll],
                    "midi": [r["midi"] for r in roll],
                },
                x="beat",
                y="midi",
                size=None,
            )

    with st.expander("Raw options sent to generator"):
        st.json(options)
else:
    st.info("Set a musician/style query and click **Generate MIDI** to see test output.")
