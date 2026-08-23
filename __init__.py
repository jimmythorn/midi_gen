"""MIDI generation package with musician-style lookup and effects."""

from .arpeggio_generation import create_arp
from .cursor_style_lookup import generate_midi_for_style, lookup_musician_style
from .musician_styles import list_musicians, list_styles

__all__ = [
    "create_arp",
    "generate_midi_for_style",
    "lookup_musician_style",
    "list_musicians",
    "list_styles",
]
