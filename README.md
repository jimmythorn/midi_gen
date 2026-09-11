# MIDI Generator

Python MIDI sketch tool: arpeggios, drones, plain-language effects, and **musician/style lookup** (local catalog + optional [Cursor SDK](https://cursor.com/docs/sdk/python)).

Honest baseline: output is musically usable as a starting sketch, not a finished composition.

## North star

**Pick style → Generate → Play into Logic → Download MIDI.**

The Streamlit Style Lab is the primary surface. The CLI (`python -m midi_gen`) remains for power/dev use.

**Musician guide:** [docs/USER_GUIDE.md](docs/USER_GUIDE.md) — Logic track setup, Cursor API key, basic usage.

## What's new

- **Musician / style lab** — catalog pick (**who**) or free-text vibe (**feel**); featured cards + vibe chips are entry points, not a closed set.
- **Flexible matching** — aliases (gymnopédie → Satie, sheets of sound → Coltrane, …) + richer vibe tags across the full catalog.
- **Recipe preview + match line** before Generate; **Try instead** related styles after.
- **Play into Logic (IAC)** — Audition→Capture strip; Refresh ports; Count-in / Loop (app-side); All notes off (CC123); Record in Logic to keep a region.
- **Logic MCP Record (optional)** — fail-closed arm + `transport.record` via Logic Pro MCP; notes still stream over IAC (never MCP MIDI import).
- **Transport prefs** — count-in / loop / soft-click / last MIDI port persist locally across Streamlit restarts (defaults Off / On / Off — Play loops until Stop).
- **Listen on home** — piano preview plays in the page after Generate (pitch-bend / tape wow audible). Play into Logic for a sampled instrument.
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

Artist gate (reject-before-generate): typed Search / feel always hits Spotify Artist Search via Client Credentials (`SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` — never commit secrets): name search first, then `genre:"query"` if name search is empty. Browse catalog picks with an empty search stay local. Accept `type=artist` with a name. `followers.total >= 10000` applies only when Spotify sends a count (Client Credentials payloads often omit followers/genres). Spotify down (HTTP / missing credentials) bypasses to the Cursor music-identity agent. Below that / non-artists fail closed before `create_arp` / SDK enrich. Sample Musician drip copy stays plain ("Not finding a musician…").

**Mood path (Sketch UX combo-box):** Style Lab exposes `genre_artist_candidates(genre)` — genre-first Spotify search → ranked artist candidates `(name, id, followers, genres)` for home-search match lists. Mood chips stay UI-owned. Fail closed when the genre has no usable artists. See [MOOD_SEARCH.md](MOOD_SEARCH.md). Does not replace the artist name path or the 10k gate.

## Play into Logic Pro (IAC)

1. **Audio MIDI Setup** → MIDI Studio → **IAC Driver** → enable **Device is online**.
2. In Logic, set a Software Instrument track’s **MIDI In** to that IAC bus (must match the port Style Lab plays to when you have more than one).
3. Generate a sketch → **Arm → Record in Logic → Play here** (live stream alone does not write a region).
4. Optional **Before Record / Capture** (collapsed): **Count-in (1 silent bar)** Off by default for instant audition; **Loop sketch** On by default (loops until Clear IAC). Soft click is under **Advanced** (off by default — click MIDI is captured if Logic is recording). **Clear IAC** beside Play stops the stream, flushes notes, and sends MMC Stop + MIDI Stop to Logic.
5. If you enabled IAC mid-session, hit **Refresh ports** — no relaunch needed.

Requires `python-rtmidi` (installed with the package). Silence checklist under Play covers MIDI In match / track hears input / instrument loaded.

### Optional: Logic Record via Logic Pro MCP (record-only spike)

Style Lab can optionally **arm a track and punch Record** through [Logic Pro MCP](https://github.com/MongLong0214/logic-pro-mcp) (stdio JSON-RPC), then stream the sketch over the **existing IAC** path so notes land while Logic is recording.

**This does not replace IAC.** MCP is never used for MIDI import, `record_sequence`, or note send. Notes always travel IAC → Logic MIDI In.

#### Install (Mac)

Prefer Homebrew, Logic Pro MCP **≥ 3.12** (ideally **3.16**):

```bash
brew tap MongLong0214/logic-pro-mcp https://github.com/MongLong0214/logic-pro-mcp
brew trust monglong0214/logic-pro-mcp   # Homebrew 6.0+
brew install logic-pro-mcp
```

Binary on `PATH` as `LogicProMCP`, or set `LOGIC_PRO_MCP_BIN` to an absolute path.

#### Jimmy’s one-time TCC clicks (launcher app)

Grant these to the app that launches Style Lab / the bridge (Terminal, Cursor, etc.) under **System Settings → Privacy & Security**:

1. **Accessibility** — enable the launcher app.
2. **Automation → Logic Pro** — allow control.
3. **Automation → System Events** — separate target; required (Logic grant alone is not enough).
4. **PostEvent** (Input Monitoring / Accessibility PostEvent) — needed for CGEvent fallbacks.

Then: open **Logic Pro** with a project document.

#### Doctor + optional arm key

```bash
LogicProMCP doctor --profile core
# machine-readable:
LogicProMCP doctor --profile core --json
```

Optional one-time (consent required) for reliable coordinate-free arm:

```bash
# Via MCP client / tool: logic_system.setup_arm_key with consent: true
# Only after you intentionally approve Key Commands mutation in Logic.
```

#### In Style Lab

- MCP status chip: **Ready** / **Offline** (fail-closed). Offline copy: *Logic Record control offline — arm & Record in Logic manually, then Play.*
- **Record in Logic** (secondary to **Play in Logic**): when Ready → MCP `arm_only` (explicit selected or sole track; ambiguous multi-track fails closed) → MCP `transport.record` (State A only) → existing **Play into Logic** IAC stream (`send_mmc=False` so MMC does not toggle MCP Record off).
- **Clear IAC** still stops/panics the IAC stream; if this session used MCP Record, also best-effort MCP `transport.stop`.

Honest Contract: **State A confirmed** = success. State B uncertain or State C failure → fail closed (UI never pretends a take was recorded).

#### Out of scope for this spike

- **MCU control surface** setup (mixer Later).
- **Scripter** insert (plugin params Later).
- MIDI Clock emit-to-Logic changes, generator/musicality changes, MCP MIDI composition/import.

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
