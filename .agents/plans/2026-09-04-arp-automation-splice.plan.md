---
kind: feature-plan
plan: 2026-09-04-arp-automation-splice
status: ready
created: 2026-09-04
source: /create-feature
---

# Arp automation splice

## Goal
Play / Record arp knobs and the step grid keep notes before the current bar, write only the rest via `write_note_events`, and keep Playing from that bar without `generate_midi_for_style` or `pending_replay`.

## Context
- Target: Streamlit MIDI Style Lab (`ui_app.py` as `PYTHONPATH=. streamlit run ui_app.py`). Package root is the repo root.
- `_apply_arp_live` (`ui_app.py` ~499) sets `_live_param_tweak` + `auto_generate` + `pending_replay`. The generate block (~2306) then calls `generate_midi_for_style` → `create_arp` → `create_midi_file` / `EffectRegistry`, overwrites `last_run["path"]`, and `_replay_into_logic` restarts `play_file` from tick 0.
- Piano-roll edits already mutate in place: `_commit_note_edits` → `refresh_last_run_after_note_write` → `write_note_events` (`note_edit.py`). That path skips `EffectRegistry` and does not set `auto_generate`.
- `create_arp` (`arpeggio_generation.py` ~243–473) builds a 16th-note `final_event_list` per bar (`create_arpeggio` + mutate + `apply_arp_step_mask` + `_expand_cell_to_grid`) then writes a file. The bar loop does not use `active_effects`.
- `midi.py` `MidiProcessor.process_events` turns that list into note_on/off at `ticks_per_beat//4 * steps_per_note` (velocity 64) then runs effects. `DEFAULT_TICKS_PER_BEAT` is 480 (`midi_types.py`).
- `LiveMidiPlayer.play_file` (`live_midi.py` ~457) snapshots a tick/seconds schedule into `_run_timed` / `_run_follow` closures. `i`, `schedule`, `tick_schedule`, `pass_index`, `session_start`, and `song_tick` are locals. There is no `current_tick` and no schedule replace. `pending_replay` is the only live-rewrite path.
- `due_index` (`midi_tempo.py` ~116) is the first schedule index with tick `> tick`.
- Why: knob motion is a take, not a new generate.

## Rationale
Direction / Steps / Evolve / Lock change the cell, so they cannot be CC or in-place pitch math. Freeze notes with `start_tick < from_tick`, expand a full take from current knobs, keep the new tail. `write_note_events` already writes that shape. The player must expose a bar-snapped playhead and swap the remaining schedule on the worker thread — UI-thread `port.send` is not safe on rtmidi, and `play_file` restart jumps to bar 1. Idle (no playhead) uses `from_tick=0`: whole file is redrawn dry, still without artist gate / `create_arp` / effects. Effect sliders stay on `auto_generate`.

