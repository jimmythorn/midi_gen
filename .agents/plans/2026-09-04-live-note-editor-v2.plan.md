---
kind: feature-plan
plan: 2026-09-04-live-note-editor-v2
status: ready
created: 2026-09-04
source: /create-feature
---

# Live note editor + arp sequencer

## Goal
After Generate, Play / Record and Geek let the user drag notes on a piano roll, drag an arp step grid to change rhythm and pitches, and move effect-level sliders — each change writes MIDI, refreshes the WAV preview, and keeps Logic streaming if Play is already on.

## Context
- Target: Streamlit MIDI Style Lab (`ui_app.py` as `PYTHONPATH=. streamlit run ui_app.py`). Package root is the repo root (`midi_gen` via `ui_app.py` sys.modules shim and `__init__.py`).
- Geek (`_render_geek_takeover`) caption is `Save only via Download — no chat edit, no note-level mutate.` and draws `st.scatter_chart` + `st.dataframe` from `events_to_roll_rows` (`preview.py`).
- `summarize_midi_file` records note-ons only, caps `note_preview` at 48, and does not pair `note_off` (no duration).
- `_render_arp_live` → `_apply_arp_live` sets `_live_param_tweak` + `auto_generate` + optional `pending_replay`. It does not edit the file on disk.
- `_apply_effects_preset` updates session preset ids only. It does **not** set `auto_generate`.
- `generate_midi_for_style` copies `overrides` into `create_arp` options. When `effects_preset` is in `to_apply` it rebuilds `effects_config` via `build_effects_config(to_apply["effects_preset"])` with no numeric overrides (`cursor_style_lookup.py`).
- `create_arp` builds a per-bar `cell`, mutates, then `_expand_cell_to_grid` (`arpeggio_generation.py` ~355–428).
- `create_midi_file` (`midi.py`) always runs `EffectRegistry`. Roll writes must bypass that.
- `live_midi.get_shared_player().play_file` streams `last_run["path"]`. `pending_replay` already restarts a take after a live rewrite (`ui_app.py` ~1588).
- Play tab renders Geek takeover **and** `_render_result_row` when `ui_takeover == "geek"` (`ui_app.py` ~2144–2152). Both call `_render_arp_live` today; Pattern mode would DuplicateWidgetID once `arp_seq` exists.
- Why: the generated sketch is inspectable, not playable-as-an-instrument.

## Rationale
Streamlit widgets cannot drag. A vanilla-JS `declare_component` (one committed `index.html`, no npm) is the only drag surface that can report pitch/time/gate on pointer-up. Note I/O must exist first so the component has a write path that skips `EffectRegistry`. Recipe rewrite (arp knobs, step grid, effect sliders) goes through `generate_midi_for_style` / `create_arp` and replaces the file; roll edits mutate that file only. Snapshot `generated_notes` at generate time so Reset can restore without a second generate. When Geek is open, Play’s left_controls must not remount the same widget keys.

