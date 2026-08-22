"""Chromatic instrument tuner for SolarOS."""

from array import array
import math

import solaros
from solaros import gfx

import pitch


CAPTURE_FRAMES = 4096
TARGET_ANALYSIS_RATE = 8000
MIN_RMS = 140
MIN_PEAK = 500
MIN_CONFIDENCE = 0.55
INPUT_GAINS = (1, 2, 4, 8, 12, 16)
DEFAULT_INPUT_GAIN_INDEX = 3
KEY_Q = ord("q")
KEY_Q_UPPER = ord("Q")
KEY_MINUS = ord("-")
KEY_PLUS = ord("+")
KEY_EQUALS = ord("=")

GLYPHS = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
    "#": ("01010", "01010", "11111", "01010", "11111", "01010", "01010"),
}


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def centered_x(width, text, character_width):
    return max(0, (width - len(text) * character_width) // 2)


def read_controls():
    gain_steps = 0
    key = gfx.getch(0)
    while key is not None:
        if key == gfx.KEY_ESCAPE or key == KEY_Q or key == KEY_Q_UPPER:
            return True, gain_steps
        if key == gfx.KEY_LEFT or key == gfx.KEY_DOWN or key == KEY_MINUS:
            gain_steps -= 1
        elif (key == gfx.KEY_RIGHT or key == gfx.KEY_UP or
              key == KEY_PLUS or key == KEY_EQUALS):
            gain_steps += 1
        key = gfx.getch(0)
    return solaros.should_exit(), gain_steps


def yield_control():
    solaros.time.sleep_ms(0)


def draw_block_glyph(x, y, pattern, scale, color):
    gfx.color(color)
    for row in range(len(pattern)):
        line = pattern[row]
        column = 0
        while column < len(line):
            if line[column] == "0":
                column += 1
                continue
            start = column
            while column < len(line) and line[column] == "1":
                column += 1
            gfx.fill_rect(x + start * scale,
                          y + row * scale,
                          (column - start) * scale,
                          scale)


def draw_note(width, y, name, octave):
    scale = clamp(width // 34, 7, 12)
    spacing = scale
    total_cells = 5 + (6 if len(name) > 1 else 0)
    x = (width - total_cells * scale) // 2
    draw_block_glyph(x, y, GLYPHS[name[0]], scale, gfx.BLACK)
    if len(name) > 1:
        draw_block_glyph(x + 6 * scale, y, GLYPHS["#"], scale, gfx.DARK)
    gfx.font(gfx.FONT_MONO_18)
    gfx.color(gfx.BLACK)
    gfx.text(x + total_cells * scale + 5, y + 7 * scale, str(octave))


def draw_no_note(width, y):
    dash_width = max(24, width // 12)
    dash_height = max(6, width // 55)
    gap = max(12, width // 30)
    x = (width - dash_width * 2 - gap) // 2
    gfx.color(gfx.BLACK)
    gfx.fill_rect(x, y + 3 * dash_height, dash_width, dash_height)
    gfx.fill_rect(x + dash_width + gap, y + 3 * dash_height,
                  dash_width, dash_height)


def draw_meter(width, y, cents):
    left = max(20, width // 12)
    right = width - left
    span = right - left
    center = (left + right) // 2
    tune_half = max(2, span // 20)

    gfx.color(gfx.LIGHT)
    gfx.fill_rect(center - tune_half, y - 18, tune_half * 2 + 1, 37)
    gfx.color(gfx.BLACK)
    gfx.line(left, y, right, y)
    for value in (-50, -25, 0, 25, 50):
        x = left + (value + 50) * span // 100
        tick = 14 if value == 0 else 8
        gfx.line(x, y - tick, x, y + tick)

    position = left + int((clamp(cents, -50.0, 50.0) + 50.0) * span / 100.0)
    gfx.color(gfx.BLACK)
    gfx.fill_rect(position - 2, y - 25, 5, 51)
    gfx.fill_circle(position, y - 27, 5)

    gfx.font(gfx.FONT_MONO_12)
    gfx.text(left - 8, y + 26, "-50")
    gfx.text(center - 3, y + 26, "0")
    gfx.text(right - 12, y + 26, "+50")


def level_percent(rms):
    return clamp(rms * 100 // 5000, 0, 100)


def draw_reading(width, height, reading, rms, peak_value, input_gain):
    gfx.clear(gfx.WHITE)
    gfx.color(gfx.BLACK)
    gfx.font(gfx.FONT_BOLD_14)
    gfx.text(centered_x(width, "CHROMATIC TUNER", 8), 18, "CHROMATIC TUNER")

    if reading is None:
        draw_no_note(width, 31)
        gfx.font(gfx.FONT_MONO_14)
        frequency_text = "--.- Hz"
        gfx.text(centered_x(width, frequency_text, 8), 130, frequency_text)
        draw_meter(width, 176, 0.0)
        detail = "LISTENING"
        if peak_value > 0 and (rms < MIN_RMS or peak_value < MIN_PEAK):
            detail = "SIGNAL LOW"
        gfx.font(gfx.FONT_BOLD_14)
        gfx.text(centered_x(width, detail, 8), 230, detail)
    else:
        name, octave, cents, frequency = reading
        draw_note(width, 31, name, octave)
        gfx.font(gfx.FONT_MONO_14)
        frequency_text = "{:.1f} Hz".format(frequency)
        gfx.text(centered_x(width, frequency_text, 8), 130, frequency_text)
        draw_meter(width, 176, cents)

        if abs(cents) <= 5.0:
            direction = "IN TUNE"
        elif cents < 0:
            direction = "TUNE UP"
        else:
            direction = "TUNE DOWN"
        cents_text = "{:+.1f} cents   {}".format(cents, direction)
        gfx.font(gfx.FONT_BOLD_14)
        gfx.text(centered_x(width, cents_text, 8), 230, cents_text)

    bar_x = max(20, width // 12)
    bar_width = width - 2 * bar_x
    bar_y = height - 47
    percent = level_percent(rms)
    gfx.color(gfx.BLACK)
    gfx.font(gfx.FONT_SMALL)
    gfx.text(bar_x, bar_y - 4, "signal")
    gfx.rect(bar_x, bar_y, bar_width, 10)
    if percent > 0:
        gfx.fill_rect(bar_x + 2, bar_y + 2,
                      max(1, (bar_width - 3) * percent // 100), 6)
    help_text = "LEFT < gain {}x > RIGHT       Q / ESC exits".format(input_gain)
    gfx.text(centered_x(width, help_text, 6), height - 10, help_text)
    gfx.present()


def draw_error(width, height, message):
    gfx.clear(gfx.WHITE)
    gfx.color(gfx.BLACK)
    gfx.font(gfx.FONT_BOLD_18)
    gfx.text(20, 38, "Tuner unavailable")
    gfx.font(gfx.FONT_MONO_12)
    text = str(message)
    if len(text) > 48:
        text = text[:48]
    gfx.text(20, 75, text)
    gfx.text(20, height - 20, "Q / ESC exits")
    gfx.present()


def strongest_channel(raw, channels, frames):
    if channels == 1:
        return 0
    scores = [0] * channels
    for frame in range(0, frames, 4):
        offset = frame * channels
        for channel in range(channels):
            value = raw[offset + channel]
            scores[channel] += -value if value < 0 else value
    selected = 0
    for channel in range(1, channels):
        if scores[channel] > scores[selected]:
            selected = channel
    return selected


def mono_samples(pcm, channels, input_gain):
    raw = array("h", pcm)
    frames = len(raw) // channels
    channel = strongest_channel(raw, channels, frames)
    mono = array("h", bytes(frames * 2))
    total = 0
    for frame in range(frames):
        value = raw[frame * channels + channel]
        mono[frame] = value
        total += value
    mean = total // frames
    for frame in range(frames):
        value = (mono[frame] - mean) * input_gain
        mono[frame] = clamp(value, -32768, 32767)
    return mono


class Analyzer:
    def __init__(self, sample_rate):
        self.sample_rate = sample_rate
        self.factor = max(1, int(sample_rate // TARGET_ANALYSIS_RATE))
        self.analysis_rate = sample_rate / self.factor

    def close(self):
        pass

    def downsample(self, mono):
        if self.factor == 1:
            return mono
        output_count = len(mono) // self.factor
        reduced = array("h", bytes(output_count * 2))
        for output_index in range(output_count):
            start = output_index * self.factor
            total = 0
            for offset in range(self.factor):
                total += mono[start + offset]
            reduced[output_index] = total // self.factor
            if output_index % 256 == 0:
                yield_control()
        return reduced

    def analyze(self, mono):
        peak_value, rms = solaros.dsp.level(mono)
        if rms < MIN_RMS or peak_value < MIN_PEAK:
            return None, rms, peak_value
        reduced = self.downsample(mono)
        if len(reduced) <= 32:
            return None, rms, peak_value
        pitch.limit_dot_amplitude(reduced)
        frequency, confidence = pitch.yin_pitch(
            reduced, self.analysis_rate, solaros.dsp.dot,
            yield_control=yield_control)
        if frequency is None or confidence < MIN_CONFIDENCE:
            return None, rms, peak_value
        return (frequency, confidence), rms, peak_value


class Tracker:
    def __init__(self):
        self.frequencies = []

    def clear(self):
        self.frequencies = []

    def update(self, frequency):
        if self.frequencies:
            previous = self.frequencies[-1]
            separation = abs(1200.0 * math.log(
                frequency / previous) / pitch.LOG_TWO)
            if separation > 100.0:
                self.frequencies = []
        self.frequencies.append(frequency)
        if len(self.frequencies) > 3:
            self.frequencies.pop(0)
        stable = pitch.median(self.frequencies)
        note = pitch.nearest_note(stable)
        return note[0], note[1], note[2], stable


def wait_for_exit():
    while not solaros.should_exit():
        key = gfx.getch(250)
        if key == gfx.KEY_ESCAPE or key == KEY_Q or key == KEY_Q_UPPER:
            break


def main():
    audio = getattr(solaros, "audio", None)
    dsp = getattr(solaros, "dsp", None)
    if (audio is None or getattr(audio, "capture", None) is None or
            dsp is None or getattr(dsp, "dot", None) is None):
        raise RuntimeError("audio capture or DSP API is unavailable")

    gfx.begin()
    analyzer = None
    try:
        width, height = gfx.size()
        tracker = Tracker()
        input_gain_index = DEFAULT_INPUT_GAIN_INDEX
        draw_reading(width, height, None, 0, 0,
                     INPUT_GAINS[input_gain_index])
        while not solaros.should_exit():
            should_exit, gain_steps = read_controls()
            if should_exit:
                break
            if gain_steps:
                input_gain_index = int(clamp(
                    input_gain_index + gain_steps, 0, len(INPUT_GAINS) - 1))
                tracker.clear()
            try:
                pcm, sample_format = audio.capture(CAPTURE_FRAMES)
                if sample_format.get("sample_format") != "s16le":
                    raise RuntimeError("audio input is not S16LE")
                channels = sample_format.get("channels", 0)
                sample_rate = sample_format.get("sample_rate", 0)
                if channels < 1 or channels > 2 or sample_rate <= 0:
                    raise RuntimeError("unsupported audio input format")
                if analyzer is None or analyzer.sample_rate != sample_rate:
                    if analyzer is not None:
                        analyzer.close()
                    analyzer = Analyzer(sample_rate)
                mono = mono_samples(pcm, channels,
                                    INPUT_GAINS[input_gain_index])
                result, rms, peak_value = analyzer.analyze(mono)
                if result is None:
                    tracker.clear()
                    reading = None
                else:
                    reading = tracker.update(result[0])
                draw_reading(width, height, reading, rms, peak_value,
                             INPUT_GAINS[input_gain_index])
            except OSError as error:
                draw_error(width, height, error)
                solaros.time.sleep_ms(500)
            except RuntimeError as error:
                draw_error(width, height, error)
                wait_for_exit()
                break
    except Exception as error:
        draw_error(width, height, error)
        wait_for_exit()
    finally:
        if analyzer is not None:
            analyzer.close()
        gfx.end()


main()
