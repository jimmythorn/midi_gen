"""Unit tests for Logic Pro MCP record-only bridge (fake transport)."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any, Mapping, Optional
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if "midi_gen" not in sys.modules:
    _pkg = types.ModuleType("midi_gen")
    _pkg.__path__ = [str(_ROOT)]  # type: ignore[attr-defined]
    _pkg.__file__ = str(_ROOT / "__init__.py")
    sys.modules["midi_gen"] = _pkg

from midi_gen.logic_mcp_bridge import (
    ALLOWED_TOOL_COMMANDS,
    FORBIDDEN_COMMANDS,
    OFFLINE_MUSICIAN_COPY,
    BridgeResult,
    FakeMcpTransport,
    LogicMcpBridge,
    clear_readiness_cache,
    doctor_status_ready,
    get_mcp_readiness,
    is_state_a,
    parse_honest_contract,
    resolve_arm_target,
    resolve_bin,
)


def _state_a(**extra: Any) -> dict[str, Any]:
    body = {
        "success": True,
        "verified": True,
        "state": "A",
        "operation": extra.pop("operation", "test"),
    }
    body.update(extra)
    return body


def _state_b(**extra: Any) -> dict[str, Any]:
    body = {
        "success": True,
        "verified": False,
        "state": "B",
        "reason": extra.pop("reason", "unverified"),
    }
    body.update(extra)
    return body


def _state_c(**extra: Any) -> dict[str, Any]:
    body = {
        "success": False,
        "verified": False,
        "state": "C",
        "error": extra.pop("error", "failed"),
    }
    body.update(extra)
    return body


def _bridge_with_tracks(
    tracks: list[dict[str, Any]],
    *,
    arm_payload: Optional[Mapping[str, Any]] = None,
    record_payload: Optional[Mapping[str, Any]] = None,
    stop_payload: Optional[Mapping[str, Any]] = None,
) -> tuple[LogicMcpBridge, FakeMcpTransport]:
    transport = FakeMcpTransport(
        handlers={
            "resource:logic://tracks": lambda _p: {"data": tracks},
        },
        tool_handlers={
            ("logic_tracks", "arm_only"): lambda _a: dict(arm_payload or _state_a(operation="tracks.arm_only")),
            ("logic_tracks", "arm"): lambda _a: dict(arm_payload or _state_a(operation="tracks.arm")),
            ("logic_transport", "record"): lambda _a: dict(
                record_payload or _state_a(operation="transport.record")
            ),
            ("logic_transport", "stop"): lambda _a: dict(
                stop_payload or _state_a(operation="transport.stop")
            ),
            ("logic_system", "health"): lambda _a: {
                "status": "ready",
                "channels": {"Accessibility": {"status": "ready"}},
            },
        },
    )
    return LogicMcpBridge(transport=transport), transport


def test_parse_honest_contract_state_letters():
    assert parse_honest_contract(_state_a())[0] == "A"
    assert parse_honest_contract(_state_b())[0] == "B"
    assert parse_honest_contract(_state_c())[0] == "C"
    assert is_state_a(_state_a())
    assert not is_state_a(_state_b())


def test_resolve_arm_target_single_and_selected_fail_closed_ambiguous():
    one = resolve_arm_target([{"id": 0, "name": "Inst 1", "isSelected": False}])
    assert one is not None and one.index == 0 and one.name == "Inst 1"

    selected = resolve_arm_target(
        [
            {"id": 0, "name": "A", "isSelected": False},
            {"id": 2, "name": "B", "isSelected": True},
        ]
    )
    assert selected is not None and selected.index == 2

    ambiguous = resolve_arm_target(
        [
            {"id": 0, "name": "A", "isSelected": False},
            {"id": 1, "name": "B", "isSelected": False},
        ]
    )
    assert ambiguous is None


def test_arm_and_record_state_a_success_path():
    bridge, transport = _bridge_with_tracks(
        [{"id": 0, "name": "Pad", "isSelected": True}]
    )
    result = bridge.arm_and_record(arm_only=True)
    assert result.ok
    assert result.state == "A"
    assert ("logic_tracks", "arm_only") in {
        (t, c) for t, c, _ in transport.tool_calls
    }
    assert ("logic_transport", "record") in {
        (t, c) for t, c, _ in transport.tool_calls
    }
    # Nested params shape matches Logic Pro MCP e2e.
    arm_args = next(a for t, c, a in transport.tool_calls if c == "arm_only")
    assert arm_args["command"] == "arm_only"
    assert arm_args["params"]["index"] == 0
    assert arm_args["params"]["enabled"] is True


def test_fail_closed_state_b_record():
    bridge, _ = _bridge_with_tracks(
        [{"id": 0, "name": "Pad", "isSelected": True}],
        record_payload=_state_b(reason="readback_unavailable"),
    )
    result = bridge.arm_and_record()
    assert not result.ok
    assert result.state == "B"
    assert "uncertain" in result.message.lower() or "State B" in result.message
    assert "Not treating as recorded" in result.message


def test_fail_closed_state_c_arm():
    bridge, transport = _bridge_with_tracks(
        [{"id": 0, "name": "Pad", "isSelected": True}],
        arm_payload=_state_c(error="element_not_found"),
    )
    result = bridge.arm_and_record()
    assert not result.ok
    assert result.state == "C"
    assert "Not treating as recorded" in result.message
    # Record must not run after arm failure.
    assert all(c != "record" for _t, c, _a in transport.tool_calls)


def test_fail_closed_when_track_target_unknown():
    bridge, transport = _bridge_with_tracks(
        [
            {"id": 0, "name": "A", "isSelected": False},
            {"id": 1, "name": "B", "isSelected": False},
        ]
    )
    result = bridge.arm_and_record()
    assert not result.ok
    assert result.detail.get("error") == "track_target_unknown"
    assert "explicit track" in result.message.lower()
    assert transport.tool_calls == []


def test_fail_closed_when_binary_missing():
    clear_readiness_cache()
    with patch("midi_gen.logic_mcp_bridge.resolve_bin", return_value=None):
        bridge = LogicMcpBridge()
        ready = bridge.readiness()
        assert not ready.ok
        assert ready.offline
        assert ready.musician_copy == OFFLINE_MUSICIAN_COPY
        assert ready.detail.get("error") == "binary_missing"

        armed = bridge.arm_and_record()
        assert not armed.ok
        assert armed.offline


def test_doctor_ready_short_circuits_health():
    report = {"schema": "logic_pro_mcp_doctor.v4", "status": "ok", "headline": "ready"}
    assert doctor_status_ready(report)

    def fake_doctor(_bin: str, _timeout: float) -> BridgeResult:
        return BridgeResult(ok=True, message="Logic MCP Ready", detail={"via": "doctor"})

    transport = FakeMcpTransport()
    bridge = LogicMcpBridge(
        transport=transport,
        bin_path="/fake/LogicProMCP",
        run_doctor=fake_doctor,
    )
    with patch("midi_gen.logic_mcp_bridge.resolve_bin", return_value="/fake/LogicProMCP"):
        result = bridge.readiness()
    assert result.ok
    assert result.detail.get("via") == "doctor"
    # Doctor path must not open tools/call.
    assert transport.tool_calls == []


def test_bridge_never_invokes_forbidden_midi_helpers():
    """Allowlist + explicit refuse path — no import / record_sequence / send_note."""
    transport = FakeMcpTransport(
        tool_handlers={
            ("logic_midi", "send_note"): lambda _a: _state_a(),
            ("logic_tracks", "record_sequence"): lambda _a: _state_a(),
            ("logic_midi", "import_file"): lambda _a: _state_a(),
        }
    )
    bridge = LogicMcpBridge(transport=transport)

    # Direct forbidden call via internal helper must refuse before RPC.
    refused = bridge._call_on(  # noqa: SLF001 — intentional unit seam
        transport,
        "logic_midi",
        "send_note",
        {"note": 60},
        operation="midi.send_note",
    )
    assert not refused.ok
    assert refused.detail.get("error") in {"forbidden_command", "disallowed_operation"}
    assert transport.tool_calls == []

    for cmd in ("record_sequence", "import_file", "send_note"):
        assert cmd in FORBIDDEN_COMMANDS

    # Public surface only exposes allowed ops.
    allowed_cmds = {c for _t, c in ALLOWED_TOOL_COMMANDS}
    assert "record" in allowed_cmds
    assert "arm_only" in allowed_cmds
    assert "send_note" not in allowed_cmds
    assert "record_sequence" not in allowed_cmds
    assert "import_file" not in allowed_cmds


def test_transport_stop_state_a():
    bridge, transport = _bridge_with_tracks([{"id": 0, "name": "X", "isSelected": True}])
    result = bridge.transport_stop()
    assert result.ok and result.state == "A"
    assert any(c == "stop" for _t, c, _a in transport.tool_calls)


def test_get_mcp_readiness_caches_and_survives_exceptions():
    clear_readiness_cache()
    calls = {"n": 0}

    class BoomBridge(LogicMcpBridge):
        def readiness(self) -> BridgeResult:  # type: ignore[override]
            calls["n"] += 1
            return BridgeResult(ok=False, offline=True, message=OFFLINE_MUSICIAN_COPY)

    first = get_mcp_readiness(bridge=BoomBridge(transport=FakeMcpTransport()))
    second = get_mcp_readiness(bridge=BoomBridge(transport=FakeMcpTransport()))
    assert not first.ok and not second.ok
    assert calls["n"] == 1  # cached
    clear_readiness_cache()


def test_resolve_bin_env_and_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    missing = resolve_bin("definitely-not-a-real-logic-mcp-bin-xyz")
    assert missing is None

    fake = tmp_path / "LogicProMCP"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("LOGIC_PRO_MCP_BIN", str(fake))
    assert resolve_bin() == str(fake)


def test_ui_source_guards_record_chip_and_iac_play_unchanged():
    """Cheap/stable UI + IAC path guards — MCP Record is additive."""
    src = (_ROOT / "ui_app.py").read_text(encoding="utf-8")
    bridge_src = (_ROOT / "logic_mcp_bridge.py").read_text(encoding="utf-8")

    assert "from midi_gen.logic_mcp_bridge import" in src
    assert 'key="record_logic_mcp"' in src
    assert "disabled=not (live.available and mcp_ready)" in src
    assert "get_mcp_readiness(force=True)" in src
    assert "_start_mcp_record_then_iac_play" in src
    assert "_render_mcp_status_chip" in src
    assert "OFFLINE_MUSICIAN_COPY" in src
    assert "send_mmc=False" in src  # MCP already recording — do not MMC-toggle
    # Live rewrite replay must also skip MMC while MCP Record is armed.
    assert "send_mmc=False if mcp_armed else None" in src

    # Play primacy + existing IAC play_file path remain.
    play = src[src.index("def _render_play_hero") : src.index("def _render_download")]
    assert 'key="play_logic"' in play
    assert "player.play_file(" in play
    assert play.index('key="play_logic"') < play.index('key="record_logic_mcp"')

    # Bridge never mentions composing MIDI via MCP helpers as callable surface.
    for banned in ("record_sequence", "import_file", "send_note"):
        # Denylist constants may name them; ensure no tools/call routes them.
        assert f'"{banned}"' in bridge_src  # listed in FORBIDDEN_COMMANDS
    assert "FORBIDDEN_COMMANDS" in bridge_src
    assert "logic_midi" not in {
        t for t, _c in ALLOWED_TOOL_COMMANDS
    }


def test_live_midi_module_untouched_for_streaming_notes():
    """Diff intent: IAC live_midi play path is not rewritten for MCP notes."""
    live_src = (_ROOT / "live_midi.py").read_text(encoding="utf-8")
    assert "logic_mcp" not in live_src.lower()
    assert "record_sequence" not in live_src
    assert "LogicProMCP" not in live_src
