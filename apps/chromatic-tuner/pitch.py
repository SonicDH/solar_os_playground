"""Pitch helpers shared by the SolarOS chromatic tuner and host tests."""

import math


NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F",
              "F#", "G", "G#", "A", "A#", "B")
A4_FREQUENCY = 440.0
A4_MIDI = 69
LOG_TWO = math.log(2.0)
DOT_AMPLITUDE_LIMIT = 240


def limit_dot_amplitude(samples):
    """Scale an S16 buffer so every pitch dot product fits a small int."""
    peak = 0
    for value in samples:
        magnitude = -value if value < 0 else value
        if magnitude > peak:
            peak = magnitude
    divisor = max(1, (peak + DOT_AMPLITUDE_LIMIT - 1) // DOT_AMPLITUDE_LIMIT)
    if divisor > 1:
        for index in range(len(samples)):
            samples[index] //= divisor
    return samples


def yin_pitch(samples, sample_rate, dot, minimum_hz=50.0,
              maximum_hz=900.0, threshold=0.20, yield_control=None):
    """Estimate frequency with a YIN-style difference function.

    ``dot`` must accept two equal-length sample buffers and return their signed
    dot product. SolarOS supplies the native implementation as ``dsp.dot``.
    """
    count = len(samples)
    if count < 32 or sample_rate <= 0:
        return None, 0.0

    minimum_lag = max(2, int(sample_rate / maximum_hz))
    maximum_lag = min(count // 2, int(sample_rate / minimum_hz) + 1)
    if minimum_lag + 2 >= maximum_lag:
        return None, 0.0

    normalized = [1.0] * (maximum_lag + 1)
    cumulative = 0.0
    for lag in range(1, maximum_lag + 1):
        if yield_control is not None and lag % 16 == 0:
            yield_control()
        left = samples[:count - lag]
        right = samples[lag:]
        difference = (dot(left, left) + dot(right, right) -
                      2 * dot(left, right))
        if difference < 0:
            difference = 0
        cumulative += difference
        if cumulative > 0:
            normalized[lag] = float(difference) * lag / cumulative

    candidate = None
    lag = minimum_lag
    while lag <= maximum_lag:
        if normalized[lag] < threshold:
            while (lag + 1 <= maximum_lag and
                   normalized[lag + 1] < normalized[lag]):
                lag += 1
            candidate = lag
            break
        lag += 1

    if candidate is None:
        candidate = minimum_lag
        for lag in range(minimum_lag + 1, maximum_lag + 1):
            if normalized[lag] < normalized[candidate]:
                candidate = lag

    confidence = 1.0 - normalized[candidate]
    if confidence <= 0:
        return None, 0.0

    period = float(candidate)
    if candidate > minimum_lag and candidate < maximum_lag:
        correlations = []
        for lag in (candidate - 1, candidate, candidate + 1):
            left = samples[:count - lag]
            right = samples[lag:]
            energy = float(dot(left, left)) * float(dot(right, right))
            if energy <= 0:
                correlations.append(0.0)
            else:
                correlations.append(dot(left, right) / math.sqrt(energy))
        before, center, after = correlations
        denominator = before - 2.0 * center + after
        if denominator != 0:
            offset = 0.5 * (before - after) / denominator
            if offset > -1.0 and offset < 1.0:
                period += offset
    if period <= 0:
        return None, 0.0
    return sample_rate / period, confidence


def nearest_note(frequency):
    """Return note name, octave, cents, MIDI number, and exact frequency."""
    if frequency is None or frequency <= 0:
        return None
    midi_float = A4_MIDI + 12.0 * math.log(
        frequency / A4_FREQUENCY) / LOG_TWO
    midi = int(midi_float + 0.5)
    cents = (midi_float - midi) * 100.0
    note_frequency = A4_FREQUENCY * (2.0 ** ((midi - A4_MIDI) / 12.0))
    return NOTE_NAMES[midi % 12], midi // 12 - 1, cents, midi, note_frequency


def median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0
