"""
Live MIDI output for auditioning into a DAW (Logic Pro via macOS IAC).

Streams note/CC/pitch-bend from a .mid file over a system MIDI output port
using wall-clock scheduling. Enable IAC in Audio MIDI Setup, point a Logic
instrument's MIDI In at that bus, then Play.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

import mido

from .midi_tempo import midi_file_schedule

try:
    import rtmidi  # noqa: F401
    _RTMIDI_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # pragma: no cover
    _RTMIDI_IMPORT_ERROR = exc


ScheduledMsg = Tuple[float, mido.Message]


@dataclass
class LiveMidiStatus:
    available: bool
    playing: bool
    port_name: Optional[str]
    ports: List[str]
    error: Optional[str] = None
    backend: Optional[str] = None


def rtmidi_available() -> bool:
    return _RTMIDI_IMPORT_ERROR is None


def list_output_ports() -> List[str]:
    """Return MIDI output port names (empty if backend missing or no devices)."""
    if not rtmidi_available():
        return []
    try:
        if getattr(mido.backend, "module_name", "") != "mido.backends.rtmidi":
            try:
                mido.set_backend("mido.backends.rtmidi")
            except Exception:
                pass
        return list(mido.get_output_names())
    except Exception:
        return []


def preferred_iac_port(ports: Optional[Sequence[str]] = None) -> Optional[str]:
    """Pick the best default port: IAC bus first, else first available."""
    names = list(ports) if ports is not None else list_output_ports()
    if not names:
        return None
    for name in names:
        if "iac" in name.lower():
            return name
    return names[0]


def _all_notes_off(port: mido.ports.BaseOutput, channels: range = range(16)) -> None:
    for ch in channels:
        try:
            port.send(mido.Message("control_change", channel=ch, control=123, value=0))
            port.send(mido.Message("pitchwheel", channel=ch, pitch=0))
        except Exception:
            pass


class LiveMidiPlayer:
    """
    Background wall-clock player for one MIDI file → one output port.

    Safe to call stop() from the UI thread. Only one clip plays at a time.
    """

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._port_name: Optional[str] = None
        self._error: Optional[str] = None
        self._playing = False

    @property
    def playing(self) -> bool:
        with self._lock:
            return self._playing and self._thread is not None and self._thread.is_alive()

    @property
    def port_name(self) -> Optional[str]:
        with self._lock:
            return self._port_name

    @property
    def last_error(self) -> Optional[str]:
        with self._lock:
            return self._error

    def status(self) -> LiveMidiStatus:
        ports = list_output_ports()
        with self._lock:
            err = self._error
            playing = self._playing and self._thread is not None and self._thread.is_alive()
            port_name = self._port_name
        if not rtmidi_available():
            err = err or f"python-rtmidi not available: {_RTMIDI_IMPORT_ERROR}"
        elif not ports:
            err = err or (
                "No MIDI output ports found. On Mac: enable IAC Driver in "
                "Audio MIDI Setup, then relaunch this app."
            )
        return LiveMidiStatus(
            available=rtmidi_available() and bool(ports),
            playing=playing,
            port_name=port_name,
            ports=ports,
            error=err,
            backend="mido+rtmidi" if rtmidi_available() else None,
        )

    def play_file(
        self,
        path: str,
        port_name: Optional[str] = None,
        *,
        on_finished: Optional[Callable[[], None]] = None,
    ) -> None:
        """Start (or restart) playback of a MIDI file on the given port."""
        midi_path = Path(path)
        if not midi_path.is_file():
            raise FileNotFoundError(path)

        ports = list_output_ports()
        if not rtmidi_available():
            raise RuntimeError(f"python-rtmidi not available: {_RTMIDI_IMPORT_ERROR}")
        if not ports:
            raise RuntimeError(
                "No MIDI output ports. Enable IAC Driver (Mac) or another virtual MIDI port."
            )

        target = port_name or preferred_iac_port(ports)
        if target is None:
            raise RuntimeError("No MIDI output port selected.")
        if target not in ports:
            match = next((p for p in ports if target.lower() in p.lower()), None)
            if match is None:
                raise RuntimeError(f"Port not found: {target!r}. Available: {ports}")
            target = match

        schedule, _duration = midi_file_schedule(str(midi_path))
        if not schedule:
            raise RuntimeError("MIDI file has no playable messages.")

        with self._lock:
            self._stop.set()
            prior = self._thread

        if prior is not None and prior.is_alive():
            prior.join(timeout=2.0)
            if prior.is_alive():
                raise RuntimeError("Previous live MIDI playback did not stop in time.")

        with self._lock:
            self._stop = threading.Event()
            self._error = None
            self._port_name = target
            self._playing = True
            stop_flag = self._stop

        def _run() -> None:
            port = None
            try:
                port = mido.open_output(target)
                start = time.perf_counter()
                for abs_sec, msg in schedule:
                    if stop_flag.is_set():
                        break
                    delay = abs_sec - (time.perf_counter() - start)
                    if delay > 0:
                        end_wait = time.perf_counter() + delay
                        while time.perf_counter() < end_wait:
                            if stop_flag.is_set():
                                break
                            time.sleep(min(0.01, max(0.0, end_wait - time.perf_counter())))
                    if stop_flag.is_set():
                        break
                    port.send(msg)
            except Exception as exc:
                with self._lock:
                    self._error = str(exc)
            finally:
                if port is not None:
                    try:
                        _all_notes_off(port)
                        port.close()
                    except Exception:
                        pass
                with self._lock:
                    self._playing = False
                if on_finished:
                    try:
                        on_finished()
                    except Exception:
                        pass

        thread = threading.Thread(target=_run, name="live-midi-player", daemon=True)
        with self._lock:
            self._thread = thread
        thread.start()

    def stop(self, wait: bool = False, timeout: float = 2.0) -> None:
        """Request stop; join optionally."""
        with self._lock:
            self._stop.set()
            thread = self._thread
        if wait and thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        with self._lock:
            if not (self._thread and self._thread.is_alive()):
                self._playing = False


_SHARED_PLAYER: Optional[LiveMidiPlayer] = None
_SHARED_LOCK = threading.Lock()


def get_shared_player() -> LiveMidiPlayer:
    global _SHARED_PLAYER
    with _SHARED_LOCK:
        if _SHARED_PLAYER is None:
            _SHARED_PLAYER = LiveMidiPlayer()
        return _SHARED_PLAYER


# Back-compat for tests that imported the private helper
def _midi_file_to_schedule(path: str):
    return midi_file_schedule(path)
