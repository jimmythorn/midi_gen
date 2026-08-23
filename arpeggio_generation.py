import os
from .notes import note_str_to_midi, note_to_name
from .arpeggio import create_arpeggio
from .drone_generation import generate_drone_events 
from .midi import create_midi_file
from typing import Dict, List, Optional, Tuple
from .effects import EffectRegistry
from .effects_base import MidiEffect

def create_arp(options: Dict):
    """
    Main function to generate MIDI data based on given options.
    """
    debug = options.get('debug', False)
    root = options.get('root', 0)
    root_notes_str_param = options.get('root_notes', None)
    generation_type = options.get('generation_type', 'arpeggio')
    
    if debug:
        print(f"[DEBUG] Generation Type: {generation_type}")
        if debug:
            print(f"[DEBUG] root_notes_str_param from options: {root_notes_str_param}")

    processed_root_notes_midi: List[int] = []
    if root_notes_str_param: 
        processed_root_notes_midi = [note_str_to_midi(note) for note in root_notes_str_param]
    else:
        processed_root_notes_midi = [root] * options.get('bars', 16)
    
    if debug:
        print(f"[DEBUG] Processed root_notes (MIDI numbers): {processed_root_notes_midi}")
        if debug:
            print(f"[DEBUG] Length of processed root_notes: {len(processed_root_notes_midi) if processed_root_notes_midi else 0}")

    mode = options.get('mode', 'major')
    bars = options.get('bars', 16)
    min_octave = options.get('min_octave', 4)
    max_octave = options.get('max_octave', 6)
    use_chord_tones = options.get('use_chord_tones', True)
    
    # Arpeggio-specific options
    arp_steps = options.get('arp_steps', 8)
    arp_mode = options.get('arp_mode', 'up')
    range_octaves = options.get('range_octaves', 1)
    evolution_rate = options.get('evolution_rate', 0.1)
    repetition_factor = options.get('repetition_factor', 5)

    # Create effects using the registry
    active_effects: List[MidiEffect] = []
    effects_config = options.get('effects_config', [])
    
    if debug:
        print("\n[DEBUG] Creating effects:")
    
    # Add other effects
    for effect_conf in effects_config:
        effect_name = effect_conf.get('name', '')
        if debug:
            print(f"[DEBUG] Processing effect: {effect_name}")
        if debug:
            print(f"[DEBUG] Effect configuration: {effect_conf}")
        
        if effect := EffectRegistry.create_effect(effect_conf):
            if debug:
                print(f"[DEBUG] Successfully created effect: {effect_name}")
            active_effects.append(effect)
        else:
            if debug:
                print(f"[WARNING] Failed to create effect: {effect_name}")

    if generation_type == 'arpeggio':
        # Each bar has 16 16th notes
        steps_per_bar = 16
        ticks_per_beat = 480  # Standard MIDI ticks per quarter note
        ticks_per_16th = ticks_per_beat // 4
        
        # Get pattern repetition setting
        repeat_pattern = options.get('repeat_pattern', False)
        
        # Calculate note length based on number of steps and repetition setting
        # If repeating or using 16 steps: each note is a 16th note
        # If not repeating: notes are longer (8th or quarter notes)
        if arp_steps == 16 or repeat_pattern:
            steps_per_note = 1  # 16th notes
            repeats_per_bar = steps_per_bar // arp_steps
        else:
            steps_per_note = steps_per_bar // arp_steps  # 2 for 8 steps, 4 for 4 steps
            repeats_per_bar = 1
        
        if debug:
            print(f"[DEBUG] Steps per bar: {steps_per_bar}")
        if debug:
            print(f"[DEBUG] Arp steps: {arp_steps}")
        if debug:
            print(f"[DEBUG] Steps per note: {steps_per_note}")
        if debug:
            print(f"[DEBUG] Pattern repeats per bar: {repeats_per_bar}")
        if debug:
            print(f"[DEBUG] Using {'16th' if steps_per_note == 1 else '8th' if steps_per_note == 2 else 'quarter'} notes")
        
        # This will hold our flat list of notes
        final_event_list: List[Optional[int]] = []
        
        if processed_root_notes_midi:
            bars_per_segment = bars // len(processed_root_notes_midi) if len(processed_root_notes_midi) > 0 else bars
            
            for idx, current_root_midi in enumerate(processed_root_notes_midi):
                num_bars_for_segment = bars_per_segment
                if idx == len(processed_root_notes_midi) - 1:
                    num_bars_for_segment = bars - (bars_per_segment * idx)
                if num_bars_for_segment <= 0: continue

                # create_arpeggio returns a pattern for one cycle (length = arp_steps)
                arpeggio_cycle_pattern = create_arpeggio(
                    current_root_midi, mode, arp_steps, min_octave, max_octave, 
                    arp_mode, range_octaves, use_chord_tones=use_chord_tones,
                    evolution_rate=evolution_rate, repetition_factor=repetition_factor
                )
                
                if not arpeggio_cycle_pattern:
                    continue
                    
                # For each bar in this segment
                for _ in range(num_bars_for_segment):
                    # Repeat the pattern if needed
                    for _ in range(repeats_per_bar):
                        # For each note in the pattern
                        for note in arpeggio_cycle_pattern:
                            if arp_steps == 16 or repeat_pattern:
                                # When using 16th notes, just add the note
                                final_event_list.append(note)
                            else:
                                # When using longer notes, add None values after each note
                                final_event_list.append(note)  # The note itself
                                final_event_list.extend([None] * (steps_per_note - 1))  # Fill remaining steps with None

        # Ensure total length matches bars * steps_per_bar
        total_expected_steps = bars * steps_per_bar
        if len(final_event_list) > total_expected_steps:
            final_event_list = final_event_list[:total_expected_steps]
        elif len(final_event_list) < total_expected_steps:
            # Pad with None if too short
            final_event_list.extend([None] * (total_expected_steps - len(final_event_list)))

    elif generation_type == 'drone':
        # Call drone generation function
        # This function must return List[Tuple[note, start_tick, duration_tick, velocity]]
        # Pass relevant options and the processed MIDI root notes
        drone_options = options.copy()
        final_event_list = generate_drone_events(drone_options, processed_root_notes_midi)
        if debug:
            print(f"[INFO] Drone generation selected. {len(final_event_list)} drone events generated.")

    # --- Filename and MIDI file creation --- 
    root_notes_names_for_file = '-'.join([note_to_name(note) for note in processed_root_notes_midi]) if processed_root_notes_midi else str(root)
    base_filename = f"{generation_type}_{mode}_{root_notes_names_for_file}"
    
    output_folder = "generated"
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(current_script_dir, output_folder)
    if not os.path.exists(output_path):
        os.makedirs(output_path)
    file_path = os.path.join(output_path, f"{base_filename}.mid")
    options['filename'] = file_path
    
    # Create the MIDI file using the master event list
    result_filename = create_midi_file(final_event_list, options, active_effects)
    print(f"\nMIDI file '{result_filename}' created with the following settings:")
    print(f"  Generation Type: {generation_type}")
    print(f"  Mode: {mode}")
    print(f"  Root Notes: {root_notes_names_for_file}")
    print(f"  Active Effects: {[type(effect).__name__ for effect in active_effects]}")

    return result_filename
