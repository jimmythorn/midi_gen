# import sys # Removed sys import
# import os # Removed os import

# Removed sys.path modification block

from .arpeggio_generation import create_arp # Updated to use package name
from typing import Dict, List, Optional
import questionary # Import questionary
from .cursor_style_lookup import generate_midi_for_style, lookup_musician_style
from .effects_presets import explain_effects_config, list_presets
from .musician_styles import list_musicians
from .preview import format_summary_text, summarize_midi_file

# Default values from the previous argparse setup
DEFAULT_ROOT = 0
DEFAULT_ROOT_NOTES = ["E4", "A4", "D4", "G4"]
DEFAULT_MODE = 'minor'
MODE_CHOICES = ['major', 'minor', 'dorian', 'phrygian', 'lydian', 'mixolydian', 'locrian']
DEFAULT_ARP_STEPS = 8

# Define step choices with musical note lengths
ARP_STEP_CHOICES = [
    questionary.Choice("16 steps (16th notes)", value=16),
    questionary.Choice("8 steps (8th notes)", value=8),
    questionary.Choice("4 steps (quarter notes)", value=4)
]

DEFAULT_MIN_OCTAVE = 3
DEFAULT_MAX_OCTAVE = 5
DEFAULT_BPM = 120
DEFAULT_BARS = 16
DEFAULT_FILENAME = 'arpeggio.mid' # Will be dynamically prefixed by generation type
DEFAULT_DRONE_FILENAME = 'drone.mid' # Default for drone generation
DEFAULT_ARP_MODE = 'up_down'
ARP_MODE_CHOICES = ['up', 'down', 'up_down', 'random', 'order']
DEFAULT_RANGE_OCTAVES = 2 # Arpeggio specific
DEFAULT_EVOLUTION_RATE = 0.35 # Arpeggio specific
DEFAULT_REPETITION_FACTOR = 9 # Arpeggio specific

# New Tape Wobble Defaults
DEFAULT_TAPE_WOBBLE_ENABLED = True
DEFAULT_WOW_RATE_HZ = 0.5 # Centered, will be float internally
DEFAULT_WOW_DEPTH_CENTS = 25 # Centered whole number
DEFAULT_FLUTTER_RATE_HZ = 8 # Centered whole number, will be float internally
DEFAULT_FLUTTER_DEPTH_CENTS = 5  # Centered whole number
DEFAULT_WOBBLE_RANDOMNESS = 0.5 # Centered, will be float internally
DEFAULT_WOBBLE_DEPTH_UNITS = 'cents' # or 'semitones'

DEFAULT_HUMANIZE_ENABLED = True
DEFAULT_HUMANIZE_RANGE = 10

# Drone specific defaults (can be expanded)
DEFAULT_DRONE_BASE_VELOCITY = 70
DEFAULT_DRONE_VARIATION_INTERVAL_BARS = 1 # How often the drone voicing can change
DEFAULT_DRONE_MIN_NOTES_HELD = 2 # Minimum notes of the chord to hold
DEFAULT_DRONE_OCTAVE_DOUBLING_CHANCE = 0.25 # Chance to double a note an octave up/down
DEFAULT_DRONE_ALLOW_OCTAVE_SHIFTS = True # Allow notes to shift octave during variation
DEFAULT_DRONE_ENABLE_WALKDOWNS = True # Enable melodic walkdowns to doubled notes
DEFAULT_DRONE_WALKDOWN_NUM_STEPS = 2 # Number of steps in the walkdown

