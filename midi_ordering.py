"""
Canonical ordering for MidiInstruction sequences before delta-time encoding.

Overlapping voices (drones) emit note_on/off pairs per note without global
order. Encoding without a sort produces negative deltas and mido raises
ValueError. Effects must not be relied on for correctness.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple, Union

from .midi_types import MidiInstruction

# Lower rank = earlier at the same tick.
_TYPE_RANK = {
    "control_change": 0,  # RPN / setup before sound
    "pitch_bend": 1,
    "note_off": 2,        # release before new attack at same tick
    "note_on": 3,
}


def _instruction_sort_key(event: Union[MidiInstruction, Tuple]) -> Tuple:
    if not isinstance(event, tuple) or not event or not isinstance(event[0], str):
        return (1 << 30, 99, 0, 0)
    msg_type = event[0]
    tick = int(event[1]) if len(event) > 1 else 0
    rank = _TYPE_RANK.get(msg_type, 50)
    # Stable-ish by note/control id when present
    payload = event[2] if len(event) > 2 else 0
    return (tick, rank, payload if isinstance(payload, int) else 0)


def sort_midi_instructions(
    events: Sequence[Union[MidiInstruction, Tuple]],
) -> List[Union[MidiInstruction, Tuple]]:
    """Return a new list sorted for non-negative MIDI delta encoding."""
    return sorted(events, key=_instruction_sort_key)
