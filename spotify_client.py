"""
Spotify Web API client (Client Credentials, Artist Search only).

Uses stdlib urllib — no user OAuth. Credentials from env:
  SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

TOKEN_URL = "https://accounts.spotify.com/api/token"
SEARCH_URL = "https://api.spotify.com/v1/search"


class SpotifyClientError(Exception):
    """HTTP / config failure talking to Spotify."""


# Product lock: Spotify has no monthly-listeners field; followers.total is the proxy floor.
MIN_SPOTIFY_FOLLOWERS = 10_000


@dataclass(frozen=True)
class SpotifyArtist:
    id: str
    name: str
    type: str
    followers_total: Optional[int]
    raw: Dict[str, Any]


def _parse_followers_total(item: Dict[str, Any]) -> Optional[int]:
    """
    Extract followers.total from a Spotify artist search item.

    Missing / malformed followers → None (caller fail-closes).
    Never uses popularity or scrapes web/charts.
    """
    followers = item.get("followers")
    if not isinstance(followers, dict):
        return None
    total = followers.get("total")
    if isinstance(total, bool):
        return None
    if isinstance(total, int):
        return total
    if isinstance(total, float) and total.is_integer():
        return int(total)
    return None


def load_spotify_credentials(
    *,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Optional[Tuple[str, str]]:
    """
    Return (client_id, client_secret) or None if either is missing.

    Explicit args win; otherwise read SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET.
    """
    cid = (client_id if client_id is not None else os.environ.get("SPOTIFY_CLIENT_ID", "")).strip()
    secret = (
        client_secret if client_secret is not None else os.environ.get("SPOTIFY_CLIENT_SECRET", "")
    ).strip()
    if not cid or not secret:
        return None
    return cid, secret


def fetch_client_credentials_token(
    client_id: str,
    client_secret: str,
    *,
    opener: Any = None,
) -> str:
    """POST client_credentials grant; return access_token."""
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    urlopen = opener if opener is not None else urllib.request.urlopen
    try:
        with urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise SpotifyClientError(f"Spotify token HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise SpotifyClientError(f"Spotify token request failed: {exc}") from exc

    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not token or not isinstance(token, str):
        raise SpotifyClientError("Spotify token response missing access_token")
    return token


def search_artists(
    query: str,
    *,
    access_token: str,
    limit: int = 5,
    opener: Any = None,
) -> List[SpotifyArtist]:
    """
    GET /v1/search?type=artist. Returns typed artist rows only (type == 'artist').
    """
    q = (query or "").strip()
    if not q:
        return []
    params = urllib.parse.urlencode(
        {
            "q": q,
            "type": "artist",
            "limit": max(1, min(int(limit), 50)),
        }
    )
    req = urllib.request.Request(
        f"{SEARCH_URL}?{params}",
        method="GET",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    urlopen = opener if opener is not None else urllib.request.urlopen
    try:
        with urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise SpotifyClientError(f"Spotify search HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise SpotifyClientError(f"Spotify search request failed: {exc}") from exc

    items = []
    if isinstance(payload, dict):
        artists = payload.get("artists") or {}
        if isinstance(artists, dict):
            raw_items = artists.get("items") or []
            if isinstance(raw_items, list):
                items = raw_items

    out: List[SpotifyArtist] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "")
        artist_id = str(item.get("id") or "")
        name = str(item.get("name") or "")
        if not artist_id:
            continue
        out.append(
            SpotifyArtist(
                id=artist_id,
                name=name,
                type=item_type,
                followers_total=_parse_followers_total(item),
                raw=item,
            )
        )
    return out


def search_artists_with_credentials(
    query: str,
    *,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    limit: int = 5,
    opener: Any = None,
) -> List[SpotifyArtist]:
    """
    Resolve env/explicit credentials, fetch token, search artists.

    Raises SpotifyClientError on HTTP failure.
    Raises MissingSpotifyCredentials when id/secret absent.
    """
    creds = load_spotify_credentials(client_id=client_id, client_secret=client_secret)
    if creds is None:
        raise MissingSpotifyCredentials(
            "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET are required for artist search"
        )
    token = fetch_client_credentials_token(creds[0], creds[1], opener=opener)
    return search_artists(query, access_token=token, limit=limit, opener=opener)


class MissingSpotifyCredentials(SpotifyClientError):
    """Client id/secret not configured."""