# New selectable choices for walkdown step duration
TICKS_PER_QUARTER_NOTE = 480
WALKDOWN_DURATION_CHOICES = [
    questionary.Choice("Eighth Note (fastest)", value=TICKS_PER_QUARTER_NOTE // 2), # 240 ticks
    questionary.Choice("Quarter Note", value=TICKS_PER_QUARTER_NOTE),             # 480 ticks
    questionary.Choice("Half Note", value=TICKS_PER_QUARTER_NOTE * 2),               # 960 ticks
    questionary.Choice("Whole Note (slowest)", value=TICKS_PER_QUARTER_NOTE * 4)             # 1920 ticks
]
DEFAULT_DRONE_WALKDOWN_STEP_TICKS = WALKDOWN_DURATION_CHOICES[0].value # Default to Eighth Note

if __name__ == "__main__":
    print("Welcome to the MIDI Generator!")
    print("Please answer the following questions to configure your MIDI output.")
    print("Press Enter to accept the default value shown in (parentheses).\n")

    # Ask for generation type FIRST
    generation_type = questionary.select(
        "Select generation type:",
        choices=[
            questionary.Choice("Musician / style lookup (catalog + optional Cursor SDK)", value="style"),
            questionary.Choice("Arpeggio", value="arpeggio"),
            questionary.Choice("Drone/Pad", value="drone")
        ],
        default="style"
    ).ask()

    if generation_type == "style":
        print("\n--- Musician / Style Lookup ---")
        catalog_names = [m.name for m in list_musicians()]
        query = questionary.autocomplete(
            "Musician or style query:",
            choices=catalog_names,
            default="Philip Glass"
        ).ask() or "Philip Glass"
        use_sdk = questionary.confirm(
            "Use Cursor SDK if CURSOR_API_KEY is set?",
            default=True
        ).ask()
        preset_choices = [
            questionary.Choice(f"{p['label']} — {p['summary']}", value=p["id"])
            for p in list_presets()
        ]
        effects_preset = questionary.select(
            "Effects preset (plain-language):",
            choices=preset_choices,
            default="tape_and_human"
        ).ask()
        bars = int(questionary.text("Number of bars:", default="8").ask() or 8)

        print("\nResolving style…")
        path, result, options = generate_midi_for_style(
            query,
            use_cursor_sdk=bool(use_sdk),
            overrides={"effects_preset": effects_preset, "bars": bars, "debug": False},
        )
        print(result.message)
        print(f"Profile: {result.profile.name} [{result.profile.source}]")
        print(f"Styles: {', '.join(result.profile.styles)}")
        print(result.profile.description)
        print("Effects:")
        for line in explain_effects_config(options.get("effects_config") or []):
            print(f"  - {line}")
        summary = summarize_midi_file(path)
        print("\n--- Test output ---")
        print(format_summary_text(summary))
        print(f"\nWrote {path}")
        raise SystemExit(0)

    # --- Common Questions --- 
    use_multiple_root_notes = questionary.confirm(
        "Use a list of root notes for different bars? (If no, a single root note will be used)", 
        default=True
    ).ask()

    root_notes_list: List[str] = []
    root_note_int: int = DEFAULT_ROOT

    if use_multiple_root_notes:
        root_notes_str = questionary.text(
            f"Enter root notes for each bar, separated by spaces (e.g., {' '.join(DEFAULT_ROOT_NOTES)}):",
            default=' '.join(DEFAULT_ROOT_NOTES)
        ).ask()
        if root_notes_str:
            root_notes_list = root_notes_str.split()
    else:
        root_note_int = int(questionary.text(
            f"Enter the MIDI root note number (0-127, C=0):",
            default=str(DEFAULT_ROOT)
        ).ask() or DEFAULT_ROOT)

    mode = questionary.select(
        "Select the musical mode:",
        choices=MODE_CHOICES,
        default=DEFAULT_MODE
    ).ask()

    min_octave = int(questionary.text("Minimum octave for notes:", default=str(DEFAULT_MIN_OCTAVE)).ask() or DEFAULT_MIN_OCTAVE)
    max_octave = int(questionary.text("Maximum octave for notes:", default=str(DEFAULT_MAX_OCTAVE)).ask() or DEFAULT_MAX_OCTAVE)
    bpm = int(questionary.text("BPM (tempo):", default=str(DEFAULT_BPM)).ask() or DEFAULT_BPM)
    bars = int(questionary.text("Number of bars:", default=str(DEFAULT_BARS)).ask() or DEFAULT_BARS)
    
    # Set default filename based on generation type
    current_default_filename = DEFAULT_DRONE_FILENAME if generation_type == 'drone' else DEFAULT_FILENAME
    base_filename = questionary.text(
        "Base filename for output MIDI (type prefix will be added):", 
        default=current_default_filename
    ).ask() or current_default_filename

    # Ask whether to use full scale or only chord tones (relevant for both, but primarily for arpeggios now)
    # For drones, use_chord_tones is implicitly True for the basic triad.
    # We can refine this later if drones need to access full scales for "interest notes".
    use_full_scale = questionary.confirm(
        "Use all scale notes? (Default is No, only chord tones like 1,3,5 will be used for arpeggios/base of drones)", 
        default=False  
    ).ask()
    use_chord_tones = not use_full_scale

    # --- Arpeggio Specific Questions ---
    arp_steps: Optional[int] = None
    arp_mode: Optional[str] = None
    range_octaves: Optional[int] = None # Arp specific
    evolution_rate: Optional[float] = None # Arp specific
    repetition_factor: Optional[int] = None # Arp specific
    repeat_pattern: Optional[bool] = None # Arp specific

    if generation_type == 'arpeggio':
        print("\n--- Arpeggio Specific Settings ---")
        print("Choose how many steps in your arpeggio cycle.")
        print("Fewer steps = longer notes. The pattern will fill the entire bar.")
        arp_steps = questionary.select(
            "Steps per arpeggio cycle:",
            choices=ARP_STEP_CHOICES,
            default=8
        ).ask()
        
        # Ask about pattern repetition if using 8 or 4 steps
        repeat_pattern = False
        if arp_steps < 16:
            print("\nYou can either:")
            print(f"- Repeat the {arp_steps}-step pattern using 16th notes")
            print(f"- Use longer notes ({arp_steps} {'8th' if arp_steps == 8 else 'quarter'} notes)")
            repeat_pattern = questionary.confirm(
                "Would you like to repeat the pattern using 16th notes?",
                default=False
            ).ask()
        
        arp_mode = questionary.select("Arpeggiator mode:", choices=ARP_MODE_CHOICES, default=DEFAULT_ARP_MODE).ask()
        range_octaves = int(questionary.text("Arpeggio range in octaves (from min_octave):", default=str(DEFAULT_RANGE_OCTAVES)).ask() or DEFAULT_RANGE_OCTAVES)
        evolution_rate = float(questionary.text("Arpeggio evolution rate (0.0 to 1.0):", default=str(DEFAULT_EVOLUTION_RATE)).ask() or DEFAULT_EVOLUTION_RATE)
        repetition_factor = int(questionary.text("Arpeggio repetition factor (1-10):", default=str(DEFAULT_REPETITION_FACTOR)).ask() or DEFAULT_REPETITION_FACTOR)
    
    # --- Drone Specific Questions (Placeholder for future) ---
    drone_base_velocity: Optional[int] = None
    drone_variation_interval_bars: Optional[int] = None
    drone_min_notes_held: Optional[int] = None
    drone_octave_doubling_chance: Optional[float] = None
    drone_allow_octave_shifts: Optional[bool] = None
    drone_enable_walkdowns: Optional[bool] = None
    drone_walkdown_num_steps: Optional[int] = None
    drone_walkdown_step_ticks: Optional[int] = None

    if generation_type == 'drone':
        print("\n--- Drone Specific Settings ---")
        drone_base_velocity = int(questionary.text("Base MIDI velocity for drone notes (0-127):", default=str(DEFAULT_DRONE_BASE_VELOCITY)).ask() or DEFAULT_DRONE_BASE_VELOCITY)
        drone_variation_interval_bars = int(questionary.text(
            f"Drone variation interval in bars (how often voicing changes, e.g., 1-4):", 
            default=str(DEFAULT_DRONE_VARIATION_INTERVAL_BARS)
        ).ask() or DEFAULT_DRONE_VARIATION_INTERVAL_BARS)
        drone_min_notes_held = int(questionary.text(
            f"Minimum notes to hold in drone chord (e.g., 2):", 
            default=str(DEFAULT_DRONE_MIN_NOTES_HELD)
        ).ask() or DEFAULT_DRONE_MIN_NOTES_HELD)
        drone_octave_doubling_chance = float(questionary.text(
            f"Chance (0.0-1.0) to double a drone note in another octave:",
            default=str(DEFAULT_DRONE_OCTAVE_DOUBLING_CHANCE)
        ).ask() or DEFAULT_DRONE_OCTAVE_DOUBLING_CHANCE)
        drone_allow_octave_shifts = questionary.confirm(
            f"Allow drone notes to occasionally shift their primary octave?",
            default=DEFAULT_DRONE_ALLOW_OCTAVE_SHIFTS
        ).ask()
        drone_enable_walkdowns = questionary.confirm(
            f"Enable melodic walkdowns/ups to doubled octave notes?",
            default=DEFAULT_DRONE_ENABLE_WALKDOWNS
        ).ask()
        if drone_enable_walkdowns:
            drone_walkdown_num_steps = int(questionary.text(
                f"Number of steps in walkdown (e.g., 1-3):",
                default=str(DEFAULT_DRONE_WALKDOWN_NUM_STEPS)
            ).ask() or DEFAULT_DRONE_WALKDOWN_NUM_STEPS)
            drone_walkdown_step_ticks = questionary.select(
                "Duration of each walkdown step:",
                choices=WALKDOWN_DURATION_CHOICES,
                default=DEFAULT_DRONE_WALKDOWN_STEP_TICKS
            ).ask()

    # --- Effects Configuration ---
    print("\n--- Effects Configuration ---")
    print("Presets explain what you'll hear; advanced Hz/cents knobs stay under the hood.")
    preset_choices = [
        questionary.Choice(f"{p['label']} — {p['summary']}", value=p["id"])
        for p in list_presets()
    ]
    selected_preset = questionary.select(
        "Effects preset:",
        choices=preset_choices,
        default="tape_and_human"
    ).ask()
    from .effects_presets import build_effects_config
    effects_config = build_effects_config(selected_preset)
    for line in explain_effects_config(effects_config):
        print(f"  · {line}")

    options: Dict = {
        'generation_type': generation_type,
        'root': root_note_int, 
        'root_notes': root_notes_list if use_multiple_root_notes and root_notes_list else None,
        'mode': mode,
        'min_octave': min_octave,
        'max_octave': max_octave,
        'bpm': bpm,
        'bars': bars,
        'filename': base_filename, # Filename prefixing will be handled in arpeggio_generation.py
        'use_chord_tones': use_chord_tones,
        'effects_config': effects_config, # Pass effects, arpeggio_generation will decide to use them

        # Arpeggio-specific - will be None if not arpeggio type
        'arp_steps': arp_steps,
        'arp_mode': arp_mode,
        'range_octaves': range_octaves,
        'evolution_rate': evolution_rate,
        'repetition_factor': repetition_factor,
        'repeat_pattern': repeat_pattern if generation_type == 'arpeggio' and arp_steps is not None and arp_steps < 16 else False,

        # Drone-specific - will be None if not drone type
        'drone_base_velocity': drone_base_velocity,
        'drone_variation_interval_bars': drone_variation_interval_bars,
        'drone_min_notes_held': drone_min_notes_held,
        'drone_octave_doubling_chance': drone_octave_doubling_chance,
        'drone_allow_octave_shifts': drone_allow_octave_shifts,
        'drone_enable_walkdowns': drone_enable_walkdowns,
        'drone_walkdown_num_steps': drone_walkdown_num_steps,
        'drone_walkdown_step_ticks': drone_walkdown_step_ticks
    }
    
    if not use_multiple_root_notes or not root_notes_list:
        options['root_notes'] = None 
        options['root'] = root_note_int 
    else:
         options['root'] = 0 # Default if multiple root notes are primary for arpeggio logic, less relevant for drone with explicit roots

    print("\nGenerating MIDI with the following options:")
    for key, value in options.items():
        print(f"- {key}: {value}")
    print("\n")
    
    create_arp(options)
