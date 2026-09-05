"""MIDI generation package with musician-style lookup and effects."""

from .arpeggio_generation import (
    apply_extend_factor,
    apply_generation_mode,
    apply_timing_factor,
    create_arp,
    resolve_drone_held,
    resolve_extend_factor,
    resolve_timing_factor,
)
from .artist_gate import ArtistGateReject, ArtistRejected, resolve_artist_query
from .cursor_style_lookup import generate_midi_for_style, lookup_musician_style
from .mood_search import (
    ArtistCandidate,
    GenreArtistCandidates,
    candidates_as_combo_rows,
    clear_genre_artist_cache,
    genre_artist_candidates,
    mood_combo_names,
)
from .musician_styles import (
    list_musicians,
    list_styles,
    resolve_section_recipe,
)

__all__ = [
    "ArtistCandidate",
    "ArtistGateReject",
    "ArtistRejected",
    "GenreArtistCandidates",
    "apply_extend_factor",
    "apply_generation_mode",
    "apply_timing_factor",
    "candidates_as_combo_rows",
    "clear_genre_artist_cache",
    "create_arp",
    "generate_midi_for_style",
    "genre_artist_candidates",
    "lookup_musician_style",
    "list_musicians",
    "list_styles",
    "mood_combo_names",
    "resolve_artist_query",
    "resolve_drone_held",
    "resolve_extend_factor",
    "resolve_section_recipe",
    "resolve_timing_factor",
]
