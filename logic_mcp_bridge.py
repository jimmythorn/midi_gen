"""
Logic Pro MCP bridge — RECORD ONLY (arm + transport.record / stop).

Talks to https://github.com/MongLong0214/logic-pro-mcp over stdio JSON-RPC.
Notes still stream via the existing IAC ``live_midi`` path — this module never
calls MCP MIDI composition/import helpers (``record_sequence``, ``import_file``,
``send_note``, …).

Honest Contract: State A confirmed → success. State B uncertain or State C
failure → fail closed (structured error, never pretend recorded).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, MutableMapping, Optional, Protocol, Sequence

# Env: absolute path or bare name on PATH. Default matches Homebrew install.
LOGIC_PRO_MCP_BIN_ENV = "LOGIC_PRO_MCP_BIN"
DEFAULT_LOGIC_PRO_MCP_BIN = "LogicProMCP"

# Musician-facing copy when the bridge cannot drive Logic Record.
OFFLINE_MUSICIAN_COPY = (
    "Logic Record control offline — arm & Record in Logic manually, then Play."
)

# Ops this spike is allowed to invoke (tool, command). Anything else is refused.
ALLOWED_TOOL_COMMANDS = frozenset(
    {
        ("logic_system", "health"),
        ("logic_tracks", "arm"),
        ("logic_tracks", "arm_only"),
        ("logic_transport", "record"),
        ("logic_transport", "stop"),
    }
)

# Explicit denylist — tests assert the bridge never routes these.
FORBIDDEN_COMMANDS = frozenset(
    {
        "record_sequence",
        "import_file",
        "send_note",
        "send_chord",
        "play_sequence",
        "send_cc",
        "send_sysex",
        "mmc_record",
        "mmc_play",
        "mmc_stop",
        "mmc_locate",
        "step_input",
    }
)

DEFAULT_RPC_TIMEOUT_SEC = 12.0
DEFAULT_DOCTOR_TIMEOUT_SEC = 20.0


@dataclass(frozen=True)
class BridgeResult:
    """Structured outcome — never raises into Streamlit."""

    ok: bool
    offline: bool = False
    state: Optional[str] = None  # "A" / "B" / "C" when known
    operation: Optional[str] = None
    message: str = ""
    detail: Mapping[str, Any] = field(default_factory=dict)

    @property
    def musician_copy(self) -> str:
        if self.offline and not self.message:
            return OFFLINE_MUSICIAN_COPY
        return self.message or OFFLINE_MUSICIAN_COPY


@dataclass(frozen=True)
class TrackTarget:
    """Explicit arm target — never invent an index among ambiguous tracks."""

    index: int
    name: Optional[str] = None
    target_ref: Optional[str] = None

    def as_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {"index": int(self.index), "enabled": True}
        if self.target_ref:
            # Prefer session-stable ref when present; drop bare index pairing.
            return {"target_ref": self.target_ref, "enabled": True}
        if self.name:
            params["expected_name"] = self.name
        return params


class McpTransport(Protocol):
    """Injectable JSON-RPC transport (real stdio or test fake)."""

    def request(
        self, method: str, params: Optional[Mapping[str, Any]] = None, *, timeout: float
    ) -> Optional[Mapping[str, Any]]:
        ...

    def notify(self, method: str, params: Optional[Mapping[str, Any]] = None) -> None:
        ...

    def close(self) -> None:
        ...


def resolve_bin(bin_override: Optional[str] = None) -> Optional[str]:
    """Return executable path, or None when missing (offline)."""
    name = (bin_override or os.environ.get(LOGIC_PRO_MCP_BIN_ENV) or DEFAULT_LOGIC_PRO_MCP_BIN).strip()
    if not name:
        return None
    if os.path.isabs(name) or os.sep in name:
        return name if os.path.isfile(name) and os.access(name, os.X_OK) else None
    return shutil.which(name)


def parse_honest_contract(payload: Any) -> tuple[Optional[str], Optional[Mapping[str, Any]]]:
    """
    Extract Honest Contract state letter from a tool payload.

    Returns (state, payload_dict). state is "A"/"B"/"C" when classifiable.
    """
    if not isinstance(payload, Mapping):
        return None, None
    data = dict(payload)
    raw = data.get("state")
    if raw is None and data.get("verified") is True and data.get("success") is True:
        return "A", data
    if raw is None and data.get("success") is False:
        return "C", data
    if isinstance(raw, str):
        letter = raw.strip().upper()
        if letter in {"A", "B", "C"}:
            return letter, data
        # Some envelopes use confirmed / uncertain / failed words.
        lowered = letter.lower()
        if lowered in {"confirmed", "success", "ok"}:
            return "A", data
        if lowered in {"uncertain", "unverified"}:
            return "B", data
        if lowered in {"failed", "failure", "error"}:
            return "C", data
    if data.get("verified") is False and data.get("success") is True:
        return "B", data
    if data.get("error") or data.get("isError") is True:
        return "C", data
    return None, data


def is_state_a(payload: Any) -> bool:
    state, _ = parse_honest_contract(payload)
    return state == "A"


def extract_tool_payload(rpc_response: Optional[Mapping[str, Any]]) -> Any:
    """Pull JSON tool body from an MCP tools/call JSON-RPC response."""
    if not isinstance(rpc_response, Mapping):
        return None
    if "error" in rpc_response:
        err = rpc_response.get("error")
        if isinstance(err, Mapping):
            return {
                "success": False,
                "verified": False,
                "state": "C",
                "error": err.get("message") or "rpc_error",
                "detail": err,
            }
        return {"success": False, "verified": False, "state": "C", "error": "rpc_error"}
    result = rpc_response.get("result")
    if not isinstance(result, Mapping):
        return None
    if result.get("isError"):
        text = _first_text_content(result)
        parsed = _try_json(text) if text else None
        if isinstance(parsed, Mapping):
            out = dict(parsed)
            out.setdefault("state", "C")
            out.setdefault("success", False)
            out.setdefault("verified", False)
            return out
        return {
            "success": False,
            "verified": False,
            "state": "C",
            "error": text or "tool_error",
        }
    structured = result.get("structuredContent")
    if isinstance(structured, Mapping):
        return structured
    text = _first_text_content(result)
    if text:
        parsed = _try_json(text)
        if parsed is not None:
            return parsed
        return {"legacy_message": text, "success": True, "verified": False, "state": "B"}
    return None


def _first_text_content(result: Mapping[str, Any]) -> str:
    content = result.get("content")
    if not isinstance(content, list):
        return ""
    for item in content:
        if isinstance(item, Mapping) and item.get("type") == "text":
            return str(item.get("text") or "")
    return ""


def _try_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def resolve_arm_target(tracks: Sequence[Mapping[str, Any]]) -> Optional[TrackTarget]:
    """
    Pick an explicit track target without guessing among many.

    Rules (fail closed when ambiguous):
    - Exactly one track → that track.
    - Exactly one ``isSelected`` track → that track.
    - Otherwise → None (caller fails closed with clear copy).
    """
    cleaned: list[Mapping[str, Any]] = [t for t in tracks if isinstance(t, Mapping)]
    if not cleaned:
        return None

    def _target(t: Mapping[str, Any]) -> Optional[TrackTarget]:
        idx = t.get("id", t.get("index"))
        if not isinstance(idx, int):
            try:
                idx = int(idx)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None
        name = t.get("name")
        name_s = name.strip() if isinstance(name, str) and name.strip() else None
        ref = t.get("target_ref") or t.get("ref")
        ref_s = ref if isinstance(ref, str) and ref.strip() else None
        return TrackTarget(index=idx, name=name_s, target_ref=ref_s)

    if len(cleaned) == 1:
        return _target(cleaned[0])

    selected = [t for t in cleaned if t.get("isSelected") is True]
    if len(selected) == 1:
        return _target(selected[0])
    return None


def parse_tracks_resource(payload: Any) -> list[dict[str, Any]]:
    """Normalize ``logic://tracks`` resource JSON into a list of track dicts."""
    data = payload
    if isinstance(payload, Mapping):
        inner = payload.get("data", payload.get("tracks", payload))
        data = inner
    if not isinstance(data, list):
        return []
    return [dict(t) for t in data if isinstance(t, Mapping)]


