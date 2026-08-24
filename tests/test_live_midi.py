"""Tests for live MIDI / IAC playback helpers."""

from __future__ import annotations

import sys
import types
import threading
import time
from pathlib import Path
from unittest.mock import patch

import mido
import pytest

_ROOT = Path(__file__).resolve().parents[1]
if "midi_gen" not in sys.modules:
    _pkg = types.ModuleType("midi_gen")
    _pkg.__path__ = [str(_ROOT)]  # type: ignore[attr-defined]
    _pkg.__file__ = str(_ROOT / "__init__.py")
    sys.modules["midi_gen"] = _pkg

from midi_gen.midi_tempo import tick_to_seconds
from midi_gen.live_midi import (
    PORT_LOST_MESSAGE,
    LiveMidiPlayer,
    _all_notes_off,
    _is_port_loss_error,
    _midi_file_to_schedule,
    bar_duration_sec,
    clock_period_sec,
    has_iac_port,
    midi_file_bpm,
    panic_flush,
    pass_duration_sec,
    port_looks_like_iac,
    preferred_iac_port,
    refresh_output_ports,
    rtmidi_available,
)


class FakeMidiPort:
    """Minimal MIDI output stand-in for panic / CC123 assertions."""

    def __init__(
        self,
        *,
        fail_send: bool = False,
        fail_exc: BaseException | None = None,
    ) -> None:
        self.sent: list[mido.Message] = []
        self.closed = False
        self.fail_send = fail_send
        self.fail_exc = fail_exc or OSError("device disconnected")

    def send(self, msg: mido.Message) -> None:
        if self.fail_send:
            raise self.fail_exc
        self.sent.append(msg)

    def close(self) -> None:
        self.closed = True


class FakeMidiInput:
    """Push MIDI into the follow-clock waiter."""

    def __init__(self) -> None:
        self._q: list[mido.Message] = []
        self._lock = threading.Lock()
        self.closed = False

    def push(self, msg: mido.Message) -> None:
        with self._lock:
            self._q.append(msg)

    def iter_pending(self):
        with self._lock:
            items = list(self._q)
            self._q.clear()
        return iter(items)

    def close(self) -> None:
        self.closed = True


def _write_tiny_midi(path: Path) -> None:
    mid = mido.MidiFile()
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120)))
    track.append(mido.Message("note_on", note=60, velocity=90, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, time=240))
    track.append(mido.Message("note_on", note=64, velocity=80, time=0))
    track.append(mido.Message("note_off", note=64, velocity=0, time=240))
    mid.save(path)


def test_preferred_iac_port_prefers_iac_name():
    assert preferred_iac_port(["USB Midi", "IAC Driver Bus 1", "Other"]) == "IAC Driver Bus 1"
    assert preferred_iac_port(["Foo", "Bar"]) == "Foo"
    assert preferred_iac_port([]) is None


def test_port_looks_like_iac_and_has_iac():
    assert port_looks_like_iac("IAC Driver Bus 1")
    assert port_looks_like_iac("iac driver bus 2")
    assert not port_looks_like_iac("USB Midi")
    assert has_iac_port(["USB Midi", "IAC Driver Bus 1"])
    assert not has_iac_port(["USB Midi", "Network Session"])
    assert not has_iac_port([])


def test_refresh_output_ports_returns_list():
    ports = refresh_output_ports()
    assert isinstance(ports, list)
    status_ports = LiveMidiPlayer().status(refresh=True).ports
    assert isinstance(status_ports, list)


def test_bar_duration_and_midi_bpm(tmp_path):
    assert abs(bar_duration_sec(120, 4) - 2.0) < 1e-9
    assert abs(bar_duration_sec(60, 4) - 4.0) < 1e-9
    assert bar_duration_sec(0, 4) > 0  # guarded floor
    assert abs(clock_period_sec(120) * 24 - 0.5) < 1e-9
    assert abs(pass_duration_sec(0.49, 120, bars=1) - 2.0) < 1e-9
    assert abs(pass_duration_sec(0.4, 120) - 0.5) < 1e-9
    assert abs(tick_to_seconds(480, 120, 480) - 0.5) < 1e-9
    assert abs(tick_to_seconds(240, 120, 480) - 0.25) < 1e-9
    path = tmp_path / "tiny.mid"
    _write_tiny_midi(path)
    assert abs(midi_file_bpm(str(path)) - 120.0) < 0.5


