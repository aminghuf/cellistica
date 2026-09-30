"""Fixed-do Italian solfège names, spelled exactly as written (G# -> Sol♯, Ab -> La♭)."""

from __future__ import annotations

from music21 import pitch

FIXED_DO = {"C": "Do", "D": "Re", "E": "Mi", "F": "Fa", "G": "Sol", "A": "La", "B": "Si"}

ACCIDENTAL_SIGNS = {
    None: "",
    "natural": "",
    "sharp": "♯",
    "flat": "♭",
    "double-sharp": "♯♯",
    "double-flat": "♭♭",
    "triple-sharp": "♯♯♯",
    "triple-flat": "♭♭♭",
}


def solfege_name(p: pitch.Pitch) -> str:
    acc = p.accidental.name if p.accidental is not None else None
    sign = ACCIDENTAL_SIGNS.get(acc)
    if sign is None:  # microtonal and other rare accidentals
        sign = p.accidental.unicode
    return FIXED_DO[p.step] + sign
