# MIDI Generator

Python MIDI sketch tool: arpeggios, drones, plain-language effects, and **musician/style lookup** (local catalog + optional [Cursor SDK](https://cursor.com/docs/sdk/python)).

Honest baseline: output is musically usable as a starting sketch, not a finished composition.

## North star

**Pick style → Generate → Play into Logic → Download MIDI.**

The Streamlit Style Lab is the primary surface. The CLI (`python -m midi_gen`) remains for power/dev use.

## What's new

- **Musician / style lab** — catalog pick (**who**) or free-text vibe (**feel**); featured cards + vibe chips are entry points, not a closed set.
- **Flexible matching** — aliases (gymnopédie → Satie, sheets of sound → Coltrane, …) + richer vibe tags across the full catalog.
- **Recipe preview + match line** before Generate; **Try instead** related styles after.
- **Play into Logic (IAC)** — Audition→Capture strip; Refresh ports; Count-in / Loop (app-side); Panic (CC123); Record in Logic to keep a region.
- **Transport prefs** — count-in / loop / soft-click / last MIDI port persist locally across Streamlit restarts (defaults Off / Off / Off).
- **Bend-aware Listen preview** — sine WAV honors pitch-bend so tape wow/flutter is audible.
- **Mode color** — characteristic tones (#4 Lydian, nat6/9 Dorian, b7 Mixolydian, …) on weak beats so modes aren’t triad wallpaper.
- **Effects presets** — Clean / Human feel / Subtle tape / Worn tape / Tape + human.
- **Cursor SDK hook** — optional; Advanced toggle in the UI (enrich-this-vibe).

## Quick start

```bash
pip install -e .
./run_ui.sh
```

Open **http://127.0.0.1:8501**.

CLI (optional / power users):

```bash
python3 -m midi_gen
```

Optional Cursor SDK enrichment: `export CURSOR_API_KEY=crsr_...` before `./run_ui.sh`.

## Play into Logic Pro (IAC)

1. **Audio MIDI Setup** → MIDI Studio → **IAC Driver** → enable **Device is online**.
2. In Logic, set a Software Instrument track’s **MIDI In** to that IAC bus (must match the port Style Lab plays to when you have more than one).
3. Generate a sketch → **Arm → Record in Logic → Play here** (live stream alone does not write a region).
4. Optional **Count-in (1 silent bar)** (off by default for instant audition) and/or **Loop sketch** — app-side only, inside the Audition→Capture strip; Stop panic-flushes hanging notes. **Panic** sends all-notes-off (CC123) without stopping. Soft click during count-in is an Advanced opt-in (off by default — click notes can land in the record region).
5. If you enabled IAC mid-session, hit **Refresh ports** — no relaunch needed.

Requires `python-rtmidi` (installed with the package). Silence checklist under Play covers MIDI In match / track hears input / instrument loaded.

## Style lookup

1. Match against a curated catalog (Eno, Glass, Reich, Debussy, Coltrane, Monk, Aphex, Bach, Satie, Frahm, …).
2. If enabled and authenticated, call Cursor SDK to return a JSON generation profile.
3. Map the profile to arpeggio/drone options + an effects preset.
4. Write MIDI under `generated/` and show Listen / Logic / Download actions.

Programmatic API:

```python
from midi_gen import generate_midi_for_style, lookup_musician_style

result = lookup_musician_style("ambient pad", use_cursor_sdk=True)
path, result, options = generate_midi_for_style(
    "Philip Glass",
    use_cursor_sdk=False,
    overrides={"bars": 8, "effects_preset": "human_feel"},
)
```

## Effects (plain language)

| Preset | What it does |
| --- | --- |
| **Clean** | No processing — inspect the raw pattern. |
| **Human feel** | Small velocity variation so notes aren't robot-loud. |
| **Subtle tape** | Gentle slow pitch drift (wow) like a healthy cassette. |
| **Worn tape** | Stronger wow + flutter + humanize for lo-fi edge. |
| **Tape + human** | Mild drift + touch — usual musical default. |

Glossary: **wow** = slow pitch sway; **flutter** = faster shimmer; depths are in **cents** (100 cents = 1 semitone).

## Generation modes

- **Arpeggio** — patterned note cells with optional modal color accents.
- **Drone/Pad** — sustained voicings with optional octave motion + color tones.
- **Style lookup** — picks mode + params from musician/style intent.

## Tests

```bash
pytest tests -q
```

## Requirements

- Python 3.10+
- `mido`, `questionary`, `streamlit`, `numpy`, `python-rtmidi`
- `cursor-sdk` (optional at runtime; required in requirements for the integration surface)