## Decisions
- Chose **vanilla-JS Streamlit custom component** (`note_editor/` at repo root → `midi_gen.note_editor`) over **React/npm** because CI and `./run_ui.sh` have no frontend build.
- Chose **inline Streamlit postMessage shim** in `index.html` (same `Streamlit.setComponentReady` / `setFrameHeight` / `setComponentValue` names as the official bootstrap) over **npm or CDN `streamlit-component-lib.js`** because “no npm” plus offline `./run_ui.sh`.
- Chose **pointer-up commit** over **per-mousemove rerun** because Streamlit reruns the full script and would stall Play.
- Chose **dedupe last payload** (`_geek_roll_last` / `_arp_seq_last`) before commit/apply over **trusting “only new values”** because `declare_component` re-emits the last `setComponentValue` every rerun and would infinite-loop `auto_generate`.
- Chose **file-level note mutate** (`list_note_events` / `write_note_events` in `note_edit.py`) over **chat or LLM edit** because Geek already forbids chat edit and Play needs a deterministic path.
- Chose **do not re-export from `__init__.py`** because that module only re-exports generate/lookup/arp helpers; import `from midi_gen.note_edit import …` and `from midi_gen.note_editor import note_editor`.
- Chose **`generated_notes` snapshot** (deepcopy at generate success) over **`generated_path` copy** because `_commit_note_edits` overwrites `last_run["path"]`; a second path is unused complexity.
- Chose **`refresh_last_run_after_note_write`** as a pure helper over **AppTest-only `_commit_note_edits`** because AppTest does not execute the iframe.
- Chose **arp step mask as `create_arp` input** over **painting MIDI only** because Direction/Steps/Octaves/Evolve must still rewrite a coherent cell.
- Chose **apply mask on `placed` after `apply_phase_offset`, before `_expand_cell_to_grid`, every bar** over **masking the seed cell once** because mutate/embellish/phase would otherwise erase the user’s grid.
- Chose **recipe rewrite wipes roll edits** over **merging roll + regenerate** because `create_arp` rebuilds the event list.
- Chose **not adding `arp_gates` / `arp_pitches` / `effects_overrides` to `LOOKUP_STICKY_OVERRIDE_KEYS`** because `_on_generate_click` → `_reset_arp_knobs` is a fresh sketch; live tweaks already skip the sticky filter (`live_tweak=True`).
- Chose **extend `_ARP_KEYS` with `arp_gates`, `arp_pitches`** and pop `effects_overrides` in `_reset_arp_knobs` so Search Generate clears the painted grid and slider levels.
- Chose **effect sliders set `_live_param_tweak` + `auto_generate`** over **mutating `last_run["options"]` in the widget** because `generate_midi_for_style` rebuilds `effects_config` from the override dict each generate.
- Chose **chips stay session-only** (no new `auto_generate` on `_apply_effects_preset`) over **“same as chips” literally** because chips today do not regenerate; sliders must. Chip `clean` only clears `effects_overrides`.
- Chose **sliders only inside `_render_effects_chips`** over **a second stack in Geek** because Geek + result_row both mount when `ui_takeover == "geek"`.
- Chose **skip `_render_arp_live` and `_render_effects_chips` in `_render_result_row` when `takeover == "geek"`** over **rendering both** because Pattern + `key="arp_seq"` would DuplicateWidgetID. Geek calls `_render_arp_live` then `_render_effects_chips` then Save.
- Chose **`build_effects_config(preset, overrides=effects_overrides)` inside `generate_midi_for_style`** when `effects_preset` is in `to_apply` over **writing `options["effects_config"]` in the slider callback** because the generate block is the only writer of a new file.
- Rejected **`st.data_editor` as the only editor** because the request is drag.
- Rejected **`st.scatter_chart` / Plotly `on_select`** because select-then-nudge is not a sequencer.
- Rejected **`st.components.v1.html` without `declare_component`** because HTML iframes cannot write session state.
- Rejected **regenerating on every roll drag** because that fights the user’s note edits.
- Rejected **`generated_path` file copy** because the live path is overwritten in place.
- Rejected **adding chip `auto_generate`** because that changes existing chip UX and is out of the requested surface.

## Preconditions
- [ ] Local Streamlit via `./run_ui.sh` (sources `.env`).
- [ ] IAC + Logic only needed to verify `pending_replay`; WAV preview is enough for note/effect checks.
- [ ] Branch is current `main` with Play/Record generate-lock commit present.
- [ ] `pytest` available in the project venv; `PYTHONPATH=.`.

## Steps
### 0. Load plan into context
- **File**: `N/A`
- **Change**: Read this plan's frontmatter, Goal, Context, Rationale, Decisions, Risks, and Out of scope. Do not start Step 1 until all are loaded.
- **Verify**: Restate the Goal in one sentence and list the rejected alternatives from `## Decisions` before proceeding.