def doctor_status_ready(report: Mapping[str, Any]) -> bool:
    """True only when doctor aggregate status is explicitly ok/ready."""
    status = str(report.get("status") or "").strip().lower()
    return status in {"ok", "ready", "pass", "passed"}


class FakeMcpTransport:
    """In-memory transport for unit tests."""

    def __init__(
        self,
        *,
        handlers: Optional[Mapping[str, Callable[[Optional[Mapping[str, Any]]], Any]]] = None,
        tool_handlers: Optional[
            Mapping[tuple[str, str], Callable[[Mapping[str, Any]], Any]]
        ] = None,
    ) -> None:
        self.handlers = dict(handlers or {})
        self.tool_handlers = dict(tool_handlers or {})
        self.calls: list[tuple[str, Optional[Mapping[str, Any]]]] = []
        self.tool_calls: list[tuple[str, str, Mapping[str, Any]]] = []
        self.closed = False
        self._id = 0

    def request(
        self, method: str, params: Optional[Mapping[str, Any]] = None, *, timeout: float
    ) -> Optional[Mapping[str, Any]]:
        self.calls.append((method, params))
        if method == "tools/call":
            name = ""
            args: Mapping[str, Any] = {}
            if isinstance(params, Mapping):
                name = str(params.get("name") or "")
                raw_args = params.get("arguments") or {}
                args = raw_args if isinstance(raw_args, Mapping) else {}
            command = str(args.get("command") or "")
            self.tool_calls.append((name, command, dict(args)))
            handler = self.tool_handlers.get((name, command))
            body = handler(args) if handler else {"state": "C", "error": "no_handler", "success": False}
            return {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "result": {
                    "content": [{"type": "text", "text": json.dumps(body)}],
                    "structuredContent": body if isinstance(body, dict) else None,
                },
            }
        if method == "resources/read":
            uri = ""
            if isinstance(params, Mapping):
                uri = str(params.get("uri") or "")
            handler = self.handlers.get(f"resource:{uri}") or self.handlers.get("resources/read")
            body = handler(params) if handler else {"data": []}
            text = json.dumps(body)
            return {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "result": {"contents": [{"uri": uri, "text": text}]},
            }
        handler = self.handlers.get(method)
        if handler is None:
            return {"jsonrpc": "2.0", "id": self._next_id(), "result": {}}
        body = handler(params)
        return {"jsonrpc": "2.0", "id": self._next_id(), "result": body}

    def notify(self, method: str, params: Optional[Mapping[str, Any]] = None) -> None:
        self.calls.append((method, params))

    def close(self) -> None:
        self.closed = True

    def _next_id(self) -> int:
        self._id += 1
        return self._id


