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


def test_mood_chip_sets_vibe_text_without_widget_exception():
    """Chip click must set vibe_text via on_click, not after the text_input binds."""
    from midi_gen.style_prompting import mood_chip_packs

    packs = mood_chip_packs()
    pack = packs[0]
    chip = pack.chips[0]
    at = _apptest()
    # Mood chips live under Search on home (Browse/Mood takeovers dropped).
    at.button(key=f"mood_{pack.id}_0").click().run()
    assert not at.exception, at.exception
    assert at.session_state["vibe_text"] == chip
    try:
        kind = at.session_state["search_kind"]
    except KeyError:
        kind = None
    assert kind == "mood"


def test_no_artist_preselected_until_search_or_pick():
    at = _apptest()
    try:
        pick = at.session_state["catalog_pick"]
    except KeyError:
        pick = None
    assert not pick
    assert at.session_state["vibe_text"] in ("", None)
    gen = next(b for b in at.button if b.label == "Generate")
    surprise = next(b for b in at.button if b.key == "surprise_me")
    assert gen.disabled
    assert not surprise.disabled
    assert surprise.label == "Random"
    captions = " ".join(c.value for c in at.caption)
    assert "Philip Glass" not in captions
    assert "Aphex Twin" not in captions
    markdown = " ".join(getattr(m, "value", "") or "" for m in at.markdown)
    assert "Nothing is selected yet" in markdown
    at.text_input(key="vibe_text").set_value("ambient drone").run()
    assert not at.exception, at.exception
    assert at.session_state["vibe_text"] == "ambient drone"


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
    assert last_run
    assert last_run.get("wav_bytes")


def test_featured_card_sets_catalog_without_widget_exception():
    from midi_gen.style_prompting import featured_style_cards

    card = featured_style_cards()[0]
    at = _apptest()
    _open_takeover(at, "more")
    at.button(key=f"feat_{card.id}").click().run()
    assert not at.exception, at.exception
    assert at.session_state["catalog_pick"] == card.name
    assert at.session_state["vibe_text"] == ""
    assert _takeover_is_closed(at)


def test_catalog_select_nils_frahm():
    at = _apptest()
    _open_takeover(at, "more")
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
    _open_takeover(at, "more")
    at.button(key="feat_frahm_felt").click().run()
    assert not at.exception, at.exception
    assert at.session_state["catalog_pick"] == "Nils Frahm"
    assert at.session_state["vibe_text"] == ""
    _open_takeover(at, "more")
    frahm = next(b for b in at.button if b.key == "feat_frahm_felt")
    assert frahm.label.startswith("●")


def test_catalog_select_keeps_feel():
    """Feel stays layered when the artist changes."""
    from midi_gen.style_prompting import mood_chip_packs

    pack = mood_chip_packs()[0]
    at = _apptest()
    at.button(key=f"mood_{pack.id}_0").click().run()
    assert at.session_state["vibe_text"] == pack.chips[0]
    _open_takeover(at, "more")
    at.selectbox(key="catalog_pick").select("Nils Frahm").run()
    assert not at.exception, at.exception
    assert at.session_state["catalog_pick"] == "Nils Frahm"
    assert at.session_state["vibe_text"] == pack.chips[0]
    captions = " ".join(c.value for c in at.caption)
    assert "Selected · **Nils Frahm**" in captions
    assert pack.chips[0] in captions


def test_half_double_bars_use_callbacks():
    at = _apptest()
    _open_takeover(at, "more")
    assert at.session_state["bars"] == 16
    at.button(key="bars_double").click().run()
    assert not at.exception, at.exception
    assert at.session_state["bars"] == 32
    at.button(key="bars_half").click().run()
    assert not at.exception, at.exception
    assert at.session_state["bars"] == 16


