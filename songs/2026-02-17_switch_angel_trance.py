from renardo import *

Clock.bpm = 140
Scale.default = Scale.minor
Root.default = "G"

lead_notes = [0, 4, 0, 9, 7]

d1 >> play("x---", dur=1, amp=1.2)

p1 >> saw(
    lead_notes,
    dur=1/4,
    oct=6,
    amp=P[0.25, 0.95, 0.95, 0.95] * 0.9,
    room=0.25,
    mix=0.2,
)

b1 >> supersaw(
    lead_notes,
    dur=1/4,
    oct=4,
    amp=0.75,
    detune=0.14,
    sus=0.22,
    hpf=90,
)

n1 >> noise(
    dur=1/2,
    hpf=6500,
    amp=linvar([0.0, 0.55], 32),
    room=0.4,
    mix=0.2,
)