### 1. Add note-event I/O
- **File**: `note_edit.py` (new, repo root / package `midi_gen`)
- **Change**: Implement `list_note_events(path: str) -> list[dict]`. Walk each track with absolute ticks. Pair `note_on` (velocity > 0) with the next `note_off` or `note_on` velocity 0 on the same `(note, channel)` using a stack so overlaps work. Each dict: `id` (int, sequential from 0 after sort), `start_tick` (int), `duration_tick` (int ≥ 1), `note` (int), `velocity` (int), `channel` (int). Sort by `(start_tick, note, channel)` then assign `id`. Implement `write_note_events(path, notes, *, bpm, ticks_per_beat)`: `mido.MidiFile(ticks_per_beat=ticks_per_beat)`, one track, `MetaMessage('set_tempo', tempo=mido.bpm2tempo(bpm))`, then `note_on`/`note_off` from clamped fields (`note` 0–127, `velocity` 1–127, `duration_tick` max(1, int), `channel` 0–15 default 0). Delta-encode by sorted start/end. Do not import or call `EffectRegistry` / `create_midi_file`. Empty `notes` → tempo-only file (0 `note_on`). Do not add names to `__init__.py`.
- **Verify**: `pytest tests/test_note_edit.py -q` (created in Step 2) exits 0.

### 2. Test note I/O
- **File**: `tests/test_note_edit.py` (new)
- **Change**: Write a 2-note MIDI via `mido` (overlap allowed: note A 0–480, note B 240–720, ticks_per_beat=480). Assert `list_note_events` durations are 480 and 480. Mutate pitch+start, `write_note_events`, re-list equals written fields (ignore `id` or assert ids 0..n-1). Empty notes → file exists and `list_note_events` is `[]` (0 note_ons). Clamp: note 200 → 127, velocity 0 → 1, duration 0 → 1.
- **Verify**: `pytest tests/test_note_edit.py -q` exits 0.

### 3. Stash edit buffer on generate
- **File**: `ui_app.py` generate-success block (`st.session_state["last_run"] = {` ~2228)
- **Change**: `from midi_gen.note_edit import list_note_events, write_note_events`. After `path` is written, `notes = list_note_events(path)`, then set `last_run["edit_notes"] = notes`, `last_run["generated_notes"] = [dict(n) for n in notes]`, `last_run["notes_dirty"] = False`. This runs on every successful `generate_midi_for_style` including `live_tweak`.
- **Verify**: `pytest tests/test_ui_prefs.py::test_arp_live_knobs_present_and_override_steps -q` exits 0. Source lock: `"edit_notes"` and `"generated_notes"` appear inside the `last_run` dict literal.

### 4. Commit roll edits to disk + preview + replay
- **File**: `ui_app.py`
- **Change**: Add `def refresh_last_run_after_note_write(last_run: dict, notes: list, *, dirty: bool) -> None:` that writes `write_note_events(last_run["path"], notes, bpm=int((last_run["options"] or {}).get("bpm") or 120), ticks_per_beat=int((last_run.get("summary") or {}).get("ticks_per_beat") or 480))`, then sets `last_run["edit_notes"] = list(notes)`, `last_run["notes_dirty"] = dirty`, `last_run["summary"] = summarize_midi_file(last_run["path"])`, `last_run["wav_bytes"] = render_midi_to_wav_bytes(last_run["path"])`. Add `def _commit_note_edits(notes: list) -> None:` that no-ops if `not st.session_state.get("last_run")`; else calls `refresh_last_run_after_note_write(..., dirty=True)` and if `get_shared_player().playing` sets `pending_replay=True`. Do not set `auto_generate` or `_live_param_tweak`. Add `tests/test_note_edit.py::test_refresh_last_run_after_note_write_changes_pitch`: build a 1-note mid via `write_note_events`, `last_run = {"path": ..., "options": {"bpm": 120}, "summary": {"ticks_per_beat": 480}}`, mutate `note` +12, call helper with `dirty=True`, assert `summarize_midi_file` / `list_note_events` pitch changed and `notes_dirty` is True.
- **Verify**: `pytest tests/test_note_edit.py -q` exits 0. Source: `"auto_generate"` not in `_commit_note_edits` body.

