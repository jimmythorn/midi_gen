"""
Live MIDI output for auditioning into a DAW (Logic Pro via macOS IAC).

Streams note/CC/pitch-bend from a .mid file over a system MIDI output port
using wall-clock scheduling. Optional app-side count-in and loop (no DAW MIDI
clock / Logic scripting). Enable IAC in Audio MIDI Setup, point a Logic
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


def port_looks_like_iac(name: str) -> bool:
    """True when a port name looks like a macOS IAC Driver bus."""
    return "iac" in (name or "").lower()


def preferred_iac_port(ports: Optional[Sequence[str]] = None) -> Optional[str]:
    """Pick the best default port: IAC bus first, else first available."""
    names = list(ports) if ports is not None else list_output_ports()
    if not names:
        return None
    for name in names:
        if port_looks_like_iac(name):
            return name
    return names[0]


def has_iac_port(ports: Optional[Sequence[str]] = None) -> bool:
    """True when any enumerated output looks like an IAC bus."""
    names = list(ports) if ports is not None else list_output_ports()
    return any(port_looks_like_iac(n) for n in names)


def refresh_output_ports() -> List[str]:
    """
    Re-enumerate MIDI outputs without relaunching the app.

    Call after enabling IAC mid-session so newly online buses appear.
    """
    if not rtmidi_available():
        return []
    try:
        # Re-assert rtmidi backend in case ports came online after startup.
        try:
            mido.set_backend("mido.backends.rtmidi")
        except Exception:
            pass
        return list(mido.get_output_names())
    except Exception:
        return []


def _all_notes_off(port: mido.ports.BaseOutput, channels: range = range(16)) -> None:
    for ch in channels:
        try:
            port.send(mido.Message("control_change", channel=ch, control=123, value=0))
            port.send(mido.Message("pitchwheel", channel=ch, pitch=0))
        except Exception:
            pass


def bar_duration_sec(bpm: float, beats_per_bar: int = 4) -> float:
    """Wall-clock seconds for one bar at the given tempo."""
    safe_bpm = max(1.0, float(bpm or 120.0))
    safe_beats = max(1, int(beats_per_bar or 4))
    return (60.0 / safe_bpm) * safe_beats


def midi_file_bpm(path: str, default: float = 120.0) -> float:
    """Best-effort BPM from the file's last set_tempo (else default)."""
    try:
        mid = mido.MidiFile(path)
        tempo = 500000
        for msg in mido.merge_tracks(mid.tracks):
            if msg.type == "set_tempo":
                tempo = msg.tempo
        return float(mido.tempo2bpm(tempo))
    except Exception:
        return float(default)


