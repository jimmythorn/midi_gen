---
kind: feature-plan
plan: 2026-09-04-live-note-editor
status: ready
created: 2026-09-04
source: /create-feature
---

# Live note editor + arp sequencer

## Goal
After Generate, Play / Record and Geek let the user drag notes on a piano roll, drag an arp step grid to change rhythm and pitches, and move effect-level sliders — each change writes MIDI, refreshes the WAV preview, and keeps Logic streaming if Play is already on.

## Context
- Target: Streamlit MIDI Style Lab, `ui_app.py`, Play / Record tab + Geek inline stack.
- Geek (`_render_geek_takeover`) states “no chat edit, no note-level mutate” and draws a read-only `st.scatter_chart` + `st.dataframe` from `events_to_roll_rows` (`preview.py`).
- `summarize_midi_file` records note-ons only, caps `note_preview` at 48, and does not pair `note_off` (no duration).
- Pattern arp knobs (`_render_arp_live` → `_apply_arp_live`) set `auto_generate` + `_live_param_tweak` and call `generate_midi_for_style` / `create_arp` — they do not edit the existing file.
- Effects are preset chips; `build_effects_config` already accepts per-effect numeric overrides; Geek only prints `explain_effects_config`.
- `live_midi.LiveMidiPlayer.play_file` streams a path; `pending_replay` already restarts a take after a live rewrite.
- Why: the generated sketch is inspectable, not playable-as-an-instrument.

## Rationale
Streamlit widgets cannot drag. A vanilla-JS `declare_component` (one committed `index.html`, no npm) is the only drag surface that can report pitch/time/gate on pointer-up via `Streamlit.setComponentValue`. Note I/O must exist first so the component has a real write path. Recipe rewrite (arp knobs, step-grid Apply, effect sliders) goes through `create_arp` and wipes piano-roll edits; the roll edits the current MIDI file only. That split matches how `create_arp` already expands a cell to a grid (`_expand_cell_to_grid`) while the file on disk is the thing Play and Preview consume.

## Decisions
- Chose **vanilla-JS Streamlit custom component** (`midi_gen/note_editor/`) over **React/npm** because CI and `./run_ui.sh` have no frontend build today.
- Chose **pointer-up commit** over **per-mousemove rerun** because Streamlit reruns the full script and would stall Play.
- Chose **file-level note mutate** (`list_note_events` / `write_note_events`) over **chat or LLM edit** because Geek already forbids chat edit and Play needs a deterministic path.
- Chose **arp step mask as `create_arp` input** over **painting MIDI only** because Direction/Steps/Octaves/Evolve must still rewrite a coherent cell.
- Chose **recipe rewrite wipes roll edits** over **merging roll + regenerate** because `create_arp` rebuilds the event list; merging is a second product.
- Chose **effect sliders + `build_effects_config` overrides + live_tweak** over **a second drag canvas** because effect params are already numeric (`wow_depth`, `humanization_range`, …) and chips stay as the preset picker.
- Rejected **`st.data_editor` as the only editor** because the request is drag.
- Rejected **`st.scatter_chart` / Plotly `on_select`** because select-then-nudge is not a sequencer.
- Rejected **`st.components.v1.html` without `declare_component`** because HTML iframes cannot write session state.
- Rejected **regenerating on every roll drag** because that fights the user’s note edits.

## Preconditions
- [ ] Local Streamlit via `./run_ui.sh` (sources `.env`).
- [ ] IAC + Logic only needed to verify `pending_replay`; WAV preview is enough for note/effect checks.
- [ ] Branch is current `main` with Play/Record generate-lock commit present.

## Steps
### 0. Load plan into context
- **File**: `N/A`
- **Change**: Read this plan's frontmatter, Goal, Context, Rationale, Decisions, Risks, and Out of scope. Do not start Step 1 until all are loaded.
- **Verify**: Restate the Goal in one sentence and list the rejected alternatives from `## Decisions` before proceeding.

### 1. Add note-event I/O
- **File**: `note_edit.py` (new, package `midi_gen`)
- **Change**: Implement `list_note_events(path) -> list[dict]` pairing `note_on`/`note_off` per track (id, start_tick, duration_tick, note, velocity, channel). Implement `write_note_events(path, notes, *, bpm, ticks_per_beat)` that writes one track, preserves tempo, does not re-run EffectRegistry. Clamp note 0–127, velocity 1–127, duration ≥ 1 tick. Export from `__init__.py` only if other modules already re-export helpers; otherwise import from `midi_gen.note_edit`.
- **Verify**: `pytest tests/test_note_edit.py -q` (create in Step 2) exits 0.

