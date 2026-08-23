from .scale import get_scale, get_mode_color_pitch_classes
from .notes import pitch_class_at_octave, midi_octave_bounds
import random
import math


def _color_midi_notes(
    root: int,
    mode: str,
    min_octave: int,
    max_octave: int,
) -> list:
    """Absolute MIDI notes for the mode's characteristic color tones in range."""
    color_pcs = get_mode_color_pitch_classes(root, mode)
    if not color_pcs:
        return []
    low, high = midi_octave_bounds(min_octave, max_octave)
    notes = []
    for octave in range(min_octave, max_octave + 1):
        for pc in color_pcs:
            midi_note = pitch_class_at_octave(pc, octave)
            if low <= midi_note <= high:
                notes.append(midi_note)
    return notes


def _nearest_color_note(anchor: int, color_notes: list) -> int:
    return min(color_notes, key=lambda n: (abs(n - anchor), n))


def paint_mode_color(
    notes: list,
    root: int,
    mode: str,
    min_octave: int,
    max_octave: int,
    *,
    accent_every: int = 4,
) -> list:
    """
    Keep chord tones on strong beats; place characteristic color on weak /
    embellish slots. Guarantees at least one color tone in the phrase when
    the mode defines any.
    """
    if not notes:
        return notes
    color_notes = _color_midi_notes(root, mode, min_octave, max_octave)
    if not color_notes:
        return list(notes)

    color_pcs = {n % 12 for n in color_notes}
    painted = list(notes)
    # Strong: beat anchors (every accent_every). Weak: approach / off-beat slots.
    period = max(2, int(accent_every))

    for i, note in enumerate(painted):
        is_strong = (i % period) == 0
        if is_strong:
            continue
        # Prefer color on approach slots (one before a strong beat) and mid-weak.
        is_approach = ((i + 1) % period) == 0
        is_mid_weak = (i % period) == (period // 2)
        if is_approach or is_mid_weak or (i % 2 == 1 and period <= 2):
            painted[i] = _nearest_color_note(note, color_notes)

    if not any((n % 12) in color_pcs for n in painted):
        # Force a color accent on the first weak slot (or last if length==1).
        slot = 1 if len(painted) > 1 else 0
        painted[slot] = _nearest_color_note(painted[slot], color_notes)

    return painted


def create_arpeggio(root: int, mode: str, length: int = 16, min_octave: int = 4, max_octave: int = 6, arp_mode: str = 'up', range_octaves: int = 1, evolution_rate: float = 0.1, repetition_factor: int = 5, rhythmic_variation: bool = False, chord_progression: list = None, embellish: bool = False, use_chord_tones: bool = True, mode_color: bool = True) -> list:
    """
    Creates an arpeggio with various musical enhancements.

    :param root: MIDI note number for the root of the scale.
    :param mode: String representing the mode of the scale.
    :param length: Number of notes in the arpeggio.
    :param min_octave: The lowest octave to use for notes.
    :param max_octave: The highest octave to use for notes.
    :param arp_mode: Arpeggiator mode - 'up', 'down', 'up_down', 'random', or 'order'.
    :param range_octaves: Number of octaves to span with the arpeggio.
    :param evolution_rate: Rate at which the arpeggio evolves (0.0 to 1.0, where 0 is no evolution).
    :param repetition_factor: Controls the level of repetition in the arpeggio (1 to 10, 10 being most repetitive).
    :param rhythmic_variation: If True, introduces syncopation or tuplets.
    :param chord_progression: List of chord roots for harmonic variation.
    :param embellish: If True, adds passing tones and neighbor notes.
    :param use_chord_tones: If True (default), arpeggiates using only chord tones (1,3,5 of the mode). 
                            If False, uses all notes of the scale.
    :param mode_color: When True with chord tones, inject characteristic mode
                       color on weak beats so Lydian/#4 etc. aren't lost.
    :return: List of MIDI note numbers forming the arpeggio with enhancements.
    """
    # Get the base pitch classes (either chord tones or full scale)
    pitch_classes = get_scale(root, mode, use_chord_tones=use_chord_tones)
    
    # Ensure pitch_classes is not empty before proceeding, especially if a mode might result in no chord tones (e.g. if definition was missing)
    if not pitch_classes:
        # Fallback to a simple root note arpeggio across octaves if scale/chord tones are empty
        # This prevents errors if a mode/chord tone definition is somehow missing or results in an empty list.
        # A more robust solution might be to raise an error or log a warning.
        pitch_classes = [root % 12] 

    arpeggio_source_notes = []
    
    # Build the source notes across octaves (written octave → MIDI),
    # clamped to the declared [min_octave, max_octave] window.
    top_octave = min(max_octave, min_octave + max(0, range_octaves))
    if top_octave < min_octave:
        top_octave = min_octave
    low_bound, high_bound = midi_octave_bounds(min_octave, max_octave)
    for octave in range(min_octave, top_octave + 1):
        for note in pitch_classes:
            midi_note = pitch_class_at_octave(note, octave)
            if low_bound <= midi_note <= high_bound:
                arpeggio_source_notes.append(midi_note)
    
    # Ensure arpeggio_source_notes is not empty if pitch_classes was valid but octaves didn't yield notes
    if not arpeggio_source_notes:
        # This might happen if min_octave is too high for the root + pitch classes
        # Fallback to just the root note at the min_octave if all else fails
        arpeggio_source_notes = [pitch_class_at_octave(root, min_octave)]
        # For now, ensuring at least one note is available.
        if not arpeggio_source_notes: # Still empty after trying with min_octave
             arpeggio_source_notes = [pitch_class_at_octave(root, 4)] # Default around octave 4

    base_pattern = []

    if arp_mode == 'up_down':
        # Build an ascending then descending contour of exactly `length` notes.
        # Skip the duplicated peak/trough note so the turnaround stays clean.
        if not arpeggio_source_notes:  # Safeguard
            arpeggio_source_notes = [pitch_class_at_octave(root, min_octave)]

        source_up = list(arpeggio_source_notes)
        source_down = list(reversed(arpeggio_source_notes))
        # Drop first of descent when it would repeat the last ascent note
        if len(source_down) > 1 and source_up and source_down[0] == source_up[-1]:
            source_down = source_down[1:]

        cycle = source_up + source_down
        if not cycle:
            cycle = list(arpeggio_source_notes)
        for i in range(length):
            base_pattern.append(cycle[i % len(cycle)])
    else:
        # Original logic for 'up', 'down', 'random', 'order' that uses an intermediate 'pattern'
        # which is then processed by repetition_factor.
        intermediate_pattern = []
        if arp_mode == 'up':
            intermediate_pattern = list(arpeggio_source_notes)
        elif arp_mode == 'down':
            intermediate_pattern = list(reversed(arpeggio_source_notes))
        elif arp_mode == 'random':
            if arpeggio_source_notes: # Check for empty list
                 intermediate_pattern = [random.choice(arpeggio_source_notes) for _ in range(len(arpeggio_source_notes))] # Create a pattern of same length as source for now
            else:
                 intermediate_pattern = [pitch_class_at_octave(root, min_octave)]
        elif arp_mode == 'order': 
            intermediate_pattern = list(arpeggio_source_notes) 
            random.shuffle(intermediate_pattern)
        else: # Default or unrecognized arp_mode (should not happen if CLI is validated)
            intermediate_pattern = list(arpeggio_source_notes) # Default to 'up' behavior for pattern source

        if not intermediate_pattern: # Handle cases where pattern might be empty
            intermediate_pattern = [pitch_class_at_octave(root, min_octave)] # Fallback to root note if empty

        # Adjust for repetition_factor using the intermediate_pattern
        repetition_factor = max(1, min(10, repetition_factor))
        if len(intermediate_pattern) > 0:
            # Expand based on length of intermediate_pattern relative to desired final 'length'
            expanded_pattern = intermediate_pattern * (length // len(intermediate_pattern) + 1)
            if repetition_factor < 10:
                for i in range(len(expanded_pattern)):
                    if random.random() > (repetition_factor / 10):
                        if arpeggio_source_notes: 
                            expanded_pattern[i] = random.choice(arpeggio_source_notes)
            base_pattern = expanded_pattern[:length]
        else:
            base_pattern = [] # Should be caught by earlier check, but as safeguard

    # Ensure base_pattern is exactly `length` notes, especially if fallbacks occurred or length was 0.
    if len(base_pattern) != length:
        # If too short (e.g. length was 0 or pattern construction failed), fill with root note or truncate.
        # This primarily guards against length=0 or issues if arpeggio_source_notes was initially empty.
        if not arpeggio_source_notes and length > 0 : arpeggio_source_notes = [pitch_class_at_octave(root, min_octave)]
        
        if length == 0: base_pattern = []
        elif len(base_pattern) < length and arpeggio_source_notes:
            # Tile the first note of arpeggio_source_notes to fill remaining space
            filler_note = arpeggio_source_notes[0]
            base_pattern.extend([filler_note] * (length - len(base_pattern)))
        elif len(base_pattern) > length:
            base_pattern = base_pattern[:length]
        elif not base_pattern and length > 0 and arpeggio_source_notes: # Completely empty, fill from source
             source_fill = list(arpeggio_source_notes)
             for i in range(length):
                 base_pattern.append(source_fill[i % len(source_fill)])

    # Rhythmic Variation (ensure base_pattern is not empty)
    if rhythmic_variation and base_pattern:
        syncopated = [note if i % 4 != 3 else None for i, note in enumerate(base_pattern)]
        tuplets = []
        for i in range(0, length, 3):
            if i + 2 < length:
                tuplets.extend(base_pattern[i:i+3])
            else:
                tuplets.extend(base_pattern[i:])
                if len(base_pattern[i:]) < 3 and length > len(base_pattern[i:]):
                     tuplets.extend([None] * (3 - len(base_pattern[i:]))) 
        base_pattern = syncopated if random.choice([True, False]) else tuplets

    current_arpeggio = []
    # Harmonic Variation with Chord Progression
    if chord_progression and base_pattern:
        prog_arpeggio = []
        current_chord_index = 0
        # Determine notes per chord segment
        notes_per_segment = length // len(chord_progression) if len(chord_progression) > 0 else length
        
        for i, note_in_pattern in enumerate(base_pattern):
            if notes_per_segment > 0 and i % notes_per_segment == 0 and i // notes_per_segment < len(chord_progression):
                current_chord_index = i // notes_per_segment
            
            new_root = chord_progression[current_chord_index]
            # Get pitch classes for the new chord root and current mode (and use_chord_tones setting)
            current_chord_pitch_classes = get_scale(new_root, mode, use_chord_tones=use_chord_tones)
            
            # Build full range of notes for this chord (respect max_octave)
            current_chord_full_range = []
            top = min(max_octave, min_octave + max(0, range_octaves))
            for octave in range(min_octave, top + 1):
                current_chord_full_range.extend([pitch_class_at_octave(pc, octave) for pc in current_chord_pitch_classes])
            
            if not current_chord_full_range: # Fallback if no notes generated
                prog_arpeggio.append(note_in_pattern) # Keep original pattern note
                continue

            if note_in_pattern is not None:
                # Map current pattern note to the closest note in the new chord's full range
                prog_arpeggio.append(min(current_chord_full_range, key=lambda x: abs(x - note_in_pattern)))
            else:
                prog_arpeggio.append(None) # Preserve rests from rhythmic variation
        current_arpeggio = prog_arpeggio
    else:
        current_arpeggio = list(base_pattern) # Ensure it's a mutable list

    # Melodic Embellishments (ensure current_arpeggio and arpeggio_source_notes are not empty)
    if embellish and current_arpeggio and arpeggio_source_notes:
        embellished_arpeggio = []
        for note in current_arpeggio:
            if note is not None:
                if random.random() < 0.3:  # 30% chance for embellishment
                    # Ensure arpeggio_source_notes has notes to pick from for embellishment
                    # And that the current note is actually in arpeggio_source_notes to find its index
                    try:
                        index = arpeggio_source_notes.index(note % 12 + (note // 12) * 12) # Normalize note to find in source
                        if random.random() < 0.5:  # Passing tone
                            embellished_arpeggio.append(arpeggio_source_notes[(index + 1) % len(arpeggio_source_notes)])
                        else:  # Neighbor note
                            embellished_arpeggio.append(arpeggio_source_notes[(index + random.choice([-1, 1])) % len(arpeggio_source_notes)])
                    except ValueError: # Note not in arpeggio_source_notes, skip embellishment for this note
                        pass      
                embellished_arpeggio.append(note)
            else:
                embellished_arpeggio.append(None)
        current_arpeggio = embellished_arpeggio

    # Evolution: prefer neighbor steps over full random jumps so motifs stay coherent.
    if evolution_rate > 0 and current_arpeggio and arpeggio_source_notes:
        evolved_arpeggio = []
        for note in current_arpeggio:
            if note is not None and random.random() < evolution_rate:
                # 80% neighbor motion, 20% free pick within the source set
                if random.random() < 0.8:
                    try:
                        # Match by pitch class + nearest octave instance in source
                        candidates = [n for n in arpeggio_source_notes if n % 12 == note % 12]
                        anchor = min(candidates, key=lambda n: abs(n - note)) if candidates else note
                        index = arpeggio_source_notes.index(anchor)
                        new_index = (index + random.choice([-1, 1])) % len(arpeggio_source_notes)
                        evolved_arpeggio.append(arpeggio_source_notes[new_index])
                    except ValueError:
                        evolved_arpeggio.append(random.choice(arpeggio_source_notes))
                else:
                    evolved_arpeggio.append(random.choice(arpeggio_source_notes))
            else:
                evolved_arpeggio.append(note)
        current_arpeggio = evolved_arpeggio

    # Remove None values, clamp to playable MIDI (note 0 is reserved as rest
    # in the arpeggio event stream — never emit it as a sounding pitch).
    final_arpeggio = [
        max(1, min(127, int(note)))
        for note in current_arpeggio
        if note is not None
    ]
    if length > 0:
        if len(final_arpeggio) < length and arpeggio_source_notes:
            filler = [arpeggio_source_notes[i % len(arpeggio_source_notes)] for i in range(length)]
            final_arpeggio = (final_arpeggio + filler)[:length]
        else:
            final_arpeggio = final_arpeggio[:length]

    # Chord-tone patterns alone collapse modes to triads — paint color accents.
    # Full-scale mode already contains color tones, so skip when not chordal.
    if mode_color and use_chord_tones and final_arpeggio:
        # ~one accent window every 1–2 bars of an 8-step cell → period 4.
        accent_every = 4 if length >= 4 else 2
        final_arpeggio = paint_mode_color(
            final_arpeggio,
            root,
            mode,
            min_octave,
            max_octave,
            accent_every=accent_every,
        )
        final_arpeggio = [max(1, min(127, int(n))) for n in final_arpeggio]

    return final_arpeggio
