import random # Added for future, more varied interest
from typing import Dict, List, Tuple, Optional
from .scale import get_scale, get_mode_color_pitch_classes # Chord tones + modal color
from .notes import pitch_class_at_octave, midi_octave_bounds
from .arpeggio import normalize_mode_color

# Type alias for structured MIDI events, ensure it matches midi.py if ever moved to a common types file
MidiEvent = Tuple[int, int, int, int] # (note, start_tick, duration_tick, velocity)

# New option for controlling drone interest
DEFAULT_DRONE_VARIATION_INTERVAL_BARS = 1 # How often the drone voicing can change
DEFAULT_DRONE_MIN_NOTES_HELD = 2 # Minimum notes of the chord to hold
DEFAULT_DRONE_OCTAVE_DOUBLING_CHANCE = 0.25
DEFAULT_DRONE_ALLOW_OCTAVE_SHIFTS = True
DEFAULT_DRONE_OCTAVE_SHIFT_CHANCE = 0.1 # Chance for a note to shift its octave in an interval
DEFAULT_DRONE_ENABLE_WALKDOWNS = True
DEFAULT_DRONE_WALKDOWN_NUM_STEPS = 2
DEFAULT_DRONE_WALKDOWN_STEP_TICKS = 240 # Defaulted to Eighth note, updated from __main__.py change
DEFAULT_MINIMUM_TARGET_SUSTAIN_TICKS_FOR_WALKDOWN = 60 # Min duration for the target note after walkdown


def _drone_color_note(
    root_midi_note: int,
    mode: str,
    min_octave: int,
    max_octave: int,
    avoid: List[int],
) -> Optional[int]:
    """Pick one characteristic color tone in range, not already in the voicing."""
    color_pcs = get_mode_color_pitch_classes(root_midi_note, mode)
    if not color_pcs:
        return None
    avoid_pcs = {n % 12 for n in avoid}
    low, high = midi_octave_bounds(min_octave, max_octave)
    candidates: List[int] = []
    for octave in range(min_octave, max_octave + 1):
        for pc in color_pcs:
            if pc in avoid_pcs:
                continue
            note = pitch_class_at_octave(pc, octave)
            if low <= note <= high:
                candidates.append(note)
    if not candidates:
        # Fall back to any color pc even if pc already present an octave away
        for octave in range(min_octave, max_octave + 1):
            for pc in color_pcs:
                note = pitch_class_at_octave(pc, octave)
                if low <= note <= high and note not in avoid:
                    candidates.append(note)
    return random.choice(candidates) if candidates else None