### 5. Vanilla JS note-editor component
- **File**: `note_editor/__init__.py`, `note_editor/frontend/index.html` (new)
- **Change**: `note_editor/__init__.py`:
  ```
  from pathlib import Path
  import streamlit.components.v1 as components
  _cmp = components.declare_component("note_editor", path=str(Path(__file__).parent / "frontend"))
  def note_editor(*, notes=None, mode="roll", steps=8, ticks_per_beat=480, key=None):
      return _cmp(notes=notes or [], mode=mode, steps=int(steps), ticks_per_beat=int(ticks_per_beat), key=key, default=None)
  ```
  `index.html` is a single committed file (no npm, no extra JS). Include a 30-line `window.Streamlit` shim that postMessages `{isStreamlitMessage: true, type: "streamlit:componentReady"|"streamlit:setFrameHeight"|"streamlit:setComponentValue"}` and listens for `streamlit:render`. On first load call `Streamlit.setComponentReady()` and `Streamlit.setFrameHeight`. Modes: `roll` — piano-roll of `args.notes`; drag body = pitch (vertical, MIDI 0–127) and start_tick (horizontal); drag right edge = duration_tick ≥ 1. `steps` — `args.steps` columns × 12 pitch rows (C4–B4); drag-paint gates; vertical drag on a lit cell writes that column’s pitch (MIDI int). Emit **only** on `pointerup`: roll → `{mode:"roll", notes:[...]}` (same dict keys as Python); steps → `{mode:"steps", gates:[bool], pitches:[int|null]}`. If `notes.length > 400`, draw rectangles only (no per-note DOM nodes). Height: roll 320, steps 220. `note_editor(...)` returns `dict | None`.
- **Verify**: `PYTHONPATH=. python -c "from midi_gen.note_editor import note_editor"` exits 0. Manual: `./run_ui.sh` — after later steps, iframe paints; no JS console errors.

### 6. Replace Geek scatter with the roll
- **File**: `ui_app.py` `_render_geek_takeover` and `_render_result_row`
- **Change**: Delete the caption substring `no chat edit, no note-level mutate.` Keep `Live options rewrite the sketch and keep streaming.` Replace `st.scatter_chart` + `st.dataframe(roll)` and the `events_to_roll_rows` call with:
  ```
  payload = note_editor(notes=run_data.get("edit_notes") or [], mode="roll",
                        ticks_per_beat=int((run_data.get("summary") or {}).get("ticks_per_beat") or 480),
                        key="geek_roll")
  if payload and payload.get("mode") == "roll" and payload.get("notes") is not None:
      if payload != st.session_state.get("_geek_roll_last"):
          st.session_state["_geek_roll_last"] = payload
          _commit_note_edits(list(payload["notes"]))
  ```
  Keep metrics, `format_summary_text`, effects bullets, raw options. Keep `_render_arp_live` above Save. After `_render_arp_live(profile)` call `_render_effects_chips(run_data)` then Save. In `_render_result_row` `left_controls`, wrap `_render_arp_live` / `_render_effects_chips` in `if takeover != "geek":`. Drop unused `events_to_roll_rows` import if nothing else uses it.
- **Verify**: `"no note-level mutate" not in Path("ui_app.py").read_text()`. `"st.scatter_chart" not in` `_render_geek_takeover` slice. `pytest tests/test_ui_prefs.py -q` (locks updated in Step 10).

### 7. Arp step sequencer on Play / Record
- **File**: `ui_app.py` (`_render_arp_live`, `_ARP_KEYS`, generate `overrides`); `arpeggio_generation.py`
- **Change**: Add `arp_gates` and `arp_pitches` to `_ARP_KEYS`. In `_render_arp_live`, after the Lock slider, when `generation_mode == "pattern"`: `steps = int(st.session_state.get("arp_steps") or 8)`. If `arp_gates` missing or `len != steps`, set `st.session_state["arp_gates"] = [True] * steps` (pad/truncate; pad=`True`). Same for `arp_pitches` with pad=`None`. Render `note_editor(mode="steps", steps=steps, key="arp_seq")`. On payload `mode=="steps"` different from `_arp_seq_last`, store `arp_gates` / `arp_pitches` and call `_apply_arp_live()`. In generate `overrides` (~2186): if `"arp_gates" in st.session_state`, pass `list(...)`; same for `arp_pitches`. In `arpeggio_generation.py` add `apply_arp_step_mask(cell, *, arp_steps, gates, pitches) -> list`: copy/pad/truncate `cell` to `arp_steps`; if `gates` is not None, rest (`None`) where `bool(gates[i])` is False (gates padded with `True`); if `pitches[i]` is `int`, replace that step. Call it on `placed` after `apply_phase_offset(...)` and before `_expand_cell_to_grid` every bar, using `options.get("arp_gates")` / `options.get("arp_pitches")`. Skip when both are absent. Do not run on the drone branch.
- **Verify**: `pytest tests/test_next_bucket.py tests/test_style_lab.py tests/test_bug_sweep.py tests/test_arp_gates.py -q` exits 0. `tests/test_arp_gates.py`: (1) `apply_arp_step_mask([60,62,64,65], arp_steps=4, gates=[True,False,True,False], pitches=None) == [60, None, 64, None]`; (2) `create_arp` with `arp_steps=4`, `bars=1`, `arp_gates=[True,False,True,False]`, `evolution_rate=0`, `repetition_factor=10`, `effects_config=[]`, `filename=tmp`, `seed=1` — `list_note_events` start ticks have no note in `[480, 960)` or `[1440, 1920)` (quarter-note slots 1 and 3).

