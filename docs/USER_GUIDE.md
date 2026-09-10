# Style Lab — musician guide

Short setup and usage for playing sketches into Logic Pro. No developer jargon required.

## Quick start

Install once, then start the app:

```bash
pip install -e .
./run_ui.sh
```

Open **http://127.0.0.1:8501** in your browser. That’s Style Lab.

## Basic usage

1. **Search** for a musician, or pick a mood / featured style.
2. Click **Generate**.
3. **Listen** to the in-page piano preview.
4. **Play into Logic** when you want your software instrument to sound it.
5. **Download MIDI** when you want the file in your session or elsewhere.

Useful knobs (kept brief):

- **Pattern | Progression** — Pattern walks an arpeggio; Progression holds each chord.
- **Timing** — Double (faster), Half / Quarter (each chord lasts longer), or 1×.
- **Song-part chips** — Intro, Verse, Pre-chorus, Chorus, Bridge, Outro. Optional; they nudge the sketch toward that part of a song.

Sketches are **starting points**, not finished songs. Shape them in Logic (or re-generate) from there.

## Set up a track in Logic (IAC)

IAC is the Mac “pipe” that lets Style Lab send MIDI notes into Logic.

1. Open **Audio MIDI Setup** → **MIDI Studio** → **IAC Driver** → turn on **Device is online**.
2. In Logic: create or select a **Software Instrument** track and load an instrument (any piano, pad, synth, etc.).
3. Set that track’s **MIDI Input** to the **IAC** bus. It must match the port shown in Style Lab. If you just enabled IAC, click **Refresh ports** in Style Lab.
4. If you want to **record** a region by hand, **Arm** the track (and hit Record in Logic when you’re ready).
5. In Style Lab: **Generate** → **Play into Logic**. By default the sketch **loops until you Stop** (Clear IAC).
6. Hearing nothing? Check this silence list:
   - MIDI In on the track matches the Style Lab port
   - The track is set to hear input
   - An instrument is loaded on the track

**Recording honesty:** Play alone streams live notes. It does **not** write a MIDI region unless Logic is actually recording — either Arm + Record yourself in Logic, or use the optional **Record** button when MCP shows Ready (see below).

## Cursor API key (optional)

Only needed for **Advanced** / enrich-this-vibe (Cursor SDK). The local catalog works without a key.

1. Get a Cursor API key from your Cursor account / docs.
2. In the terminal, before starting Style Lab:

```bash
export CURSOR_API_KEY=crsr_...
./run_ui.sh
```

Never commit the key to git or paste it into a shared file.

## Optional Spotify keys

Artist search in Style Lab may need Spotify app credentials:

```bash
export SPOTIFY_CLIENT_ID=...
export SPOTIFY_CLIENT_SECRET=...
```

Never commit those. If they’re missing, you can still use the local catalog and featured styles.

## Optional Logic Record (MCP)

If Style Lab shows a green **Ready** chip for Logic Record, the **Record** button can arm the track and punch Record for you, then Play streams notes over IAC as usual.

If the chip is **Offline** (or Record isn’t there yet): in Logic do **Arm → Record** yourself, then hit **Play into Logic** in Style Lab.

Full Mac setup (Homebrew install, Accessibility / Automation permissions, `LogicProMCP doctor`) lives in the README under **Optional: Logic Record via Logic Pro MCP** when that section is on your branch — don’t dig through TCC settings unless you’re enabling that helper.
