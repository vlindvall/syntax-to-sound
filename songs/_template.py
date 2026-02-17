"""
Syntax to Sound - Renardo song sketch
Title: {song_title}
Created: {created_at}
"""

from renardo import *  # noqa: F403

Clock.bpm = 120
Scale.default = "minor"
Root.default = 0

# Start by layering patterns on players p1, p2, ... and iterate quickly.
# Example:
# p1 >> pluck([0, 2, 4, 7], dur=1/2, amp=0.8)
# p2 >> bass([0, -2, -4], dur=1, amp=0.9)