def test_midi_file_schedule_orders_events(tmp_path):
    path = tmp_path / "tiny.mid"
    _write_tiny_midi(path)
    schedule, duration = _midi_file_to_schedule(str(path))
    assert len(schedule) >= 4
    times = [t for t, _ in schedule]
    assert times == sorted(times)
    assert duration >= times[-1]
    assert all(msg.time == 0 for _, msg in schedule)


def test_player_status_reports_backend():
    player = LiveMidiPlayer()
    status = player.status()
    assert status.backend == ("mido+rtmidi" if rtmidi_available() else None)
    assert isinstance(status.ports, list)
    assert status.playing is False
    assert player.phase == "idle"


def test_play_file_missing_raises(tmp_path):
    player = LiveMidiPlayer()
    with pytest.raises(FileNotFoundError):
        player.play_file(str(tmp_path / "nope.mid"), port_name="missing")


def test_all_notes_off_sends_cc123_on_fake_port():
    """Hard Stop flush: sustain off, CC120/123, pitch reset, explicit note_off."""
    port = FakeMidiPort()
    panic_flush(port)
    cc123 = [
        m
        for m in port.sent
        if m.type == "control_change" and m.control == 123
    ]
    cc120 = [
        m
        for m in port.sent
        if m.type == "control_change" and m.control == 120
    ]
    sustain = [
        m
        for m in port.sent
        if m.type == "control_change" and m.control == 64
    ]
    bends = [m for m in port.sent if m.type == "pitchwheel"]
    offs = [m for m in port.sent if m.type == "note_off"]
    assert len(cc123) == 16, "panic flush must send CC123 on every channel"
    assert len(cc120) == 16
    assert len(sustain) == 16
    assert all(m.value == 0 for m in cc123 + cc120 + sustain)
    assert {m.channel for m in cc123} == set(range(16))
    assert len(bends) == 16
    assert all(m.pitch == 0 for m in bends)
    assert len(offs) == 128 * 16
    assert {(m.channel, m.note) for m in offs} == {
        (ch, n) for ch in range(16) for n in range(128)
    }


def test_all_notes_off_alias_matches_panic():
    port_a, port_b = FakeMidiPort(), FakeMidiPort()
    _all_notes_off(port_a)
    panic_flush(port_b)
    assert [
        (m.type, getattr(m, "control", None), getattr(m, "channel", None))
        for m in port_a.sent
    ] == [
        (m.type, getattr(m, "control", None), getattr(m, "channel", None))
        for m in port_b.sent
    ]


def test_stop_panic_flush_sends_cc123_on_fake_port(tmp_path):
    """Stop() must deliver CC123 all-notes-off via named-port panic flush."""
    fake = FakeMidiPort()
    opened: list[str] = []

    def _open(name: str):
        opened.append(name)
        return fake

    player = LiveMidiPlayer()
    path = tmp_path / "tiny.mid"
    _write_tiny_midi(path)

    with patch("midi_gen.live_midi.list_output_ports", return_value=["Fake Bus"]), patch(
        "midi_gen.live_midi.rtmidi_available", return_value=True
    ), patch("midi_gen.live_midi.mido.open_output", side_effect=_open):
        player.play_file(str(path), "Fake Bus", count_in_bars=0, loop=False)
        deadline = time.time() + 1.0
        while not player.playing and time.time() < deadline:
            time.sleep(0.01)
        player.stop(wait=True)

    assert not player.playing
    assert player.phase == "idle"
    assert "Fake Bus" in opened
    # Worker finally and/or Stop's panic_flush_named both send CC123 — at least one full set.
    cc123 = [m for m in fake.sent if m.type == "control_change" and m.control == 123]
    assert len(cc123) >= 16
    assert all(m.control == 123 and m.value == 0 for m in cc123)
    assert set(range(16)).issubset({m.channel for m in cc123})
    offs = [m for m in fake.sent if m.type == "note_off"]
    assert len(offs) >= 128 * 16


