import os
from .notes import note_str_to_midi, note_to_name
from .arpeggio import create_arpeggio
from .drone_generation import generate_drone_events
from .midi import create_midi_file
from typing import Any, Dict, List, Optional, Sequence, Union
from .effects import EffectRegistry
from .effects_base import MidiEffect
from .pattern_development import (
    apply_phase_offset,
    evolve_phase,
    mutate_cell,
    normalize_development,
)
import random


def _resolve_chord_progression(
    raw: Any,
    fallback_root: int,
) -> Optional[List[int]]:
    """Accept MIDI ints, note-name strings, or None → list of MIDI roots."""
    if not raw:
        return None
    if not isinstance(raw, (list, tuple)):
        return None
    out: List[int] = []
    for item in raw:
        if isinstance(item, int):
            out.append(int(item))
        elif isinstance(item, str):
            try:
                out.append(note_str_to_midi(item))
            except (ValueError, IndexError, TypeError):
                continue
    return out or None


# timing_factor discrete set: Double / 1× / Half / Quarter time.
_TIMING_FACTORS = (0.5, 1.0, 2.0, 4.0)


def resolve_extend_factor(raw: Any) -> int:
    """Clamp legacy extend multiplier to 1–4 (identity when unset / invalid).

    ``extend_factor`` cannot express Double time (0.5). Prefer ``timing_factor``.
    Mapping when only extend is set: 1→1, 2→2, 3→3, 4→4.
    """
    if raw is None:
        return 1
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 1
    return max(1, min(4, value))


def resolve_timing_factor(raw: Any) -> float:
    """Clamp timing_factor to {0.5, 1, 2, 4}; identity 1.0 when unset / invalid.

    Semantics (multiply bars-per-chord; chord count unchanged):
      0.5 Double  — faster (shorter bars-per-chord)
      1   identity
      2   Half    — 1 bar/chord → 2
      4   Quarter — 1 bar/chord → 4
    """
    if raw is None:
        return 1.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 1.0
    for allowed in _TIMING_FACTORS:
        if abs(value - allowed) < 1e-9:
            return allowed
    return 1.0


def _segment_count_for_timing(options: Dict) -> int:
    """Chord / root segment count for bars-per-chord stretch math."""
    prog = options.get("chord_progression")
    if isinstance(prog, (list, tuple)) and len(prog) > 0:
        return len(prog)
    roots = options.get("root_notes")
    if isinstance(roots, (list, tuple)) and len(roots) > 0:
        return len(roots)
    return 1


def _effective_timing_factor(options: Dict, factor: Optional[Any] = None) -> float:
    """Prefer timing_factor; fall back to extend_factor (1–4 only, no 0.5)."""
    if factor is not None:
        # Explicit kwarg: accept timing set, else legacy extend int (incl. 3).
        as_timing = resolve_timing_factor(factor)
        try:
            raw_f = float(factor)
        except (TypeError, ValueError):
            return as_timing
        if any(abs(raw_f - a) < 1e-9 for a in _TIMING_FACTORS):
            return as_timing
        return float(resolve_extend_factor(factor))
    if options.get("timing_factor") is not None:
        return resolve_timing_factor(options.get("timing_factor"))
    # Legacy alias: extend_factor 1→1, 2→2, 4→4 (and 3→3); no Double via extend.
    return float(resolve_extend_factor(options.get("extend_factor", 1)))


def apply_timing_factor(options: Dict, factor: Optional[Any] = None) -> Dict:
    """
    Return a copy of ``options`` with ``bars`` scaled by timing_factor.

    Multiplies bars-per-chord (total ``bars`` proportionally). Chord count /
    progression length unchanged.

    Double (0.5) floors at ½ bar per chord — never below 0.5 bars/chord after
    stretch; ``bars`` rounded to an integer ≥ 1.

    Prefer ``timing_factor``. If only ``extend_factor`` is set, map 1→1, 2→2,
    4→4 (no 0.5 via extend). Safe before ``create_arp``.
    """
    opts = dict(options)
    resolved = _effective_timing_factor(opts, factor)
    opts["timing_factor"] = resolved
    # Keep extend_factor readable for legacy callers when expressible as 1–4.
    if resolved in (1.0, 2.0, 3.0, 4.0) and float(resolved) == int(resolved):
        opts["extend_factor"] = int(resolved)
    else:
        # Double time is timing-only; legacy extend stays identity.
        opts["extend_factor"] = 1

    if abs(resolved - 1.0) > 1e-9:
        base_bars = int(opts.get("bars", 16))
        n = _segment_count_for_timing(opts)
        base_bpc = base_bars / float(n)
        new_bpc = max(0.5, base_bpc * resolved)
        opts["bars"] = max(1, int(round(new_bpc * n)))
    return opts


