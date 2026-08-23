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

try:
    import rtmidi  # noqa: F401 — presence check; mido opens via midi/rtmidi backend
    _RTMIDI_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # pragma: no cover - environment dependent
    _RTMIDI_IMPORT_ERROR = exc


ScheduledMsg = Tuple[float, mido.Message]  # abs seconds, message


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
        # Ensure rtmidi backend (needed on some installs)
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
        lower = name.lower()
        if "iac" in lower:
            return name
    return names[0]


def _midi_file_to_schedule(path: str) -> Tuple[List[ScheduledMsg], float]:
    """
    Flatten a MIDI file into absolute-second message times using its tempo map.
    """
    mid = mido.MidiFile(path)
    # merge_tracks preserves tempo messages for tick2second via play(),
    # but we need a static schedule for interruptible playback.
    ticks_per_beat = mid.ticks_per_beat or 480
    tempo = 500000  # µs per beat (120 BPM)
    abs_tick = 0
    schedule: List[ScheduledMsg] = []

    for msg in mido.merge_tracks(mid.tracks):
        abs_tick += msg.time
        if msg.type == "set_tempo":
            tempo = msg.tempo
            continue
        if msg.is_meta:
            continue
        seconds = mido.tick2second(abs_tick, ticks_per_beat, tempo)
        # Copy without delta time — rtmidi send expects zero-time messages
        schedule.append((seconds, msg.copy(time=0)))

    duration = schedule[-1][0] if schedule else 0.0
    return schedule, duration


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
        return self._playing and self._thread is not None and self._thread.is_alive()

    @property
    def port_name(self) -> Optional[str]:
        return self._port_name

    @property
    def last_error(self) -> Optional[str]:
        return self._error

    def status(self) -> LiveMidiStatus:
        ports = list_output_ports()
        err = self._error
        if not rtmidi_available():
            err = err or f"python-rtmidi not available: {_RTMIDI_IMPORT_ERROR}"
        elif not ports:
            err = err or (
                "No MIDI output ports found. On Mac: enable IAC Driver in "
                "Audio MIDI Setup, then relaunch this app."
            )
        return LiveMidiStatus(
            available=rtmidi_available() and bool(ports),
            playing=self.playing,
            port_name=self._port_name,
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
            # Allow substring match (Logic / OS rename quirks)
            match = next((p for p in ports if target.lower() in p.lower()), None)
            if match is None:
                raise RuntimeError(f"Port not found: {target!r}. Available: {ports}")
            target = match

        schedule, _duration = _midi_file_to_schedule(str(midi_path))
        if not schedule:
            raise RuntimeError("MIDI file has no playable messages.")

        self.stop(wait=True)

        self._stop.clear()
        self._error = None
        self._port_name = target
        self._playing = True

        def _run() -> None:
            port = None
            try:
                port = mido.open_output(target)
                start = time.perf_counter()
                for abs_sec, msg in schedule:
                    if self._stop.is_set():
                        break
                    delay = abs_sec - (time.perf_counter() - start)
                    if delay > 0:
                        # Wait in slices so stop() is responsive
                        end_wait = time.perf_counter() + delay
                        while time.perf_counter() < end_wait:
                            if self._stop.is_set():
                                break
                            time.sleep(min(0.01, end_wait - time.perf_counter()))
                    if self._stop.is_set():
                        break
                    port.send(msg)
            except Exception as exc:
                self._error = str(exc)
            finally:
                if port is not None:
                    try:
                        _all_notes_off(port)
                        port.close()
                    except Exception:
                        pass
                self._playing = False
                if on_finished:
                    try:
                        on_finished()
                    except Exception:
                        pass

        self._thread = threading.Thread(target=_run, name="live-midi-player", daemon=True)
        self._thread.start()

    def stop(self, wait: bool = False, timeout: float = 2.0) -> None:
        """Request stop and panic notes off (via next open or current thread cleanup)."""
        self._stop.set()
        thread = self._thread
        if wait and thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        if not (thread and thread.is_alive()):
            self._playing = False


# Process-wide player for the Streamlit UI (one audition stream).
_SHARED_PLAYER: Optional[LiveMidiPlayer] = None
_SHARED_LOCK = threading.Lock()


def get_shared_player() -> LiveMidiPlayer:
    global _SHARED_PLAYER
    with _SHARED_LOCK:
        if _SHARED_PLAYER is None:
            _SHARED_PLAYER = LiveMidiPlayer()
        return _SHARED_PLAYER