def test_panic_flush_named_sends_cc123_on_fake_port():
    """Named-port Hard Stop path: open → CC123×16 → close (isolated unit)."""
    fake = FakeMidiPort()

    with patch("midi_gen.live_midi.mido.open_output", return_value=fake) as opener:
        from midi_gen.live_midi import panic_flush_named

        panic_flush_named("Fake Bus")
        opener.assert_called_once_with("Fake Bus")

    cc123 = [m for m in fake.sent if m.type == "control_change" and m.control == 123]
    assert len(cc123) == 16
    assert all(m.value == 0 for m in cc123)
    assert {m.channel for m in cc123} == set(range(16))
    offs = [m for m in fake.sent if m.type == "note_off"]
    assert len(offs) == 128 * 16
    assert fake.closed is True


def test_is_port_loss_error_prefers_specific_signals():
    """Bare 'midi' / 'failed to' must not remap; real port/device loss still matches."""
    # Real port / device / I/O failure signals → True
    assert _is_port_loss_error(OSError("device disconnected"))
    assert _is_port_loss_error(RuntimeError("MIDI port closed"))
    assert _is_port_loss_error(OSError("rtmidi: failed to open port"))
    assert _is_port_loss_error(OSError("no such device"))
    assert _is_port_loss_error(BrokenPipeError("broken pipe"))
    # Unrelated / too-generic wording → False (keep real message)
    assert not _is_port_loss_error(ValueError("bad velocity"))
    assert not _is_port_loss_error(RuntimeError("failed to parse sketch"))
    assert not _is_port_loss_error(RuntimeError("unexpected midi encoding"))
    assert not _is_port_loss_error(Exception("midi"))
    assert not _is_port_loss_error(Exception("failed to"))
    assert not _is_port_loss_error(Exception("invalid argument"))
    assert not _is_port_loss_error(Exception("port"))  # bare "port" alone


def test_send_fail_clears_playing_and_sets_port_lost(tmp_path):
    """Mid-play send failure must clear Playing and surface port-lost message."""
    fail_port = FakeMidiPort(fail_send=True)

    player = LiveMidiPlayer()
    path = tmp_path / "tiny.mid"
    _write_tiny_midi(path)

    with patch("midi_gen.live_midi.list_output_ports", return_value=["Fake Bus"]), patch(
        "midi_gen.live_midi.rtmidi_available", return_value=True
    ), patch("midi_gen.live_midi.mido.open_output", return_value=fail_port), patch(
        "midi_gen.live_midi.panic_flush_named"
    ):
        player.play_file(str(path), "Fake Bus", count_in_bars=0, loop=False)
        deadline = time.time() + 2.0
        while player.playing and time.time() < deadline:
            time.sleep(0.02)
        # Worker should have exited with the honest error.
        assert not player.playing
        assert player.last_error == PORT_LOST_MESSAGE
        assert player.status().playing is False


def test_non_port_send_error_keeps_real_message(tmp_path):
    """Send failures that are not port-loss keep their real message (not remapped)."""
    fail_port = FakeMidiPort(
        fail_send=True, fail_exc=ValueError("unexpected midi encoding")
    )
    player = LiveMidiPlayer()
    path = tmp_path / "tiny.mid"
    _write_tiny_midi(path)

    with patch("midi_gen.live_midi.list_output_ports", return_value=["Fake Bus"]), patch(
        "midi_gen.live_midi.rtmidi_available", return_value=True
    ), patch("midi_gen.live_midi.mido.open_output", return_value=fail_port), patch(
        "midi_gen.live_midi.panic_flush_named"
    ):
        player.play_file(str(path), "Fake Bus", count_in_bars=0, loop=False)
        deadline = time.time() + 2.0
        while player.playing and time.time() < deadline:
            time.sleep(0.02)

    assert not player.playing
    assert player.last_error == "unexpected midi encoding"
    assert player.last_error != PORT_LOST_MESSAGE