def apply_extend_factor(options: Dict, factor: Optional[Any] = None) -> Dict:
    """
    Thin alias of ``apply_timing_factor``.

    Legacy ``extend_factor`` is 1–4 only (no Double / 0.5). Prefer
    ``timing_factor`` / ``apply_timing_factor`` for new callers.
    """
    return apply_timing_factor(options, factor=factor)


def apply_generation_mode(
    options: Dict,
    mode: Optional[str],
) -> Dict:
    """
    Home Pattern | Progression override on a flat options dict.

    ``pattern`` → ``generation_type=arpeggio`` (leave ``drone_held`` alone).
    ``progression`` → ``generation_type=drone`` and ``drone_held=True`` unless
    options already have explicit ``drone_held=False`` (Eno wash opt-out wins).
    ``None`` / unknown → copy unchanged.

    Does not rewrite ``chord_progression``, ``development``, or fingerprint
    fields. Recipe/who default still comes from the profile; this is a UI
    toggle override only.
    """
    opts = dict(options)
    if mode is None:
        return opts
    key = str(mode).strip().lower()
    if key == "pattern":
        opts["generation_type"] = "arpeggio"
    elif key == "progression":
        opts["generation_type"] = "drone"
        # Explicit False (wash) must still win.
        if opts.get("drone_held") is not False:
            opts["drone_held"] = True
    return opts


def resolve_drone_held(
    options: Dict,
    chord_progression: Optional[List[int]],
) -> bool:
    """
    Held progression default: True when ``chord_progression`` is set.

    Explicit ``drone_held`` / ``held`` wins. Ambient wash recipes opt out with
    ``drone_held=False`` (or omit progression).
    """
    if "drone_held" in options:
        return bool(options["drone_held"])
    if "held" in options:
        return bool(options["held"])
    return bool(chord_progression)


def apply_arp_step_mask(
    cell: Sequence[Optional[int]],
    *,
    arp_steps: int,
    gates: Optional[Sequence[Any]] = None,
    pitches: Optional[Sequence[Any]] = None,
) -> List[Optional[int]]:
    """Pad/truncate a cell, rest closed gates, replace int pitches."""
    out: List[Optional[int]] = list(cell)[:arp_steps]
    if len(out) < arp_steps:
        out.extend([None] * (arp_steps - len(out)))
    if gates is not None:
        padded_gates = list(gates)[:arp_steps]
        padded_gates.extend([True] * (arp_steps - len(padded_gates)))
        for index, on in enumerate(padded_gates):
            if not on:
                out[index] = None
    if pitches is not None:
        padded_pitches = list(pitches)[:arp_steps]
        padded_pitches.extend([None] * (arp_steps - len(padded_pitches)))
        for index, pitch in enumerate(padded_pitches):
            if isinstance(pitch, int):
                out[index] = pitch
    return out


def _expand_cell_to_grid(
    cell: Sequence[Optional[int]],
    *,
    arp_steps: int,
    steps_per_note: int,
    repeat_pattern: bool,
    repeats_per_bar: int,
) -> List[Optional[int]]:
    """Place one bar of a cell onto the 16th-note event grid."""
    events: List[Optional[int]] = []
    for _ in range(repeats_per_bar):
        for note in cell:
            if arp_steps == 16 or repeat_pattern or steps_per_note <= 1:
                events.append(note)
            else:
                events.append(note)
                events.extend([None] * (steps_per_note - 1))
    return events


