# Held Progression + Extend (Engine First Slice)

Beat writer's block: drone path becomes a held chord progression (one triad per N bars), not ambient voicing wash. Extend 2–4× stretches bars-per-chord without adding chord changes.

## Completed Tasks

- [x] Verify `generate_drone_events` segments by roots; `chord_progression` arp-only today
- [x] Held progression mode (`drone_held`) — sustained triad per segment
- [x] Drive drone segments from `chord_progression` when set
- [x] `extend_factor` (1–4) multiplies bars / bars-per-chord
- [x] Tests: held boundaries, extend 2×/4×, non-held wash, seed determinism

## In Progress Tasks

- [ ] PR review / CI green

## Future Tasks

- [ ] Section chips / Extend UI / drip copy (Sample Musician)
- [ ] Section role schema + bridge/chorus/verse progressions via SDK/catalog
- [ ] Matching, live Logic key, key chip, Rovi

## Implementation Plan

1. `drone_held` defaults True when `chord_progression` is set; False keeps legacy wash.
2. Held path emits one chord-tone voicing for the full segment duration (no walkdowns / doubling / shifts / color accents).
3. Drone `create_arp` replaces segment roots with resolved `chord_progression` when present.
4. `apply_extend_factor` clamps 1–4 and multiplies `bars` once before generation.

### Relevant Files

- `drone_generation.py` — held sustain path ✅
- `arpeggio_generation.py` — extend_factor, progression→roots, held defaults ✅
- `tests/test_held_progression.py` — engine tests ✅
- `TASKS.md` — this tracker ✅