### 8. Effect level sliders
- **File**: `ui_app.py` (`_render_effects_chips`, `_apply_effects_preset`, generate `overrides`); `cursor_style_lookup.py`
- **Change**: Import `build_effects_config`, `EFFECT_PARAM_HELP`. Add `_FX_SLIDER_SPEC = {"wow_rate_hz": (0.05, 2.0, 0.05), "wow_depth": (0, 50, 1), "flutter_rate_hz": (1.0, 16.0, 0.5), "flutter_depth": (0, 16, 1), "randomness": (0.0, 1.0, 0.05), "humanization_range": (0, 32, 1)}` (skip `depth_units`). Add `_apply_effect_level()`: read all `fx_lvl_*` widget keys into `st.session_state["effects_overrides"]` as `{effect_name: {param: value}}`, set `_live_param_tweak=True` and `auto_generate=True`, and `pending_replay` if playing. At end of `_render_effects_chips`, `cfg = build_effects_config(session presets, overrides=st.session_state.get("effects_overrides"))`. For each effect dict, for each numeric key in `_FX_SLIDER_SPEC` present on that effect, `st.slider(..., key=f"fx_lvl_{name}_{param}", value=current, min/max/step from spec, help=EFFECT_PARAM_HELP[param], on_change=_apply_effect_level)`. If `notes_dirty`, caption `Recipe rewrite replaces piano-roll edits.` In `_apply_effects_preset`, when `pid == "clean"` (and when chosen becomes `["clean"]`), set `st.session_state["effects_overrides"] = {}` and pop all `fx_lvl_*` keys. In `_reset_arp_knobs`, also `st.session_state.pop("effects_overrides", None)` and pop keys starting `fx_lvl_`. In generate `overrides`, if `st.session_state.get("effects_overrides")`: `overrides["effects_overrides"] = dict(...)`. In `generate_midi_for_style`, when rebuilding config: `options["effects_config"] = build_effects_config(to_apply["effects_preset"], overrides=to_apply.get("effects_overrides"))`.
- **Verify**: `pytest tests/test_style_lab.py -q` exits 0. New source lock in `tests/test_ui_prefs.py`: `_render_effects_chips` body contains `effects_overrides` and `build_effects_config`. AppTest: Philip Glass + `auto_generate`, move `fx_lvl_humanize_velocity_humanization_range` if the widget exists (tape_and_human default), after run `last_run["notes_dirty"] is False`.

### 9. Dirty-state + reset
- **File**: `ui_app.py` (`_render_effects_chips` footer)
- **Change**: If `last_run.get("notes_dirty")`, caption `Piano-roll edits will be replaced if you change Arp, Steps grid, or Effects.` Button `Reset to generated` (`key="reset_generated_notes"`) enabled only when `notes_dirty`. `on_click=_reset_generated_notes`. `_reset_generated_notes`: read `generated_notes` from `last_run`; `refresh_last_run_after_note_write(last_run, [dict(n) for n in generated_notes], dirty=False)`; if playing, `pending_replay=True`. Do not set `auto_generate`. Do not call `generate_midi_for_style`. Add `tests/test_note_edit.py::test_reset_restores_generated_notes`: generate-shaped `last_run` with `generated_notes` snapshot, commit a pitch edit via the helper (`dirty=True`), then write snapshot back with `dirty=False`; `list_note_events` equals `generated_notes` (field-wise).
- **Verify**: `pytest tests/test_note_edit.py::test_reset_restores_generated_notes -q` exits 0. Source: `generate_midi_for_style` not in `_reset_generated_notes`.