def test_silent_count_in_sends_no_notes(tmp_path):
    """click=False count-in must emit no note_on/note_off (truly silent bar)."""
    fake = FakeMidiPort()
    player = LiveMidiPlayer()
    path = tmp_path / "tiny.mid"
    _write_tiny_midi(path)

    with patch("midi_gen.live_midi.list_output_ports", return_value=["Fake Bus"]), patch(
        "midi_gen.live_midi.rtmidi_available", return_value=True
    ), patch("midi_gen.live_midi.mido.open_output", return_value=fake), patch(
        "midi_gen.live_midi.panic_flush_named"
    ):
        # Long count-in so we can sample the silent window before notes start.
        player.play_file(
            str(path),
            "Fake Bus",
            count_in_bars=8,
            bpm=60,
            loop=False,
            click=False,
        )
        deadline = time.time() + 1.0
        while player.phase != "count_in" and time.time() < deadline:
            time.sleep(0.01)
        assert player.phase == "count_in"
        time.sleep(0.2)
        assert player.phase == "count_in"
        notes = [m for m in fake.sent if m.type in ("note_on", "note_off")]
        assert notes == [], f"silent count-in leaked notes: {notes}"
        player.stop(wait=True)

    assert not player.playing
    assert player.phase == "idle"


def test_stop_mid_sustain_emits_note_off_for_sounding_pitch(tmp_path):
    """Stop during a long drone note must send that pitch's note_off (Logic ignores CC123)."""
    mid = mido.MidiFile()
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(60)))
    track.append(mido.Message("note_on", note=60, velocity=90, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, time=480 * 16))
    path = tmp_path / "drone.mid"
    mid.save(path)

    fake = FakeMidiPort()
    player = LiveMidiPlayer()
    with patch("midi_gen.live_midi.list_output_ports", return_value=["Fake Bus"]), patch(
        "midi_gen.live_midi.rtmidi_available", return_value=True
    ), patch("midi_gen.live_midi.mido.open_output", return_value=fake):
        player.play_file(str(path), "Fake Bus", count_in_bars=0, loop=False)
        deadline = time.time() + 1.0
        while time.time() < deadline:
            if any(m.type == "note_on" and m.note == 60 for m in fake.sent):
                break
            time.sleep(0.01)
        assert any(m.type == "note_on" and m.note == 60 for m in fake.sent)
        player.stop(wait=True)

    assert not player.playing
    offs = [m for m in fake.sent if m.type == "note_off" and m.note == 60]
    assert offs, "Stop must note_off the hanging pitch, not only CC123"


def test_replay_after_hung_prior_thread(tmp_path):
    """If a prior play thread will not join, panic-flush and restart cleanly."""
    path = tmp_path / "tiny.mid"
    _write_tiny_midi(path)
    player = LiveMidiPlayer()
    fake = FakeMidiPort()
    panic_calls: list[str] = []

    # Simulate a stuck prior worker that ignores the stop flag.
    stuck = threading.Event()

    def _hang_forever() -> None:
        stuck.wait(timeout=30)

    hung = threading.Thread(target=_hang_forever, name="hung-prior", daemon=True)
    with player._lock:
        player._thread = hung
        player._playing = True
        player._phase = "playing"
        player._port_name = "Fake Bus"
        player._stop = threading.Event()
    hung.start()

    with patch("midi_gen.live_midi.list_output_ports", return_value=["Fake Bus"]), patch(
        "midi_gen.live_midi.rtmidi_available", return_value=True
    ), patch("midi_gen.live_midi.mido.open_output", return_value=fake), patch(
        "midi_gen.live_midi.panic_flush_named",
        side_effect=lambda name: panic_calls.append(name or ""),
    ):
        # join timeout is 1.5s inside play_file — keep test honest but bounded.
        player.play_file(str(path), "Fake Bus", count_in_bars=0, loop=False)

    assert "Fake Bus" in panic_calls
    # New play should be allowed (playing or finished without raise).
    deadline = time.time() + 2.0
    while player.playing and time.time() < deadline:
        time.sleep(0.02)
    assert player.phase == "idle"
    stuck.set()


def test_stop_clears_playing_flag(tmp_path):
    """Stop(wait=True) must clear Playing so the UI never sticks."""
    player = LiveMidiPlayer()
    status = player.status()
    if not status.available:
        pytest.skip(status.error or "no MIDI ports")

    path = tmp_path / "tiny.mid"
    _write_tiny_midi(path)
    port = preferred_iac_port(status.ports) or status.ports[0]
    player.play_file(str(path), port)
    assert player.playing
    player.stop(wait=True)
    assert not player.playing
    assert player.status().playing is False
    assert player.phase == "idle"


