"""
MIDI effect implementations.
"""

import random
import math
from dataclasses import dataclass
from typing import List, Optional, Dict, Union, cast, Tuple
from .effects_base import (
    MidiEffect, NoteContext, EffectConfiguration, EffectType,
    create_note_context, convert_legacy_to_instructions
)
from .midi_types import (
    MidiInstruction, WobbleState, Tick, NoteValue, Velocity,
    MIDI_PITCH_BEND_CENTER, MIDI_PITCH_BEND_MIN, MIDI_PITCH_BEND_MAX,
    DEFAULT_PITCH_BEND_UPDATE_RATE, PITCH_BEND_THRESHOLD,
    DEFAULT_BEND_UP_CENTS, DEFAULT_BEND_DOWN_CENTS,
    DEFAULT_RANDOMNESS, DEFAULT_TICKS_PER_BEAT,
    MIN_TIME_BETWEEN_BENDS_MS
)

class EffectRegistry:
    """Registry for MIDI effects."""
    
    @classmethod
    def create_effect(cls, effect_conf: Dict) -> Optional[MidiEffect]:
        """Create an effect from configuration."""
        effect_name = effect_conf.get('name', '')
        
        if effect_name == 'tape_wobble':
            config = TapeWobbleConfiguration(
                bend_up_cents=effect_conf.get('wow_depth', DEFAULT_BEND_UP_CENTS),
                bend_down_cents=effect_conf.get('wow_depth', DEFAULT_BEND_DOWN_CENTS),
                randomness=effect_conf.get('randomness', DEFAULT_RANDOMNESS),
                depth_units=effect_conf.get('depth_units', 'cents'),
                pitch_bend_update_rate=effect_conf.get('flutter_rate_hz', DEFAULT_PITCH_BEND_UPDATE_RATE)
            )
            return TapeWobbleEffect(config)
            
        elif effect_name == 'humanize_velocity':
            config = HumanizeVelocityConfiguration(
                humanization_range=effect_conf.get('humanization_range', DEFAULT_HUMANIZE_RANGE)
            )
            return HumanizeVelocityEffect(config)

            
        return None

# Constants for tape wobble effect
SEMITONES_PER_BEND = 2.0  # Standard pitch bend range
MIN_TIME_BETWEEN_BENDS_MS = 5.0  # Minimum time between pitch bend messages

# Default values for tape wobble configuration
DEFAULT_WOW_RATE_HZ = 0.5
DEFAULT_WOW_DEPTH = 20.0  # cents
DEFAULT_FLUTTER_RATE_HZ = 7.0
DEFAULT_FLUTTER_DEPTH = 5.0  # cents
DEFAULT_RANDOMNESS = 1.0
DEFAULT_PITCH_BEND_UPDATE_RATE = 30.0

# Default values for humanize velocity configuration
DEFAULT_HUMANIZE_RANGE = 10

@dataclass
class HumanizeVelocityConfiguration(EffectConfiguration):
    """Configuration for velocity humanization effect."""
    base_velocity: int = 85  # Base velocity for notes (0-127)
    humanization_range: int = 10  # Maximum velocity adjustment (±range/2)
    downbeat_emphasis: int = 4  # Additional velocity for downbeats
    pattern_strength: float = 0.6  # How strongly to apply musical patterns (0-1)
    trend_probability: float = 0.3  # Probability of starting a velocity trend
    
    def __post_init__(self):
        """Set default values and validate configuration."""
        self.effect_type = EffectType.NOTE_PROCESSOR
        self.priority = 100  # Apply early in the chain
        
        # Validate velocity parameters
        if not 0 <= self.base_velocity <= 127:
            raise ValueError("base_velocity must be between 0 and 127")
        if self.humanization_range < 0:
            raise ValueError("humanization_range must be non-negative")
        if self.base_velocity + (self.humanization_range / 2) + self.downbeat_emphasis > 127:
            raise ValueError("base_velocity + (humanization_range/2) + downbeat_emphasis cannot exceed 127")
        if self.base_velocity - (self.humanization_range / 2) < 1:
            raise ValueError("base_velocity - (humanization_range/2) cannot be less than 1")
        if not 0 <= self.pattern_strength <= 1:
            raise ValueError("pattern_strength must be between 0 and 1")
        if not 0 <= self.trend_probability <= 1:
            raise ValueError("trend_probability must be between 0 and 1")

