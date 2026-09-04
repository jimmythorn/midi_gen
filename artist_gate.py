"""
Reject-before-generate artist gate.

Product lock:
  1. Typed search / feel always hits Spotify (force_spotify).
  2. Browse catalog pick with empty search may accept locally.
  3. Spotify Artist Search (name, then genre: field) accepts only
     type=artist AND followers.total >= MIN_SPOTIFY_FOLLOWERS (10_000).
  4. Else drip-reject (no create_arp / Cursor SDK / generate).

Spotify has no monthly-listeners field; followers.total is the floor proxy.
Popularity is not the threshold. Catalog/alias never hit this floor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Union

from .musician_styles import MUSICIAN_STYLE_CATALOG
from .spotify_client import (
    MIN_SPOTIFY_FOLLOWERS,
    MissingSpotifyCredentials,
    SpotifyArtist,
    SpotifyClientError,
    search_artists_with_credentials,
)

RejectReason = Literal[
    "not_a_musician",
    "too_small",
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
    """True when query shares a token with the musician name (not tags / id)."""
    import re

    def tokens(text: str) -> set[str]:
        return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t}

    q_tokens = tokens(query)
    if not q_tokens:
        return False
    return bool(q_tokens & tokens(profile.name))


def _local_catalog_identity_hit(
    query: str,
    *,
    identity_name: Optional[str] = None,
) -> bool:
    """
    True only for a catalog musician name (or pinned identity).

    Style aliases and vibe tags do not count — those query Spotify for artists.
    """
    if _catalog_identity(identity_name):
        return True
    q = (query or "").strip()
    if not q:
        return False
    if _catalog_identity(q):
        return True
    return any(_name_token_overlap(q, profile) for profile in MUSICIAN_STYLE_CATALOG)


def resolve_artist_query(
    query: str,
    *,
    identity_name: Optional[str] = None,
    spotify_search=None,
    force_spotify: bool = False,
) -> ArtistGateResult:
    """
    Pre-generate artist gate shared by lookup and generate paths.

    ``spotify_search`` is an injectable callable(query) -> list[SpotifyArtist]
    (tests); default uses Client Credentials Artist Search.

    ``force_spotify`` is the Search / feel path — never catalog-short-circuit.
    """
    q = (query or "").strip()
    identity = (identity_name or "").strip() or None

    if not q and not identity:
        return ArtistGateReject(
            query=q,
            reason="empty_query",
            message="Empty musician query — nothing to generate.",
        )

    # Browse pick only. Typed search always continues to Spotify.
    if not force_spotify and _local_catalog_identity_hit(
        q or identity or "", identity_name=identity
    ):
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

    # Accept only explicit type=artist rows with a name.
    typed = [
        a for a in artists if a.type == "artist" and a.id and str(a.name or "").strip()
    ]
    if not typed:
        return ArtistGateReject(
            query=search_q,
            reason="not_a_musician",
            message=f"Spotify returned no type=artist results for {search_q!r}.",
        )

    # Floor only when Spotify sends followers.total. Client Credentials search
    # currently omits followers/genres; missing count is not a reject.
    qualifying = [
        a
        for a in typed
        if a.followers_total is None or a.followers_total >= MIN_SPOTIFY_FOLLOWERS
    ]
    if not qualifying:
        return ArtistGateReject(
            query=search_q,
            reason="too_small",
            message=(
                f"Spotify artist(s) for {search_q!r} below "
                f"followers.total >= {MIN_SPOTIFY_FOLLOWERS} floor."
            ),
        )

    hit = qualifying[0]
    return ArtistGateAccept(
        query=search_q,
        source="spotify",
        spotify_artist=hit,
        message=f"Spotify artist match: {hit.name} ({hit.followers_total} followers).",
    )


def require_artist(
    query: str,
    *,
    identity_name: Optional[str] = None,
    spotify_search=None,
    force_spotify: bool = False,
) -> ArtistGateAccept:
    """Gate helper: return accept or raise ArtistRejected."""
    result = resolve_artist_query(
        query,
        identity_name=identity_name,
        spotify_search=spotify_search,
        force_spotify=force_spotify,
    )
    if isinstance(result, ArtistGateReject) or not result.accepted:
        raise ArtistRejected(result)  # type: ignore[arg-type]
    return result