def test_count_in_phase_then_stop(tmp_path):
    """Count-in starts in count_in phase; Stop clears honestly."""
    player = LiveMidiPlayer()
    status = player.status()
    if not status.available:
        pytest.skip(status.error or "no MIDI ports")

    path = tmp_path / "tiny.mid"
    _write_tiny_midi(path)
    port = preferred_iac_port(status.ports) or status.ports[0]
    # Long count-in so we can observe the phase before notes.
    player.play_file(str(path), port, count_in_bars=8, bpm=60, loop=False)
    time.sleep(0.05)
    assert player.playing
    assert player.phase == "count_in"
    player.stop(wait=True)
    assert not player.playing
    assert player.phase == "idle"
    assert player.status().playing is False


def test_loop_until_stop(tmp_path):
    """Loop keeps Playing until Stop; natural end does not apply."""
    player = LiveMidiPlayer()
    status = player.status()
    if not status.available:
        pytest.skip(status.error or "no MIDI ports")

    path = tmp_path / "tiny.mid"
    _write_tiny_midi(path)
    port = preferred_iac_port(status.ports) or status.ports[0]
    player.play_file(str(path), port, count_in_bars=0, loop=True)
    time.sleep(0.15)
    assert player.playing
    assert player.looping
    player.stop(wait=True)
    assert not player.playing
    assert not player.looping
    assert player.phase == "idle"


def test_play_and_stop_with_virtual_port(tmp_path):
    """
    If the environment has no MIDI outs, skip.
    On Mac with IAC (or any virtual port), smoke-test start/stop.
    """
    player = LiveMidiPlayer()
    status = player.status()
    if not status.available:
        pytest.skip(status.error or "no MIDI ports")

    path = tmp_path / "tiny.mid"
    _write_tiny_midi(path)
    port = preferred_iac_port(status.ports) or status.ports[0]
    player.play_file(str(path), port)
    assert player.playing
    time.sleep(0.05)
    player.stop(wait=True)
    assert not player.playing


def test_ui_count_in_default_is_false():
    """Instant audition: live_count_in session default must be False (opt-in)."""
    src = (_ROOT / "ui_app.py").read_text(encoding="utf-8")
    assert 'st.session_state["live_count_in"] = False' in src or (
        'bool(prefs.get("live_count_in", False))' in src
    )
    # Must not hard-default count-in On.
    assert 'st.session_state["live_count_in"] = True' not in src


def test_ui_crisp_audit_extras_a_through_e():
    """Source-level guards for transport freeze, Generate stop, count-in honesty."""
    src = (_ROOT / "ui_app.py").read_text(encoding="utf-8")
    # A — freeze transport chrome while playing
    assert "disabled=_transport_busy" in src
    assert '_transport_busy = bool(player.playing)' in src
    # B — Refresh must not clobber Streaming mid-play
    assert "if _force_refresh and player.playing" in src
    assert "def _apply_refresh_ports" in src
    assert "if player.playing:" in src
    # C — Stop before Generate writes new MIDI
    assert "player.stop(wait=True)" in src
    assert src.index("player.stop(wait=True)") < src.index("generate_midi_for_style(")
    # D — Logic lock (follow MIDI Start); denser opts collapsed
    assert "Lock to Logic clock" in src
    assert "waiting for Logic Play" in src
    assert 'key="live_sync_logic"' in src
    assert "not synced to Logic" not in src
    assert "Sketch tempo" in src
    assert "Count-in (1 silent bar)" in src
    assert 'st.session_state.get("live_soft_click", False)' in src
    assert "Soft click during count-in" in src
    assert "click MIDI will be captured if Logic is recording" in src
    assert 'st.expander("Before Record / Capture"' in src
    # Soft click defaults Off — never force click=True as the literal play default.
    assert 'st.session_state["live_soft_click"] = True' not in src
    # E — last_error → live_message; keep Stop when was_playing / failed Play
    assert 'st.session_state["live_message"] = err' in src
    assert 'st.session_state["live_was_playing"] = bool(player.playing)' in src
    # Natural end always sets Finished (no Streaming-prefix requirement).
    assert 'st.session_state["live_message"] = "Finished."' in src
    assert 'msg.startswith("Streaming")' not in src
    # Sample Musician bar — Play hero; compact Panic; caption-only countdown; prefs
    assert 'key="panic_logic"' in src
    assert '"Panic"' in src
    assert "All notes off (CC123)" in src
    assert "player.panic(" in src
    assert "transport_caption()" in src
    assert "_persist_live_prefs" in src
    assert "st.columns([4, 1, 1])" in src  # Play dominates Stop/Panic


