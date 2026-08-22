# Chromatic Tuner

Chromatic Tuner listens to the default SolarOS audio input and shows the
nearest equal-tempered note. Its horizontal needle covers -50 through +50
cents around that note. The center band marks the in-tune region.

Hold the sound source near the microphone and sustain one clear note at a
time. The single tuner face always shows its needle and signal meter, with a
large `--` until a note locks. A detected note adds its frequency, name and
octave, cents, and pitch confidence. Detection covers approximately 50 through
900 Hz and uses A4 = 440 Hz.

## Controls

- Left/Right (or `-`/`+`) adjusts input sensitivity from 1x through 16x.
- Escape or `Q` exits.

The tuner starts at 8x input sensitivity. Reduce it if a loud instrument clips
the signal meter, or increase it for a quiet source. This bounded digital gain
works consistently across supported audio-input devices and does not change
the system microphone setting.

## Requirements

Chromatic Tuner requires SolarOS 4.8.9 or newer, a graphic display, an audio
input, PSRAM-backed Python, and the `solaros.audio.capture` and `solaros.dsp`
APIs. It captures at most 4096 native frames per update. The app does not write
recordings to storage.

Room noise, simultaneous notes, strong echoes, or a weak signal can prevent a
stable reading. For best results, play a single sustained note and mute other
strings or sound sources.
