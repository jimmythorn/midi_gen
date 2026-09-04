"""MIDI generation package with musician-style lookup and effects."""

from .arpeggio_generation import (
    apply_extend_factor,
    create_arp,
    resolve_drone_held,
    resolve_extend_factor,
)
from .artist_gate import ArtistGateReject, ArtistRejected, resolve_artist_query
from .cursor_style_lookup import generate_midi_for_style, lookup_musician_style
from .musician_styles import (
    list_musicians,
    list_styles,
    resolve_section_recipe,
)

__all__ = [
    "ArtistGateReject",
    "ArtistRejected",
    "apply_extend_factor",
    "create_arp",
    "generate_midi_for_style",
    "lookup_musician_style",
    "list_musicians",
    "list_styles",
    "resolve_artist_query",
    "resolve_drone_held",
    "resolve_extend_factor",
    "resolve_section_recipe",
]
