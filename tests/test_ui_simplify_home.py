"""UI Simplify Now — timing / mode wiring + home chrome (musician labels)."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
if "midi_gen" not in sys.modules:
    _pkg = types.ModuleType("midi_gen")
    _pkg.__path__ = [str(_ROOT)]  # type: ignore[attr-defined]
    _pkg.__file__ = str(_ROOT / "__init__.py")
    sys.modules["midi_gen"] = _pkg

from midi_gen.arpeggio_generation import apply_generation_mode, apply_timing_factor
from midi_gen.cursor_style_lookup import (
    LOOKUP_STICKY_OVERRIDE_KEYS,
    generate_midi_for_style,
)
from midi_gen.style_prompting import (
    DEFAULT_GENERATION_MODE,
    DEFAULT_TIMING_FACTOR,
    TIMING_CHIP_FACTORS,
    TIMING_CHIP_LABELS,
    catalog_name_matches,
    clamp_generation_mode,
    clamp_timing_factor,
    generation_mode_from_type,
    toggle_timing_factor,
)


def test_timing_chip_toggle_and_labels():
    assert tuple(TIMING_CHIP_FACTORS) == (0.5, 1.0, 2.0, 4.0)
    assert [f for f, _ in TIMING_CHIP_LABELS] == list(TIMING_CHIP_FACTORS)
    assert clamp_timing_factor(None) == DEFAULT_TIMING_FACTOR
    assert toggle_timing_factor(1, 0.5) == 0.5
    assert toggle_timing_factor(0.5, 0.5) == 1.0
    assert toggle_timing_factor(1, 2) == 2.0
    assert toggle_timing_factor(2, 4) == 4.0
    assert toggle_timing_factor(4, 4) == 1.0
    assert toggle_timing_factor(1, 1) == 1.0


def test_generation_mode_clamp_and_legacy_type():
    assert clamp_generation_mode("pattern") == "pattern"
    assert clamp_generation_mode("progression") == "progression"
    assert clamp_generation_mode("arpeggio") == "pattern"
    assert clamp_generation_mode("drone") == "progression"
    assert generation_mode_from_type("arpeggio") == "pattern"
    assert generation_mode_from_type("drone") == "progression"
    assert DEFAULT_GENERATION_MODE == "progression"


def test_catalog_name_matches_artist_combo():
    hits = catalog_name_matches("Glass", limit=5)
    assert "Philip Glass" in hits
    assert catalog_name_matches("", limit=5) == []


def test_generate_overrides_wire_timing_and_generation_mode(tmp_path):
    captured = {}

    def fake_create_arp(options):
        # Mirror Engine create_arp stretch.
        stretched = apply_timing_factor(dict(options))
        captured["options"] = stretched
        out = tmp_path / "sketch.mid"
        out.write_bytes(b"MThd")
        return str(out)

    with mock.patch(
        "midi_gen.arpeggio_generation.create_arp", side_effect=fake_create_arp
    ):
        path, result, options = generate_midi_for_style(
            "Philip Glass",
            use_cursor_sdk=False,
            overrides={
                "bars": 8,
                "timing_factor": 2,
                "generation_mode": "pattern",
            },
        )
    assert path.endswith("sketch.mid")
    assert result.profile.id == "glass_minimal"
    assert options.get("generation_type") == "arpeggio"
    assert captured["options"].get("timing_factor") in (2, 2.0)
    assert captured["options"]["bars"] == 16


def test_generate_progression_mode_respects_wash_opt_out(tmp_path):
    captured = {}

    def fake_create_arp(options):
        captured["options"] = dict(options)
        out = tmp_path / "wash.mid"
        out.write_bytes(b"MThd")
        return str(out)

    # Seed options path: inject drone_held=False via sticky override after mode.
    with mock.patch(
        "midi_gen.arpeggio_generation.create_arp", side_effect=fake_create_arp
    ):
        _path, _result, options = generate_midi_for_style(
            "Brian Eno",
            use_cursor_sdk=False,
            overrides={
                "bars": 8,
                "generation_mode": "progression",
                "drone_held": False,
            },
            live_tweak=True,
        )
    assert options.get("generation_type") == "drone"
    assert options.get("drone_held") is False
    assert captured["options"].get("drone_held") is False


def test_sticky_keys_include_timing_and_generation_mode():
    assert "timing_factor" in LOOKUP_STICKY_OVERRIDE_KEYS
    assert "generation_mode" in LOOKUP_STICKY_OVERRIDE_KEYS


def test_ui_simplify_home_source_and_apptest():
    src = (_ROOT / "ui_app.py").read_text(encoding="utf-8")
    assert '"Random"' in src
    assert '"Surprise me"' not in src
    assert "Try instead" not in src or "Try instead dropped" in src
    assert "Who or vibe" not in src
    assert "Song part" in src
    assert "Full sketch" not in src
    assert "Play / Record" in src
    assert "Search + Preview" in src
    assert 'key="home_timing_0_5"' in src or "home_timing_" in src
    assert 'key="home_mode_pattern"' in src or "home_mode_" in src
    assert "home_timing_select" not in src
    assert "home_mode_select" not in src
    assert "_render_timing_chips" in src
    assert "_render_generation_mode_toggle" in src
    assert "_render_section_chips" in src
    assert "generation_mode" in src
    assert "timing_factor" in src
    assert "Audition → Capture" not in src
    assert "Browse / Mood" in src or '"Browse"' not in src
    assert '"More"' not in src
    assert '"Effects"' not in src
    assert '"Debug"' in src and '"Geek"' in src
    assert "def _render_home_header" in src
    assert 'key="takeover_debug"' in src[src.index("def _render_home_header") : src.index("def _render_geek_entry")]
    assert "st.tabs" in src
    assert 'key="home_tabs"' in src
    assert "_queue_play_record_tab" in src
    assert "_render_play_hero" in src
    assert "player.play_file" in src
    assert "MMC Record" in src
    assert "loops until Stop" in src
    assert "from midi_gen.live_midi import" in src
    assert "genre_artist_candidates" not in src
    assert "_mood_combo_names" not in src
    assert "_render_compact_controls_strip" not in src
    # Post-Generate caption: prefer generation_mode, else map type→mode label
    assert "format_generation_mode_label(options.get('generation_mode')" in src
    assert "generation_mode_from_type(options.get('generation_type'))" in src
    assert "format_generation_mode_label(options.get('generation_type'))" not in src
    # Chips sit under Search text input (on_click; no selectbox value fights).
    search_fn = src[src.index("def _render_search_feel") : src.index("GENERATE_BUSY_COPY")]
    assert "st.radio" not in search_fn
    assert '"Mood or Artist"' not in search_fn
    assert '["Mood", "Artist"]' in search_fn
    assert 'key="search_kind_tabs"' in search_fn
    assert search_fn.index('key="search_kind_tabs"') < search_fn.index("_render_search_query")
    assert "_render_part_and_timing_row" in src[
        src.index("def _render_search_query") : src.index("def _render_search_feel")
    ] or "_render_part_and_timing_row" in search_fn
    assert "on_click=_apply_timing_factor" in src
    assert "on_click=_apply_generation_mode" in src
    assert "on_click=_apply_section_chip" in src
    assert '[data-testid="stTab"]' in src
    assert "font-size: 1.85rem !important" in src
    assert "min-height: 4.5rem !important" in src
    assert "st.html(" in src
    query_fn = src[src.index("def _render_search_query") : src.index("def _render_search_feel")]
    assert "search_match_pick" not in query_fn
    assert "st.selectbox" not in query_fn
    assert "_render_random_button" not in query_fn
    assert query_fn.index('key="vibe_text"') < query_fn.index("_render_part_and_timing_row")
    assert search_fn.index("_render_random_button") < search_fn.index("_render_search_query")
    assert "vertical_alignment=\"bottom\"" in search_fn
    assert "st-key-search_kind_tabs" in src
    assert "font-size: 1.15rem !important" in src
    assert "_render_who_caption" not in search_fn
    assert "No mood matches for that genre yet" not in src
    assert 'key="surprise_me"' in src[
        src.index("def _render_random_button") : src.index("def _render_search_feel")
    ]
    assert "_render_generate_row" not in src
    # Search: feel + sketch. Result/loading/effects sit on Play / Record.
    home = src[src.index("with tab_search:") : src.index("with tab_play:")]
    assert home.index("_render_search_feel") < home.index("_render_sketch_layout")
    assert "_render_generate_loading" not in home
    assert "_render_result_row" not in home
    assert "_render_effects_chips" not in home
    sketch_fn = src[
        src.index("def _render_sketch_layout") : src.index("def _render_featured_styles")
    ]
    assert sketch_fn.index('key="bars"') < sketch_fn.index('key="chord_count"')
    assert sketch_fn.index('key="chord_count"') < sketch_fn.index('key="home_generate"')
    assert "_render_bars_knobs" not in home
    assert "_render_mood_packs" not in home
    assert "_render_arp_live" not in home
    assert 'key="mood_select"' not in src
    assert "_MOOD_GROUP_PREFIX" not in src
    assert "_render_generate_row" not in home
    assert "_render_compact_controls_strip" not in home
    assert "_render_recipe_panel" not in home
    play_tab = src[src.index("with tab_play:") : src.index("# Auto-generate")]
    assert play_tab.index("_render_geek_entry") < play_tab.index("_render_geek_takeover")
    assert play_tab.index("_render_geek_takeover") < play_tab.index("_render_generate_loading")
    assert play_tab.index("_render_generate_loading") < play_tab.index("_render_result_row")
    assert "if _gen_busy and not run" in play_tab
    assert play_tab.index("_render_result_row") < play_tab.index("_render_capture_setup")
    assert "_render_play_hero" not in play_tab
    assert "_render_effects_chips" not in play_tab
    assert "_render_geek_entry" not in home
    assert "live_midi.py" not in play_tab  # no rewrite

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(_ROOT / "ui_app.py"), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    home_keys = {b.key for b in at.button}
    assert "takeover_more" not in home_keys
    assert "takeover_debug" in home_keys
    assert "takeover_geek" in home_keys
    assert "takeover_browse" not in home_keys
    assert "takeover_capture" not in home_keys
    assert "takeover_moods" not in home_keys
    assert "home_timing_1_0" in home_keys
    assert "home_timing_0_5" in home_keys
    assert "search_kind" not in {s.key for s in at.selectbox}
    assert at.session_state["search_kind"] == "artist"
    assert "home_timing_select" not in {s.key for s in at.selectbox}
    assert "home_mode_pattern" in home_keys
    assert "home_mode_progression" in home_keys
    assert "home_mode_select" not in {s.key for s in at.selectbox}
    assert "home_section_intro" in home_keys
    assert "home_section_select" not in {s.key for s in at.selectbox}
    assert "mood_select" not in {s.key for s in at.selectbox}
    assert "search_match_pick" not in {s.key for s in at.selectbox}
    at.session_state["search_kind_tabs"] = "Mood"
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["search_kind"] == "mood"
    assert "search_match_pick" not in {s.key for s in at.selectbox}
    assert not any(str(k).startswith("mood_") for k in home_keys if k)
    labels = {b.key: b.label for b in at.button if b.key and b.key.startswith("takeover_")}
    assert "takeover_effects" not in labels
    assert labels["takeover_debug"] == "Debug"
    assert labels["takeover_geek"] == "Geek"
    assert "bars_half" not in home_keys
    assert "bars_double" not in home_keys
    assert "bars" in {s.key for s in at.slider}
    assert "chord_count" in {s.key for s in at.slider}
    gen = next(b for b in at.button if b.key == "home_generate")
    assert gen.label == "Generate"
    assert gen.disabled
    select_keys = {s.key for s in at.selectbox}
    assert "arp_mode" not in select_keys
    surprise = next(b for b in at.button if b.key == "surprise_me")
    assert surprise.label == "Random"

    at.button(key="home_timing_2_0").click().run()
    assert not at.exception, at.exception
    assert float(at.session_state["timing_factor"]) == 2.0
    at.button(key="home_mode_pattern").click().run()
    assert not at.exception, at.exception
    assert at.session_state["generation_mode"] == "pattern"
    select_keys = {s.key for s in at.selectbox}
    assert "arp_mode" not in select_keys
    at.button(key="home_section_verse").click().run()
    assert not at.exception, at.exception
    assert at.session_state["section_role"] == "verse"