@dataclass
class TapeWobbleConfiguration(EffectConfiguration):
    """Configuration for tape wobble effect."""
    bend_up_cents: float = DEFAULT_BEND_UP_CENTS
    bend_down_cents: float = DEFAULT_BEND_DOWN_CENTS
    randomness: float = DEFAULT_RANDOMNESS
    depth_units: str = 'cents'
    pitch_bend_update_rate: float = DEFAULT_PITCH_BEND_UPDATE_RATE

    def __post_init__(self):
        """Validate configuration parameters and set effect type."""
        self.effect_type = EffectType.SEQUENCE_PROCESSOR
        self.priority = 200  # Run after note-level effects
        
        # Validate parameters
        if self.bend_up_cents < 0:
            raise ValueError("bend_up_cents must be positive")
        if self.bend_down_cents < 0:
            raise ValueError("bend_down_cents must be positive")
        if not 0 <= self.randomness <= 1:
            raise ValueError("randomness must be between 0 and 1")
        if self.depth_units not in ['cents', 'semitones']:
            raise ValueError("depth_units must be 'cents' or 'semitones'")
        if self.pitch_bend_update_rate <= 0:
            raise ValueError("pitch_bend_update_rate must be positive")

# Legacy type for backward compatibility
MidiEvent = tuple[int, int, int, int]  # (note, start_tick, duration_tick, velocity)