## Decisions
- Chose **splice at bar-snapped playhead** over **full `create_arp` rewrite** because the request is “do not rewrite the whole file.”
- Chose **`expand_arp_notes` = full take + drop head in `splice_from_tick`** over **expand-from-bar-only** because the existing bar loop + seed + mutate is defined from bar 0; slicing notes is the same output for the tail and keeps `create_arp` tests stable.
- Chose **extract `_build_arp_event_list` from `create_arp`** over **calling `create_arp` then `list_note_events`** because `create_arp` always runs `EffectRegistry` and writes a new file.
- Chose **dry tail (velocity 64, grid ticks, no `EffectRegistry`)** over **re-effecting the tail** because effects are file-wide and out of this surface. Audible seam at the splice bar is accepted.
- Chose **reseed via new knobs from bar 0 (emit tail only)** over **snapshot `arp_cell` and continue mutate** because `create_arp` does not persist the cell; a snapshot is a second product.
- Chose **automation list as audit** (`last_run["arp_automation"]`) over **re-render from all breakpoints** because v1 apply is “current knobs from this bar forward.”
- Chose **`current_tick()` from player clock** over **Streamlit guessing elapsed** because follow mode already has `song_tick` and internal mode already has `session_start`.
- Chose **bar snap** `from_tick = (tick // (tpb*4)) * (tpb*4)` over **exact tick** because the expander is bar-grid; mid-bar splice would split a slot.
- Chose **clip notes that cross `from_tick`** over **keeping full duration** because an overlapping head note fights the new tail.
- Chose **worker-thread pending swap** (`replace_schedule` sets `_pending_path`; `_run_timed` / `_run_follow` apply it) over **UI-thread `port.send`** because rtmidi send is not thread-safe.
- Chose **promote `schedule`, `tick_schedule`, `i`, `pass_index`, `session_start`, `song_tick`, `play_bpm`, `tpb`, `pass_ticks` to instance fields** over **rewriting a live clock engine** because Play already streams a file.
- Chose **note_off vanished sounding pitches only** over **`panic_flush` on swap** because a full panic clicks the bus and restarts the feel.
- Chose **keep original `pass_ticks` / `pass_len` on swap** over **recomputing from the new file** because loop length is `options["bars"]`, not last note-off.
- Chose **idle `from_tick=0`** over **deferring until Play** because stopped knobs must still update Preview WAV / Geek roll.
- Chose **not setting `auto_generate` / `_live_param_tweak` / `pending_replay` in `_apply_arp_live`** over **keeping replay** because replay is a start-from-zero.
- Chose **do not re-export from `__init__.py`** because that module only re-exports generate/lookup/arp helpers; import `from midi_gen.arpeggio_generation import expand_arp_notes` and `from midi_gen.note_edit import splice_from_tick`.
- Rejected **live clock engine (emit next step, no file)** because WAV preview, Geek roll, and `play_file` all consume a path.
- Rejected **MIDI CC automation lanes** because `arp_mode` / `arp_steps` / evolve are sequence changes, not CC.
- Rejected **in-place transpose / rest-only** because Direction / Steps / Evolve / Lock rebuild the cell.
- Rejected **keep `auto_generate` and skip the artist gate** because that still rewrites every bar and re-runs effects.
- Rejected **`generated_path` file copy for undo** because `generated_notes` + Reset already restore the generate snapshot.
- Rejected **hot-swapping by calling `play_file` again** because `play_file` joins the worker, panics, and MIDI Starts at 0.
- Rejected **changing effect sliders to splice** because wow / flutter / humanize are not bar-local.
- Rejected **mid-take BPM** because the player clock is fixed at `play_file` and `write_note_events` writes one `set_tempo`.
- Rejected **adding `arp_automation` to `LOOKUP_STICKY_OVERRIDE_KEYS`** because Generate is a fresh sketch.

## Preconditions
- [ ] Local Streamlit via `./run_ui.sh` (sources `.env`).
- [ ] IAC + Logic only needed to verify `replace_schedule` while Playing; WAV preview is enough for idle splice.
- [ ] Branch has live note editor + arp knobs (`_apply_arp_live`, `note_edit.py`, `note_editor/`).
- [ ] `pytest` in the project venv; `PYTHONPATH=.`.

## Steps
### 0. Load plan into context
- **File**: `N/A`
- **Change**: Read this plan's frontmatter, Goal, Context, Rationale, Decisions, Risks, and Out of scope. Do not start Step 1 until all are loaded.
- **Verify**: Restate the Goal in one sentence and list the rejected alternatives from `## Decisions` before proceeding.

### 1. Extract event-list build + expand_arp_notes
- **File**: `arpeggio_generation.py`
- **Change**: Move the arpeggio block that sets `steps_per_note` / `repeats_per_bar` and fills `final_event_list` (`create_arp` from `if generation_type == 'arpeggio':` at the 16th-grid section through the pad-to-`bars * 16` block, currently ~320–473) into `def _build_arp_event_list(options: Dict) -> List[Optional[int]]:`. That function mutates `options["steps_per_note"]` the same way `create_arp` does today. `create_arp` calls it after building `active_effects` and before `create_midi_file`. Add `def events_to_notes(event_list, *, steps_per_note: int, ticks_per_beat: int = 480) -> list:` that mirrors `MidiProcessor.process_events` arpeggio duration math and does **not** call `EffectRegistry` / `create_note_context`: `sixteenth = ticks_per_beat // 4`, `duration = sixteenth * max(1, steps_per_note)`, walk the list in `slot_steps` jumps, skip `None` and `<= 0`, append `{start_tick, duration_tick, note, velocity: 64, channel: 0}`. Add `def expand_arp_notes(options: Dict) -> list:` that `opts = apply_timing_factor(dict(options))`, returns `[]` if `opts.get("generation_type", "arpeggio") != "arpeggio"`, else `_build_arp_event_list(opts)` then `events_to_notes(..., steps_per_note=int(opts.get("steps_per_note") or 1), ticks_per_beat=int(opts.get("ticks_per_beat") or 480))`. Do not write a file. Do not import `EffectRegistry` in these helpers.
- **Verify**: `pytest tests/test_arp_gates.py tests/test_next_bucket.py tests/test_style_lab.py tests/test_bug_sweep.py tests/test_timing_and_generation_mode.py -q` exits 0. New `tests/test_arp_expand.py`: (1) `expand_arp_notes` on the `test_create_arp_gates_even_rests` options (no `filename` required) yields the same start ticks as `list_note_events(create_arp(...))` when `effects_config=[]`; (2) `events_to_notes([60, None], steps_per_note=2, ticks_per_beat=480)` → one note `{start_tick: 0, duration_tick: 240, note: 60, velocity: 64, channel: 0}`.