### 2. Test note I/O
- **File**: `tests/test_note_edit.py` (new)
- **Change**: Write a 2-note MIDI via `mido` (overlap allowed). Assert `list_note_events` durations match. `write_note_events` after pitch+start mutate; re-list equals written. Empty notes → valid empty file (0 note_ons).
- **Verify**: `pytest tests/test_note_edit.py -q` exits 0.

### 3. Stash edit buffer on generate
- **File**: `ui_app.py` generate-success block (`st.session_state["last_run"] = {`)
- **Change**: After writing `path`, set `last_run["edit_notes"] = list_note_events(path)` and `last_run["notes_dirty"] = False`. On every successful `generate_midi_for_style` (including live_tweak), replace `edit_notes` from the new file and set `notes_dirty` False.
- **Verify**: `pytest tests/test_ui_prefs.py::test_arp_live_knobs_present_and_override_steps -q` exits 0 (generate still completes). Source lock: `"edit_notes"` in `ui_app.py` last_run dict.

### 4. Commit roll edits to disk + preview + replay
- **File**: `ui_app.py`
- **Change**: Add `_commit_note_edits(notes: list) -> None`. Write `write_note_events(last_run["path"], notes, bpm=options["bpm"], ticks_per_beat=summary["ticks_per_beat"])`. Set `last_run["edit_notes"]`, `notes_dirty=True`, refresh `wav_bytes` via `render_midi_to_wav_bytes`, refresh `summary` via `summarize_midi_file`. If `get_shared_player().playing`, set `pending_replay=True` (same as `_apply_arp_live`). Do not set `auto_generate`.
- **Verify**: Unit-test `_commit_note_edits` by extracting it if needed; otherwise `pytest` AppTest: generate Philip Glass, mutate one note in session, call commit helper, assert `summarize_midi_file` pitch changed and `auto_generate` is not set.

### 5. Vanilla JS note-editor component
- **File**: `note_editor/__init__.py`, `note_editor/frontend/index.html` (new)
- **Change**: `declare_component("note_editor", path=str(Path(__file__).parent / "frontend"))`. `index.html` loads Streamlit component lib from CDN (`streamlit-component-lib` is not required if using the standard `<script src="./streamlit-component-lib.js">` — **copy the official bootstrap snippet** that calls `Streamlit.setComponentReady` + `setFrameHeight` + `setComponentValue`). Modes: `roll` and `steps`. `roll`: piano-roll grid, drag note vertically (pitch) and horizontally (start); drag right edge (duration). `steps`: `arp_steps` columns × one octave-ish pitch rows; drag paint gates; vertical drag on a lit cell sets pitch. Emit JSON only on `pointerup`: `{mode, notes}` or `{mode, gates: [bool], pitches: [int|null]}`. No npm. Commit the HTML. Python wrapper `note_editor(notes=..., mode=..., steps=..., key=...) -> dict | None`.
- **Verify**: `python -c "from midi_gen.note_editor import note_editor"` imports. Manual: `./run_ui.sh` — component iframe paints without JS console errors.

### 6. Replace Geek scatter with the roll
- **File**: `ui_app.py` `_render_geek_takeover`
- **Change**: Delete the “no chat edit, no note-level mutate” caption. Replace `st.scatter_chart` + `st.dataframe(roll)` with `note_editor(notes=last_run["edit_notes"], mode="roll", key="geek_roll")`. On return value, call `_commit_note_edits`. Keep metrics + `format_summary_text` + effects bullets + raw options. Keep `_render_arp_live` above Save.
- **Verify**: Source: `"no note-level mutate" not in ui_app.py`. `pytest tests/test_ui_prefs.py -q` — update any string locks that required the old caption or `st.scatter_chart` in geek.

### 7. Arp step sequencer on Play / Record
- **File**: `ui_app.py` `_render_arp_live`; `arpeggio_generation.py` `create_arp`
- **Change**: When `generation_mode == "pattern"`, under existing knobs render `note_editor(mode="steps", steps=session arp_steps, key="arp_seq")`. Persist `arp_gates` (list[bool] length `arp_steps`) and `arp_pitches` (list[int|null]). On component value, write those keys and call `_apply_arp_live`. In `create_arp`, after the cell is built and before `_expand_cell_to_grid`, if `options["arp_gates"]` is present, apply rest (`None`) where gate is False; if `arp_pitches[i]` is an int, replace that step’s MIDI note. Length-mismatch: pad/truncate to `arp_steps`. Evolve/mutate still runs, then re-apply gates/pitches each bar so the user’s grid stays the rhythm source.
- **Verify**: `pytest tests/test_next_bucket.py tests/test_style_lab.py tests/test_bug_sweep.py -q` still pass. New `tests/test_arp_gates.py`: `create_arp` with `arp_gates=[True, False, True, False]` and `arp_steps=4` yields rests on even steps (assert via `list_note_events` start ticks).