def test_player_panic_flushes_cc123_without_stopping(tmp_path):
    """Panic() must CC123-flush via named port and leave playback running."""
    fake = FakeMidiPort()
    player = LiveMidiPlayer()
    path = tmp_path / "tiny.mid"
    _write_tiny_midi(path)
    hang = threading.Event()

    class SlowPort(FakeMidiPort):
        def send(self, msg: mido.Message) -> None:
            # Stall first note so Panic can fire mid-play.
            if msg.type == "note_on" and not hang.is_set():
                hang.wait(timeout=2.0)
            super().send(msg)

    slow = SlowPort()
    opened: list[str] = []

    def _open(name: str):
        opened.append(name)
        # First open = play worker; later opens = panic_flush_named.
        if opened.count(name) == 1:
            return slow
        return fake

    with patch("midi_gen.live_midi.list_output_ports", return_value=["Fake Bus"]), patch(
        "midi_gen.live_midi.rtmidi_available", return_value=True
    ), patch("midi_gen.live_midi.mido.open_output", side_effect=_open):
        player.play_file(str(path), "Fake Bus", count_in_bars=0, loop=False)
        deadline = time.time() + 1.0
        while not player.playing and time.time() < deadline:
            time.sleep(0.01)
        assert player.playing
        player.panic("Fake Bus")
        # Panic must not clear Playing (Stop does that).
        assert player.playing
        hang.set()
        player.stop(wait=True)

    cc123 = [m for m in fake.sent if m.type == "control_change" and m.control == 123]
    # Panic alone sends 16; Stop afterward may add another set via the same open path.
    assert len(cc123) >= 16
    assert set(range(16)).issubset({m.channel for m in cc123})
    offs = [m for m in fake.sent if m.type == "note_off"]
    assert len(offs) >= 128 * 16


def test_transport_caption_count_in(tmp_path):
    """Count-in shows remaining bar:beat + seconds; clears to Playing/Idle."""
    fake = FakeMidiPort()
    player = LiveMidiPlayer()
    path = tmp_path / "tiny.mid"
    _write_tiny_midi(path)

    with patch("midi_gen.live_midi.list_output_ports", return_value=["Fake Bus"]), patch(
        "midi_gen.live_midi.rtmidi_available", return_value=True
    ), patch("midi_gen.live_midi.mido.open_output", return_value=fake), patch(
        "midi_gen.live_midi.panic_flush_named"
    ):
        # 2 bars @ 60 BPM 4/4 = 8s; remaining should show bars:beats from sketch BPM.
        player.play_file(
            str(path),
            "Fake Bus",
            count_in_bars=2,
            bpm=60,
            beats_per_bar=4,
            loop=False,
            click=False,
        )
        deadline = time.time() + 1.0
        while player.phase != "count_in" and time.time() < deadline:
            time.sleep(0.01)
        assert player.phase == "count_in"
        caption = player.transport_caption()
        assert caption.startswith("Count-in…")
        assert "left" in caption
        assert "s" in caption
        rem_bb = player.count_in_remaining_bars_beats()
        assert rem_bb is not None
        bars_left, beats_left = rem_bb
        assert bars_left >= 1  # early in a 2-bar count-in
        assert 0 <= beats_left < 4
        # Playing caption must clear count-in wording.
        with player._lock:
            player._phase = "playing"
            player._count_in_end = None
        assert player.transport_caption() == "Playing"
        player.stop(wait=True)

    assert player.transport_caption() == "Idle"
    assert player.count_in_remaining_bars_beats() is None


