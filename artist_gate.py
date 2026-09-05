"""
Reject-before-generate artist gate.

Product lock:
  1. Typed search / feel always hits Spotify (force_spotify).
  2. Browse catalog pick with empty search may accept locally.
  3. Spotify Artist Search (name, then genre: field) accepts only
     type=artist AND followers.total >= MIN_SPOTIFY_FOLLOWERS (10_000).
  4. Spotify down (HTTP / missing credentials) bypasses to the Cursor
     music-identity agent.
  5. Spotify content reject (no_match / not_a_musician / too_small) stays reject.
  6. Else drip-reject (no create_arp / Cursor SDK / generate).

Spotify has no monthly-listeners field; followers.total is the floor proxy.
Popularity is not the threshold. Catalog/alias never hit this floor.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Literal, Optional, Union

from .musician_styles import MUSICIAN_STYLE_CATALOG, alias_target_ids
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
AcceptSource = Literal["catalog", "spotify", "agent"]


@dataclass(frozen=True)
class ArtistGateAccept:
    """Query cleared the gate — generation / SDK may proceed."""

    query: str
    source: AcceptSource
    message: str = ""
    spotify_artist: Optional[SpotifyArtist] = None
    agent_name: Optional[str] = None
    agent_kind: Optional[str] = None
    agent_genres: tuple[str, ...] = ()
    accepted: Literal[True] = True


@dataclass(frozen=True)
class ArtistGateReject:
    """Fail-closed reject — Sample Musician can drip ``reason`` in the UI."""

    query: str
    reason: RejectReason
    message: str = ""
    accepted: Literal[False] = False


ArtistGateResult = Union[ArtistGateAccept, ArtistGateReject]

_SPOTIFY_DOWN_UNTIL = 0.0
_SPOTIFY_DOWN_HOLD_S = 45.0


def clear_spotify_down_cache() -> None:
    """Test helper — forget a cached Spotify outage."""
    global _SPOTIFY_DOWN_UNTIL
    _SPOTIFY_DOWN_UNTIL = 0.0


def _mark_spotify_down() -> None:
    global _SPOTIFY_DOWN_UNTIL
    _SPOTIFY_DOWN_UNTIL = time.monotonic() + _SPOTIFY_DOWN_HOLD_S


def _spotify_marked_down() -> bool:
    return time.monotonic() < _SPOTIFY_DOWN_UNTIL


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
    True only for a catalog musician name, alias, or pinned identity.

    Typed search still hits Spotify via ``force_spotify``.
    """
    if _catalog_identity(identity_name):
        return True
    q = (query or "").strip()
    if not q:
        return False
    if _catalog_identity(q):
        return True
    if alias_target_ids(q):
        return True
    return any(_name_token_overlap(q, profile) for profile in MUSICIAN_STYLE_CATALOG)


def _default_music_identity(query: str):
    from .music_identity import lookup_music_identity_with_sdk

    return lookup_music_identity_with_sdk(query)


def _apply_music_identity(search_q: str, music_identity):
    """Run agent identity. None = unavailable (fall through)."""
    from .music_identity import MusicIdentityAccept, MusicIdentityReject

    try:
        ident = music_identity(search_q)
    except Exception:
        return None
    if ident is None:
        return None
    if isinstance(ident, MusicIdentityReject):
        return ArtistGateReject(
            query=search_q,
            reason=ident.reason,
            message=ident.message or f"Not a musician: {search_q!r}.",
        )
    if isinstance(ident, MusicIdentityAccept):
        return ArtistGateAccept(
            query=search_q,
            source="agent",
            agent_name=ident.name,
            agent_kind=ident.kind,
            agent_genres=ident.genres,
            message=f"Agent music identity: {ident.kind} {ident.name!r}.",
        )
    return None


def resolve_artist_query(
    query: str,
    *,
    identity_name: Optional[str] = None,
    spotify_search=None,
    music_identity=None,
    force_spotify: bool = False,
    allow_cursor_fallback: bool = True,
) -> ArtistGateResult:
    """
    Pre-generate artist gate shared by lookup and generate paths.

    ``spotify_search`` is an injectable callable(query) -> list[SpotifyArtist]
    (tests); default uses Client Credentials Artist Search.

    ``music_identity`` is an injectable callable(query) -> MusicIdentityResult | None.
    Production calls it only when Spotify is down and
    ``allow_cursor_fallback`` is true.

    The home pre-paint gate sets ``allow_cursor_fallback=False`` so a 429
    can show Generating; ``require_artist`` during generate then asks Cursor.

    Injected ``spotify_search`` without ``music_identity`` skips the agent so
    existing Spotify unit tests stay Spotify-only.

    ``force_spotify`` is the Search / feel path — skip catalog unless a
    catalog identity is already pinned.
    """
    q = (query or "").strip()
    identity = (identity_name or "").strip() or None

    if not q and not identity:
        return ArtistGateReject(
            query=q,
            reason="empty_query",
            message="Empty musician query — nothing to generate.",
        )

    # Browse / pinned who stay local. Typed search without a pin hits Spotify.
    pinned_catalog = _catalog_identity(identity)
    if pinned_catalog or (
        not force_spotify
        and _local_catalog_identity_hit(q or identity or "", identity_name=identity)
    ):
        who = identity or q
        return ArtistGateAccept(
            query=q or who,
            source="catalog",
            message=f"Local catalog / alias hit for {who!r}.",
        )

    search_q = identity or q
    search_fn = (
        spotify_search if spotify_search is not None else search_artists_with_credentials
    )
    spotify_down: Optional[ArtistGateReject] = None
    artists: List[SpotifyArtist] = []
    if spotify_search is None and _spotify_marked_down():
        spotify_down = ArtistGateReject(
            query=search_q,
            reason="spotify_error",
            message="Spotify unavailable (cached).",
        )
    else:
        try:
            artists = search_fn(search_q)
        except MissingSpotifyCredentials as exc:
            spotify_down = ArtistGateReject(
                query=search_q,
                reason="missing_credentials",
                message=str(exc),
            )
        except SpotifyClientError as exc:
            if spotify_search is None:
                _mark_spotify_down()
            spotify_down = ArtistGateReject(
                query=search_q,
                reason="spotify_error",
                message=f"Spotify artist search failed: {exc}",
            )

    if spotify_down is not None:
        identity_fn = music_identity
        if (
            allow_cursor_fallback
            and identity_fn is None
            and spotify_search is None
        ):
            identity_fn = _default_music_identity
        if allow_cursor_fallback and identity_fn is not None:
            agent_result = _apply_music_identity(search_q, identity_fn)
            if agent_result is not None:
                return agent_result
            return ArtistGateAccept(
                query=search_q,
                source="agent",
                agent_name=search_q,
                agent_kind="artist",
                message=(
                    f"Spotify down; Cursor identity unavailable — generate {search_q!r}."
                ),
            )
        return spotify_down

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
    music_identity=None,
    force_spotify: bool = False,
    allow_cursor_fallback: bool = True,
) -> ArtistGateAccept:
    """Gate helper: return accept or raise ArtistRejected."""
    result = resolve_artist_query(
        query,
        identity_name=identity_name,
        spotify_search=spotify_search,
        music_identity=music_identity,
        force_spotify=force_spotify,
        allow_cursor_fallback=allow_cursor_fallback,
    )
    if isinstance(result, ArtistGateReject) or not result.accepted:
        raise ArtistRejected(result)  # type: ignore[arg-type]
    return result
