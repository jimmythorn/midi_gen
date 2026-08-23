"""Helpers for summarizing generated MIDI as test/debug output."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import mido

from .notes import note_to_name


def summarize_midi_file(path: str, max_notes: int = 48) -> Dict[str, Any]:
    """
    Parse a MIDI file into a compact test-output summary for the UI/CLI.
    """
    mid = mido.MidiFile(path)
    note_ons: List[Tuple[int, int, int]] = []  # tick, note, velocity
    pitch_bends = 0
    abs_tick = 0

    # Use first track that has notes; accumulate absolute time per track
    for track in mid.tracks:
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                note_ons.append((abs_tick, msg.note, msg.velocity))
            elif msg.type == "pitchwheel" and getattr(msg, "pitch", 0) != 0:
                pitch_bends += 1

    note_ons.sort(key=lambda x: x[0])
    pitches = [n for _, n, _ in note_ons]
    velocities = [v for _, _, v in note_ons]
    pitch_counts = Counter(pitches)

    preview = [
        {
            "tick": tick,
            "note": note,
            "name": note_to_name(note),
            "velocity": vel,
        }
        for tick, note, vel in note_ons[:max_notes]
    ]

    duration_beats = 0.0
    if mid.ticks_per_beat and note_ons:
        last_tick = max(t for t, _, _ in note_ons)
        duration_beats = last_tick / float(mid.ticks_per_beat)

    return {
        "path": str(path),
        "filename": Path(path).name,
        "ticks_per_beat": mid.ticks_per_beat,
        "track_count": len(mid.tracks),
        "note_on_count": len(note_ons),
        "unique_pitches": len(pitch_counts),
        "pitch_bend_events": pitch_bends,
        "duration_beats_approx": round(duration_beats, 2),
        "pitch_range": {
            "min": note_to_name(min(pitches)) if pitches else None,
            "max": note_to_name(max(pitches)) if pitches else None,
        },
        "velocity_range": {
            "min": min(velocities) if velocities else None,
            "max": max(velocities) if velocities else None,
            "avg": round(sum(velocities) / len(velocities), 1) if velocities else None,
        },
        "most_common_notes": [
            {"name": note_to_name(n), "count": c} for n, c in pitch_counts.most_common(8)
        ],
        "note_preview": preview,
        "truncated": len(note_ons) > max_notes,
    }


def events_to_roll_rows(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert note preview into rows suitable for a simple table / chart."""
    return [
        {
            "index": i,
            "beat": round(row["tick"] / max(summary.get("ticks_per_beat") or 480, 1), 3),
            "note": row["name"],
            "midi": row["note"],
            "velocity": row["velocity"],
        }
        for i, row in enumerate(summary.get("note_preview") or [])
    ]


def format_summary_text(summary: Dict[str, Any]) -> str:
    lines = [
        f"File: {summary['filename']}",
        f"Notes: {summary['note_on_count']}  |  Unique pitches: {summary['unique_pitches']}  |  "
        f"Pitch bends: {summary['pitch_bend_events']}",
        f"Range: {summary['pitch_range']['min']} – {summary['pitch_range']['max']}",
        f"Velocity: {summary['velocity_range']['min']}–{summary['velocity_range']['max']} "
        f"(avg {summary['velocity_range']['avg']})",
        f"Approx length: {summary['duration_beats_approx']} beats",
        "Top notes: "
        + ", ".join(f"{n['name']}×{n['count']}" for n in summary["most_common_notes"]),
        "Preview: "
        + " ".join(n["name"] for n in summary["note_preview"][:24])
        + (" …" if summary.get("truncated") else ""),
    ]
    return "\n".join(lines)
