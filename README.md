# MIDI Generator

Python MIDI sketch tool: arpeggios, drones, plain-language effects, and **musician/style lookup** (local catalog + optional [Cursor SDK](https://cursor.com/docs/sdk/python)).

Honest baseline: output is musically usable as a starting sketch, not a finished composition. Patterns are tightened versus the first pass, but this remains a conceptual generator.

## What's new

- **Musician / style lab** — query “Philip Glass”, “ambient drone”, “angular jazz”, etc.
- **Cursor SDK hook** — when `CURSOR_API_KEY` is set, an agent can refine the style → generation recipe as JSON; otherwise the local catalog is used.
- **Effects presets** — Clean / Human feel / Subtle tape / Worn tape / Tape + human, explained in plain language (Hz/cents stay under the hood).
- **Streamlit test UI** — generate, inspect note preview + stats, download `.mid` / WAV, **Play into Logic via IAC**.

## Quick start

```bash
pip install -e .
./run_ui.sh
```

Open **http://127.0.0.1:8501** — generate from a musician/style query, **listen to the WAV preview**, **Play into Logic** (IAC), inspect notes, download MIDI/WAV.

CLI (optional):

```bash
python3 -m midi_gen
```

Optional Cursor SDK enrichment: `export CURSOR_API_KEY=crsr_...` before `./run_ui.sh`.

## Play into Logic Pro (IAC)

1. **Audio MIDI Setup** → MIDI Studio → **IAC Driver** → enable **Device is online**.
2. In Logic, set a Software Instrument track’s **MIDI In** to that IAC bus.
3. In the Style Lab UI, choose the IAC port → **Play into Logic**.
4. Optional: hit **Record** in Logic to capture a region (live stream alone does not write the project).

Requires `python-rtmidi` (installed with the package).

## Style lookup

1. Match against a curated catalog (Eno, Glass, Reich, Debussy, Coltrane, Monk, Aphex, Bach, Satie, Frahm, …).
2. If enabled and authenticated, call Cursor SDK to return a JSON generation profile.
3. Map the profile to arpeggio/drone options + an effects preset.
4. Write MIDI under `generated/` and show a test summary (note count, range, preview).

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

- **Arpeggio** — patterned note cells (up / down / up_down / random / order).
- **Drone/Pad** — sustained voicings with optional octave motion.
- **Style lookup** — picks mode + params from musician/style intent.

## Tests

```bash
PYTHONPATH=/tmp/py pytest /tmp/py/midi_gen/tests -q
```

## Requirements

- Python 3.10+
- `mido`, `questionary`, `streamlit`
- `cursor-sdk` (optional at runtime; required in requirements for the integration surface)