def generate_drone_events(options: Dict, processed_root_notes_midi: List[int]) -> List[MidiEvent]:
    """
    Generates drone events with dynamic voicing, octave doubling/shifts, and DIATONIC melodic walkdowns.
    """
    bpm = options.get('bpm', 120)
    total_bars = options.get('bars', 16)
    mode = options.get('mode', 'major')
    min_octave_param = options.get('min_octave', 3)
    max_octave_param = options.get('max_octave', 5)
    base_velocity = options.get('drone_base_velocity', 70)
    color_enabled, _color_intervals, _color_accent = normalize_mode_color(
        options.get('mode_color', True), mode
    )
    
    variation_interval_bars = options.get('drone_variation_interval_bars', DEFAULT_DRONE_VARIATION_INTERVAL_BARS)
    min_notes_held = options.get('drone_min_notes_held', DEFAULT_DRONE_MIN_NOTES_HELD)
    octave_doubling_chance = options.get('drone_octave_doubling_chance', DEFAULT_DRONE_OCTAVE_DOUBLING_CHANCE)
    allow_octave_shifts = options.get('drone_allow_octave_shifts', DEFAULT_DRONE_ALLOW_OCTAVE_SHIFTS)
    octave_shift_one_note_chance = options.get('drone_octave_shift_one_note_chance', DEFAULT_DRONE_OCTAVE_SHIFT_CHANCE)
    enable_walkdowns = options.get('drone_enable_walkdowns', DEFAULT_DRONE_ENABLE_WALKDOWNS)
    walkdown_num_steps_config = options.get('drone_walkdown_num_steps', DEFAULT_DRONE_WALKDOWN_NUM_STEPS)
    walkdown_step_ticks_config = options.get('drone_walkdown_step_ticks', DEFAULT_DRONE_WALKDOWN_STEP_TICKS)
    min_target_sustain_ticks = options.get('min_target_sustain_ticks_for_walkdown', DEFAULT_MINIMUM_TARGET_SUSTAIN_TICKS_FOR_WALKDOWN)

    ticks_per_beat = 480
    ticks_per_bar = ticks_per_beat * 4
    variation_interval_ticks = variation_interval_bars * ticks_per_bar

    final_drone_events: List[MidiEvent] = []
    global_current_tick = 0 # Tracks the absolute start tick for events across segments

    if not processed_root_notes_midi:
        # Fallback for no root notes (unchanged)
        c3_midi = 48 
        drone_chord_notes_pc = get_scale(c3_midi, 'major', use_chord_tones=True) 
        drone_chord_notes_abs = [pitch_class_at_octave(pc, min_octave_param) for pc in drone_chord_notes_pc]
        drone_chord_notes_abs = [max(1, min(127, note)) for note in drone_chord_notes_abs]
        total_duration_ticks = total_bars * ticks_per_bar
        for note in drone_chord_notes_abs:
            final_drone_events.append((note, 0, total_duration_ticks, base_velocity))
        return final_drone_events

    num_root_notes = len(processed_root_notes_midi)
    bars_per_segment = total_bars // num_root_notes if num_root_notes > 0 else total_bars

    for idx, root_midi_note in enumerate(processed_root_notes_midi):
        segment_duration_bars = bars_per_segment
        if idx == num_root_notes - 1: # Last segment gets remaining bars
            segment_duration_bars = total_bars - (bars_per_segment * idx)
        
        if segment_duration_bars <= 0:
            continue

        segment_start_tick = global_current_tick
        segment_duration_ticks = segment_duration_bars * ticks_per_bar

        chord_tone_pitch_classes = get_scale(root_midi_note, mode, use_chord_tones=True)
        
        base_chord_notes = sorted(list(set([
            max(1, min(127, pitch_class_at_octave(pc, min_octave_param))) for pc in chord_tone_pitch_classes
        ])))
        if not base_chord_notes: # Fallback
            base_chord_notes = [max(1, min(127, root_midi_note))] 
        
        num_chord_notes = len(base_chord_notes)
        if num_chord_notes == 0: continue # Should not happen if fallback works

        if options.get('debug'):
            print(f"[DRONE DEBUG] Root: {root_midi_note}, Mode: {mode}, Base Chord: {base_chord_notes}, Segment Bars: {segment_duration_bars}")

        # Get full scale notes in a relevant range for diatonic walkdowns
        full_scale_pitch_classes = get_scale(root_midi_note, mode, use_chord_tones=False)
        diatonic_notes_in_range: List[int] = []
        # Generate notes for a few octaves around min_octave_param to ensure coverage for walkdowns
        octave_span_for_scale = range(min_octave_param -1, max_octave_param + 2) # e.g. if min=3,max=5 -> octaves 2,3,4,5,6
        for pc in full_scale_pitch_classes:
            for oct_num in octave_span_for_scale:
                note_val = pitch_class_at_octave(pc, oct_num)
                if 0 <= note_val <= 127:
                    diatonic_notes_in_range.append(note_val)
        diatonic_notes_in_range = sorted(list(set(diatonic_notes_in_range)))

        # Iterate through variation intervals within this segment
        current_segment_tick_offset = 0
        variation_pattern_counter = 0 # Simple counter for alternating pattern

        while current_segment_tick_offset < segment_duration_ticks:
            interval_actual_duration_ticks = min(variation_interval_ticks, segment_duration_ticks - current_segment_tick_offset)
            if interval_actual_duration_ticks <= 0: break

            interval_start_abs_tick = global_current_tick + current_segment_tick_offset
            current_interval_base_notes = []
            if num_chord_notes < 3 or num_chord_notes < min_notes_held:
                current_interval_base_notes = list(base_chord_notes)
            else:
                current_interval_base_notes.append(base_chord_notes[0]) # Root
                pattern_idx = variation_pattern_counter % 4
                if pattern_idx == 0 or pattern_idx == 2: current_interval_base_notes.extend(base_chord_notes[1:])
                elif pattern_idx == 1 and num_chord_notes > 1: current_interval_base_notes.append(base_chord_notes[num_chord_notes-1]) # 5th-like
                elif pattern_idx == 3 and num_chord_notes > 1: current_interval_base_notes.append(base_chord_notes[1]) # 3rd-like
            current_interval_base_notes = sorted(list(set(current_interval_base_notes)))
            if len(current_interval_base_notes) < min_notes_held and num_chord_notes >= min_notes_held:
                needed = min_notes_held - len(current_interval_base_notes)
                potential_adds = [n for n in base_chord_notes if n not in current_interval_base_notes]
                current_interval_base_notes.extend(potential_adds[:needed])
                current_interval_base_notes = sorted(list(set(current_interval_base_notes)))

            # Modal color accent at least every ~1–2 bars of music.
            if color_enabled:
                every = 1 if variation_interval_bars >= 2 else 2
                if variation_pattern_counter % every == 0:
                    color_note = _drone_color_note(
                        root_midi_note,
                        mode,
                        min_octave_param,
                        max_octave_param,
                        current_interval_base_notes,
                    )
                    if color_note is not None:
                        current_interval_base_notes.append(color_note)
                        current_interval_base_notes = sorted(list(set(current_interval_base_notes)))

            # 2. Apply octave shift to one note (if enabled) from the base voicing
            notes_for_direct_play_and_doubling_source = list(current_interval_base_notes)
            shifted_one_note_this_interval = False
            if allow_octave_shifts:
                # Create a list of indices to shuffle for randomizing which note gets shifted
                indices_to_try_shift = list(range(len(notes_for_direct_play_and_doubling_source)))
                random.shuffle(indices_to_try_shift)
                for i in indices_to_try_shift:
                    note_to_potentially_shift = notes_for_direct_play_and_doubling_source[i]
                    if random.random() < octave_shift_one_note_chance: # Apply overall chance here too
                        direction = random.choice([-12, 12])
                        shifted_note = note_to_potentially_shift + direction
                        low, high = midi_octave_bounds(min_octave_param, max_octave_param)
                        if low <= shifted_note <= high and 0 <= shifted_note <= 127:
                            notes_for_direct_play_and_doubling_source[i] = shifted_note
                            shifted_one_note_this_interval = True
                            break # Only shift one note per interval
            notes_for_direct_play_and_doubling_source = sorted(list(set(notes_for_direct_play_and_doubling_source)))

            # 3. Add events for these (potentially shifted) main notes
            for main_note in notes_for_direct_play_and_doubling_source:
                final_drone_events.append((main_note, interval_start_abs_tick, interval_actual_duration_ticks, base_velocity))
            
            # 4. Process octave doubling (max one per interval, with walkdowns) for each of these main notes
            has_doubled_a_note_this_interval = False
            shuffled_sources_for_doubling = list(notes_for_direct_play_and_doubling_source) # Create a copy to shuffle
            random.shuffle(shuffled_sources_for_doubling)

            for note_being_doubled_source in shuffled_sources_for_doubling: 
                if not has_doubled_a_note_this_interval and random.random() < octave_doubling_chance:
                    direction = random.choice([-12, 12])
                    doubled_note_target = note_being_doubled_source + direction
                    doubled_note_target = max(0, min(127, doubled_note_target))
                    low, high = midi_octave_bounds(min_octave_param, max_octave_param + 1)
                    if not (low <= doubled_note_target <= high):
                        continue

                    actual_walk_notes_to_play: List[int] = []
                    actual_total_walkdown_duration = 0
                    can_afford_walk = (
                        enable_walkdowns
                        and walkdown_num_steps_config > 0
                        and walkdown_step_ticks_config > 0
                        and interval_actual_duration_ticks
                        >= (walkdown_num_steps_config * walkdown_step_ticks_config) + min_target_sustain_ticks
                    )

                    if can_afford_walk:
                        temp_walk_notes = []
                        for step_index_from_target in range(walkdown_num_steps_config, 0, -1):
                            found_step_note: Optional[int] = None
                            if doubled_note_target > note_being_doubled_source:
                                notes_below = [n for n in diatonic_notes_in_range if n < doubled_note_target]
                                if len(notes_below) >= step_index_from_target:
                                    found_step_note = notes_below[-step_index_from_target]
                            else:
                                notes_above = [n for n in diatonic_notes_in_range if n > doubled_note_target]
                                if len(notes_above) >= step_index_from_target:
                                    found_step_note = notes_above[step_index_from_target - 1]

                            if found_step_note is not None:
                                if not temp_walk_notes or found_step_note != temp_walk_notes[-1]:
                                    temp_walk_notes.append(found_step_note)

                        actual_walk_notes_to_play = temp_walk_notes
                        actual_total_walkdown_duration = (
                            len(actual_walk_notes_to_play) * walkdown_step_ticks_config
                        )

                    # Walk-in notes (only when walkdowns produced steps)
                    current_walk_event_tick_offset = 0
                    for walk_note in actual_walk_notes_to_play:
                        final_drone_events.append((
                            walk_note,
                            interval_start_abs_tick + current_walk_event_tick_offset,
                            walkdown_step_ticks_config,
                            max(1, base_velocity - 15),
                        ))
                        current_walk_event_tick_offset += walkdown_step_ticks_config

                    # Always emit the doubled target when doubling fires
                    target_note_start_tick = interval_start_abs_tick + actual_total_walkdown_duration
                    target_note_duration = interval_actual_duration_ticks - actual_total_walkdown_duration
                    if target_note_duration < min_target_sustain_ticks:
                        # Fall back to full-interval sustain if walk ate too much time
                        target_note_start_tick = interval_start_abs_tick
                        target_note_duration = interval_actual_duration_ticks

                    if target_note_duration > 0:
                        final_drone_events.append((
                            doubled_note_target,
                            target_note_start_tick,
                            target_note_duration,
                            base_velocity,
                        ))
                        has_doubled_a_note_this_interval = True
                        break

            current_segment_tick_offset += interval_actual_duration_ticks
            variation_pattern_counter += 1
        
        global_current_tick += segment_duration_ticks # Advance global tick by the processed segment duration

    return final_drone_events