class StdioMcpSession:
    """Newline-delimited JSON-RPC over a spawned LogicProMCP process."""

    def __init__(
        self,
        bin_path: str,
        *,
        timeout: float = DEFAULT_RPC_TIMEOUT_SEC,
        popen: Optional[Callable[..., subprocess.Popen]] = None,
    ) -> None:
        self.bin_path = bin_path
        self.timeout = timeout
        self._popen = popen or subprocess.Popen
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._responses: MutableMapping[Any, Mapping[str, Any]] = {}
        self._lock = threading.Lock()
        self._id = 0
        self._stderr = ""

    def start(self) -> BridgeResult:
        try:
            self._proc = self._popen(
                [self.bin_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except OSError as exc:
            return BridgeResult(
                ok=False,
                offline=True,
                message=OFFLINE_MUSICIAN_COPY,
                detail={"error": "spawn_failed", "exc": str(exc)},
            )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        init = self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "midi_gen_logic_mcp_bridge", "version": "0.1"},
            },
            timeout=self.timeout,
        )
        if not init or "result" not in init:
            self.close()
            return BridgeResult(
                ok=False,
                offline=True,
                message=OFFLINE_MUSICIAN_COPY,
                detail={"error": "initialize_failed", "response": init},
            )
        self.notify("notifications/initialized")
        return BridgeResult(ok=True, message="initialized")

    def request(
        self, method: str, params: Optional[Mapping[str, Any]] = None, *, timeout: float
    ) -> Optional[Mapping[str, Any]]:
        if self._proc is None or self._proc.stdin is None:
            return None
        req_id = self._next_id()
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            msg["params"] = dict(params)
        try:
            self._proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            return None
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if req_id in self._responses:
                    return self._responses.pop(req_id)
            if self._proc.poll() is not None:
                return None
            time.sleep(0.02)
        return None

    def notify(self, method: str, params: Optional[Mapping[str, Any]] = None) -> None:
        if self._proc is None or self._proc.stdin is None:
            return
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = dict(params)
        try:
            self._proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            return

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _read_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(msg, dict) and msg.get("id") is not None:
                    with self._lock:
                        self._responses[msg["id"]] = msg
        except Exception:
            return

    def _next_id(self) -> int:
        self._id += 1
        return self._id


