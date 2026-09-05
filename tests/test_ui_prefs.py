"""Tests for lightweight local UI preference store."""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if "midi_gen" not in sys.modules:
    _pkg = types.ModuleType("midi_gen")
    _pkg.__path__ = [str(_ROOT)]  # type: ignore[attr-defined]
    _pkg.__file__ = str(_ROOT / "__init__.py")
    sys.modules["midi_gen"] = _pkg

from midi_gen.ui_prefs import DEFAULT_PREFS, load_prefs, prefs_for_session, save_prefs


def test_load_prefs_defaults_when_missing(tmp_path):
    path = tmp_path / "missing.json"
    prefs = load_prefs(path)
    assert prefs["live_count_in"] is False
    assert prefs["live_loop"] is True
    assert prefs["live_soft_click"] is False
    assert prefs["live_sync_logic"] is False
    assert prefs["live_port"] is None
    assert prefs == DEFAULT_PREFS


def test_save_and_reload_roundtrip(tmp_path):
    path = tmp_path / "ui_prefs.json"
    save_prefs(
        {
            "live_count_in": True,
            "live_loop": True,
            "live_soft_click": False,
            "live_port": "IAC Driver Bus 1",
            "ignored": "nope",
        },
        path=path,
    )
    prefs = load_prefs(path)
    assert prefs["live_count_in"] is True
    assert prefs["live_loop"] is True
    assert prefs["live_soft_click"] is False
    assert prefs["live_port"] == "IAC Driver Bus 1"
    assert "ignored" not in prefs
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["live_count_in"] is True


