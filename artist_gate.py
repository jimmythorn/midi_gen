"""
Reject-before-generate artist gate.

Product lock:
  1. Local catalog / alias hit → accept (never call Spotify).
  2. Else Spotify Artist Search (Client Credentials) → accept only if type=artist.
  3. Else drip-reject (no create_arp / Cursor SDK / generate).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Union

from .musician_styles import (
    MUSICIAN_STYLE_CATALOG,
    alias_target_ids,
    find_profiles,
    score_profile,
)
from .spotify_client import (
    MissingSpotifyCredentials,
    SpotifyArtist,
    SpotifyClientError,
    search_artists_with_credentials,
)

RejectReason = Literal[
    "not_a_musician",
    "missing_credentials",
    "no_match",
    "empty_query",
    "spotify_error",
]
AcceptSource = Literal["catalog", "spotify"]


@dataclass(frozen=True)
class ArtistGateAccept:
    """Query cleared the gate — generation / SDK may proceed."""

    query: str
    source: AcceptSource
    message: str = ""
    spotify_artist: Optional[SpotifyArtist] = None
    accepted: Literal[True] = True


@dataclass(frozen=True)
class ArtistGateReject:
    """Fail-closed reject — Sample Musician can drip ``reason`` in the UI."""

    query: str
    reason: RejectReason
    message: str = ""
    accepted: Literal[False] = False


ArtistGateResult = Union[ArtistGateAccept, ArtistGateReject]


class ArtistRejected(Exception):
    """Raised when generate/lookup must stop before create_arp or SDK enrich."""

    def __init__(self, result: ArtistGateReject):
        self.result = result
        msg = result.message or f"Artist rejected ({result.reason})"
        super().__init__(msg)


def _catalog_identity(name: Optional[str]) -> bool:
    n = (name or "").strip().lower()
    if not n:
        return False
    return any(p.name.lower() == n for p in MUSICIAN_STYLE_CATALOG)


def _name_token_overlap(query: str, profile) -> bool:
    """True when query shares a token with the musician name or id (not description-only)."""
    import re

    def tokens(text: str) -> set[str]:
        return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t}

    q_tokens = tokens(query)
    if not q_tokens:
        return False
    name_tokens = tokens(profile.name) | tokens(profile.id.replace("_", " "))
    return bool(q_tokens & name_tokens)


def _local_catalog_or_alias_hit(
    query: str,
    *,
    identity_name: Optional[str] = None,
) -> bool:
    """
    True for curated catalog / alias hits.

    Weak description-only keyword scores (e.g. \"music\" in a blurb) do not count —
    those must fall through to Spotify so non-artists fail closed.
    """
    if _catalog_identity(identity_name):
        return True
    q = (query or "").strip()
    if not q:
        return False
    if alias_target_ids(q):
        return True
    for profile in find_profiles(q, limit=5):
        if score_profile(q, profile) >= 5.0:
            return True
        if _name_token_overlap(q, profile):
            return True
    return False


def resolve_artist_query(
    query: str,
    *,
    identity_name: Optional[str] = None,
    spotify_search=None,
) -> ArtistGateResult:
    """
    Pre-generate artist gate shared by lookup and generate paths.

    ``spotify_search`` is an injectable callable(query) -> list[SpotifyArtist]
    (tests); default uses Client Credentials Artist Search.
    """
    q = (query or "").strip()
    identity = (identity_name or "").strip() or None

    if not q and not identity:
        return ArtistGateReject(
            query=q,
            reason="empty_query",
            message="Empty musician query — nothing to generate.",
        )

    # Catalog / alias hit: accept and skip Spotify entirely.
    if _local_catalog_or_alias_hit(q or identity or "", identity_name=identity):
        who = identity or q
        return ArtistGateAccept(
            query=q or who,
            source="catalog",
            message=f"Local catalog / alias hit for {who!r}.",
        )

    search_q = identity or q
    search_fn = spotify_search if spotify_search is not None else search_artists_with_credentials
    try:
        artists = search_fn(search_q)
    except MissingSpotifyCredentials as exc:
        return ArtistGateReject(
            query=search_q,
            reason="missing_credentials",
            message=str(exc),
        )
    except SpotifyClientError as exc:
        return ArtistGateReject(
            query=search_q,
            reason="spotify_error",
            message=f"Spotify artist search failed: {exc}",
        )

    if not artists:
        return ArtistGateReject(
            query=search_q,
            reason="no_match",
            message=f"No Spotify artist match for {search_q!r}.",
        )

    # Accept only explicit type=artist rows (Artist Search should already filter).
    typed = [a for a in artists if a.type == "artist"]
    if not typed:
        return ArtistGateReject(
            query=search_q,
            reason="not_a_musician",
            message=f"Spotify returned no type=artist results for {search_q!r}.",
        )

    hit = typed[0]
    return ArtistGateAccept(
        query=search_q,
        source="spotify",
        spotify_artist=hit,
        message=f"Spotify artist match: {hit.name}.",
    )


def require_artist(
    query: str,
    *,
    identity_name: Optional[str] = None,
    spotify_search=None,
) -> ArtistGateAccept:
    """Gate helper: return accept or raise ArtistRejected."""
    result = resolve_artist_query(
        query,
        identity_name=identity_name,
        spotify_search=spotify_search,
    )
    if isinstance(result, ArtistGateReject) or not result.accepted:
        raise ArtistRejected(result)  # type: ignore[arg-type]
    return result