### 2. Splice helper
- **File**: `note_edit.py`
- **Change**: Add `def splice_from_tick(kept: list, replacement: list, from_tick: int) -> list:`. `from_tick = max(0, int(from_tick))`. For each note in `kept` with `start_tick < from_tick`, copy the dict; if `start_tick + duration_tick > from_tick`, set `duration_tick = max(1, from_tick - start_tick)`. Append every note in `replacement` with `start_tick >= from_tick` (copy dicts). Do not reassign `id` here (callers that write via `write_note_events` ignore `id`; `list_note_events` re-ids on read).
- **Verify**: `tests/test_note_edit.py::test_splice_from_tick_keeps_head_clips_and_replaces_tail`: kept = note A `start=0 duration=2400 note=60`, note B `start=1920 duration=480 note=64`; replacement = note C `start=1920 duration=480 note=72`; `from_tick=1920` → A clipped to `duration_tick=1920`, no B, C present. Empty kept + replacement from 0 → replacement only.

### 3. Playhead on LiveMidiPlayer
- **File**: `live_midi.py`
- **Change**: On `play_file`, after computing `play_bpm`, `tpb`, `pass_ticks`, `schedule`, `tick_schedule`, store instance fields under `_lock`: `_play_bpm`, `_tpb`, `_pass_ticks`, `_pass_len`, `_tick_schedule`, `_schedule`, `_i = 0`, `_pass_index = 0`, `_session_start = None`, `_song_tick = 0.0`, `_follow = follow`, `_pending_path = None`. In `_run_timed`, set `_session_start = session_start` when entering the play loop (same `perf_counter` as today). In `_run_follow`, write `_song_tick = song_tick` whenever `song_tick` changes. Change the timed/follow loops to read/write `self._schedule` / `self._tick_schedule` / `self._i` / `self._pass_index` (not closure locals). Add `def current_tick(self) -> Optional[int]:` — return `None` unless `_phase == "playing"`; if `_follow`, return `int(self._song_tick) % max(1, self._pass_ticks)`; else if `_session_start is None`, return `None`; else `elapsed = time.perf_counter() - self._session_start`, `ticks = elapsed * self._play_bpm / 60.0 * self._tpb`, return `int(ticks) % max(1, self._pass_ticks)`. Count-in and syncing return `None`.
- **Verify**: `tests/test_live_midi.py::test_current_tick_two_seconds_at_120`: construct `LiveMidiPlayer()`, set `_phase="playing"`, `_follow=False`, `_play_bpm=120`, `_tpb=480`, `_pass_ticks=100000`, `_session_start=time.perf_counter()-2.0`; `current_tick()` is in `1920±40`. `test_current_tick_idle_is_none`: fresh player → `None`. Existing `tests/test_live_midi.py` play/stop tests still exit 0.

