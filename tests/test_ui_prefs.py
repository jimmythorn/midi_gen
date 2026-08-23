"""Tests for lightweight local UI preference store."""

from __future__ import annotations

import json
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
    assert prefs["live_loop"] is False
    assert prefs["live_soft_click"] is False
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
    # Point load at our temp file by monkeypatching via explicit path merge:
    # prefs_for_session uses load_prefs() default path — test the filter helper
    # against an in-memory-equivalent by saving then loading with ports filter.
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