class LiveMidiPlayer:
    """
    Background wall-clock player for one MIDI file → one output port.

    App-side count-in and loop only — no DAW MIDI clock / Logic scripting.
    Safe to call stop() from the UI thread. Only one clip plays at a time.
    """

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._port_name: Optional[str] = None
        self._error: Optional[str] = None
        self._playing = False
        self._phase: str = "idle"  # idle | count_in | playing
        self._looping = False

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

    @property
    def phase(self) -> str:
        """idle | count_in | playing — honest UI caption source."""
        with self._lock:
            if not (self._playing and self._thread is not None and self._thread.is_alive()):
                return "idle"
            return self._phase

    @property
    def looping(self) -> bool:
        with self._lock:
            alive = (
                self._playing
                and self._thread is not None
                and self._thread.is_alive()
            )
            return bool(self._looping and alive)

    def status(self, *, refresh: bool = False) -> LiveMidiStatus:
        ports = refresh_output_ports() if refresh else list_output_ports()
        with self._lock:
            err = self._error
            thread = self._thread
            playing = self._playing and thread is not None and thread.is_alive()
            # Honest flag: if the worker already exited, never report Playing.
            if self._playing and (thread is None or not thread.is_alive()):
                self._playing = False
                self._phase = "idle"
                self._looping = False
                playing = False
            port_name = self._port_name
        if not rtmidi_available():
            err = err or f"python-rtmidi not available: {_RTMIDI_IMPORT_ERROR}"
        elif not ports:
            err = err or (
                "No MIDI output ports found. On Mac: enable IAC Driver in "
                "Audio MIDI Setup, then hit Refresh ports."
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
        count_in_bars: float = 0.0,
        bpm: Optional[float] = None,
        beats_per_bar: int = 4,
        loop: bool = False,
        click: bool = False,
        on_finished: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Start (or restart) playback of a MIDI file on the given port.

        count_in_bars: silent (default) or click bars before notes — app-side
        only, so Logic Record can already be rolling before the sketch starts.
        loop: repeat the sketch until Stop (all-notes-off between passes).
        click: when True, emit a soft metronome note each beat of the count-in
        (same port — will be captured if Logic is recording; off by default).
        """
        midi_path = Path(path)
        if not midi_path.is_file():
            raise FileNotFoundError(path)

        ports = list_output_ports()
        if not rtmidi_available():
            raise RuntimeError(f"python-rtmidi not available: {_RTMIDI_IMPORT_ERROR}")
        if not ports:
            raise RuntimeError(
                "No MIDI output ports. Enable IAC Driver (Mac), then Refresh ports."
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

        play_bpm = float(bpm) if bpm and bpm > 0 else midi_file_bpm(str(midi_path))
        count_bars = max(0.0, float(count_in_bars or 0.0))
        count_in_sec = bar_duration_sec(play_bpm, beats_per_bar) * count_bars
        beat_sec = 60.0 / max(1.0, play_bpm)
        click_beats = int(round(count_bars * max(1, int(beats_per_bar or 4))))

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
            self._phase = "count_in" if count_in_sec > 0 else "playing"
            self._looping = bool(loop)
            stop_flag = self._stop

        def _wait_until(deadline: float) -> bool:
            """Sleep until deadline; return True if stop requested."""
            while time.perf_counter() < deadline:
                if stop_flag.is_set():
                    return True
                time.sleep(min(0.01, max(0.0, deadline - time.perf_counter())))
            return stop_flag.is_set()

        def _run_count_in(port: mido.ports.BaseOutput) -> bool:
            """Return True if stop requested during count-in."""
            if count_in_sec <= 0:
                return False
            with self._lock:
                self._phase = "count_in"
            start = time.perf_counter()
            if click and click_beats > 0:
                # Soft rim-ish click on ch 9 (GM drums) when possible — still
                # same IAC bus; prefer silent count-in for clean region capture.
                for i in range(click_beats):
                    if stop_flag.is_set():
                        return True
                    beat_at = start + i * beat_sec
                    if _wait_until(beat_at):
                        return True
                    try:
                        note = 37 if i % max(1, int(beats_per_bar)) == 0 else 42
                        port.send(
                            mido.Message(
                                "note_on", channel=9, note=note, velocity=70
                            )
                        )
                        port.send(
                            mido.Message(
                                "note_off", channel=9, note=note, velocity=0
                            )
                        )
                    except Exception:
                        pass
                return _wait_until(start + count_in_sec)
            return _wait_until(start + count_in_sec)

        def _run_schedule(port: mido.ports.BaseOutput) -> bool:
            """Play one pass; return True if stop requested."""
            with self._lock:
                self._phase = "playing"
            start = time.perf_counter()
            for abs_sec, msg in schedule:
                if stop_flag.is_set():
                    return True
                delay = abs_sec - (time.perf_counter() - start)
                if delay > 0:
                    if _wait_until(time.perf_counter() + delay):
                        return True
                if stop_flag.is_set():
                    return True
                port.send(msg)
            return stop_flag.is_set()

        def _run() -> None:
            port = None
            try:
                port = mido.open_output(target)
                if _run_count_in(port):
                    return
                while True:
                    if _run_schedule(port):
                        return
                    with self._lock:
                        should_loop = self._looping
                    if not should_loop or stop_flag.is_set():
                        return
                    # Flush hanging notes between passes; keep Playing honest.
                    try:
                        _all_notes_off(port)
                    except Exception:
                        pass
                    # Tiny gap so Logic sees a clean boundary between loops.
                    if _wait_until(time.perf_counter() + 0.05):
                        return
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
                    self._phase = "idle"
                    self._looping = False
                if on_finished:
                    try:
                        on_finished()
                    except Exception:
                        pass

        thread = threading.Thread(target=_run, name="live-midi-player", daemon=True)
        with self._lock:
            self._thread = thread
        thread.start()

    def stop(self, wait: bool = True, timeout: float = 2.0) -> None:
        """
        Request stop and clear Playing once the worker exits.

        Default wait=True so the UI does not linger on Playing and hanging
        notes are flushed (all-notes-off in the worker finally block).
        """
        with self._lock:
            self._stop.set()
            self._looping = False
            thread = self._thread
        if wait and thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        with self._lock:
            if not (self._thread and self._thread.is_alive()):
                self._playing = False
                self._phase = "idle"
            elif wait:
                # Timed out — still clear Playing so the UI is honest.
                self._playing = False
                self._phase = "idle"


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
