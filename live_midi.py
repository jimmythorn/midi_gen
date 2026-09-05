"""
Live MIDI output for auditioning into a DAW (Logic Pro via macOS IAC).

Streams note/CC/pitch-bend from a .mid file over a system MIDI output port
using wall-clock scheduling at sketch BPM, or by following Logic's MIDI
Start/Clock so notes land on the DAW grid. Optional outbound clock if Logic
is the slave. Enable IAC in Audio MIDI Setup, point a Logic instrument's
MIDI In at that bus, then Play.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

import mido

from .midi_tempo import (
    midi_file_schedule,
    midi_file_tick_schedule,
    seconds_schedule_at_bpm,
    tick_to_seconds,
    due_index,
    spp_to_ticks,
)

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


def list_input_ports() -> List[str]:
    """Return MIDI input port names (empty if backend missing or no devices)."""
    if not rtmidi_available():
        return []
    try:
        if getattr(mido.backend, "module_name", "") != "mido.backends.rtmidi":
            try:
                mido.set_backend("mido.backends.rtmidi")
            except Exception:
                pass
        return list(mido.get_input_names())
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


PORT_LOST_MESSAGE = "MIDI port lost — Refresh ports."

# MIDI Machine Control (universal device 0x7F). Logic listens when
# Project Settings → Synchronization → MIDI → Listen to MMC Input.
_MMC_STOP = (0x7F, 0x7F, 0x06, 0x01)
_MMC_RECORD_STROBE = (0x7F, 0x7F, 0x06, 0x06)


def mmc_sysex(command: Sequence[int]) -> mido.Message:
    return mido.Message("sysex", data=list(command))


def _all_notes_off(port, channels: range = range(16)) -> None:
    """
    Release hanging notes on ``port``.

    Logic software instruments often ignore CC123 (All Notes Off) over IAC, so
    Stop must also drop sustain, send All Sound Off, and explicit note_off for
    every pitch. Pitch-bend reset stays so tape wobble does not leave a bend.
    """
    for ch in channels:
        try:
            port.send(mido.Message("control_change", channel=ch, control=64, value=0))
            port.send(mido.Message("control_change", channel=ch, control=120, value=0))
            port.send(mido.Message("control_change", channel=ch, control=123, value=0))
            port.send(mido.Message("pitchwheel", channel=ch, pitch=0))
            for note in range(128):
                port.send(mido.Message("note_off", channel=ch, note=note, velocity=0))
        except Exception:
            pass


def panic_flush(port) -> None:
    """Hard Stop helper — same as all-notes-off; kept for call-site clarity / tests."""
    _all_notes_off(port)


def panic_flush_named(port_name: Optional[str]) -> None:
    """
    Open ``port_name`` briefly and send a full note-kill flush
    (sustain off, CC120, CC123, explicit note_off × 128).

    Used when Re-Play abandons a prior thread that did not join in time.
    Clear IAC / Stop uses ``logic_stop_flush_named`` (MMC + MIDI Stop first).
    """
    if not port_name:
        return
    port = None
    try:
        port = mido.open_output(port_name)
        panic_flush(port)
    except Exception:
        pass
    finally:
        if port is not None:
            try:
                port.close()
            except Exception:
                pass


def logic_stop_flush(port) -> None:
    """Stop Logic (MMC Stop + MIDI Stop), then flush hanging notes."""
    try:
        port.send(mmc_sysex(_MMC_STOP))
    except Exception:
        pass
    try:
        port.send(mido.Message("stop"))
    except Exception:
        pass
    panic_flush(port)


def logic_stop_flush_named(port_name: Optional[str]) -> None:
    """
    Open ``port_name`` and stop Logic, then flush the bus.

    Always sends MMC Stop and MIDI Stop so Record/Play drop even when the
    play worker already exited or never owned the port.
    """
    if not port_name:
        return
    port = None
    try:
        port = mido.open_output(port_name)
        logic_stop_flush(port)
    except Exception:
        pass
    finally:
        if port is not None:
            try:
                port.close()
            except Exception:
                pass


def _is_port_loss_error(exc: BaseException) -> bool:
    """
    True when ``exc`` looks like a MIDI port/device/I/O failure.

    Keep needles specific — bare substrings like ``\"midi\"`` or ``\"failed to\"``
    would remap unrelated errors to :data:`PORT_LOST_MESSAGE`.
    """
    text = str(exc).lower()
    needles = (
        "midi port",
        "port closed",
        "port not found",
        "port unavailable",
        "no such port",
        "invalid port",
        "open port",
        "failed to open",
        "device disconnected",
        "device not connected",
        "device unavailable",
        "no such device",
        "not connected",
        "disconnected",
        "rtmidi",
        "i/o error",
        "broken pipe",
    )
    return any(n in text for n in needles)


CLOCKS_PER_QUARTER = 24


def bar_duration_sec(bpm: float, beats_per_bar: int = 4) -> float:
    """Wall-clock seconds for one bar at the given tempo."""
    safe_bpm = max(1.0, float(bpm or 120.0))
    safe_beats = max(1, int(beats_per_bar or 4))
    return (60.0 / safe_bpm) * safe_beats


def clock_period_sec(bpm: float) -> float:
    """Seconds between MIDI clocks (24 per quarter note)."""
    return (60.0 / max(1.0, float(bpm or 120.0))) / CLOCKS_PER_QUARTER


def pass_duration_sec(
    file_duration: float,
    bpm: float,
    *,
    beats_per_bar: int = 4,
    bars: Optional[float] = None,
) -> float:
    """
    Loop / clock length on the beat grid.

    Prefer explicit bar count (sketch length). Otherwise snap file length up
    to the next beat so wrap-around does not drift.
    """
    beat = 60.0 / max(1.0, float(bpm or 120.0))
    raw = max(0.0, float(file_duration or 0.0))
    if bars is not None and float(bars) > 0:
        raw = max(raw, bar_duration_sec(bpm, beats_per_bar) * float(bars))
    if raw <= 0:
        return beat * max(1, int(beats_per_bar or 4))
    return max(beat, math.ceil(raw / beat - 1e-9) * beat)


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
    Background player for one MIDI file → one output port.

    Default: wall-clock at sketch BPM. Optional follow of incoming MIDI
    Start/Clock so notes land on Logic's grid. Safe to call stop() from the
    UI thread. Only one clip plays at a time.
    """

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._port_name: Optional[str] = None
        self._error: Optional[str] = None
        self._playing = False
        self._phase: str = "idle"  # idle | syncing | count_in | playing
        self._looping = False
        self._count_in_bars: float = 0.0
        self._count_in_end: Optional[float] = None  # perf_counter deadline
        self._count_in_bpm: float = 120.0
        self._count_in_beats_per_bar: int = 4
        self._follow = False
        self._session_start: Optional[float] = None
        self._play_bpm: float = 120.0
        self._tpb: int = 480
        self._pass_ticks: int = 1
        self._pass_len: float = 1.0
        self._clock_dt: float = clock_period_sec(120.0)
        self._tick_schedule: List[Tuple[int, mido.Message]] = []
        self._schedule: List[ScheduledMsg] = []
        self._i: int = 0
        self._pass_index: int = 0
        self._next_clock_n: int = 1
        self._tempo_epoch: int = 0

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
        """idle | syncing | count_in | playing — honest UI caption source."""
        with self._lock:
            if not (self._playing and self._thread is not None and self._thread.is_alive()):
                return "idle"
            return self._phase

    @property
    def count_in_bars(self) -> float:
        with self._lock:
            return float(self._count_in_bars)

    @property
    def count_in_remaining_sec(self) -> Optional[float]:
        """Seconds left in count-in, or None when not counting in."""
        with self._lock:
            if self._phase != "count_in" or self._count_in_end is None:
                return None
            alive = (
                self._playing
                and self._thread is not None
                and self._thread.is_alive()
            )
            if not alive:
                return None
            end = self._count_in_end
        return max(0.0, end - time.perf_counter())

    def count_in_remaining_bars_beats(self) -> Optional[Tuple[int, int]]:
        """
        Remaining whole bars and beats in the current count-in (sketch BPM).

        Returns ``(bars, beats)`` from remaining wall time, or None when not
        in count-in. Cleared as soon as Playing starts.
        """
        rem = self.count_in_remaining_sec
        if rem is None:
            return None
        with self._lock:
            bpm = max(1.0, float(self._count_in_bpm or 120.0))
            bpb = max(1, int(self._count_in_beats_per_bar or 4))
        beat_sec = 60.0 / bpm
        rem_beats = int(rem / beat_sec + 1e-9)
        if rem > 0 and rem_beats == 0:
            rem_beats = 1  # sub-beat remainder still counts as a beat left
        bars = rem_beats // bpb
        beats = rem_beats % bpb
        return bars, beats

    def transport_caption(self) -> str:
        """
        Honest UI caption for the active phase.

        Count-in → remaining bar/beat (and seconds) from sketch BPM.
        Playing → plain ``Playing`` (count-in caption cleared).
        Finished / idle captions are owned by the UI after the worker exits.
        """
        phase = self.phase
        if phase == "syncing":
            return "Waiting for Logic Play…"
        if phase == "count_in":
            rem = self.count_in_remaining_sec
            rem_bb = self.count_in_remaining_bars_beats()
            if rem_bb is not None and rem is not None:
                bars_left, beats_left = rem_bb
                return (
                    f"Count-in… {bars_left}:{beats_left} left · {rem:.1f}s"
                )
            if rem is not None:
                return f"Count-in… {rem:.1f}s left"
            return "Count-in…"
        if phase == "playing":
            return "Playing"
        return "Idle"

    def set_bpm(self, bpm: float) -> bool:
        """Retune the playing clock from the current tick. No restart.

        Returns False when idle, locked to Logic, or still in count-in.
        """
        new_bpm = max(40.0, min(240.0, float(bpm)))
        now = time.perf_counter()
        with self._lock:
            if self._phase != "playing" or self._follow:
                return False
            if self._session_start is None or not self._tick_schedule:
                return False
            old = max(1.0, float(self._play_bpm or 120.0))
            if abs(old - new_bpm) < 1e-6:
                return True
            tpb = max(1, int(self._tpb or 480))
            pass_ticks = max(1, int(self._pass_ticks or 1))
            elapsed = max(0.0, now - float(self._session_start))
            ticks_total = elapsed * old / 60.0 * tpb
            elapsed_new = ticks_total * 60.0 / new_bpm / tpb
            looping = bool(self._looping)
            if looping:
                pass_index = int(ticks_total // pass_ticks)
                local_tick = ticks_total - pass_index * pass_ticks
            else:
                pass_index = 0
                local_tick = ticks_total
            self._session_start = now - elapsed_new
            self._play_bpm = new_bpm
            self._count_in_bpm = new_bpm
            self._schedule = seconds_schedule_at_bpm(
                self._tick_schedule, new_bpm, tpb
            )
            self._pass_len = tick_to_seconds(pass_ticks, new_bpm, tpb)
            self._clock_dt = clock_period_sec(new_bpm)
            self._pass_index = pass_index
            self._i = due_index(self._tick_schedule, 0, local_tick)
            self._next_clock_n = int(elapsed_new / self._clock_dt + 1e-9) + 1
            self._tempo_epoch += 1
        return True

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
                self._count_in_end = None
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
        bars: Optional[float] = None,
        loop: bool = True,
        click: bool = False,
        send_clock: bool = False,
        send_mmc: Optional[bool] = None,
        sync: str = "internal",
        on_finished: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Start (or restart) playback of a MIDI file on the given port.

        count_in_bars: silent (default) or click bars before notes — app-side
        only, so Logic Record can already be rolling before the sketch starts.
        bars: sketch length used for loop wrap and clock span (beat-aligned).
        loop: repeat the sketch until Stop (default True; no gap; no panic between passes).
        click: when True, emit a soft metronome note each beat of the count-in
        (same port — will be captured if Logic is recording; off by default).
        send_clock: MIDI Start/Clock/Stop at sketch BPM (Logic as slave).
        send_mmc: MMC Record Strobe before Start so Logic can punch Record
        (default on when send_clock is on). Logic must Listen to MMC Input.
        sync: ``internal`` wall-clock, or ``follow`` wait for Logic MIDI Start
        then chase incoming clock so notes hit Logic's beat.
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

        tick_schedule, last_tick, tpb = midi_file_tick_schedule(str(midi_path))
        if not tick_schedule:
            raise RuntimeError("MIDI file has no playable messages.")

        play_bpm = float(bpm) if bpm and bpm > 0 else midi_file_bpm(str(midi_path))
        follow = str(sync or "internal").lower() == "follow"
        use_clock_out = bool(send_clock) and not follow
        use_mmc = bool(use_clock_out if send_mmc is None else send_mmc) and not follow
        count_bars = 0.0 if follow else max(0.0, float(count_in_bars or 0.0))
        count_in_sec = bar_duration_sec(play_bpm, beats_per_bar) * count_bars
        beat_sec = 60.0 / max(1.0, play_bpm)
        click_beats = int(round(count_bars * max(1, int(beats_per_bar or 4))))
        beat_ticks = max(1, int(tpb))
        pass_ticks = max(1, int(last_tick))
        if bars is not None and float(bars) > 0:
            pass_ticks = max(
                pass_ticks,
                int(round(float(bars) * max(1, int(beats_per_bar or 4)) * beat_ticks)),
            )
        if pass_ticks % beat_ticks:
            pass_ticks = ((pass_ticks + beat_ticks - 1) // beat_ticks) * beat_ticks
        schedule = seconds_schedule_at_bpm(tick_schedule, play_bpm, tpb)
        pass_len = tick_to_seconds(pass_ticks, play_bpm, tpb)
        clock_dt = clock_period_sec(play_bpm)

        with self._lock:
            self._stop.set()
            prior = self._thread
            prior_port = self._port_name

        if prior is not None and prior.is_alive():
            prior.join(timeout=1.5)
            if prior.is_alive():
                # Prior hang / still winding down: panic-flush then abandon so
                # a second Play always restarts cleanly (never stuck Re-Play).
                panic_flush_named(prior_port or target)
                with self._lock:
                    self._playing = False
                    self._phase = "idle"
                    self._looping = False
                    self._count_in_end = None
                    # Drop identity so the abandoned finally does not clobber us.
                    if self._thread is prior:
                        self._thread = None

        with self._lock:
            self._stop = threading.Event()
            self._error = None
            self._port_name = target
            self._playing = True
            self._follow = follow
            self._play_bpm = play_bpm
            self._tpb = tpb
            self._pass_ticks = pass_ticks
            self._pass_len = pass_len
            self._clock_dt = clock_dt
            self._tick_schedule = tick_schedule
            self._schedule = schedule
            self._i = 0
            self._pass_index = 0
            self._next_clock_n = 1
            self._session_start = None
            self._tempo_epoch = 0
            self._phase = (
                "syncing"
                if follow
                else ("count_in" if count_in_sec > 0 else "playing")
            )
            self._looping = bool(loop)
            self._count_in_bars = count_bars if count_in_sec > 0 else 0.0
            self._count_in_end = None
            self._count_in_bpm = play_bpm
            self._count_in_beats_per_bar = max(1, int(beats_per_bar or 4))
            stop_flag = self._stop

        def _wait_until(deadline: float) -> bool:
            """Sleep until deadline; 2ms chunks, spin last ~1ms. True if stop."""
            while True:
                if stop_flag.is_set():
                    return True
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    return stop_flag.is_set()
                if remaining > 0.0015:
                    time.sleep(min(0.002, remaining - 0.001))

        def _send(port, msg: mido.Message) -> None:
            try:
                port.send(msg)
            except Exception as exc:
                if _is_port_loss_error(exc):
                    raise RuntimeError(PORT_LOST_MESSAGE) from exc
                raise

        def _run_count_in(port) -> bool:
            """Return True if stop requested during count-in."""
            if count_in_sec <= 0:
                return False
            start = time.perf_counter()
            with self._lock:
                self._phase = "count_in"
                self._count_in_bars = count_bars
                self._count_in_end = start + count_in_sec
                self._count_in_bpm = play_bpm
                self._count_in_beats_per_bar = max(1, int(beats_per_bar or 4))
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
                        _send(
                            port,
                            mido.Message(
                                "note_on", channel=9, note=note, velocity=70
                            ),
                        )
                        _send(
                            port,
                            mido.Message(
                                "note_off", channel=9, note=note, velocity=0
                            ),
                        )
                    except RuntimeError:
                        raise
                    except Exception:
                        pass
                return _wait_until(start + count_in_sec)
            # click=False: truly silent — wait only, no notes.
            return _wait_until(start + count_in_sec)

        def _wait_play(deadline: float, epoch: int) -> str:
            """stop | due | tempo — abort the wait when set_bpm retunes the clock."""
            while True:
                if stop_flag.is_set():
                    return "stop"
                if self._tempo_epoch != epoch:
                    return "tempo"
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    return "due" if not stop_flag.is_set() else "stop"
                if remaining > 0.0015:
                    time.sleep(min(0.002, remaining - 0.001))

        def _run_timed(port) -> None:
            """Wall-clock notes at sketch BPM. Optional outbound clock as slave master."""
            with self._lock:
                self._phase = "playing"
                self._count_in_end = None
                self._session_start = time.perf_counter()
                self._i = 0
                self._pass_index = 0
                self._next_clock_n = 1
            if use_mmc:
                try:
                    _send(port, mmc_sysex(_MMC_RECORD_STROBE))
                except Exception:
                    pass
            if use_clock_out:
                try:
                    _send(port, mido.Message("songpos", pos=0))
                except Exception:
                    pass
                _send(port, mido.Message("start"))
            # Downbeat is MIDI Start. First clock is 1/24 after, not at t=0.
            while True:
                if stop_flag.is_set():
                    return
                with self._lock:
                    session_start = float(self._session_start or time.perf_counter())
                    pass_len_now = float(self._pass_len)
                    schedule_now = self._schedule
                    clock_dt_now = float(self._clock_dt)
                    pass_index = int(self._pass_index)
                    i = int(self._i)
                    next_clock_n = int(self._next_clock_n)
                    epoch = int(self._tempo_epoch)
                pass_end = (pass_index + 1) * pass_len_now
                note_t: Optional[float] = None
                if i < len(schedule_now):
                    candidate = pass_index * pass_len_now + schedule_now[i][0]
                    if candidate <= pass_end + 1e-9:
                        note_t = candidate
                clock_t = next_clock_n * clock_dt_now
                due: List[float] = [pass_end]
                if note_t is not None:
                    due.append(note_t)
                if use_clock_out and clock_t <= pass_end + 1e-9:
                    due.append(clock_t)
                t = min(due)
                waited = _wait_play(session_start + t, epoch)
                if waited == "stop":
                    return
                if waited == "tempo":
                    continue
                if use_clock_out and abs(clock_t - t) <= 1e-9:
                    elapsed = time.perf_counter() - session_start
                    now_n = int(elapsed / clock_dt_now + 1e-9)
                    if now_n > next_clock_n:
                        with self._lock:
                            if self._tempo_epoch == epoch:
                                self._next_clock_n = now_n
                        continue
                    _send(port, mido.Message("clock"))
                    with self._lock:
                        if self._tempo_epoch == epoch:
                            self._next_clock_n = next_clock_n + 1
                    continue
                if note_t is not None and abs(note_t - t) <= 1e-9:
                    _send(port, schedule_now[i][1])
                    with self._lock:
                        if self._tempo_epoch == epoch:
                            self._i = i + 1
                    continue
                with self._lock:
                    should_loop = self._looping
                    if should_loop and self._tempo_epoch == epoch:
                        self._pass_index = pass_index + 1
                        self._i = 0
                if not should_loop or stop_flag.is_set():
                    return

        def _run_follow(port, sync_in) -> None:
            """Fire notes on Logic MIDI Start, then chase incoming clock."""
            with self._lock:
                self._phase = "syncing"
                self._count_in_end = None
            ticks_per_clock = float(tpb) / float(CLOCKS_PER_QUARTER)
            song_tick = 0.0
            i = 0
            pass_index = 0
            locked = False

            def _flush() -> bool:
                nonlocal i, pass_index
                while True:
                    local = song_tick - pass_index * pass_ticks
                    if local < -1e-9:
                        return False
                    new_i = due_index(tick_schedule, i, local)
                    for k in range(i, new_i):
                        _send(port, tick_schedule[k][1])
                    i = new_i
                    if local + 1e-9 < pass_ticks:
                        return False
                    with self._lock:
                        looping_now = self._looping
                    if not looping_now:
                        return True
                    pass_index += 1
                    i = 0

            while not stop_flag.is_set():
                try:
                    pending = list(sync_in.iter_pending())
                except Exception:
                    pending = []
                if not pending:
                    time.sleep(0.001)
                    continue
                for msg in pending:
                    typ = getattr(msg, "type", "")
                    if typ == "start":
                        song_tick = 0.0
                        i = 0
                        pass_index = 0
                        locked = True
                        with self._lock:
                            self._phase = "playing"
                        if _flush():
                            return
                    elif typ == "continue":
                        locked = True
                        with self._lock:
                            self._phase = "playing"
                        if _flush():
                            return
                    elif typ == "songpos":
                        song_tick = float(
                            spp_to_ticks(int(getattr(msg, "pos", 0) or 0), tpb)
                        )
                        bar_ticks = beat_ticks * max(1, int(beats_per_bar or 4))
                        if bar_ticks and int(round(song_tick)) % bar_ticks == 0:
                            locked = True
                            pass_index = int(song_tick // pass_ticks) if pass_ticks else 0
                            local = song_tick - pass_index * pass_ticks
                            i = due_index(tick_schedule, 0, local)
                            with self._lock:
                                self._phase = "playing"
                            if _flush():
                                return
                    elif typ == "clock":
                        if not locked:
                            continue
                        song_tick += ticks_per_clock
                        if _flush():
                            return
                    elif typ == "stop":
                        if locked:
                            return

        def _run() -> None:
            port = None
            sync_in = None
            sent_start = False
            sent_mmc = False
            try:
                try:
                    port = mido.open_output(target)
                except Exception as exc:
                    # Open failure is always a port problem for the user.
                    raise RuntimeError(PORT_LOST_MESSAGE) from exc
                if follow:
                    try:
                        sync_in = mido.open_input(target)
                    except Exception:
                        sync_in = None
                if follow and sync_in is not None:
                    _run_follow(port, sync_in)
                    return
                if _run_count_in(port):
                    return
                sent_start = bool(use_clock_out)
                sent_mmc = bool(use_mmc)
                _run_timed(port)
            except Exception as exc:
                with self._lock:
                    if isinstance(exc, RuntimeError) and str(exc) == PORT_LOST_MESSAGE:
                        self._error = PORT_LOST_MESSAGE
                    elif _is_port_loss_error(exc):
                        self._error = PORT_LOST_MESSAGE
                    else:
                        self._error = str(exc)
            finally:
                if sync_in is not None:
                    try:
                        sync_in.close()
                    except Exception:
                        pass
                if port is not None:
                    try:
                        if sent_mmc:
                            try:
                                port.send(mmc_sysex(_MMC_STOP))
                            except Exception:
                                pass
                        if sent_start:
                            try:
                                port.send(mido.Message("stop"))
                            except Exception:
                                pass
                        panic_flush(port)
                        port.close()
                    except Exception:
                        pass
                with self._lock:
                    # Only clear if we are still the active worker (Re-Play may
                    # have abandoned this thread and started a new one).
                    if self._thread is thread:
                        self._playing = False
                        self._phase = "idle"
                        self._looping = False
                        self._count_in_end = None
                if on_finished:
                    try:
                        on_finished()
                    except Exception:
                        pass

        thread = threading.Thread(target=_run, name="live-midi-player", daemon=True)
        with self._lock:
            self._thread = thread
        thread.start()

    def stop(
        self,
        wait: bool = True,
        timeout: float = 2.0,
        port_name: Optional[str] = None,
    ) -> None:
        """
        Clear IAC: stop the worker, stop Logic, flush hanging notes.

        Sends MMC Stop + MIDI Stop + note-off even if the worker already
        exited or never started — so a stuck Logic Record/Play still drops.
        """
        with self._lock:
            self._stop.set()
            self._looping = False
            thread = self._thread
            target = port_name or self._port_name
        if wait and thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        logic_stop_flush_named(target)
        with self._lock:
            self._playing = False
            self._phase = "idle"
            self._looping = False
            self._count_in_end = None

    def panic(self, port_name: Optional[str] = None) -> None:
        """Same as stop — one control clears the bus and stops Logic."""
        self.stop(wait=True, port_name=port_name)


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
