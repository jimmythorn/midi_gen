"""
Bar-by-bar pattern development for arpeggio sketches.

Seeds a short cell, then mutates every N bars so sketches evolve instead of
tiling one cycle forever. Defaults keep backward-compatible static tiling.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Sequence, Union

Note = Union[int, None]

DEFAULT_MUTATE_OPS = ("add_attack", "add_rest", "invert", "thin", "phase_creep")


def normalize_development(raw: Any) -> Optional[Dict[str, Any]]:
    """
    Normalize optional development config.

    Accepts:
      - None / False / {} → no development (caller tiles statically)
      - True → sensible defaults (mutate every bar)
      - dict with seed_bars / mutate_every_n / mutate_ops / …
    """
    if raw is None or raw is False:
        return None
    if raw is True:
        raw = {}
    if not isinstance(raw, dict):
        return None
    if raw.get("enabled") is False:
        return None

    ops = raw.get("mutate_ops") or list(DEFAULT_MUTATE_OPS)
    if isinstance(ops, str):
        ops = [ops]
    ops = [str(op).strip().lower() for op in ops if str(op).strip()]
    if not ops:
        ops = list(DEFAULT_MUTATE_OPS)

    seed_bars = int(raw.get("seed_bars", 1))
    seed_bars = max(1, min(2, seed_bars))
    mutate_every_n = int(raw.get("mutate_every_n", 1))
    mutate_every_n = max(1, mutate_every_n)
    additive_only = bool(raw.get("additive_only", False))
    if additive_only:
        # Glass-style: grow density only — never thin or rest away material.
        ops = [op for op in ops if op in ("add_attack", "invert", "phase_creep")]
        if "add_attack" not in ops:
            ops.insert(0, "add_attack")

    return {
        "enabled": True,
        "seed_bars": seed_bars,
        "mutate_every_n": mutate_every_n,
        "mutate_ops": ops,
        "phase_creep": bool(raw.get("phase_creep", "phase_creep" in ops)),
        "additive_only": additive_only,
        "max_phase": int(raw.get("max_phase", 2)),  # sixteenths: 0→+1→+2
    }


def _sounding_indices(cell: Sequence[Note]) -> List[int]:
    return [i for i, n in enumerate(cell) if n is not None]


def _rest_indices(cell: Sequence[Note]) -> List[int]:
    return [i for i, n in enumerate(cell) if n is None]


def mutate_cell(
    cell: Sequence[Note],
    *,
    mutate_ops: Sequence[str],
    source_notes: Optional[Sequence[int]] = None,
    additive_only: bool = False,
    rng: Optional[random.Random] = None,
) -> List[Note]:
    """
    Apply one mutation chosen from mutate_ops.

    Ops:
      - add_attack: turn a rest into a neighbor/source attack (or duplicate a neighbor)
      - add_rest: drop one attack to a rest (skipped when additive_only)
      - invert: reverse the sounding contour (rests stay put)
      - thin: keep every other attack (skipped when additive_only)
      - phase_creep: handled by caller via phase offset (no-op here)
    """
    rng = rng or random
    out: List[Note] = list(cell)
    if not out:
        return out

    candidates = [op for op in mutate_ops if op != "phase_creep"]
    if additive_only:
        candidates = [op for op in candidates if op in ("add_attack", "invert")]
    if not candidates:
        return out

    op = rng.choice(candidates)

    if op == "add_attack":
        rests = _rest_indices(out)
        sounding = _sounding_indices(out)
        if rests:
            idx = rng.choice(rests)
            if sounding:
                anchor = out[rng.choice(sounding)]
                assert anchor is not None
                if source_notes:
                    # Prefer nearest source pitch for musical continuity
                    out[idx] = min(source_notes, key=lambda n: abs(n - anchor))
                else:
                    out[idx] = anchor
            elif source_notes:
                out[idx] = rng.choice(list(source_notes))
        elif sounding and len(sounding) < len(out):
            # No rests: duplicate a pitch into a weak slot by replacing a mid attack's
            # neighbor with an extra chord tone — densify by re-articulating.
            idx = sounding[len(sounding) // 2]
            neighbor = out[idx]
            if source_notes and neighbor is not None:
                # Nudge toward a nearby source note (additive color)
                choices = [n for n in source_notes if n != neighbor]
                if choices:
                    out[idx] = min(choices, key=lambda n: abs(n - neighbor))
        return out

    if op == "add_rest" and not additive_only:
        sounding = _sounding_indices(out)
        # Keep at least two attacks so the cell doesn't collapse
        if len(sounding) > 2:
            # Prefer weak slots (odd indices) for rests
            weak = [i for i in sounding if i % 2 == 1] or sounding[1:]
            out[rng.choice(weak)] = None
        return out

    if op == "invert":
        sounding = [out[i] for i in _sounding_indices(out)]
        if len(sounding) >= 2:
            flipped = list(reversed(sounding))
            fi = 0
            for i, note in enumerate(out):
                if note is not None:
                    out[i] = flipped[fi]
                    fi += 1
        return out

    if op == "thin" and not additive_only:
        sounding = _sounding_indices(out)
        if len(sounding) > 3:
            # Drop every other weak attack
            for i in sounding[1::2]:
                if i % 2 == 1:
                    out[i] = None
        return out

    return out


def apply_phase_offset(cell: Sequence[Note], phase_sixteenths: int) -> List[Note]:
    """Rotate cell later by phase_sixteenths steps (wrap). phase 0 = identity."""
    if not cell or phase_sixteenths <= 0:
        return list(cell)
    n = len(cell)
    shift = phase_sixteenths % n
    return list(cell[-shift:] + cell[:-shift]) if shift else list(cell)


def evolve_phase(current: int, *, max_phase: int = 2) -> int:
    """Creep phase 0 → +1 → +2 (sixteenths), then hold at max."""
    return min(max_phase, max(0, current) + 1)
