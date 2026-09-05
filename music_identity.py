"""
Music-identity resolver — Cursor fallback when Spotify is down.

The agent answers: is this a recording/performing musician or a named
genre? It does not write MIDI. Production calls it only after Spotify fails.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional, Tuple, Union

IdentityKind = Literal["artist", "genre"]
IdentityRejectReason = Literal["not_a_musician", "no_match"]

MUSIC_IDENTITY_JSON_SCHEMA = """
Return one JSON object only. No prose.

Music and musical composition only: recording/performing musicians, bands,
composers, DJs, or named music genres/styles. Reject people who are not
musicians. Reject non-music topics.

{
  "ok": true or false,
  "kind": "artist" or "genre",
  "name": "canonical musician or genre name",
  "genres": ["tag", "..."],
  "confidence": 0.0 to 1.0,
  "reason": "not_a_musician" or "no_match"
}

When ok is false, kind and name may be empty. reason is required.
When ok is true, kind and name are required. reason may be empty.
"""


@dataclass(frozen=True)
class MusicIdentityAccept:
    query: str
    kind: IdentityKind
    name: str
    genres: Tuple[str, ...] = ()
    confidence: float = 0.0


@dataclass(frozen=True)
class MusicIdentityReject:
    query: str
    reason: IdentityRejectReason
    message: str = ""


MusicIdentityResult = Union[MusicIdentityAccept, MusicIdentityReject]

_IDENTITY_CACHE: dict[str, MusicIdentityResult] = {}
_IDENTITY_CACHE_LIMIT = 64


def clear_music_identity_cache() -> None:
    _IDENTITY_CACHE.clear()


def _cache_key(query: str) -> str:
    return (query or "").strip().lower()


def _cache_get(query: str) -> Optional[MusicIdentityResult]:
    return _IDENTITY_CACHE.get(_cache_key(query))


def _cache_put(query: str, result: MusicIdentityResult) -> MusicIdentityResult:
    key = _cache_key(query)
    if key not in _IDENTITY_CACHE and len(_IDENTITY_CACHE) >= _IDENTITY_CACHE_LIMIT:
        _IDENTITY_CACHE.pop(next(iter(_IDENTITY_CACHE)))
    _IDENTITY_CACHE[key] = result
    return result


def _as_str_list(raw: Any) -> Tuple[str, ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    out: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return tuple(out)


def parse_music_identity(payload: Any, *, query: str) -> Optional[MusicIdentityResult]:
    """
    Validate an agent JSON object. None = unusable payload (treat as unavailable).
    """
    if not isinstance(payload, dict):
        return None
    ok = payload.get("ok")
    if not isinstance(ok, bool):
        return None
    q = (query or "").strip()
    if not ok:
        reason = str(payload.get("reason") or "").strip()
        if reason not in ("not_a_musician", "no_match"):
            reason = "not_a_musician"
        return MusicIdentityReject(
            query=q,
            reason=reason,  # type: ignore[arg-type]
            message=str(payload.get("message") or "").strip(),
        )
    kind = str(payload.get("kind") or "").strip().lower()
    name = str(payload.get("name") or "").strip()
    if kind not in ("artist", "genre") or not name:
        return None
    try:
        confidence = float(payload.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < 0:
        confidence = 0.0
    if confidence > 1:
        confidence = 1.0
    return MusicIdentityAccept(
        query=q,
        kind=kind,  # type: ignore[arg-type]
        name=name,
        genres=_as_str_list(payload.get("genres")),
        confidence=confidence,
    )


def lookup_music_identity_with_sdk(query: str) -> Optional[MusicIdentityResult]:
    """Ask the Cursor agent for a music-identity verdict. None if SDK is down."""
    from .cursor_style_lookup import _extract_json_object, cursor_sdk_available

    q = (query or "").strip()
    if not q or not cursor_sdk_available():
        return None
    cached = _cache_get(q)
    if cached is not None:
        return cached

    from .music_agent import MUSIC_SANDBOX_RULES, create_music_agent
    import os

    prompt = (
        f"{MUSIC_SANDBOX_RULES}\n"
        f"Query: {q!r}\n\n"
        f"{MUSIC_IDENTITY_JSON_SCHEMA}"
    )
    api_key = os.environ["CURSOR_API_KEY"]
    try:
        with create_music_agent(api_key=api_key, name="midi-gen-identity") as agent:
            run = agent.send(prompt)
            raw = run.text() if hasattr(run, "text") else str(run)
            if callable(raw):
                raw = raw()
    except Exception:
        return None
    parsed = parse_music_identity(_extract_json_object(str(raw)), query=q)
    if parsed is None:
        return None
    return _cache_put(q, parsed)
