"""Vanilla-JS Streamlit note editor (piano roll + step grid)."""

from pathlib import Path
from typing import Any, Optional

import streamlit.components.v1 as components

_cmp = components.declare_component(
    "note_editor",
    path=str(Path(__file__).parent / "frontend"),
)


def note_editor(
    *,
    notes=None,
    mode: str = "roll",
    steps: int = 8,
    ticks_per_beat: int = 480,
    gates=None,
    pitches=None,
    key: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    return _cmp(
        notes=notes or [],
        mode=mode,
        steps=int(steps),
        ticks_per_beat=int(ticks_per_beat),
        gates=gates,
        pitches=pitches,
        key=key,
        default=None,
    )
