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
    assert "Who or vibe" in src
    assert "Song part" in src
    assert "Play / Record" in src
    assert "Search + Preview" in src
    assert 'key_prefix="home_timing"' in src
    assert 'key_prefix="home_mode"' in src
    assert "generation_mode" in src
    assert "timing_factor" in src
    assert "Audition → Capture" not in src
    assert "Browse / Mood" in src or '"Browse"' not in src
    assert '"More"' in src and '"Debug"' in src and '"Geek"' in src
    assert "st.tabs" in src
    assert "_render_play_hero" in src
    assert "player.play_file" in src
    assert "MMC Record" in src
    assert "loops until Stop" in src
    assert "from midi_gen.live_midi import" in src
    assert "genre_artist_candidates" in src
    assert "_render_compact_controls_strip" in src
    # Post-Generate caption: prefer generation_mode, else map type→mode label
    assert "format_generation_mode_label(options.get('generation_mode')" in src
    assert "generation_mode_from_type(options.get('generation_type'))" in src
    assert "format_generation_mode_label(options.get('generation_type'))" not in src
    # Locked Search+Preview order: search → mood → preview → strip → generate
    home = src[src.index("with tab_search:") : src.index("with tab_play:")]
    assert home.index("_render_search_feel") < home.index("_render_mood_packs")
    assert home.index("_render_mood_packs") < home.index("_render_recipe_panel")
    assert home.index("_render_recipe_panel") < home.index("_render_compact_controls_strip")
    assert home.index("_render_compact_controls_strip") < home.index("_render_generate_row")
    # Play tab wraps existing stack only
    play_tab = src[src.index("with tab_play:") : src.index("# Auto-generate")]
    assert "_render_play_hero" in play_tab
    assert "_render_capture_setup" in play_tab
    assert "live_midi.py" not in play_tab  # no rewrite

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(_ROOT / "ui_app.py"), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    home_keys = {b.key for b in at.button}
    assert "takeover_more" in home_keys
    assert "takeover_debug" in home_keys
    assert "takeover_geek" in home_keys
    assert "takeover_browse" not in home_keys
    assert "takeover_capture" not in home_keys
    assert "takeover_moods" not in home_keys
    assert "home_timing_1_0" in home_keys
    assert "home_timing_0_5" in home_keys
    assert "home_mode_pattern" in home_keys
    assert "home_mode_progression" in home_keys
    assert "home_section_intro" in home_keys
    assert any(k.startswith("mood_") for k in home_keys)
    labels = {b.key: b.label for b in at.button if b.key and b.key.startswith("takeover_")}
    assert labels["takeover_more"] == "More"
    assert labels["takeover_debug"] == "Debug"
    assert labels["takeover_geek"] == "Geek"
    surprise = next(b for b in at.button if b.key == "surprise_me")
    assert surprise.label == "Random"

    at.button(key="home_timing_2_0").click().run()
    assert not at.exception, at.exception
    assert float(at.session_state["timing_factor"]) == 2.0
    at.button(key="home_mode_pattern").click().run()
    assert not at.exception, at.exception
    assert at.session_state["generation_mode"] == "pattern"


def test_mood_combo_wires_genre_artist_candidates():
    """#34 on main → mood combo uses genre_artist_candidates → ranked names."""
    from midi_gen import ui_app as app
    from midi_gen.mood_search import ArtistCandidate, GenreArtistCandidates

    fake = GenreArtistCandidates(
        genre_query="ambient",
        candidates=(
            ArtistCandidate(
                id="a1",
                name="Brian Eno",
                followers_total=500_000,
                genres=("ambient",),
            ),
            ArtistCandidate(
                id="a2",
                name="Aphex Twin",
                followers_total=400_000,
                genres=("ambient", "idm"),
            ),
        ),
        ok=True,
    )
    with mock.patch(
        "midi_gen.mood_search.genre_artist_candidates", return_value=fake
    ):
        names = app._mood_combo_names("ambient", limit=10)
    assert names == ["Brian Eno", "Aphex Twin"]
    assert "Philip Glass" in catalog_name_matches("Glass", limit=3)