def test_ui_widget_mutations_use_callbacks():
    src = (_ROOT / "ui_app.py").read_text(encoding="utf-8")
    assert "on_change=_on_catalog_pick_change" in src
    assert "on_click=_apply_half_bars" in src
    assert "on_click=_apply_double_bars" in src
    assert "on_click=_apply_refresh_ports" in src
    assert "on_click=_apply_again" in src
    assert "on_click=_apply_surprise" in src
    assert "surprise_roll(" in src
    assert 'st.session_state["effects_preset"] = effects_preset' in src
    assert "on_click=_apply_effects_preset" in src
    assert "on_click=_apply_timing_factor" in src
    assert "on_click=_apply_generation_mode" in src
    after_vibe_widget = src.split('key="vibe_text"', 1)[1]
    assert 'st.session_state["vibe_text"] = chip' not in after_vibe_widget


def test_arp_live_knobs_present_and_override_steps():
    at = _apptest()
    _open_takeover(at, "more")
    keys = [s.key for s in at.selectbox]
    assert "arp_mode" in keys
    assert "arp_steps" in keys
    assert "arp_range_octaves" in keys
    at.selectbox(key="arp_steps").select(16).run()
    assert not at.exception, at.exception
    assert at.session_state["arp_steps"] == 16
    at.button(key="takeover_back").click().run()
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
    """Search+Preview | Play/Record on main; More/Effects/Debug/Geek takeovers."""
    src = (_ROOT / "ui_app.py").read_text(encoding="utf-8")
    assert "TAKEOVER_LABELS" in src
    assert 'f"takeover_{key}"' in src
    assert 'key="takeover_back"' in src
    assert '"More"' in src and '"Effects"' in src
    assert '"Debug"' in src and '"Geek"' in src
    block = src[src.index("TAKEOVER_LABELS") : src.index("TAKEOVER_LABELS") + 350]
    assert list(
        k
        for k in ("more", "effects", "debug", "geek")
        if f'"{k}"' in block
    ) == ["more", "effects", "debug", "geek"]
    assert "st.navigation" not in src
    assert "pages/" not in src
    home_src = src[src.index("# --- HOME") :]
    assert "st.tabs" in home_src
    assert "_render_search_feel" in home_src
    geek = src[src.index("def _render_geek_takeover") : src.index("def _render_effects_takeover")]
    assert "_render_arp_live" in geek
    assert "def _render_listen" in src
    assert 'placeholder="Select an artist…"' in src
    assert '"Generate"' in src
    assert '"Random"' in src
    assert '"Play in Logic"' in src
    assert '"Download MIDI"' in src
    assert '"Again"' in src
    assert "Try instead dropped" in src
    assert "with_fun_now" in src
    assert "Not finding a musician" in src or "ARTIST_REJECT_DRIP" in src
    assert "MMC Record" in src
    assert "Re-Play" in src
    assert "def _render_generate_loading" in src
    assert "GENERATE_BUSY_COPY" in src
    cap = src.index("def _render_capture_setup")
    adv = src.index("def _render_advanced_takeover")
    assert "Audition → Capture" not in src[cap:adv]
    play = src[src.index("def _render_play_hero") : src.index("def _render_download")]
    assert "AUDITION_CAPTURE_STRIP_HTML" not in play

    at = _apptest()
    assert _takeover_is_closed(at)
    home_keys = {b.key for b in at.button}
    assert "takeover_more" in home_keys
    assert "takeover_geek" in home_keys
    assert "takeover_browse" not in home_keys
    assert "feat_glass_minimal" not in home_keys
    assert "bars_half" not in home_keys
    labels = {b.key: b.label for b in at.button if b.key and b.key.startswith("takeover_")}
    assert labels["takeover_more"] == "More"
    assert labels["takeover_debug"] == "Debug"
    assert labels["takeover_geek"] == "Geek"
    _open_takeover(at, "more")
    assert at.session_state["ui_takeover"] == "more"
    at.button(key="takeover_back").click().run()
    assert _takeover_is_closed(at)