def test_soft_click_count_in_emits_notes(tmp_path):
    """click=True count-in emits note_on/off; click=False stays silent (locked)."""
    fake = FakeMidiPort()
    player = LiveMidiPlayer()
    path = tmp_path / "tiny.mid"
    _write_tiny_midi(path)

    with patch("midi_gen.live_midi.list_output_ports", return_value=["Fake Bus"]), patch(
        "midi_gen.live_midi.rtmidi_available", return_value=True
    ), patch("midi_gen.live_midi.mido.open_output", return_value=fake), patch(
        "midi_gen.live_midi.panic_flush_named"
    ):
        player.play_file(
            str(path),
            "Fake Bus",
            count_in_bars=1,
            bpm=240,  # fast so clicks arrive quickly
            loop=False,
            click=True,
        )
        deadline = time.time() + 2.0
        while player.playing and time.time() < deadline:
            notes = [m for m in fake.sent if m.type in ("note_on", "note_off")]
            if notes:
                break
            time.sleep(0.02)
        player.stop(wait=True)

    click_notes = [
        m for m in fake.sent if m.type in ("note_on", "note_off") and m.channel == 9
    ]
    assert click_notes, "soft click count-in should emit ch9 metronome notes"


def test_play_sends_midi_start_clock_stop(tmp_path):
    """Playback emits MIDI Start/Clock/Stop at sketch BPM."""
    fake = FakeMidiPort()
    player = LiveMidiPlayer()
    path = tmp_path / "tiny.mid"
    _write_tiny_midi(path)

    with patch("midi_gen.live_midi.list_output_ports", return_value=["Fake Bus"]), patch(
        "midi_gen.live_midi.rtmidi_available", return_value=True
    ), patch("midi_gen.live_midi.mido.open_output", return_value=fake), patch(
        "midi_gen.live_midi.panic_flush_named"
    ):
        player.play_file(
            str(path),
            "Fake Bus",
            count_in_bars=0,
            bpm=120,
            bars=1,
            loop=False,
            send_clock=True,
            sync="internal",
        )
        deadline = time.time() + 2.0
        while player.playing and time.time() < deadline:
            if any(m.type == "clock" for m in fake.sent) and any(
                m.type == "note_on" for m in fake.sent
            ):
                break
            time.sleep(0.02)
        player.stop(wait=True)

    types = [m.type for m in fake.sent]
    assert "start" in types
    assert "clock" in types
    assert "stop" in types
    assert types.index("start") < types.index("clock")
    assert types.index("note_on") < types.index("clock")


def test_follow_logic_start_fires_downbeat_notes(tmp_path):
    """Notes wait for MIDI Start, then fire on tick 0 (Logic downbeat)."""
    fake_out = FakeMidiPort()
    fake_in = FakeMidiInput()
    player = LiveMidiPlayer()
    path = tmp_path / "tiny.mid"
    _write_tiny_midi(path)

    with patch("midi_gen.live_midi.list_output_ports", return_value=["Fake Bus"]), patch(
        "midi_gen.live_midi.rtmidi_available", return_value=True
    ), patch("midi_gen.live_midi.mido.open_output", return_value=fake_out), patch(
        "midi_gen.live_midi.mido.open_input", return_value=fake_in
    ), patch("midi_gen.live_midi.panic_flush_named"):
        player.play_file(
            str(path),
            "Fake Bus",
            count_in_bars=0,
            bpm=120,
            bars=1,
            loop=False,
            sync="follow",
            send_clock=False,
        )
        deadline = time.time() + 1.0
        while player.phase != "syncing" and time.time() < deadline:
            time.sleep(0.01)
        assert player.phase == "syncing"
        assert player.transport_caption() == "Waiting for Logic Play…"
        time.sleep(0.05)
        assert not any(m.type == "note_on" for m in fake_out.sent)
        fake_in.push(mido.Message("start"))
        deadline = time.time() + 1.0
        while time.time() < deadline:
            if any(m.type == "note_on" and m.note == 60 for m in fake_out.sent):
                break
            time.sleep(0.01)
        player.stop(wait=True)

    assert any(m.type == "note_on" and m.note == 60 for m in fake_out.sent)
    assert not any(m.type == "clock" for m in fake_out.sent)


def test_scheduler_has_no_loop_gap_and_tight_wait():
    src = (_ROOT / "live_midi.py").read_text(encoding="utf-8")
    assert "time.sleep(min(0.002, remaining - 0.001))" in src
    assert "time.sleep(min(0.01" not in src
    assert "time.perf_counter() + 0.05" not in src
    assert 'mido.Message("clock")' in src
    assert 'mido.Message("start")' in src
    assert "panic_flush(port)" in src
    # Loop must not panic between passes (that stall desyncs the grid).
    assert "no gap; no panic between passes" in src