def test_corrupt_prefs_fall_back_to_defaults(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_prefs(path) == DEFAULT_PREFS


def test_prefs_for_session_drops_stale_port(tmp_path):
    path = tmp_path / "ui_prefs.json"
    save_prefs({"live_port": "Gone Bus", "live_count_in": True}, path=path)
    from midi_gen import ui_prefs

    original = ui_prefs.prefs_path
    try:
        ui_prefs.prefs_path = lambda: path  # type: ignore[assignment]
        prefs = prefs_for_session(["IAC Driver Bus 1"])
        assert prefs["live_port"] is None
        assert prefs["live_count_in"] is True
        prefs_ok = prefs_for_session(["Gone Bus", "Other"])
        assert prefs_ok["live_port"] == "Gone Bus"
    finally:
        ui_prefs.prefs_path = original  # type: ignore[assignment]


def test_prefs_survive_relaunch_roundtrip(tmp_path):
    """count-in / loop / port survive a full relaunch (disk); soft-click too."""
    path = tmp_path / "ui_prefs.json"
    save_prefs(
        {
            "live_count_in": True,
            "live_loop": True,
            "live_port": "IAC Driver Bus 1",
            "live_soft_click": False,
        },
        path=path,
    )
    # Simulate Streamlit relaunch: fresh load from disk.
    restored = load_prefs(path)
    assert restored["live_count_in"] is True
    assert restored["live_loop"] is True
    assert restored["live_port"] == "IAC Driver Bus 1"
    assert restored["live_soft_click"] is False
    # Rerun-equivalent: same values still present after a no-op merge save.
    save_prefs({"live_count_in": True}, path=path)
    again = load_prefs(path)
    assert again["live_loop"] is True
    assert again["live_port"] == "IAC Driver Bus 1"


def _apptest():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(_ROOT / "ui_app.py"), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    at.session_state["use_sdk"] = False
    return at


def _open_takeover(at, key: str):
    at.button(key=f"takeover_{key}").click().run()
    assert not at.exception, at.exception
    assert at.session_state["ui_takeover"] == key
    return at


def _takeover_is_closed(at) -> bool:
    try:
        return not at.session_state["ui_takeover"]
    except KeyError:
        return True


def test_no_artist_preselected_until_search_or_pick():
    at = _apptest()
    try:
        pick = at.session_state["catalog_pick"]
    except KeyError:
        pick = None
    assert not pick
    assert at.session_state["vibe_text"] in ("", None)
    surprise = next(b for b in at.button if b.key == "surprise_me")
    gen = next(b for b in at.button if b.key == "home_generate")
    assert gen.label == "Generate"
    assert gen.disabled
    assert not surprise.disabled
    assert surprise.label == "Random"
    captions = " ".join(c.value for c in at.caption)
    assert "Philip Glass" not in captions
    assert "Aphex Twin" not in captions
    markdown = " ".join(getattr(m, "value", "") or "" for m in at.markdown)
    assert "Nothing is selected yet" not in markdown
    assert "About to generate" not in markdown
    at.text_input(key="vibe_text").set_value("ambient drone").run()
    assert not at.exception, at.exception
    assert at.session_state["vibe_text"] == "ambient drone"
    gen = next(b for b in at.button if b.key == "home_generate")
    assert not gen.disabled


def test_classic_rock_placeholder_present():
    src = (_ROOT / "ui_app.py").read_text(encoding="utf-8")
    assert "classic rock" in src
    assert 'key="vibe_text"' in src


def test_surprise_me_populates_artist_and_effects():
    from midi_gen.effects_presets import list_presets
    from midi_gen.musician_styles import MUSICIAN_STYLE_CATALOG

    names = {m.name for m in MUSICIAN_STYLE_CATALOG}
    preset_ids = {p["id"] for p in list_presets()}
    at = _apptest()
    at.session_state["use_sdk"] = False
    at.button(key="surprise_me").click().run()
    assert not at.exception, at.exception
    assert at.session_state["catalog_pick"] in names
    assert at.session_state["effects_preset"] in preset_ids
    try:
        last_run = at.session_state["last_run"]
    except KeyError:
        last_run = None
    assert not last_run
    at.button(key="home_generate").click().run()
    assert not at.exception, at.exception
    last_run = at.session_state["last_run"]
    assert last_run
    assert last_run.get("wav_bytes")
    assert at.session_state["home_tabs"] == "Play / Record"


def test_pattern_select_regenerates_after_progression():
    from midi_gen.style_prompting import generation_mode_from_type

    at = _apptest()
    at.session_state["use_sdk"] = False
    at.session_state["catalog_pick"] = "Philip Glass"
    at.session_state["auto_generate"] = True
    at.run()
    assert not at.exception, at.exception
    opts = at.session_state["last_run"]["options"]
    mode = opts.get("generation_mode") or generation_mode_from_type(
        opts.get("generation_type")
    )
    assert mode == "progression"
    at.selectbox(key="home_mode_select").select("pattern").run()
    assert not at.exception, at.exception
    assert at.session_state["generation_mode"] == "pattern"
    opts = at.session_state["last_run"]["options"]
    stale = opts.get("generation_mode") or generation_mode_from_type(
        opts.get("generation_type")
    )
    assert stale == "progression"
    at.button(key="home_generate").click().run()
    assert not at.exception, at.exception
    opts = at.session_state["last_run"]["options"]
    mode = opts.get("generation_mode") or generation_mode_from_type(
        opts.get("generation_type")
    )
    assert mode == "pattern"
    assert opts.get("generation_type") == "arpeggio"


def test_featured_card_sets_catalog_without_widget_exception():
    from midi_gen.style_prompting import featured_style_cards

    card = featured_style_cards()[0]
    at = _apptest()
    _open_takeover(at, "debug")
    at.button(key=f"feat_{card.id}").click().run()
    assert not at.exception, at.exception
    assert at.session_state["catalog_pick"] == card.name
    assert at.session_state["vibe_text"] == ""
    assert _takeover_is_closed(at)


def test_catalog_select_nils_frahm():
    at = _apptest()
    _open_takeover(at, "debug")
    options = list(at.selectbox(key="catalog_pick").options)
    assert "Nils Frahm" in options
    at.selectbox(key="catalog_pick").select("Nils Frahm").run()
    assert not at.exception, at.exception
    assert at.session_state["catalog_pick"] == "Nils Frahm"
    assert at.session_state["vibe_text"] == ""
    frahm = next(b for b in at.button if b.key == "feat_frahm_felt")
    glass = next(b for b in at.button if b.key == "feat_glass_minimal")
    assert frahm.label.startswith("●")
    assert not glass.label.startswith("●")
    captions = " ".join(c.value for c in at.caption)
    assert "Selected · **Nils Frahm**" in captions


def test_featured_nils_frahm_sets_catalog():
    at = _apptest()
    _open_takeover(at, "debug")
    at.button(key="feat_frahm_felt").click().run()
    assert not at.exception, at.exception
    assert at.session_state["catalog_pick"] == "Nils Frahm"
    assert at.session_state["vibe_text"] == ""
    _open_takeover(at, "debug")
    frahm = next(b for b in at.button if b.key == "feat_frahm_felt")
    assert frahm.label.startswith("●")


def test_catalog_select_keeps_feel():
    """Feel stays layered when the artist changes."""
    at = _apptest()
    at.text_input(key="vibe_text").set_value("ambient drone").run()
    assert at.session_state["vibe_text"] == "ambient drone"
    _open_takeover(at, "debug")
    at.selectbox(key="catalog_pick").select("Nils Frahm").run()
    assert not at.exception, at.exception
    assert at.session_state["catalog_pick"] == "Nils Frahm"
    assert at.session_state["vibe_text"] == "ambient drone"
    captions = " ".join(c.value for c in at.caption)
    assert "Selected · **Nils Frahm**" in captions


def test_effects_chip_selects_session_preset():
    at = _apptest()
    at.session_state["catalog_pick"] = "Philip Glass"
    at.session_state["auto_generate"] = True
    at.run()
    assert not at.exception, at.exception
    last_run = at.session_state["last_run"]
    old = str((last_run.get("options") or {}).get("effects_preset") or "")
    try:
        session_fx = at.session_state["effects_preset"]
    except KeyError:
        session_fx = old
    old = old or str(session_fx or "")
    target = "clean" if old != "clean" else "worn_tape"
    at.button(key=f"fx_chip_{target}").click().run()
    assert not at.exception, at.exception
    assert at.session_state["effects_preset"] == target
    chip = next(b for b in at.button if b.key == f"fx_chip_{target}")
    assert chip.label.startswith("●")


def test_effects_chips_multi_select():
    at = _apptest()
    at.session_state["catalog_pick"] = "Philip Glass"
    at.session_state["auto_generate"] = True
    at.run()
    assert not at.exception, at.exception
    at.button(key="fx_chip_clean").click().run()
    at.button(key="fx_chip_human_feel").click().run()
    at.button(key="fx_chip_subtle_tape").click().run()
    assert not at.exception, at.exception
    assert at.session_state["effects_preset"] == "human_feel,subtle_tape"
    assert list(at.session_state["effects_presets"]) == ["human_feel", "subtle_tape"]
    human = next(b for b in at.button if b.key == "fx_chip_human_feel")
    tape = next(b for b in at.button if b.key == "fx_chip_subtle_tape")
    assert human.label.startswith("●")
    assert tape.label.startswith("●")


def test_ui_widget_mutations_use_callbacks():
    src = (_ROOT / "ui_app.py").read_text(encoding="utf-8")
    assert "on_change=_on_catalog_pick_change" in src
    assert "on_click=_apply_half_bars" not in src
    assert "on_click=_apply_double_bars" not in src
    assert "on_click=_apply_refresh_ports" in src
    assert "on_click=_apply_again" not in src
    assert "on_click=_apply_surprise" in src
    assert "on_change=_on_vibe_search_submit" not in src
    assert "on_click=_on_generate_click" in src
    assert "pending_search_generate" not in src
    assert "_render_recipe_panel" not in src
    assert "About to generate" not in src
    assert "surprise_roll(" in src
    assert 'st.session_state["effects_preset"] = effects_preset' in src
    assert "on_click=_apply_effects_preset" in src
    assert "on_change=_on_timing_select" in src
    assert "on_change=_on_generation_mode_select" in src
    assert 'st.session_state["auto_generate"] = True' not in src[
        src.index("def _apply_generation_mode") : src.index("def _on_generation_mode_select")
    ]
    assert 'st.session_state["auto_generate"] = True' in src[
        src.index("def _on_generate_click") : src.index("def _apply_featured_style")
    ]
    assert "on_change=_on_mood_select" not in src
    assert 'key="mood_select"' not in src
    after_vibe_widget = src.split('key="vibe_text"', 1)[1]
    assert 'st.session_state["vibe_text"] = chip' not in after_vibe_widget


def test_arp_live_knobs_present_and_override_steps():
    at = _apptest()
    at.session_state["use_sdk"] = False
    keys = [s.key for s in at.selectbox]
    assert "arp_mode" not in keys
    at.selectbox(key="home_mode_select").select("pattern").run()
    assert not at.exception, at.exception
    keys = [s.key for s in at.selectbox]
    assert "arp_mode" not in keys
    at.session_state["catalog_pick"] = "Philip Glass"
    at.session_state["auto_generate"] = True
    at.run()
    assert not at.exception, at.exception
    keys = [s.key for s in at.selectbox]
    assert "arp_mode" in keys
    assert "arp_steps" in keys
    assert "arp_range_octaves" in keys
    at.selectbox(key="arp_steps").select(16).run()
    assert not at.exception, at.exception
    assert at.session_state["arp_steps"] == 16
    _open_takeover(at, "debug")
    assert "sketch_bpm" in [n.key for n in at.number_input]
    src = (_ROOT / "ui_app.py").read_text(encoding="utf-8")
    assert "pending_replay" in src
    assert "on_change=_apply_arp_live" in src
    assert 'overrides["arp_mode"]' in src
    assert 'key="sketch_bpm"' in src
    assert 'overrides["bpm"]' in src
    assert "live_tweak=" in src
    assert "_pending_profile_knobs" in src


def test_sdk_status_follows_toggle_and_key():
    src = (_ROOT / "ui_app.py").read_text(encoding="utf-8")
    assert 'key="use_sdk"' in src
    assert "SDK: ready" in src
    assert "CURSOR_API_KEY missing" in src
    assert "offline — catalog only" not in src
    assert "load_dotenv_if_present()" not in src
    assert "_load_repo_dotenv()" in src
    assert "def _cursor_api_key_present()" in src
    assert 'st.session_state["use_sdk"] = _cursor_api_key_present()' in src
    assert '("use_sdk", _cursor_api_key_present())' in src


def test_use_sdk_defaults_on_when_cursor_key_present():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(_ROOT / "ui_app.py"), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    expected = bool(os.environ.get("CURSOR_API_KEY", "").strip())
    assert at.session_state["use_sdk"] is expected


def test_one_page_chrome_takeovers_source_and_nav():
    """Search+Preview | Play/Record on main; Debug in header; Geek chrome."""
    src = (_ROOT / "ui_app.py").read_text(encoding="utf-8")
    assert "TAKEOVER_LABELS" in src
    assert "TAKEOVER_TITLES" in src
    assert 'key="takeover_geek"' in src
    assert 'key="takeover_back"' in src
    assert '"More"' not in src
    assert '"Effects"' not in src
    assert '"Debug"' in src and '"Geek"' in src
    block = src[src.index("TAKEOVER_LABELS") : src.index("TAKEOVER_TITLES")]
    assert list(
        k
        for k in ("more", "effects", "debug", "geek")
        if f'"{k}"' in block
    ) == ["geek"]
    header_fn = src[src.index("def _render_home_header") : src.index("def _render_geek_entry")]
    geek_fn = src[src.index("def _render_geek_entry") : src.index("def _apply_surprise")]
    assert 'key="takeover_debug"' in header_fn
    assert "takeover_debug" not in geek_fn
    assert "st.navigation" not in src
    assert "pages/" not in src
    home_src = src[src.index("# --- HOME") :]
    assert home_src.index("_render_home_header") < home_src.index("st.tabs")
    assert "_render_chrome_row" not in src
    assert "st.tabs" in home_src
    assert "_render_search_feel" in home_src
    geek = src[src.index("def _render_geek_takeover") : src.index("# --- Takeover OR home")]
    assert "_render_arp_live" in geek
    assert "def _render_listen" in src
    result_row = src[src.index("def _render_result_row") : src.index("def _render_effects_chips")]
    assert "st.columns" in result_row
    assert "_render_listen" in result_row
    assert "_render_download" in result_row
    assert "_render_play_hero" in result_row
    assert result_row.index("_render_listen") < result_row.index("_render_play_hero")
    assert '"### Preview"' in src or "### Preview" in src
    assert "Preview here" not in src
    assert "st.success" not in result_row
    assert "result.message" not in result_row
    assert result_row.index("aside_col") < result_row.index("format_likeness_blurb")
    assert result_row.index("format_likeness_blurb") < result_row.index("_render_listen")
    assert result_row.index("_render_listen") < result_row.index("_render_arp_live")
    assert result_row.index("_render_arp_live") < result_row.index("_render_effects_chips")
    assert 'placeholder="Select an artist…"' in src
    assert 'key="home_generate"' in src
    assert '"Generate"' in src
    assert "_render_generate_row" not in src
    assert '"Random"' in src
    assert '"Play in Logic"' in src
    assert '"Download MIDI"' in src
    assert '"Again"' not in src
    assert "_render_again_try" not in src
    assert "with_fun_now" not in src
    assert "Not finding a musician" in src or "ARTIST_REJECT_DRIP" in src
    assert "MMC Record" in src
    assert "Re-Play" in src
    assert "def _render_generate_loading" in src
    assert "GENERATE_BUSY_COPY" in src
    assert "_render_recipe_panel" not in home_src
    cap = src.index("def _render_capture_setup")
    adv = src.index("def _render_advanced_takeover")
    assert "Audition → Capture" not in src[cap:adv]
    assert "port_col, record_col" in src[cap:adv]
    play = src[src.index("def _render_play_hero") : src.index("def _render_download")]
    assert "AUDITION_CAPTURE_STRIP_HTML" not in play

    at = _apptest()
    assert _takeover_is_closed(at)
    home_keys = {b.key for b in at.button}
    assert "takeover_more" not in home_keys
    assert "takeover_geek" in home_keys
    assert "takeover_browse" not in home_keys
    assert "feat_glass_minimal" not in home_keys
    assert "bars_half" not in home_keys
    labels = {b.key: b.label for b in at.button if b.key and b.key.startswith("takeover_")}
    assert "takeover_effects" not in labels
    assert labels["takeover_debug"] == "Debug"
    assert labels["takeover_geek"] == "Geek"
    _open_takeover(at, "debug")
    assert at.session_state["ui_takeover"] == "debug"
    at.button(key="takeover_back").click().run()
    assert _takeover_is_closed(at)