### 4. Worker-thread schedule replace
- **File**: `live_midi.py`
- **Change**: Add `def replace_schedule(self, path: str) -> None:` that no-ops if `_phase != "playing"`; else `self._pending_path = path` under `_lock`. Add `def _apply_pending_schedule(self, port) -> None:` used only from the worker: if `_pending_path` is set, `midi_file_tick_schedule` + `seconds_schedule_at_bpm(..., self._play_bpm, tpb)` (use the new file's `tpb` only for parsing; keep `self._tpb` / `_pass_ticks` / `_pass_len` / `_session_start` / `_pass_index` / `_follow` / `_song_tick`). Compute `local = self.current_tick() or 0`. Build sounding pitch/channel sets from old `_tick_schedule` vs new schedule at `local` (note_on vel>0 minus later note_off / vel0). Under `_lock` assign `_tick_schedule`, `_schedule`, `_i = due_index(new_tick_schedule, 0, local)`, clear `_pending_path`. On `port`, `note_off` each vanished `(note, channel)` only. Do not `stop()`, do not MIDI Start/Stop, do not `panic_flush`, do not reset `_session_start`. At the top of each `_run_timed` loop iteration and each `_run_follow` pending-wait iteration, if `_pending_path`: `_apply_pending_schedule(port)`.
- **Verify**: `tests/test_live_midi.py::test_replace_schedule_advances_index_and_note_offs_vanished`: FakeMidiPort + patches like `test_stop_panic_flush_sends_cc123_on_fake_port`. File A: note 60 at tick 0 duration 480, note 64 at tick 1920 duration 480. `play_file` A at bpm=120, loop=True, count_in=0. Set `_session_start = perf_counter()-1.0` so `current_tick` ~960. File B: note 72 at tick 1920 duration 480 only. `replace_schedule(B)` then `time.sleep(0.05)`. Assert `_pending_path is None`, `_i == due_index(B_schedule, 0, local)`, and a `note_off` for note 60 was sent if it was still sounding. Assert `play_file` was not called a second time (wrap the method or count `open_output`). `test_replace_schedule_idle_noop`: idle player, `replace_schedule` does not raise and does not open a port.

### 5. Reroute `_apply_arp_live`
- **File**: `ui_app.py`
- **Change**: Import `expand_arp_notes` and `splice_from_tick`. Rewrite `_apply_arp_live` to: return if no `last_run` or `(last_run.get("options") or {}).get("generation_type") == "drone"`. Copy `options = dict(last_run["options"] or {})`. Stamp session knobs with the same mapping as the generate block (~2338–2353): `arp_mode`, `arp_steps`, `range_octaves` from `arp_range_octaves`, `evolution_rate` from `arp_evolve`, `repetition_factor` from `arp_repeat`, `arp_gates`, `arp_pitches`. Do **not** stamp `bpm` (out of scope). `tpb = int((last_run.get("summary") or {}).get("ticks_per_beat") or 480)`. `bar_ticks = tpb * 4`. `tick = get_shared_player().current_tick()`. `from_tick = 0 if tick is None else (int(tick) // bar_ticks) * bar_ticks`. `tail = expand_arp_notes(options)`. `notes = splice_from_tick(list(last_run.get("edit_notes") or []), tail, from_tick)`. `refresh_last_run_after_note_write(last_run, notes, dirty=True)`. `last_run["options"] = options`. Append `{tick: from_tick, arp_mode, arp_steps, range_octaves, evolution_rate, repetition_factor}` to `last_run.setdefault("arp_automation", [])`. If `get_shared_player().phase == "playing"`: `get_shared_player().replace_schedule(last_run["path"])`. Delete every assignment to `auto_generate`, `_live_param_tweak`, and `pending_replay` from this function. In the generate-success `last_run` dict (~2376), add `"arp_automation": []`. Change `_render_arp_live` caption from `Mess with these while Playing — sketch rewrites and keeps streaming.` to `Moves draw from this bar. Playing does not restart. Effects stay on Generate.`
- **Verify**: Source: `"auto_generate"` not in the `_apply_arp_live` function body; `"pending_replay"` not in that body; `"_live_param_tweak"` not in that body. `pytest tests/test_ui_prefs.py::test_arp_live_knobs_present_and_override_steps -q` exits 0 after Step 6 lock updates. New AppTest in that file `test_arp_live_splice_does_not_set_auto_generate`: Philip Glass + `use_sdk=False` + `auto_generate` once to get `last_run`; then `at.selectbox(key="arp_steps").select(16).run()`; assert `at.session_state.get("auto_generate")` is falsy; assert `last_run["notes_dirty"] is True`; assert `last_run["arp_automation"]` is a non-empty list; assert `"generate_midi_for_style"` was not needed (no new `generate_error`).

### 6. Lock tests and Geek copy
- **File**: `tests/test_ui_prefs.py`, `tests/test_ui_simplify_home.py`
- **Change**: In `test_arp_live_knobs_present_and_override_steps`, keep widget-key asserts and `on_change=_apply_arp_live`. Replace the requirement that this path uses generate: keep `"pending_replay" in src` (effects / roll still use it). Add source locks: `_apply_arp_live` slice contains `expand_arp_notes`, `splice_from_tick`, `replace_schedule`; `_apply_arp_live` slice does not contain `auto_generate` or `_live_param_tweak`. Keep `overrides["arp_mode"]` in the generate block (Generate click still stamps knobs). `_render_arp_live` slice contains the new caption substring `Moves draw from this bar`. `test_ui_simplify_home.py`: `_render_arp_live` still absent from Search `home` and still not a direct call in `play_tab`.
- **Verify**: `pytest tests/test_ui_prefs.py tests/test_ui_simplify_home.py tests/test_live_midi.py tests/test_note_edit.py tests/test_arp_expand.py tests/test_arp_gates.py tests/test_next_bucket.py tests/test_style_lab.py tests/test_bug_sweep.py tests/test_timing_and_generation_mode.py -q` exits 0.

## Validations
- [ ] `pytest tests/test_arp_expand.py tests/test_note_edit.py tests/test_live_midi.py tests/test_ui_prefs.py tests/test_ui_simplify_home.py tests/test_arp_gates.py tests/test_next_bucket.py tests/test_style_lab.py tests/test_bug_sweep.py tests/test_timing_and_generation_mode.py tests/test_live_midi.py -q` exits 0
- [ ] `./run_ui.sh`: Generate a Pattern sketch → change Direction while stopped → Preview WAV / Geek roll change; no Generate spinner; no artist gate
- [ ] Same sketch, Play, change Steps after bar 1 → stream does not jump to bar 1; bars already heard stay; later bars use the new grid
- [ ] Paint a rest on the step grid → same splice path; no `auto_generate`
- [ ] Move an effect slider → still regenerates (unchanged)
- [ ] Reset to generated restores the generate snapshot (wipes the collage)
- [ ] Open Geek on a Pattern sketch: no DuplicateWidgetID

## Rollback
- `git restore ui_app.py arpeggio_generation.py note_edit.py live_midi.py tests/test_ui_prefs.py tests/test_ui_simplify_home.py tests/test_live_midi.py tests/test_note_edit.py` and delete `tests/test_arp_expand.py` if uncommitted.
- If committed: `git revert` the feature commits (one commit per step if shipped via `/feature-ship`).
- Do not restore `__init__.py` (this plan does not edit it).

## Risks
- rtmidi is not thread-safe. Mitigation: `replace_schedule` only sets `_pending_path`; the worker applies the swap and note_offs (Step 4).
- `declare_component` re-emits last step-grid payload every rerun. Mitigation: existing `_arp_seq_last` equality guard stays; `_apply_arp_live` is still the only writer.
- Idle splice (`from_tick=0`) drops wow / flutter / humanize on the whole file. Accepted; caption says effects stay on Generate.
- Tail is dry and on-grid next to an effected head. Audible seam at the bar line. Accepted.
- Evolve / Lock after a splice do not continue the in-memory cell; they reseed from current knobs. Accepted (no cell snapshot).
- Follow mode + swap: Logic clock keeps running; we chase `song_tick` and do not MIDI Start. If Logic was recording the old notes, the region already captured the past — same as DAW automation.
- Loop wrap: next pass plays the spliced file from tick 0 (old head + new tail). Correct for a collage take.
- `_apply_pending_schedule` during a sounding note: clip + note_off can shorten a note that already started. Same as a bar-line edit.
- Streamlit custom component AppTest does not execute the iframe. Step-grid splice is covered by calling `_apply_arp_live` after setting `arp_gates` in AppTest / unit tests; manual `./run_ui.sh` covers paint.
- `current_tick` ±40 ticks at 120 BPM is ~20ms of clock jitter. Bar snap (1920 ticks) absorbs it.

## Out of scope
- Effect slider splice / live CC / pitchbend emission
- Mid-take BPM / tempo map
- Re-rendering the file from the full `arp_automation` lane
- Persisting / continuing `arp_cell` across splices
- Live clock engine that never writes a file
- Drone / Progression knobs
- Chat / Cursor-agent note editing
- Writing a Logic region
- Changing Search + Preview Generate or the artist gate
- npm / React toolchain
- Making effect chips auto-generate
- Adding automation keys to `LOOKUP_STICKY_OVERRIDE_KEYS`

## Go / No-Go
**GO** — `write_note_events` and the `create_arp` bar loop are the write and expand seams; the player already schedules by tick. The missing pieces are extract + splice + playhead + worker swap. Rejected alternatives (full generate, `play_file` restart, UI-thread send) are the current bugs.
