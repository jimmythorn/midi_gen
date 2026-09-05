"""Vanilla-JS Streamlit WAV preview that keeps playing across reruns."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

import streamlit.components.v1 as components

_cmp = components.declare_component(
    "preview_audio",
    path=str(Path(__file__).parent / "frontend"),
)


def preview_audio(
    *,
    wav_bytes: bytes | None,
    rev: int = 0,
    key: Optional[str] = None,
) -> None:
    _cmp(
        wav_b64=base64.b64encode(wav_bytes or b"").decode("ascii"),
        rev=int(rev),
        key=key,
        default=None,
    )
