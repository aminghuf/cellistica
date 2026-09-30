"""Cello strings, left-hand positions and hand shapes.

Everything here is plain data so it can be edited without touching the search.

A *position* is named by where the 1st finger sits, in semitones above the open
string. In a normal (closed) hand the four fingers cover a minor third:
finger n sits at ``offset + (n - 1)``. Extensions reshape the hand:

* ``back``: the 1st finger reaches one semitone lower (offset - 1), fingers 2-4 stay.
* ``fwd``:  a whole step between fingers 1 and 2, so 2-4 move up one semitone.
"""

from __future__ import annotations

from dataclasses import dataclass

# Open strings, lowest first. MIDI numbers: C2=36, G2=43, D3=50, A3=57.
STRINGS: tuple[tuple[str, int], ...] = (("C", 36), ("G", 43), ("D", 50), ("A", 57))

# MusicXML <string> numbers count from the highest string: A=1, D=2, G=3, C=4.
MUSICXML_STRING_NUMBER = {"A": 1, "D": 2, "G": 3, "C": 4}

# name -> 1st-finger offset in semitones above the open string.
# Restricted to the neck (half .. 4th). Add entries here (e.g. "upper 2nd": 4)
# to widen the search; keep them ordered low -> high.
POSITIONS: dict[str, int] = {
    "half": 1,
    "1st": 2,
    "2nd": 3,
    "3rd": 5,
    "4th": 7,
}

# hand shape -> finger -> semitones relative to the position's 1st-finger offset.
HAND_SHAPES: dict[str, dict[int, int]] = {
    "closed": {1: 0, 2: 1, 3: 2, 4: 3},
    "back": {1: -1, 2: 1, 3: 2, 4: 3},
    "fwd": {1: 0, 2: 2, 3: 3, 4: 4},
}


@dataclass(frozen=True, slots=True)
class Placement:
    """One way to play one pitch: which string and finger, in which hand frame."""

    string: str  # "C" | "G" | "D" | "A"
    position: str  # key of POSITIONS
    shape: str  # key of HAND_SHAPES
    finger: int  # 0 = open string, 1..4

    @property
    def string_index(self) -> int:
        return next(i for i, (name, _) in enumerate(STRINGS) if name == self.string)

    @property
    def is_open(self) -> bool:
        return self.finger == 0

    @property
    def extended(self) -> bool:
        """True when this finger sits somewhere a closed hand could not put it."""
        if self.is_open or self.shape == "closed":
            return False
        return HAND_SHAPES[self.shape][self.finger] != HAND_SHAPES["closed"][self.finger]


def placements_for(midi: int) -> list[Placement]:
    """All neck placements (half..4th position) that produce ``midi``.

    Open strings are returned once per (position, closed shape): playing an open
    string does not move the hand, so the search needs to know where the hand is.
    """
    out: list[Placement] = []
    for string, open_midi in STRINGS:
        interval = midi - open_midi
        if interval == 0:
            out.extend(Placement(string, pos, "closed", 0) for pos in POSITIONS)
            continue
        for pos, base in POSITIONS.items():
            for shape, fingers in HAND_SHAPES.items():
                for finger, rel in fingers.items():
                    if base + rel == interval:
                        p = Placement(string, pos, shape, finger)
                        # A shape that doesn't change this finger is just the closed hand.
                        if shape == "closed" or p.extended:
                            out.append(p)
    return out


def neck_range() -> tuple[int, int]:
    """Lowest and highest MIDI pitch reachable without thumb position."""
    lo = STRINGS[0][1]
    top_pos = max(POSITIONS.values())
    top_rel = max(max(f.values()) for f in HAND_SHAPES.values())
    hi = STRINGS[-1][1] + top_pos + top_rel
    return lo, hi