class LogicMcpBridge:
    """
    Fail-closed record-only client.

    Construct with an injected transport for tests, or call helpers that spawn
    a short-lived stdio session per operation group.
    """

    def __init__(
        self,
        transport: Optional[McpTransport] = None,
        *,
        bin_path: Optional[str] = None,
        rpc_timeout: float = DEFAULT_RPC_TIMEOUT_SEC,
        doctor_timeout: float = DEFAULT_DOCTOR_TIMEOUT_SEC,
        run_doctor: Optional[Callable[[str, float], BridgeResult]] = None,
        session_factory: Optional[Callable[[str], StdioMcpSession]] = None,
    ) -> None:
        self._transport = transport
        self._bin_path = bin_path
        self.rpc_timeout = rpc_timeout
        self.doctor_timeout = doctor_timeout
        self._run_doctor = run_doctor or _run_doctor_cli
        self._session_factory = session_factory or (
            lambda path: StdioMcpSession(path, timeout=rpc_timeout)
        )
        self._owns_transport = False

    # --- readiness ---------------------------------------------------------

    def readiness(self) -> BridgeResult:
        """Doctor ``--profile core`` when CLI works; else MCP ``health``."""
        bin_path = resolve_bin(self._bin_path)
        if not bin_path and self._transport is None:
            return BridgeResult(
                ok=False,
                offline=True,
                message=OFFLINE_MUSICIAN_COPY,
                detail={"error": "binary_missing"},
            )
        if bin_path:
            doctor = self._run_doctor(bin_path, self.doctor_timeout)
            if doctor.ok:
                return doctor
            # Doctor ran but not ready → still fail closed (not "unknown ready").
            if doctor.detail.get("error") not in {
                "doctor_unavailable",
                "doctor_spawn_failed",
                "doctor_timeout",
                "doctor_parse_failed",
            }:
                return doctor
            # Fall through to MCP health when doctor CLI itself is unavailable.
        return self.health()

    def health(self) -> BridgeResult:
        return self._with_session(self._health_on)

    # --- record ops --------------------------------------------------------

    def arm_track(self, target: TrackTarget, *, arm_only: bool = True) -> BridgeResult:
        command = "arm_only" if arm_only else "arm"
        return self._call_allowed(
            "logic_tracks",
            command,
            target.as_params(),
            operation=f"tracks.{command}",
        )

    def transport_record(self) -> BridgeResult:
        return self._call_allowed(
            "logic_transport",
            "record",
            None,
            operation="transport.record",
        )

    def transport_stop(self) -> BridgeResult:
        return self._call_allowed(
            "logic_transport",
            "stop",
            None,
            operation="transport.stop",
            # Stop is best-effort for UI teardown; still fail-closed on B/C when online.
        )

    def list_tracks(self) -> BridgeResult:
        def _op(transport: McpTransport) -> BridgeResult:
            resp = transport.request(
                "resources/read",
                {"uri": "logic://tracks"},
                timeout=self.rpc_timeout,
            )
            if resp is None:
                return BridgeResult(
                    ok=False,
                    offline=True,
                    message=OFFLINE_MUSICIAN_COPY,
                    detail={"error": "tracks_timeout"},
                )
            text = ""
            try:
                text = resp["result"]["contents"][0].get("text", "")  # type: ignore[index]
            except (KeyError, IndexError, TypeError, AttributeError):
                text = ""
            payload = _try_json(text) if text else None
            tracks = parse_tracks_resource(payload)
            return BridgeResult(
                ok=True,
                message=f"{len(tracks)} track(s)",
                detail={"tracks": tracks},
            )

        return self._with_session(_op)

    def arm_and_record(self, *, arm_only: bool = True) -> BridgeResult:
        """
        Resolve explicit track → arm → transport.record in one session.

        Fail closed when track target cannot be determined without guessing.
        """

        def _op(transport: McpTransport) -> BridgeResult:
            tracks_res = self._list_tracks_on(transport)
            if not tracks_res.ok:
                return tracks_res
            tracks = list(tracks_res.detail.get("tracks") or [])
            target = resolve_arm_target(tracks)
            if target is None:
                return BridgeResult(
                    ok=False,
                    offline=False,
                    state="C",
                    operation="tracks.arm",
                    message=(
                        "Logic Record control needs an explicit track — "
                        "select one track in Logic (or keep a single-track project), then retry."
                    ),
                    detail={"error": "track_target_unknown", "track_count": len(tracks)},
                )
            arm = self._call_on(
                transport,
                "logic_tracks",
                "arm_only" if arm_only else "arm",
                target.as_params(),
                operation=f"tracks.{'arm_only' if arm_only else 'arm'}",
            )
            if not arm.ok:
                return arm
            rec = self._call_on(
                transport,
                "logic_transport",
                "record",
                None,
                operation="transport.record",
            )
            if not rec.ok:
                return rec
            return BridgeResult(
                ok=True,
                state="A",
                operation="arm_and_record",
                message=f"Armed track {target.index}"
                + (f" ({target.name})" if target.name else "")
                + " · Logic Record confirmed.",
                detail={"target": target.as_params(), "arm": arm.detail, "record": rec.detail},
            )

        return self._with_session(_op)

    # --- internals ---------------------------------------------------------

    def _health_on(self, transport: McpTransport) -> BridgeResult:
        payload_res = self._call_on(
            transport,
            "logic_system",
            "health",
            None,
            operation="system.health",
            require_state_a=False,
        )
        if payload_res.offline:
            return payload_res
        body = dict(payload_res.detail.get("payload") or {})
        # Health is read-ish — treat channel readiness, not HC State A, as the gate.
        ready = _health_payload_ready(body)
        if ready:
            return BridgeResult(
                ok=True,
                message="Logic MCP Ready",
                detail={"payload": body, "via": "health"},
            )
        return BridgeResult(
            ok=False,
            offline=True,
            message=OFFLINE_MUSICIAN_COPY,
            detail={"payload": body, "via": "health", "error": "health_not_ready"},
        )

    def _list_tracks_on(self, transport: McpTransport) -> BridgeResult:
        resp = transport.request(
            "resources/read",
            {"uri": "logic://tracks"},
            timeout=self.rpc_timeout,
        )
        if resp is None:
            return BridgeResult(
                ok=False,
                offline=True,
                message=OFFLINE_MUSICIAN_COPY,
                detail={"error": "tracks_timeout"},
            )
        text = ""
        try:
            text = resp["result"]["contents"][0].get("text", "")  # type: ignore[index]
        except (KeyError, IndexError, TypeError, AttributeError):
            text = ""
        payload = _try_json(text) if text else None
        tracks = parse_tracks_resource(payload)
        return BridgeResult(ok=True, detail={"tracks": tracks})

    def _call_allowed(
        self,
        tool: str,
        command: str,
        params: Optional[Mapping[str, Any]],
        *,
        operation: str,
        require_state_a: bool = True,
    ) -> BridgeResult:
        return self._with_session(
            lambda t: self._call_on(
                t,
                tool,
                command,
                params,
                operation=operation,
                require_state_a=require_state_a,
            )
        )

    def _call_on(
        self,
        transport: McpTransport,
        tool: str,
        command: str,
        params: Optional[Mapping[str, Any]],
        *,
        operation: str,
        require_state_a: bool = True,
    ) -> BridgeResult:
        if command in FORBIDDEN_COMMANDS:
            return BridgeResult(
                ok=False,
                state="C",
                operation=operation,
                message="Refused forbidden MCP MIDI/import command.",
                detail={"error": "forbidden_command", "command": command},
            )
        if (tool, command) not in ALLOWED_TOOL_COMMANDS:
            return BridgeResult(
                ok=False,
                state="C",
                operation=operation,
                message="Refused non-record MCP operation.",
                detail={"error": "disallowed_operation", "tool": tool, "command": command},
            )
        args: dict[str, Any] = {"command": command}
        if params:
            # Match Logic Pro MCP e2e: nested params object.
            args["params"] = dict(params)
        resp = transport.request(
            "tools/call",
            {"name": tool, "arguments": args},
            timeout=self.rpc_timeout,
        )
        if resp is None:
            return BridgeResult(
                ok=False,
                offline=True,
                operation=operation,
                message=OFFLINE_MUSICIAN_COPY,
                detail={"error": "rpc_timeout"},
            )
        payload = extract_tool_payload(resp)
        state, normalized = parse_honest_contract(payload)
        detail = {"payload": normalized or payload, "rpc": resp}
        if not require_state_a:
            return BridgeResult(
                ok=True,
                state=state,
                operation=operation,
                message=operation,
                detail=detail,
            )
        if state == "A":
            return BridgeResult(
                ok=True,
                state="A",
                operation=operation,
                message=f"{operation} confirmed (State A).",
                detail=detail,
            )
        if state == "B":
            reason = ""
            if isinstance(normalized, Mapping):
                reason = str(normalized.get("reason") or normalized.get("error") or "")
            return BridgeResult(
                ok=False,
                state="B",
                operation=operation,
                message=(
                    f"Logic Record uncertain (State B)"
                    + (f" — {reason}" if reason else "")
                    + ". Not treating as recorded."
                ),
                detail=detail,
            )
        # State C or unclassifiable → fail closed
        err = ""
        if isinstance(normalized, Mapping):
            err = str(normalized.get("error") or normalized.get("reason") or "")
        return BridgeResult(
            ok=False,
            state=state or "C",
            operation=operation,
            message=(
                f"Logic Record failed"
                + (f" — {err}" if err else " (State C)")
                + ". Not treating as recorded."
            ),
            detail=detail,
        )

    def _with_session(self, fn: Callable[[McpTransport], BridgeResult]) -> BridgeResult:
        if self._transport is not None:
            try:
                return fn(self._transport)
            except Exception as exc:  # pragma: no cover — defensive for Streamlit
                return BridgeResult(
                    ok=False,
                    offline=True,
                    message=OFFLINE_MUSICIAN_COPY,
                    detail={"error": "transport_exception", "exc": str(exc)},
                )
        bin_path = resolve_bin(self._bin_path)
        if not bin_path:
            return BridgeResult(
                ok=False,
                offline=True,
                message=OFFLINE_MUSICIAN_COPY,
                detail={"error": "binary_missing"},
            )
        session = self._session_factory(bin_path)
        started = session.start()
        if not started.ok:
            session.close()
            return started
        try:
            return fn(session)
        except Exception as exc:  # pragma: no cover
            return BridgeResult(
                ok=False,
                offline=True,
                message=OFFLINE_MUSICIAN_COPY,
                detail={"error": "session_exception", "exc": str(exc)},
            )
        finally:
            session.close()


