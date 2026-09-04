# Style Lab Section Recipes

Section-aware who+section → progression + mode + bars, stacked on Engine held+Extend (PR #29).

## Completed Tasks

- [x] Schema: section / section_role / sections + profile_from_dict round-trip
- [x] resolve_section_recipe → flat Engine chord_progression / mode / bars
- [x] to_options emits drone_held / extend_factor when set; Eno wash stays False
- [x] Catalog fingerprints: bridge≠chorus on Glass/Reich/Eno/Coltrane (+ sparse peers)
- [x] SDK schema honesty B + progression-bearing few-shot neighbors
- [x] Wire section cue into generate_midi_for_style
- [x] Tests for resolve / bridge≠chorus / schema / few-shot
- [x] PR #30 open targeting main (stacked on Engine #29)

## In Progress Tasks

- [ ] Composer hear-check: bridge≠chorus roots; no Glass wallpaper on stranger accepts

## Future Tasks

- [ ] Streamlit section chips / Extend UI
- [ ] Deep ELO-class hand-authored sections[] gallery
- [ ] Matching Next / key chip

## Implementation Plan

1. Nested `section` or `sections[]` resolve to flat options before create_arp.
2. Catalog owns fingerprints; SDK invents only for stranger/Spotify path with B honesty.
3. Do not undo wash `drone_held=False` on eno_ambient / sparse ambient.
4. Stacked on Engine PR #29 (`drone_held` + `extend_factor`).

### Relevant Files

- `musician_styles.py` — schema, catalog sections, resolve helpers ✅
- `cursor_style_lookup.py` — STYLE_PROFILE_JSON_SCHEMA, few-shot, generate wire ✅
- `tests/test_section_recipes.py` — section tests ✅
- `STYLE_LAB_SECTIONS.md` — this tracker ✅
