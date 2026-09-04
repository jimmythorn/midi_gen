# Mood Search via Spotify Genres

Style Lab API so Sketch UX can populate home-search combo-box match lists from Spotify genre queries, without rewriting Streamlit layout, Pattern|Progression, or Logic/IAC/Play.

## Completed Tasks

- [x] Reuse Client Credentials Spotify client (`SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`)
- [x] Genre-first search helper (does not replace name-first artist path)
- [x] Ranked artist candidates API (name, id, followers, genres) for gate → recipe
- [x] Fail closed when genre has no usable artists
- [x] Unit tests (no network)
- [x] Document Sketch UX call path

## In Progress Tasks

- [ ] PR review / merge

## Future Tasks

- [ ] Sketch UX wires mood chips + combo-box to `genre_artist_candidates`
- [ ] Optional artist hydrate if search payloads omit followers/genres in prod

## Implementation Plan

1. `spotify_client.search_artists_by_genre` — always `genre:"…"` field filter.
2. `mood_search.genre_artist_candidates` — Style Lab glue: credentials → genre search → filter/rank → fail-closed result.
3. Keep `search_artists_for_query` / `resolve_artist_query` artist path + 10k follower gate intact.
4. Export from package `__init__`; short doc for Sketch UX.

### Relevant Files

- `spotify_client.py` — genre-first search primitive ✅
- `mood_search.py` — ranked candidates API + combo-row helper ✅
- `tests/test_mood_search.py` — unit tests ✅
- `MOOD_SEARCH.md` — Sketch UX call contract ✅
- `__init__.py` — public exports ✅
- `README.md` — pointer to mood API ✅