def create_arp(options: Dict):
    """
    Main function to generate MIDI data based on given options.
    """
    options = apply_timing_factor(dict(options))  # avoid mutating caller; stretch bars
    debug = options.get('debug', False)
    root = options.get('root', 0)
    root_notes_str_param = options.get('root_notes', None)
    generation_type = options.get('generation_type', 'arpeggio')
    if generation_type not in ('arpeggio', 'drone'):
        raise ValueError(f"Unsupported generation_type: {generation_type!r}")

    if debug:
        print(f"[DEBUG] Generation Type: {generation_type}")
        print(f"[DEBUG] root_notes_str_param from options: {root_notes_str_param}")
        tf = options.get("timing_factor", 1)
        if tf != 1 and tf != 1.0:
            print(f"[DEBUG] timing_factor={tf} → bars={options.get('bars')}")
        elif options.get("extend_factor", 1) > 1:
            print(f"[DEBUG] extend_factor={options['extend_factor']} → bars={options.get('bars')}")

    processed_root_notes_midi: List[int] = []
    if root_notes_str_param:
        processed_root_notes_midi = [note_str_to_midi(note) for note in root_notes_str_param]
    else:
        processed_root_notes_midi = [root] * options.get('bars', 16)

    if debug:
        print(f"[DEBUG] Processed root_notes (MIDI numbers): {processed_root_notes_midi}")
        print(f"[DEBUG] Length of processed root_notes: {len(processed_root_notes_midi) if processed_root_notes_midi else 0}")

    mode = options.get('mode', 'major')
    bars = options.get('bars', 16)
    min_octave = options.get('min_octave', 4)
    max_octave = options.get('max_octave', 6)
    use_chord_tones = options.get('use_chord_tones', True)
    mode_color = options.get('mode_color', True)

    # Arpeggio-specific options
    arp_steps = options.get('arp_steps', 8)
    arp_mode = options.get('arp_mode', 'up')
    range_octaves = options.get('range_octaves', 1)
    evolution_rate = options.get('evolution_rate', 0.1)
    repetition_factor = options.get('repetition_factor', 5)
    rhythmic_variation = bool(options.get('rhythmic_variation', False))
    embellish = bool(options.get('embellish', False))
    chord_progression = _resolve_chord_progression(
        options.get('chord_progression'),
        root,
    )
    development = normalize_development(options.get('development'))
    if generation_type == 'arpeggio':
        if not isinstance(arp_steps, int) or arp_steps <= 0:
            raise ValueError(f"arp_steps must be a positive int, got {arp_steps!r}")

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
            print(f"[DEBUG] Effect configuration: {effect_conf}")

        if effect := EffectRegistry.create_effect(effect_conf):
            if debug:
                print(f"[DEBUG] Successfully created effect: {effect_name}")
            active_effects.append(effect)
        else:
            # Unknown names are a configuration error — don't silently drop them.
            raise ValueError(f"Unknown or invalid effect: {effect_name!r} ({effect_conf})")

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

        # Expose to MIDI writer so note duration matches the label (8th/quarter).
        options['steps_per_note'] = steps_per_note

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
        if debug and development:
            print(f"[DEBUG] Development: {development}")

        # This will hold our flat list of notes
        final_event_list: List[Optional[int]] = []
        rng = random.Random(options.get('seed')) if options.get('seed') is not None else random.Random()

        if processed_root_notes_midi:
            bars_per_segment = bars // len(processed_root_notes_midi) if len(processed_root_notes_midi) > 0 else bars
            global_bar = 0

            for idx, current_root_midi in enumerate(processed_root_notes_midi):
                num_bars_for_segment = bars_per_segment
                if idx == len(processed_root_notes_midi) - 1:
                    num_bars_for_segment = bars - (bars_per_segment * idx)
                if num_bars_for_segment <= 0:
                    continue

                # Seed cell for this harmonic segment
                segment_progression = chord_progression
                if segment_progression is None and options.get('chord_progression') is None:
                    # Optional per-segment vamp: allow profiles to pass relative
                    # progression keyed off the current root via 'chord_intervals'
                    intervals = options.get('chord_intervals')
                    if intervals and isinstance(intervals, (list, tuple)):
                        segment_progression = [
                            current_root_midi + int(iv) for iv in intervals
                        ]

                seed = create_arpeggio(
                    current_root_midi,
                    mode,
                    arp_steps,
                    min_octave,
                    max_octave,
                    arp_mode,
                    range_octaves,
                    use_chord_tones=use_chord_tones,
                    evolution_rate=evolution_rate,
                    repetition_factor=repetition_factor,
                    mode_color=mode_color,
                    rhythmic_variation=rhythmic_variation,
                    embellish=embellish,
                    chord_progression=segment_progression,
                    bar_index=global_bar,
                    preserve_rests=True,
                    rng=rng,
                )
                if not seed:
                    continue

                cell: List[Optional[int]] = list(seed)
                phase = 0
                source_notes = [n for n in cell if n is not None]

                for bar_i in range(num_bars_for_segment):
                    # Mutate after the seed window, every N bars
                    if development and bar_i >= development["seed_bars"]:
                        since_seed = bar_i - development["seed_bars"]
                        if since_seed % development["mutate_every_n"] == 0:
                            cell = mutate_cell(
                                cell,
                                mutate_ops=development["mutate_ops"],
                                source_notes=source_notes or None,
                                additive_only=development["additive_only"],
                                rng=rng,
                            )
                            if development.get("phase_creep"):
                                phase = evolve_phase(
                                    phase, max_phase=development.get("max_phase", 2)
                                )

                    # Re-apply bar-aware rhythm/embellish lightly when enabled
                    # (keeps odd-bar accent flip alive across developed cells).
                    bar_cell = list(cell)
                    if rhythmic_variation and bar_i > 0:
                        from .arpeggio import _apply_rhythmic_variation
                        bar_cell = _apply_rhythmic_variation(
                            bar_cell, bar_index=global_bar + bar_i, rng=rng
                        )
                        if len(bar_cell) < arp_steps:
                            bar_cell = bar_cell + [None] * (arp_steps - len(bar_cell))
                        bar_cell = bar_cell[:arp_steps]
                    if embellish and (global_bar + bar_i) % 2 == 0 and source_notes:
                        from .arpeggio import _apply_embellish
                        bar_cell = _apply_embellish(
                            bar_cell,
                            source_notes,
                            bar_index=global_bar + bar_i,
                            steps_hint=arp_steps,
                            rng=rng,
                        )

                    placed = apply_phase_offset(bar_cell, phase)
                    gates = options.get("arp_gates")
                    pitches = options.get("arp_pitches")
                    if gates is not None or pitches is not None:
                        placed = apply_arp_step_mask(
                            placed,
                            arp_steps=arp_steps,
                            gates=gates,
                            pitches=pitches,
                        )
                    final_event_list.extend(
                        _expand_cell_to_grid(
                            placed,
                            arp_steps=arp_steps,
                            steps_per_note=steps_per_note,
                            repeat_pattern=bool(repeat_pattern),
                            repeats_per_bar=repeats_per_bar,
                        )
                    )

                global_bar += num_bars_for_segment

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
        # Recipe progression wins over parallel root_notes for segment roots.
        if chord_progression:
            processed_root_notes_midi = list(chord_progression)
        drone_held = resolve_drone_held(drone_options, chord_progression)
        drone_options["drone_held"] = drone_held
        # Slow sparse mutate: map development.mutate_every_n → variation interval
        # (wash path only — held sustains one voicing for the full segment)
        if (
            not drone_held
            and development
            and development.get("mutate_every_n")
        ):
            drone_options["drone_variation_interval_bars"] = max(
                int(drone_options.get("drone_variation_interval_bars", 2)),
                int(development["mutate_every_n"]),
            )
        # Same seed contract as arpeggio path — Again / explicit seed must bind drone RNG
        drone_rng = (
            random.Random(options.get("seed"))
            if options.get("seed") is not None
            else random.Random()
        )
        final_event_list = generate_drone_events(
            drone_options, processed_root_notes_midi, rng=drone_rng
        )
        if debug:
            print(
                f"[INFO] Drone generation selected "
                f"(held={drone_held}). {len(final_event_list)} drone events generated."
            )

    # --- Filename and MIDI file creation ---
    root_notes_names_for_file = '-'.join([note_to_name(note) for note in processed_root_notes_midi]) if processed_root_notes_midi else str(root)
    base_filename = f"{generation_type}_{mode}_{root_notes_names_for_file}"

    output_folder = "generated"
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(current_script_dir, output_folder)
    if not os.path.exists(output_path):
        os.makedirs(output_path)
    # Honor an explicit filename (tests / callers); otherwise build under generated/.
    explicit = options.get('filename')
    if explicit and (os.path.isabs(str(explicit)) or str(explicit).endswith('.mid')):
        file_path = str(explicit)
        parent = os.path.dirname(file_path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent)
    else:
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
