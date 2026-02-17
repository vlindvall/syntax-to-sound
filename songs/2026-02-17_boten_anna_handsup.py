"""
Hands-Up sketch inspired by early 2000s Eurodance / "Boten Anna" energy.
"""

from renardo import *

# Global settings
Clock.bpm = 140
Scale.default = Scale.minor
Root.default = "A"

BAR = 4

# 128 bars total -> ~219 seconds (~3m39s) at 140 BPM
section_bars = [8, 16, 16, 16, 16, 8, 8, 16, 16, 8]
section_beats = [bars * BAR for bars in section_bars]
total_beats = sum(section_beats)

# Section gates
intro = var([1, 0, 0, 0, 0, 0, 0, 0, 0, 0], section_beats)
verse = var([0, 1, 0, 1, 0, 1, 0, 0, 0, 0], section_beats)
chorus = var([0, 0, 1, 0, 1, 0, 0, 1, 1, 0], section_beats)
build = var([0, 0, 0, 0, 0, 0, 1, 0, 0, 0], section_beats)
outro = var([0, 0, 0, 0, 0, 0, 0, 0, 0, 1], section_beats)

# DRUMS
# d1: kick + offbeat open hat + busy 16th pulse
d1 >> play(
    "x-o-x-o-x-o-x-o-",
    dur=1 / 4,
    amp=(0.95 + (chorus * 0.2)) * expvar([0.0, 1.0], [16, 0]),
    hpf=expvar([120, 220], [96, 32]),
)

# Extra constant closed-hat layer for a stronger "running" 16th feel
d2 >> play(
    "----------------",
    dur=1 / 4,
    amp=(0.16 + (chorus * 0.05)) * (1 - outro * 0.4),
    hpf=9000,
)

# ICONIC GALLOPING BASS
bass_line = P[0, 0, -7, 0, 0, -7, 0, -7]

b1 >> saw(
    bass_line,
    dur=1 / 4,
    oct=4,
    sus=0.11,
    amp=(0.86 + chorus * 0.14) * (1 - outro * 0.25),
    lpf=linvar([900, 2200], 32) + chorus * 500,
    hpf=100,
)

# VERSE PLUCK (filtered and simpler)
p2 >> pluck(
    [0, 2, 4, 2, 0, 2, 3, 2],
    dur=1 / 2,
    oct=5,
    sus=0.2,
    amp=verse * 0.55,
    lpf=linvar([900, 2600], [32, 32]),
    room=0.2,
    mix=0.15,
)

# CHORUS LEAD (bright, syncopated, poppy)
lead_notes = [0, 2, 4, 3, 2, 0, 2, 4, 7, 4, 3, 2]
lead_dur = P[1 / 4, 1 / 4, 1 / 2, 1 / 4, 1 / 4, 1 / 2]

p1 >> pluck(
    lead_notes,
    dur=lead_dur,
    oct=6,
    sus=0.12,
    amp=chorus * expvar([0.0, 1.0], [4, 0]),
    lpf=linvar([2200, 6500], [16, 16]),
    hpf=1200 + linvar([0, 2600], 16) * (chorus + build),
    room=0.25,
    mix=0.2,
)

# Small riser texture during build bars
n1 >> noise(
    dur=1 / 2,
    amp=build * linvar([0.0, 0.35], 32),
    hpf=linvar([3500, 9500], 32),
    room=0.3,
    mix=0.2,
)

# Auto-stop around 3m39s
Clock.future(total_beats, lambda: Clock.clear())