# --- Tape Wobble Generation Function ---
def tape_wobble(options: dict) -> List[tuple[float, int]]:
    """
    Generates a simulated "tape wobble" modulation signal over time.
    
    Returns:
        List of tuples (time_sec, bend_value) where:
        - time_sec: The time in seconds when this bend value should be applied
        - bend_value: The MIDI pitch bend value (-8192 to 8191)
    """
    debug = options.get('debug', False)
    if debug:
        print("\n=== Tape Wobble Generation Debug ===")
    duration = options.get('duration_sec', 5.0)
    wow_rate = options.get('wow_rate_hz', DEFAULT_WOW_RATE_HZ)
    wow_depth = options.get('wow_depth', DEFAULT_WOW_DEPTH)
    flutter_rate = options.get('flutter_rate_hz', DEFAULT_FLUTTER_RATE_HZ)
    flutter_depth = options.get('flutter_depth', DEFAULT_FLUTTER_DEPTH)
    randomness = options.get('randomness', DEFAULT_RANDOMNESS)
    depth_units = options.get('depth_units', 'cents')
    
    if debug:
        print(f"Parameters:")
        print(f"  Duration: {duration:.2f} sec")
        print(f"  Wow Rate: {wow_rate:.2f} Hz, Depth: {wow_depth:.2f}")
        print(f"  Flutter Rate: {flutter_rate:.2f} Hz, Depth: {flutter_depth:.2f}")
        print(f"  Randomness: {randomness:.2f}")
        print(f"  Depth Units: {depth_units}")
    
    # Calculate optimal sample rate
    nyquist_factor = 4.0
    min_sample_rate = max(
        wow_rate * nyquist_factor,
        flutter_rate * nyquist_factor,
        DEFAULT_PITCH_BEND_UPDATE_RATE
    )
    sample_rate_hz = min(50, max(10, int(min_sample_rate)))
    if debug:
        print(f"Calculated sample rate: {sample_rate_hz} Hz")
    
    if duration <= 0:
        if debug:
            print("Duration <= 0, returning empty list")
        return []

    num_samples = int(duration * sample_rate_hz)
    wobble_data: List[tuple[float, int]] = []
    last_emitted_value = 0
    last_emission_time = 0.0

    # Initialize phase offsets
    clamped_randomness = max(0.0, min(1.0, randomness))
    wow_phase = random.random() * 2 * math.pi * clamped_randomness
    flutter_phase = random.random() * 2 * math.pi * clamped_randomness
    
    if debug:
        print(f"\nInitial phases:")
        print(f"  Wow Phase: {wow_phase:.2f} rad")
        print(f"  Flutter Phase: {flutter_phase:.2f} rad")
        print("\nStarting wobble generation...")

    # Always emit initial center value
    wobble_data.append((0.0, 0))

    # Debug counters
    total_values = 0
    emitted_values = 0

    for i in range(num_samples):
        total_values += 1
        t = i / sample_rate_hz
        
        # Calculate components
        wow = wow_depth * math.sin(2 * math.pi * wow_rate * t + wow_phase)
        flutter = flutter_depth * math.sin(2 * math.pi * flutter_rate * t + flutter_phase)
        total_mod = wow + flutter

        # Convert to pitch bend value
        if depth_units == 'cents':
            semitones = total_mod / 100.0
        else:
            semitones = total_mod

        bend_value = int(round((semitones / SEMITONES_PER_BEND) * 8192))
        bend_value = max(MIDI_PITCH_BEND_MIN, min(MIDI_PITCH_BEND_MAX, bend_value))

        # Determine if we should emit
        time_since_last = t - last_emission_time
        value_change = abs(bend_value - last_emitted_value)
        
        if (time_since_last >= MIN_TIME_BETWEEN_BENDS_MS / 1000.0 and 
            value_change >= PITCH_BEND_THRESHOLD):
            wobble_data.append((t, bend_value))
            last_emitted_value = bend_value
            last_emission_time = t
            emitted_values += 1
            
            if debug and (emitted_values <= 5 or emitted_values % 50 == 0):
                print(f"t={t:.3f}s: wow={wow:.2f}, flutter={flutter:.2f}, total={total_mod:.2f}, "
                      f"semitones={semitones:.3f}, bend={bend_value}")

    if debug:
        ratio = (total_values / emitted_values) if emitted_values else 0
        print(f"\nWobble generation complete:")
        print(f"Total values calculated: {total_values}")
        print(f"Values emitted: {emitted_values}")
        print(f"Compression ratio: {ratio:.1f}:1")
        print("=====================================\n")
    return wobble_data


