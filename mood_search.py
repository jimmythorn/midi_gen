"""
Mood path: Spotify genre → ranked artist candidates for Sketch UX combo-box.

Style Lab owns this thin glue. Mood chips stay UI-owned; Sketch calls
``genre_artist_candidates`` for match lists under home search, then feeds a
chosen artist name into the existing gate → recipe flow.

Does not touch Pattern|Progression, catalog fingerprints, Logic/IAC/Play,
or Streamlit layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Literal, Optional, Sequence, Tuple

from .spotify_client import (
    MIN_SPOTIFY_FOLLOWERS,
    MissingSpotifyCredentials,
    SpotifyArtist,
    SpotifyClientError,
    search_artists_by_genre_with_credentials,
)

GenreRejectReason = Literal[
    "empty_query",
    "no_match",
    "too_small",
    "missing_credentials",
    "spotify_error",
]


@dataclass(frozen=True)
class ArtistCandidate:
    """One combo-box row: gate-ready Spotify artist fields."""

    id: str
    name: str
    followers_total: Optional[int]
    genres: Tuple[str, ...]


@dataclass(frozen=True)
class GenreArtistCandidates:
    """
    Result of genre → artist candidate lookup.

    ``ok`` False = fail closed (no usable candidates). Sketch UX should not
    invent artists; show empty match list / drip from ``message`` / ``reason``.
    """

    genre_query: str
    candidates: Tuple[ArtistCandidate, ...]
    ok: bool
    reason: Optional[GenreRejectReason] = None
    message: str = ""


def _as_candidate(artist: SpotifyArtist) -> Optional[ArtistCandidate]:
    if artist.type != "artist":
        return None
    artist_id = str(artist.id or "").strip()
    name = str(artist.name or "").strip()
    if not artist_id or not name:
        return None
    return ArtistCandidate(
        id=artist_id,
        name=name,
        followers_total=artist.followers_total,
        genres=tuple(artist.genres),
    )


def _genre_overlap_score(genre_query: str, genres: Sequence[str]) -> int:
    """Higher when artist genre tags match the mood query (exact > substring)."""
    q = (genre_query or "").strip().lower()
    if not q:
        return 0
    # Strip leading genre: wrapper if a caller passed a field filter.
    if q.startswith("genre:"):
        q = q[6:].strip().strip('"').strip()
    score = 0
    for raw in genres:
        g = str(raw or "").strip().lower()
        if not g:
            continue
        if g == q:
            score += 3
        elif q in g or g in q:
            score += 1
    return score


def _usable(
    candidate: ArtistCandidate,
    *,
    min_followers: int,
) -> bool:
    """Same floor policy as artist_gate: missing followers is not a reject."""
    if candidate.followers_total is None:
        return True
    return candidate.followers_total >= min_followers


def _rank_key(
    candidate: ArtistCandidate,
    *,
    genre_query: str,
) -> Tuple[int, int, str]:
    """
    Sort key (descending via negation on ints): genre overlap, followers, name.

    Artists with unknown followers rank after known counts so Sketch sees
    gate-strong hits first when Spotify sends totals.
    """
    overlap = _genre_overlap_score(genre_query, candidate.genres)
    followers = candidate.followers_total
    follower_rank = followers if followers is not None else -1
    return (overlap, follower_rank, candidate.name.lower())


def rank_artist_candidates(
    artists: Sequence[SpotifyArtist],
    *,
    genre_query: str,
    limit: int = 10,
    min_followers: int = MIN_SPOTIFY_FOLLOWERS,
) -> Tuple[Tuple[ArtistCandidate, ...], Optional[GenreRejectReason], str]:
    """
    Filter + rank Spotify artists into gate-suitable combo candidates.

    Returns (candidates, reason_if_empty, message).
    """
    typed: List[ArtistCandidate] = []
    for artist in artists:
        cand = _as_candidate(artist)
        if cand is not None:
            typed.append(cand)

    if not typed:
        return (
            (),
            "no_match",
            f"No Spotify artists for genre {genre_query!r}.",
        )

    usable = [c for c in typed if _usable(c, min_followers=min_followers)]
    if not usable:
        return (
            (),
            "too_small",
            (
                f"Spotify genre {genre_query!r} returned artists below "
                f"followers.total >= {min_followers} floor."
            ),
        )

    ranked = sorted(
        usable,
        key=lambda c: _rank_key(c, genre_query=genre_query),
        reverse=True,
    )
    capped = tuple(ranked[: max(1, min(int(limit), 50))])
    return (capped, None, f"{len(capped)} artist candidate(s) for genre {genre_query!r}.")


def candidates_as_combo_rows(
    result: GenreArtistCandidates,
) -> List[dict]:
    """JSON-friendly rows for Sketch UX combo-box match lists."""
    rows: List[dict] = []
    for c in result.candidates:
        rows.append(
            {
                "id": c.id,
                "name": c.name,
                "followers": c.followers_total,
                "genres": list(c.genres),
            }
        )
    return rows


def genre_artist_candidates(
    genre: str,
    *,
    limit: int = 10,
    min_followers: int = MIN_SPOTIFY_FOLLOWERS,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    opener: Any = None,
    genre_search=None,
) -> GenreArtistCandidates:
    """
    Mood path entry: genre query → ranked artist candidates.

    Sketch UX: call on mood chip / typed genre under home search; bind
    ``candidates_as_combo_rows(result)`` into the combo-box. On pick, pass
    ``candidate.name`` (or id+name) into existing ``require_artist`` /
    generate — do not bypass the 10k gate.

    ``genre_search`` is injectable ``(genre) -> list[SpotifyArtist]`` for tests.
    Default uses Client Credentials genre-first search.
    """
    q = (genre or "").strip()
    if not q:
        return GenreArtistCandidates(
            genre_query="",
            candidates=(),
            ok=False,
            reason="empty_query",
            message="Empty genre query — nothing to search.",
        )

    search_fn = (
        genre_search
        if genre_search is not None
        else (
            lambda g: search_artists_by_genre_with_credentials(
                g,
                client_id=client_id,
                client_secret=client_secret,
                limit=max(limit, 10),
                opener=opener,
            )
        )
    )

    try:
        artists = search_fn(q)
    except MissingSpotifyCredentials as exc:
        return GenreArtistCandidates(
            genre_query=q,
            candidates=(),
            ok=False,
            reason="missing_credentials",
            message=str(exc),
        )
    except SpotifyClientError as exc:
        return GenreArtistCandidates(
            genre_query=q,
            candidates=(),
            ok=False,
            reason="spotify_error",
            message=f"Spotify genre search failed: {exc}",
        )

    candidates, reason, message = rank_artist_candidates(
        artists,
        genre_query=q,
        limit=limit,
        min_followers=min_followers,
    )
    if reason is not None:
        return GenreArtistCandidates(
            genre_query=q,
            candidates=(),
            ok=False,
            reason=reason,
            message=message,
        )
    return GenreArtistCandidates(
        genre_query=q,
        candidates=candidates,
        ok=True,
        reason=None,
        message=message,
    )
