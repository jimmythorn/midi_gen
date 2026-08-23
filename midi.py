"""
MIDI file creation and event processing.
"""

import mido
from typing import Dict, List, Union, cast, Tuple, Optional
# import random # No longer needed
# import math # No longer needed
from .effects_base import (
    MidiEffect, NoteContext, EffectChain,
    create_note_context, convert_legacy_to_instructions
)
from .effects import EffectRegistry
from .midi_types import (
    MidiInstruction, NoteValue, Velocity, Tick, BendValue,
    MIDI_PITCH_BEND_CENTER, DEFAULT_TICKS_PER_BEAT
)
from .midi_ordering import sort_midi_instructions

# Removed calculate_note_length function as it's overcomplicated for fixed 16th notes

# Type alias for structured MIDI events
MidiEvent = Tuple[int, int, int, int] # (note, start_tick, duration_tick, velocity)

class MidiProcessor:
    """Handles MIDI event processing and effect application."""
    
    def __init__(self):
        self.effect_chain = EffectChain()
        
    def add_effect(self, effect: MidiEffect) -> None:
        """Add an effect to the processing chain."""
        self.effect_chain.add_effect(effect)
    
    def process_events(self, 
                      event_list: Union[List[MidiInstruction], List],
                      options: Dict) -> List[Union[MidiInstruction, Tuple]]:
        """
        Process a list of MIDI events through the effect chain.
        Handles both new MidiInstruction format and legacy formats.
        """
        # First determine if we're dealing with new format instructions
        is_new_format = (event_list and isinstance(event_list[0], tuple) 
                        and isinstance(event_list[0][0], str))
        
        if is_new_format:
            # Already in new format, process directly
            return self.effect_chain.process_sequence(
                cast(List[MidiInstruction], event_list),
                options
            )
        else:
            # Convert legacy format to intermediate representation
            processed_events = self._process_legacy_format_events(event_list, options)
            # Process through effect chain
            return self.effect_chain.process_sequence(processed_events, options)
    
    def _process_legacy_format_events(self, 
                                    event_list: List,
                                    options: Dict) -> List[Union[MidiInstruction, Tuple]]:
        """
        Process events in legacy format, applying note-level effects first.
        
        Args:
            event_list: List of events in legacy format
            options: Processing options including generation_type
            
        Returns:
            List of processed events in new MidiInstruction format
        """
        generation_type = options.get('generation_type', 'arpeggio')
        processed_events = []
        
        if generation_type == 'arpeggio':
            sixteenth_note_duration_ticks = DEFAULT_TICKS_PER_BEAT // 4
            # steps_per_note: 1=16th, 2=8th, 4=quarter — set by create_arp so
            # MIDI note length matches the arp_steps / repeat_pattern labels.
            steps_per_note = max(1, int(options.get('steps_per_note', 1)))
            current_tick = 0
            i = 0
            n_events = len(event_list)

            while i < n_events:
                raw_note_value = event_list[i]
                # Each attack (or rest) occupies a note-slot of steps_per_note
                # sixteenths. Padding Nones that follow an attack are absorbed
                # into that slot's duration — not treated as separate rests.
                slot_steps = steps_per_note
                duration_ticks = sixteenth_note_duration_ticks * slot_steps

                if raw_note_value is None:
                    current_tick += duration_ticks
                    i += slot_steps
                    continue

                # Create note context for this step
                ctx = create_note_context(
                    note=int(raw_note_value),
                    velocity=64,
                    tick=current_tick,
                    options=options,
                    duration_ticks=duration_ticks,
                    is_first_note=(i == 0),
                    is_last_note=(i >= n_events - slot_steps)
                )

                # Process through note-level effects
                processed_ctx = self.effect_chain.process_note(ctx)

                # Create note events if note is valid (note 0 is a rare edge —
                # treat as silent to avoid C-1 accidents from clamp bugs).
                if processed_ctx['note'] > 0:
                    processed_events.extend([
                        ('note_on', current_tick, processed_ctx['note'],
                         processed_ctx['velocity'], processed_ctx['channel']),
                        ('note_off', current_tick + duration_ticks,
                         processed_ctx['note'], 0, processed_ctx['channel'])
                    ])

                current_tick += duration_ticks
                i += slot_steps
                
        elif generation_type == 'drone':
            # For drones, we need to track the maximum tick for proper duration calculation
            max_tick = 0
            
            for event in event_list:
                if len(event) < 4:  # Skip invalid events
                    continue
                    
                note, start_tick, duration_tick, velocity = event
                if duration_tick <= 0:
                    continue
                    
                # Update max_tick considering both start and duration
                max_tick = max(max_tick, start_tick + duration_tick)
                    
                # Create note context
                ctx = create_note_context(
                    note=note,
                    velocity=velocity,
                    tick=start_tick,
                    options=options,
                    duration_ticks=duration_tick
                )
                
                # Process through note-level effects
                processed_ctx = self.effect_chain.process_note(ctx)
                
                if processed_ctx['note'] > 0:
                    processed_events.extend([
                        ('note_on', start_tick, processed_ctx['note'],
                         processed_ctx['velocity'], processed_ctx['channel']),
                        ('note_off', start_tick + duration_tick,
                         processed_ctx['note'], 0, processed_ctx['channel'])
                    ])
            
            # Update options with the correct total duration
            options['total_ticks'] = max_tick
        
        return processed_events

def create_midi_file(
    event_list: Union[List[MidiInstruction], List],
    options: Dict,
    active_effects: List[MidiEffect]
) -> str:
    """Creates a MIDI file from the processed events."""
    # Initialize processor and add the already created effects
    processor = MidiProcessor()
    for effect in active_effects:
        processor.add_effect(effect)
    
    # Process all events through the effect chain
    processed_events = processor.process_events(event_list, options)
    # Always sort before delta encoding — overlapping voices (drones) are unordered.
    processed_events = sort_midi_instructions(processed_events)
    
    # Create MIDI file
    filename = options.get('filename', "output.mid")
    bpm = options.get('bpm', 120)
    ticks_per_beat = options.get('ticks_per_beat', DEFAULT_TICKS_PER_BEAT)
    
    mid = mido.MidiFile(ticks_per_beat=ticks_per_beat)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    
    # Set tempo
    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(bpm)))
    
    # Convert all events to MIDI messages
    last_tick = 0
    for event in processed_events:
        if isinstance(event, tuple):
            if isinstance(event[0], str):  # New format
                msg_type, tick, *params = event
                delta_tick = max(0, tick - last_tick)
                
                if msg_type == 'note_on':
                    track.append(mido.Message('note_on',
                                           note=params[0],
                                           velocity=params[1],
                                           channel=params[2],
                                           time=delta_tick))
                elif msg_type == 'note_off':
                    track.append(mido.Message('note_off',
                                           note=params[0],
                                           velocity=params[1],
                                           channel=params[2],
                                           time=delta_tick))
                elif msg_type == 'pitch_bend':
                    track.append(mido.Message('pitchwheel',
                                           pitch=params[0],
                                           channel=params[1],
                                           time=delta_tick))
                elif msg_type == 'control_change':
                    track.append(mido.Message('control_change',
                                           control=params[0],
                                           value=params[1],
                                           channel=params[2],
                                           time=delta_tick))
                
                last_tick = max(last_tick, tick)
    
    mid.save(filename)
    return filename