# --- Tape Wobble Effect Class (replaces ShimmerEffect) ---
class TapeWobbleEffect(MidiEffect):
    """
    Simulates tape machine pitch instability through wow and flutter effects.
    This is a sequence-level processor that generates MIDI pitch bend messages.
    """
    
    def __init__(self, config: Optional[TapeWobbleConfiguration] = None):
        """Initialize with optional configuration."""
        super().__init__(config or TapeWobbleConfiguration())
        self.config = cast(TapeWobbleConfiguration, self.config)
        self.wobble_state = WobbleState()
    
    def _validate_configuration(self) -> None:
        """Configuration is already validated in TapeWobbleConfiguration.__post_init__"""
        pass
    
    def _process_note_impl(self, ctx: NoteContext) -> NoteContext:
        """Note-level processing is a no-op for this effect."""
        return ctx
    
    def _process_sequence_impl(self, 
                             events: List[Union[MidiInstruction, Tuple]], 
                             options: Dict) -> List[MidiInstruction]:
        """Process the complete sequence, adding pitch bend messages for the wobble effect."""
        debug = options.get('debug', False)
        _print = print if debug else (lambda *a, **k: None)
        # Get sequence parameters
        bpm = options.get('bpm', 120)
        ticks_per_beat = options.get('ticks_per_beat', DEFAULT_TICKS_PER_BEAT)
        
        # First, analyze note lengths and positions
        note_events = []
        max_tick = 0
        
        for event in events:
            if isinstance(event, tuple):
                if isinstance(event[0], str):  # New format
                    msg_type, tick, *params = event
                    if msg_type == 'note_on':
                        note_events.append((tick, params[0]))  # (start_tick, note)
                    elif msg_type == 'note_off':
                        max_tick = max(max_tick, tick)
                else:  # Legacy format
                    if len(event) >= 3:  # note, start_tick, duration_tick
                        note, start_tick, duration_tick, *_ = event
                        note_events.append((start_tick, note))
                        max_tick = max(max_tick, start_tick + duration_tick)
        
        # Sort notes by start time
        note_events.sort(key=lambda x: x[0])
        
        total_duration_seconds = (max_tick / ticks_per_beat) * (60.0 / bpm)
        _print(f"Sequence duration: {total_duration_seconds:.2f} seconds")
        _print(f"BPM: {bpm}, Ticks per beat: {ticks_per_beat}")
        _print(f"Found {len(note_events)} notes")
        
        # Generate wobble data based on note positions
        wobble_events = self._generate_wobble_events(
            total_duration_seconds, 
            bpm, 
            ticks_per_beat,
            note_events
        )
        
        # Convert to MIDI instructions
        midi_channel = 0
        midi_instructions: List[MidiInstruction] = []
        
        # Add RPN messages for pitch bend range
        _print("\nAdding RPN configuration messages...")
        midi_instructions.extend([
            ('control_change', 0, 101, 0, midi_channel),   # RPN MSB
            ('control_change', 0, 100, 0, midi_channel),   # RPN LSB
            ('control_change', 0, 6, 2, midi_channel),     # Data Entry MSB (2 semitones)
            ('control_change', 0, 38, 0, midi_channel),    # Data Entry LSB (0)
            ('control_change', 0, 101, 127, midi_channel), # Exit RPN mode
            ('control_change', 0, 100, 127, midi_channel)  # Exit RPN mode
        ])
        
        # Add original events
        for event in events:
            if isinstance(event, tuple):
                midi_instructions.append(event)
        
        # Add pitch bend events
        _print("\nAdding pitch bend messages...")
        for time_sec, bend_value in wobble_events:
            tick = int((time_sec * bpm * ticks_per_beat) / 60.0)
            midi_instructions.append(('pitch_bend', tick, bend_value, midi_channel))
        
        # Sort all instructions by tick and type
        midi_instructions.sort(key=lambda x: (x[1], x[0] != 'note_off'))
        return midi_instructions
    
    def _generate_wobble_events(self, 
                              duration_sec: float, 
                              bpm: float, 
                              ticks_per_beat: int,
                              note_events: List[Tuple[int, int]]) -> List[Tuple[float, int]]:
        """
        Generate note-synchronized wobble data points.
        Each note alternates direction - if one note goes up, the next goes down.
        Returns list of (time_sec, bend_value) tuples.
        """
        _print("\nGenerating alternating note-synchronized wobble data...")
        
        # Calculate musical time parameters
        beats_per_bar = 4  # Assuming 4/4 time
        seconds_per_beat = 60.0 / bpm
        seconds_per_bar = seconds_per_beat * beats_per_bar
        total_bars = duration_sec / seconds_per_bar
        
        _print(f"Musical timing:")
        _print(f"  BPM: {bpm}")
        _print(f"  Total bars: {total_bars:.2f}")
        _print(f"  Seconds per bar: {seconds_per_bar:.2f}")
        
        # Calculate note timings in seconds
        note_times = [(tick / ticks_per_beat * seconds_per_beat, note) 
                     for tick, note in note_events]
        
        if not note_times:
            note_times = [(0, 60)]  # Default note if no notes found
        
        # Randomly determine initial direction
        first_note_up = random.choice([True, False])
        _print(f"\nInitial direction: {'UP' if first_note_up else 'DOWN'}")
        
        # Calculate optimal sample rate
        sample_rate_hz = self.config.pitch_bend_update_rate
        num_samples = int(duration_sec * sample_rate_hz)
        
        wobble_data: List[Tuple[float, int]] = []
        last_emitted_value = 0
        last_emission_time = 0.0
        
        # Add initial center point
        wobble_data.append((0.0, 0))
        _print("\nGenerating pitch bend curve...")
        
        # Apply very slight random variation to max bend values
        rand_factor = 1.0 + (random.random() - 0.5) * self.config.randomness
        max_up_cents = self.config.bend_up_cents * rand_factor
        rand_factor = 1.0 + (random.random() - 0.5) * self.config.randomness
        max_down_cents = self.config.bend_down_cents * rand_factor
        
        _print(f"Maximum bend values (with randomness):")
        _print(f"  Up: {max_up_cents:.1f} cents")
        _print(f"  Down: {max_down_cents:.1f} cents")
        
        for i in range(num_samples):
            t = i / sample_rate_hz
            
            # Find current note segment
            current_note_idx = 0
            for idx, (note_time, _) in enumerate(note_times[1:], 1):
                if t >= note_time:
                    current_note_idx = idx
                else:
                    break
            
            # Calculate position within note
            note_start_time = note_times[current_note_idx][0]
            note_end_time = note_times[current_note_idx + 1][0] if current_note_idx + 1 < len(note_times) else duration_sec
            note_duration = note_end_time - note_start_time
            position_in_note = (t - note_start_time) / note_duration
            
            # Determine direction for this note (alternates each note)
            note_goes_up = first_note_up if current_note_idx % 2 == 0 else not first_note_up
            
            # Calculate smooth curve using sine interpolation
            curve_position = (1 - math.cos(position_in_note * math.pi)) / 2
            
            # Calculate bend amount in cents based on direction
            if note_goes_up:
                bend_cents = curve_position * max_up_cents
            else:
                bend_cents = -curve_position * max_down_cents
            
            # Convert to pitch bend value
            if self.config.depth_units == 'cents':
                semitones = bend_cents / 100.0
            else:
                semitones = bend_cents
            
            # Calculate bend value ensuring it stays within MIDO's required range
            bend_value = int(round((semitones / SEMITONES_PER_BEND) * 8192))
            bend_value = max(MIDI_PITCH_BEND_MIN, min(MIDI_PITCH_BEND_MAX, bend_value))
            
            # Determine if we should emit this value
            time_since_last = t - last_emission_time
            value_change = abs(bend_value - last_emitted_value)
            
            if (time_since_last >= MIN_TIME_BETWEEN_BENDS_MS / 1000.0 and 
                (value_change >= PITCH_BEND_THRESHOLD or time_since_last >= 0.1)):
                wobble_data.append((t, bend_value))
                last_emitted_value = bend_value
                last_emission_time = t
                
                # Log progress at key points
                if position_in_note < 0.1 or len(wobble_data) <= 1:
                    direction = "UP" if note_goes_up else "DOWN"
                    _print(f"Note {current_note_idx + 1} ({direction}): {bend_cents:+.1f} cents (bend: {bend_value:+d})")
        
        _print(f"\nGenerated {len(wobble_data)} pitch bend points")
        return wobble_data