### 8. Effect level sliders
- **File**: `ui_app.py` `_render_effects_chips` (or new `_render_effects_levels` called under the chips in `_render_result_row` and Geek)
- **Change**: From current `effects_config` / `build_effects_config(session presets)`, render a slider per numeric key in `EFFECT_PARAM_HELP` that exists on an active effect (`wow_depth`, `wow_rate_hz`, `flutter_depth`, `flutter_rate_hz`, `randomness`, `humanization_range`). On change: store `effects_overrides` dict, `options["effects_config"] = build_effects_config(presets, overrides=effects_overrides)`, set `_live_param_tweak` + `auto_generate` (same as chips). Caption when `notes_dirty`: “Recipe rewrite replaces piano-roll edits.” Chip `clean` clears overrides.
- **Verify**: `pytest tests/test_style_lab.py -q` (preset merge). New assert in `tests/test_ui_prefs.py` that `_render_effects` source contains `effects_overrides` and `build_effects_config`. AppTest: generate, move `humanization_range` if exposed, `last_run["notes_dirty"]` is False after live_tweak.

### 9. Dirty-state + reset
- **File**: `ui_app.py` Play column / Geek
- **Change**: If `notes_dirty`, show caption “Piano-roll edits will be replaced if you change Arp, Steps grid, or Effects.” Button `Reset to generated` is **not** a second generate: it is only enabled after a wipe… **Wrong.** Reset must re-read the last generated file. Store `last_run["generated_path"]` copy **or** keep `last_run["generated_notes"]` snapshot at generate time. Reset: `write_note_events` from `generated_notes`, `notes_dirty=False`, refresh wav/summary, `pending_replay` if playing. Do not call `generate_midi_for_style`.
- **Verify**: Test: generate, commit a pitch edit, reset, `list_note_events` matches `generated_notes`.

### 10. Lock tests and Geek copy
- **File**: `tests/test_ui_prefs.py`, `tests/test_ui_simplify_home.py`
- **Change**: Update source-order locks: Geek contains `note_editor` / `geek_roll`, not `st.scatter_chart`. Play arp contains `arp_seq`. `_render_generate_loading` / result_row order unchanged. Add `"no note-level mutate" not in src`.
- **Verify**: `pytest tests/test_ui_prefs.py tests/test_ui_simplify_home.py tests/test_live_midi.py tests/test_note_edit.py tests/test_arp_gates.py -q` exits 0.

## Validations
- [ ] `pytest tests/test_note_edit.py tests/test_arp_gates.py tests/test_ui_prefs.py tests/test_ui_simplify_home.py tests/test_live_midi.py tests/test_style_lab.py tests/test_bug_sweep.py -q` exits 0
- [ ] `./run_ui.sh`: Generate a Pattern sketch → Geek roll shows notes → drag one note → Preview WAV changes; Play button still works
- [ ] Pattern: paint a rest on the step grid → sketch rewrites; even steps silent in Preview
- [ ] Move an effect slider → new file; piano-roll dirty caption appears only if a roll edit was committed first
- [ ] While Playing, drag a note → stream restarts (`pending_replay`) without a second Generate click
- [ ] Reset restores pre-roll notes without calling the artist gate

## Rollback
- `git revert` the feature commits (one commit per step if shipped via `/feature-ship`).
- If only uncommitted: `git restore ui_app.py arpeggio_generation.py __init__.py` and delete `note_edit.py`, `note_editor/`, `tests/test_note_edit.py`, `tests/test_arp_gates.py`.

## Risks
- Streamlit custom components often fail AppTest (iframe not executed). Mitigation: backend tests carry correctness; UI tests are source locks + one manual `./run_ui.sh` pass.
- `create_arp` evolve/mutate can fight a painted grid. Mitigation: re-apply `arp_gates` / `arp_pitches` after mutate each bar (Step 7).
- Large sketches (drones) make the roll heavy. Mitigation: render notes from `edit_notes` (full file, not 48-cap preview); if >400 notes, draw velocity-clipped rectangles and skip per-note DOM.
- Effect sliders regenerate and wipe roll edits. Mitigation: dirty caption (Step 9); accepted, not merged.

## Out of scope
- Chat / Cursor-agent note editing
- Writing a Logic region or arranging on the DAW timeline
- Multi-track / per-channel editors
- Undo history beyond Reset to generated
- New effect types
- Changing Search + Preview Generate flow or artist gate
- npm / React toolchain

## Go / No-Go
**GO** — seams exist (`create_arp` cell, `build_effects_config` overrides, `pending_replay`); drag requires a committed JS component, not a Streamlit widget swap.