def _health_payload_ready(body: Mapping[str, Any]) -> bool:
    """Best-effort parse of ``logic_system.health`` / resource health shapes."""
    if not body:
        return False
    if body.get("ready") is True or body.get("ok") is True:
        return True
    status = str(body.get("status") or "").lower()
    if status in {"ok", "ready", "healthy"}:
        return True
    channels = body.get("channels")
    if isinstance(channels, Mapping):
        # Ready when Accessibility (core arm/record path) reports ready.
        ax = channels.get("Accessibility") or channels.get("accessibility")
        if isinstance(ax, Mapping) and str(ax.get("status") or "").lower() in {
            "ready",
            "ok",
            "available",
        }:
            return True
        if isinstance(ax, str) and ax.lower() in {"ready", "ok", "available"}:
            return True
    # Some health payloads nest under data.
    data = body.get("data")
    if isinstance(data, Mapping) and data is not body:
        return _health_payload_ready(data)
    return False


def _run_doctor_cli(bin_path: str, timeout: float) -> BridgeResult:
    """Run ``LogicProMCP doctor --profile core --json`` (no MCP session)."""
    try:
        proc = subprocess.run(
            [bin_path, "doctor", "--profile", "core", "--json"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return BridgeResult(
            ok=False,
            offline=True,
            message=OFFLINE_MUSICIAN_COPY,
            detail={"error": "doctor_unavailable"},
        )
    except subprocess.TimeoutExpired:
        return BridgeResult(
            ok=False,
            offline=True,
            message=OFFLINE_MUSICIAN_COPY,
            detail={"error": "doctor_timeout"},
        )
    except OSError as exc:
        return BridgeResult(
            ok=False,
            offline=True,
            message=OFFLINE_MUSICIAN_COPY,
            detail={"error": "doctor_spawn_failed", "exc": str(exc)},
        )
    # Older builds may not implement doctor — treat as unavailable for health fallback.
    if proc.returncode in {127, 2} and "doctor" in (proc.stderr or "").lower():
        return BridgeResult(
            ok=False,
            offline=True,
            message=OFFLINE_MUSICIAN_COPY,
            detail={"error": "doctor_unavailable", "stderr": proc.stderr[-500:]},
        )
    report = _try_json(proc.stdout or "")
    if not isinstance(report, Mapping):
        # Non-JSON / unknown subcommand → let caller fall back to health.
        if proc.returncode != 0 and not (proc.stdout or "").strip():
            return BridgeResult(
                ok=False,
                offline=True,
                message=OFFLINE_MUSICIAN_COPY,
                detail={
                    "error": "doctor_unavailable",
                    "returncode": proc.returncode,
                    "stderr": (proc.stderr or "")[-500:],
                },
            )
        return BridgeResult(
            ok=False,
            offline=True,
            message=OFFLINE_MUSICIAN_COPY,
            detail={"error": "doctor_parse_failed", "stdout": (proc.stdout or "")[:500]},
        )
    if doctor_status_ready(report):
        return BridgeResult(
            ok=True,
            message="Logic MCP Ready",
            detail={"via": "doctor", "report": report},
        )
    headline = str(report.get("headline") or report.get("status") or "not ready")
    return BridgeResult(
        ok=False,
        offline=True,
        message=OFFLINE_MUSICIAN_COPY,
        detail={"via": "doctor", "report": report, "headline": headline, "error": "doctor_not_ready"},
    )


# --- module-level helpers for the UI ---------------------------------------

_shared_readiness: Optional[BridgeResult] = None
_shared_readiness_at: float = 0.0
_READINESS_TTL_SEC = 8.0


def get_mcp_readiness(*, force: bool = False, bridge: Optional[LogicMcpBridge] = None) -> BridgeResult:
    """Cached readiness probe for the Streamlit chip (fail-closed)."""
    global _shared_readiness, _shared_readiness_at
    now = time.time()
    if (
        not force
        and _shared_readiness is not None
        and (now - _shared_readiness_at) < _READINESS_TTL_SEC
    ):
        return _shared_readiness
    client = bridge or LogicMcpBridge()
    try:
        result = client.readiness()
    except Exception as exc:  # pragma: no cover
        result = BridgeResult(
            ok=False,
            offline=True,
            message=OFFLINE_MUSICIAN_COPY,
            detail={"error": "readiness_exception", "exc": str(exc)},
        )
    _shared_readiness = result
    _shared_readiness_at = now
    return result


def clear_readiness_cache() -> None:
    global _shared_readiness, _shared_readiness_at
    _shared_readiness = None
    _shared_readiness_at = 0.0