# Remove old HumanizeVelocityEffect if it's not used or if we are simplifying
# For now, let's keep it as it's a different type of effect.
class HumanizeVelocityEffect(MidiEffect):
    """
    Adds natural variation to note velocities to simulate human performance.
    Includes musical patterns like:
    - First/last note emphasis
    - Beat position awareness
    - Gradual velocity trends
    - Natural accent patterns
    """
    
    def __init__(self, config: Optional[HumanizeVelocityConfiguration] = None):
        """Initialize with optional configuration."""
        super().__init__(config or HumanizeVelocityConfiguration())
        self.config = cast(HumanizeVelocityConfiguration, self.config)
        self._reset_state()
    
    def _reset_state(self) -> None:
        """Reset the internal state for new sequence."""
        self.current_trend: Optional[float] = None  # Direction of velocity trend
        self.trend_remaining: int = 0  # How many notes remain in current trend
        self.last_velocity: int = self.config.base_velocity
        self.notes_processed: int = 0
    
    def _validate_configuration(self) -> None:
        """Configuration is already validated in HumanizeVelocityConfiguration.__post_init__"""
        pass
    
    def _calculate_position_emphasis(self, ctx: NoteContext) -> int:
        """Calculate velocity emphasis based on note position in sequence."""
        is_first_note = ctx.get('is_first_note', False)
        is_last_note = ctx.get('is_last_note', False)
        
        emphasis = 0
        if is_first_note:
            # First notes often slightly stronger
            emphasis += int(3 * self.config.pattern_strength)
        elif is_last_note:
            # Last notes often slightly softer
            emphasis -= int(2 * self.config.pattern_strength)
        
        return emphasis
    
    def _calculate_beat_emphasis(self, ctx: NoteContext) -> int:
        """Calculate velocity emphasis based on beat position."""
        tick = ctx.get('tick', 0)
        ticks_per_beat = ctx.get('options', {}).get('ticks_per_beat', DEFAULT_TICKS_PER_BEAT)
        
        # Calculate beat position
        beat_position = (tick % (ticks_per_beat * 4)) / ticks_per_beat
        
        emphasis = 0
        if beat_position < 0.1:  # Downbeat
            emphasis += int(self.config.downbeat_emphasis * self.config.pattern_strength)
        elif abs(beat_position - 2) < 0.1:  # Backbeat
            emphasis += int(2 * self.config.pattern_strength)
        
        return emphasis
    
    def _update_velocity_trend(self) -> int:
        """Update and return the current velocity trend influence."""
        if self.trend_remaining <= 0:
            # Consider starting new trend
            if random.random() < self.config.trend_probability:
                self.current_trend = random.choice([-1.0, 1.0]) * self.config.pattern_strength
                self.trend_remaining = random.randint(3, 8)  # Trend length
            else:
                self.current_trend = None
        
        if self.current_trend is not None:
            self.trend_remaining -= 1
            return int(self.current_trend * (self.config.humanization_range / 4))
        return 0
    
    def _process_note_impl(self, ctx: NoteContext) -> NoteContext:
        """Apply sophisticated velocity humanization to a single note."""
        if ctx['velocity'] <= 0:  # Don't process note-off events
            return ctx
        
        # Get base velocity
        if ctx['velocity'] == 64:  # Default MIDI velocity
            base = self.config.base_velocity
        else:
            base = max(1, min(127, ctx['velocity']))
        
        # Calculate various influences
        position_emphasis = self._calculate_position_emphasis(ctx)
        beat_emphasis = self._calculate_beat_emphasis(ctx)
        trend_influence = self._update_velocity_trend()
        
        # Calculate random variation (smaller range now that we have other influences)
        random_variation = random.randint(
            -self.config.humanization_range // 3,
            self.config.humanization_range // 3
        )
        
        # Combine all influences
        total_adjustment = (
            position_emphasis +
            beat_emphasis +
            trend_influence +
            random_variation
        )
        
        # Create new context with adjusted velocity
        new_ctx = ctx.copy()
        new_velocity = max(1, min(127, base + total_adjustment))
        new_ctx['velocity'] = new_velocity
        
        # Debug output for significant changes or pattern events
        if (abs(total_adjustment) > self.config.humanization_range // 3 or
            position_emphasis != 0 or beat_emphasis != 0):
            if False:  # verbose per-note logging disabled by default
                print(f"Note velocity adjusted: {base} -> {new_velocity} "
                  f"(total: {total_adjustment:+d}, "
                  f"pos: {position_emphasis:+d}, "
                  f"beat: {beat_emphasis:+d}, "
                  f"trend: {trend_influence:+d}, "
                  f"random: {random_variation:+d})")
        
        # Update state
        self.last_velocity = new_velocity
        self.notes_processed += 1
        
        return new_ctx
    
    def _process_sequence_impl(self, events: List[Union[MidiInstruction, Tuple]], 
                             options: Dict) -> List[Union[MidiInstruction, Tuple]]:
        """Reset state at start of sequence."""
        self._reset_state()
        return events