### 10. Lock tests and Geek copy
- **File**: `tests/test_ui_prefs.py`, `tests/test_ui_simplify_home.py`
- **Change**: Geek slice (`def _render_geek_takeover` … `# --- Takeover OR home`): assert `note_editor` and `geek_roll` in slice; assert `st.scatter_chart` not in slice; assert `_render_effects_chips` in slice; keep `_render_arp_live` in slice. `_render_arp_live` slice contains `arp_seq`. Full `ui_app.py` src: `"no note-level mutate" not in src`. Keep `_render_generate_loading` / result_row call order locks unchanged (`_render_listen` < `_render_arp_live` < `_render_effects_chips` still in result_row source). `test_ui_simplify_home.py`: `_render_effects_chips` / `_render_arp_live` still absent from Search `home` and still absent as direct calls in `play_tab` (they stay inside helpers). Do not add `note_editor` to Search.
- **Verify**: `pytest tests/test_ui_prefs.py tests/test_ui_simplify_home.py tests/test_live_midi.py tests/test_note_edit.py tests/test_arp_gates.py -q` exits 0.

## Validations
- [x] `pytest tests/test_note_edit.py tests/test_arp_gates.py tests/test_ui_prefs.py tests/test_ui_simplify_home.py tests/test_live_midi.py tests/test_style_lab.py tests/test_bug_sweep.py tests/test_next_bucket.py -q` exits 0
- [ ] `./run_ui.sh`: Generate a Pattern sketch → Geek roll shows notes → drag one note → Preview WAV changes; Play button still works
- [ ] Pattern: paint a rest on the step grid → sketch rewrites; even steps silent in Preview
- [ ] Move an effect slider → new file; piano-roll dirty caption appears only if a roll edit was committed first
- [ ] While Playing, drag a note → stream restarts (`pending_replay`) without a second Generate click
- [ ] Reset restores pre-roll notes without calling the artist gate
- [ ] Open Geek on a Pattern sketch: no Streamlit DuplicateWidgetID

## Rollback
- `git revert` the feature commits (one commit per step if shipped via `/feature-ship`).
- If only uncommitted: `git restore ui_app.py arpeggio_generation.py cursor_style_lookup.py` and delete `note_edit.py`, `note_editor/`, `tests/test_note_edit.py`, `tests/test_arp_gates.py`. Do not restore `__init__.py` (this plan does not edit it).

## Risks
- Streamlit custom components often fail AppTest (iframe not executed). Mitigation: backend tests carry correctness; UI tests are source locks + one manual `./run_ui.sh` pass.
- `declare_component` re-emits last value every rerun. Mitigation: `_geek_roll_last` / `_arp_seq_last` equality guard (Step 6–7).
- Geek + result_row both mount. Mitigation: skip arp/chips in result_row when `takeover == "geek"` (Step 6).
- `create_arp` evolve/mutate can fight a painted grid. Mitigation: re-apply mask on `placed` every bar (Step 7).
- Large sketches (drones) make the roll heavy. Mitigation: if `notes.length > 400`, rectangles only (Step 5).
- Effect sliders regenerate and wipe roll edits. Mitigation: dirty caption (Step 9); accepted, not merged.
- Chip `clean` clears overrides but does not rewrite the file until the next Generate or slider live_tweak. Accepted.

## Out of scope
- Chat / Cursor-agent note editing
- Writing a Logic region or arranging on the DAW timeline
- Multi-track / per-channel editors
- Undo history beyond Reset to generated
- New effect types
- Changing Search + Preview Generate flow or artist gate
- npm / React toolchain
- Making effect chips auto-generate (they do not today)
- Adding `arp_gates` / `effects_overrides` to `LOOKUP_STICKY_OVERRIDE_KEYS`

## Go / No-Go
**GO** — seams exist (`create_arp` cell, `build_effects_config` overrides, `pending_replay`); drag requires a committed JS component; v1 forks (`generated_path` vs snapshot, chip vs slider generate, duplicate Geek/Play keys) are closed.
