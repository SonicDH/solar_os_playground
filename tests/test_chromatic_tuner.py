import importlib.util
import math
from array import array
from pathlib import Path
import sys
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
PITCH_PATH = REPOSITORY / "apps/chromatic-tuner/pitch.py"
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location("chromatic_tuner_pitch", PITCH_PATH)
assert SPEC is not None and SPEC.loader is not None
pitch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pitch)


def dot(left, right):
    return sum(a * b for a, b in zip(left, right))


def small_int_dot(left, right):
    result = dot(left, right)
    if not -(1 << 30) <= result < (1 << 30):
        raise OverflowError("small int overflow")
    return result


def sine(frequency, sample_rate=8000, count=2000, amplitude=12000):
    return array(
        "h",
        (int(amplitude * math.sin(2.0 * math.pi * frequency * index / sample_rate))
         for index in range(count)),
    )


class ChromaticTunerTest(unittest.TestCase):
    def test_nearest_note_uses_a4_440(self):
        note = pitch.nearest_note(440.0)
        self.assertEqual(note[:2], ("A", 4))
        self.assertAlmostEqual(note[2], 0.0, places=6)

    def test_nearest_note_reports_signed_cents(self):
        self.assertAlmostEqual(pitch.nearest_note(445.0)[2], 19.56, places=1)
        self.assertAlmostEqual(pitch.nearest_note(435.0)[2], -19.79, places=1)

    def test_yin_finds_low_mid_and_high_notes(self):
        for expected in (82.4069, 261.6256, 440.0, 880.0):
            measured, confidence = pitch.yin_pitch(sine(expected), 8000, dot)
            self.assertIsNotNone(measured)
            self.assertLess(abs(measured - expected) / expected, 0.005)
            self.assertGreater(confidence, 0.9)

    def test_scaled_signal_fits_small_int_dot(self):
        samples = sine(440.0, count=4096, amplitude=32000)
        pitch.limit_dot_amplitude(samples)
        measured, confidence = pitch.yin_pitch(samples, 8000, small_int_dot)
        self.assertIsNotNone(measured)
        self.assertLess(abs(measured - 440.0) / 440.0, 0.005)
        self.assertGreater(confidence, 0.9)

if __name__ == "__main__":
    unittest.main()
