# UI Simplify Now — Streamlit home

Musician-facing chrome: plain labels + layout rearrange. Do not rewrite the Logic / IAC / loop-until-Stop / record MIDI stream stack.

## Completed Tasks

- [x] Merge Engine APIs from PR #33 (`timing_factor`, `apply_generation_mode`) onto latest main
- [x] Search: Mood | Artist mode + catalog match combo list
- [x] Mood chips under search; drop Browse takeover
- [x] Timing chips (Double / 1× / Half / Quarter) → `timing_factor`
- [x] Song part chips relabel; Pattern | Progression → `apply_generation_mode`
- [x] Tabs: Search + Preview | Play / Record; drop Audition strip, Try instead
- [x] Surprise → Random; Geek live arp knobs; plain labels
- [x] Tests for timing/mode wiring; update chrome tests

## In Progress Tasks

- (none)

## Future Tasks

- [ ] Matching Next, key chip, Audio FX DSP (out of scope)
- [ ] Live Spotify genre match list hydration when credentials present (catalog combo works offline)

## Implementation Plan

Prefer rearrange / relabel / tab wrap of existing `_render_play_hero`, `_render_capture_setup`, generate pipeline. Engine overrides: `timing_factor` + `apply_generation_mode` (wash `drone_held=False` wins). Preview stays the hero under search.

### Relevant Files

- `ui_app.py` — home chrome, tabs, chips, generate overrides ✅
- `style_prompting.py` — timing chip helpers, labels, mood gate hook ✅
- `cursor_style_lookup.py` — apply `generation_mode` after layout ✅
- `spotify_client.py` — mood genre-first search helper ✅
- `arpeggio_generation.py` — Engine APIs (from #33) ✅
- `tests/test_ui_simplify_home.py` — new UI wiring tests ✅
- `tests/test_ui_prefs.py` — chrome / takeover expectations ✅

### Deliberately not touched (Logic stack)

- `live_midi.py` player / IAC / MMC / clock / loop-until-Stop
- `play_file` / `stop` / port refresh semantics
- Note fingerprint / recipe matching / Audio FX DSP
