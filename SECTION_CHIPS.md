# Intro / Outro / Pre-chorus Section Chips

Extend home Section (optional) chips beyond Verse / Chorus / Bridge so musicians
can sketch intro, outro, and pre-chorus fingerprints in the same who → chip →
Extend → Generate → Play loop.

## Completed Tasks

- [x] Extend `SECTION_ROLES` / `_SECTION_CUE_RE` / normalize + parse for intro, outro, pre-chorus
- [x] Extend `SECTION_CHIP_ROLES` / `SECTION_CHIP_LABELS` and home chip row width
- [x] Add distinct catalog `sections[]` fingerprints for all sectioned artists
- [x] Update SDK schema role enums in `cursor_style_lookup.py`
- [x] Tests for chip set, toggle, resolve paths, missing-section fallback

## In Progress Tasks

- [x] Verify full pytest suite green (section tests; Spotify-gated failures pre-exist)

## Future Tasks

- [ ] Optional Style Lab UI surfacing of new roles (home chips already ship)

## Implementation Plan

Same path as Verse / Chorus / Bridge: chip → `session_state.section_role` →
`resolve_section_recipe` / Engine options. Missing catalog section stamps the
role and keeps top-level progression (existing fallback).

### Relevant Files

- `musician_styles.py` — roles, cue parse, catalog `sections[]` ✅
- `style_prompting.py` — chip role/label tuples ✅
- `ui_app.py` — `_render_section_chips` + chip row CSS ✅
- `cursor_style_lookup.py` — SDK schema + generate docstring ✅
- `tests/test_section_chips_extend_ui.py` — chip toggle + preview ✅
- `tests/test_section_recipes.py` — resolve + catalog distinctness ✅
