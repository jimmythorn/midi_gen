from typing import List

_NOTE_NAMES_SHARP = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
_FLAT_TO_SHARP = {
    'Db': 'C#',
    'Eb': 'D#',
    'Fb': 'E',
    'Gb': 'F#',
    'Ab': 'G#',
    'Bb': 'A#',
    'Cb': 'B',
}


def _normalize_note_name(note: str) -> str:
    """Normalize note letter to sharp spelling used by the MIDI table."""
    if len(note) >= 2 and note[1] == 'b':
        mapped = _FLAT_TO_SHARP.get(note[:2])
        if mapped is None:
            raise ValueError(f"Unrecognized flat note: {note}")
        return mapped + note[2:]
    return note


def note_str_to_midi(note_str: str) -> int:
    """
    Converts a note string like 'E3', 'G#4', or 'Bb3' to its MIDI note number.

    :param note_str: String representing a note, e.g., 'E3', 'G#4', 'Db3'.
    :return: Corresponding MIDI note number.
    """
    note_str = _normalize_note_name(note_str.strip())
    # Accidental may be '#' 
    if len(note_str) >= 3 and note_str[1] == '#':
        note = note_str[:2]
        octave = int(note_str[2:])
    else:
        note = note_str[0]
        octave = int(note_str[1:])

    # MIDI note number: C-1 = 0, so add 1 to written octave
    index = _NOTE_NAMES_SHARP.index(note)
    return index + ((octave + 1) * 12)


def note_to_name(note: int) -> str:
    """
    Converts a MIDI note number to its musical name (sharp spelling).

    :param note: MIDI note number.
    :return: String representation of the note (e.g., 'C4').
    """
    octave = note // 12 - 1
    return f"{_NOTE_NAMES_SHARP[note % 12]}{octave}"


def pitch_class_at_octave(pitch_class: int, octave: int) -> int:
    """
    Place a pitch class (0-11) at a written octave (C4 = middle C = MIDI 60).

    MIDI numbering uses C-1 = 0, so written octave N starts at (N + 1) * 12.
    """
    return (pitch_class % 12) + ((octave + 1) * 12)


def midi_octave_bounds(min_octave: int, max_octave: int) -> tuple[int, int]:
    """Inclusive MIDI note range covering written octaves [min_octave, max_octave]."""
    low = pitch_class_at_octave(0, min_octave)  # C at min octave
    high = pitch_class_at_octave(11, max_octave)  # B at max octave
    return low, high


def shift_midi_by_octaves(midi: int, delta: int) -> int:
    """Move a MIDI note by ``delta`` octaves. Clamp to 1–127 (never C-1)."""
    return max(1, min(127, int(midi) + 12 * int(delta)))


def shift_note_name_octave(name: str, delta: int) -> str:
    """Move a written note name by ``delta`` octaves. Sharp spelling out."""
    return note_to_name(shift_midi_by_octaves(note_str_to_midi(str(name)), delta))
