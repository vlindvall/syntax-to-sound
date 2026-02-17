"""
Switch Angel - Afterburner
A second trance sketch for live coding sets.
"""

from renardo import *

# Global settings
Clock.bpm = 140
Scale.default = Scale.minor
Root.default = "G"

lead_notes = [0, 4, 0, 9, 7]

# Kick: straight 4-on-the-floor
# Pattern is one beat long and repeats every bar.
d1 >> play("x---", dur=1, amp=1.2)

# Lead: bright saw in 16ths with built-in pumping amp motion.
p1 >> saw(
    lead_notes,
    dur=1/4,
    oct=6,
    amp=P[0.2, 0.85, 0.9, 0.95],
    lpf=3800,
    room=0.28,
    mix=0.2,
)

# Rolling bass: same motif, 2 octaves down, supersaw detune for grit.
b1 >> supersaw(
    lead_notes,
    dur=1/4,
    oct=4,
    amp=0.9,
    detune=0.22,
    sus=0.2,
    lpf=1200,
    hpf=90,
)

# 32-beat high-passed noise riser to lift transitions.
n1 >> noise(
    dur=1/2,
    hpf=7000,
    amp=linvar([0.0, 0.5], 32),
    room=0.35,
    mix=0.2,
)

# Optional pressure hats.
h1 >> play("-*-*", dur=1/2, amp=0.25, hpf=9000)
