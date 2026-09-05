"""Vanilla-JS Streamlit note editor (piano roll + step grid)."""

from pathlib import Path
from typing import Any, Optional

import streamlit.components.v1 as components

_cmp = components.declare_component(
    "note_editor",
    path=str(Path(__file__).parent / "frontend"),
)

PREVIEW_CLOCK_CHANNEL = "midi_gen_preview_clock"


def preview_step_index(t_sec: float, bpm: float, steps: int) -> int:
    """Column for a 4/4 bar of ``steps`` slots at ``t_sec``."""
    n = max(1, int(steps))
    beats = float(t_sec) * float(bpm) / 60.0
    return int(beats * n / 4.0) % n


def note_editor(
    *,
    notes=None,
    mode: str = "roll",
    steps: int = 8,
    ticks_per_beat: int = 480,
    bpm: int = 120,
    gates=None,
    pitches=None,
    key: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    return _cmp(
        notes=notes or [],
        mode=mode,
        steps=int(steps),
        ticks_per_beat=int(ticks_per_beat),
        bpm=int(bpm),
        gates=gates,
        pitches=pitches,
        key=key,
        default=None,
    )
