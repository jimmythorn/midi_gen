# Mood search (Spotify genre → artist candidates)

Style Lab helper for Sketch UX home-search combo-box match lists. Mood chips stay UI-owned.

## Call contract

```python
from midi_gen import (
    candidates_as_combo_rows,
    genre_artist_candidates,
)

# Mood chip or typed genre under home search (not artist-name path).
result = genre_artist_candidates("ambient", limit=10)

if not result.ok:
    # Fail closed: empty combo / drip. Reasons:
    # empty_query | no_match | too_small | missing_credentials | spotify_error
    rows = []
else:
    rows = candidates_as_combo_rows(result)
    # each row: {id, name, followers, genres}

# On combo pick → existing gate → recipe (do not bypass 10k follower gate):
#   require_artist(picked["name"], force_spotify=True)
#   or generate_midi_for_style(picked["name"], ...)
```

## Credentials

Reuses Client Credentials: `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`.

Missing credentials → `ok=False`, `reason="missing_credentials"`.

## Paths (do not conflate)

| Path | Entry | Behavior |
| --- | --- | --- |
| **Artist** | typed musician name / `resolve_artist_query` | Name search first, genre fallback; 10k gate |
| **Mood** | `genre_artist_candidates` | Genre-first only; ranked candidates for combo-box |

Pattern|Progression (Engine), catalog fingerprints, Logic/IAC/Play, and Streamlit layout are out of scope for this API.
