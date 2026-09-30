"""music21 glue: load a score, pick the cello part, write annotations back as MusicXML.

Pitches always come from music21's absolute ``Pitch`` objects, so clefs (bass,
tenor, treble and changes between them) never enter into it.
"""

from __future__ import annotations

import copy
import re
import statistics
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from music21 import articulations, chord, converter, expressions, instrument, note, stream
from music21.musicxml.m21ToXml import GeneralObjectExporter

from .config import Weights
from .fingering import Event, solve
from .positions import MUSICXML_STRING_NUMBER, Placement
from .solfege import solfege_name

CELLO_NAME = re.compile(r"(violon)?cell[oe]|violonchelo|\bvc\b|\bvlc\b", re.IGNORECASE)
POSITION_LABELS = {"half": "½ pos.", "1st": "I pos.", "2nd": "II pos.", "3rd": "III pos.", "4th": "IV pos."}


class PartSelectionError(ValueError):
    pass


def load(path: str | Path) -> stream.Score:
    s = converter.parse(str(path))
    if isinstance(s, stream.Opus):  # several movements in one file: take the first
        s = s.scores[0]
    if not isinstance(s, stream.Score):
        wrapped = stream.Score()
        wrapped.insert(0, s)
        s = wrapped
    return s


def load_bytes(data: bytes) -> stream.Score:
    s = converter.parseData(data, format="musicxml")
    if isinstance(s, stream.Opus):
        s = s.scores[0]
    return s


def _part_names(part: stream.Part) -> list[str]:
    inst = part.getInstrument(returnDefault=False)
    names = [part.partName, part.partAbbreviation]
    if inst is not None:
        names += [inst.instrumentName, inst.partName, inst.instrumentAbbreviation]
    return [n for n in names if n]


def _is_cello(part: stream.Part) -> bool:
    inst = part.getInstrument(returnDefault=False)
    if isinstance(inst, instrument.Violoncello):
        return True
    return any(CELLO_NAME.search(n) for n in _part_names(part))


def _midis(part: stream.Part) -> list[int]:
    return [p.midi for n in part.recurse().notes for p in n.pitches]


def describe_parts(score: stream.Score) -> list[dict]:
    out = []
    for i, part in enumerate(score.parts):
        midis = _midis(part)
        names = _part_names(part)
        out.append(
            {
                "index": i,
                "name": names[0] if names else f"Part {i + 1}",
                "is_cello": _is_cello(part),
                "notes": len(midis),
                "median_midi": statistics.median(midis) if midis else None,
            }
        )
    return out


def choose_part(score: stream.Score, override: str | None = None) -> int:
    """Index of the part to annotate.

    ``override`` is a 0-based index or a case-insensitive substring of the part
    name. Otherwise: the first cello part, else the lowest-sounding part.
    """
    parts = describe_parts(score)
    if not parts:
        raise PartSelectionError("score has no parts")
    if override not in (None, ""):
        if override.isdigit():
            idx = int(override)
            if idx >= len(parts):
                raise PartSelectionError(f"part {idx} out of range (score has {len(parts)})")
            return idx
        for p in parts:
            if override.lower() in p["name"].lower():
                return p["index"]
        raise PartSelectionError(f"no part named like {override!r}")
    for p in parts:
        if p["is_cello"] and p["notes"]:
            return p["index"]
    with_notes = [p for p in parts if p["notes"]]
    if not with_notes:
        return 0
    return min(with_notes, key=lambda p: p["median_midi"])["index"]


@dataclass
class _Slot:
    """One DP event plus the score objects its pitches came from."""

    notes: list[note.Note]  # each is a Note, or a Note inside a Chord
    owner: list[note.GeneralNote]  # the Note or Chord that sits in the stream
    after_break: bool


def _is_tie_continuation(n: note.Note) -> bool:
    return n.tie is not None and n.tie.type in ("stop", "continue")


def _collect(part: stream.Part) -> list[_Slot]:
    """Playable events in time order; simultaneous notes (double stops, or two
    voices sounding together) merge into one event. Rests set a break flag."""
    items = []
    for el in part.recurse().notesAndRests:
        off = el.getOffsetInHierarchy(part)
        grace = el.duration.isGrace
        items.append((off, 0 if grace else 1, el))
    items.sort(key=lambda t: (t[0], t[1]))

    slots: list[_Slot] = []
    last_key = None
    brk = False
    for off, order, el in items:
        if isinstance(el, note.Rest):
            brk = True
            continue
        if isinstance(el, chord.Chord):
            members = list(el.notes)
        elif isinstance(el, note.Note):
            members = [el]
        else:  # unpitched
            continue
        members = [n for n in members if not _is_tie_continuation(n)]
        if not members:
            # A held note: the hand stays put, nothing to finger.
            continue
        key = (off, order)
        if slots and key == last_key and order == 1:
            slots[-1].notes.extend(members)
            slots[-1].owner.extend([el] * len(members))
        else:
            slots.append(_Slot(members, [el] * len(members), brk))
            brk = False
        last_key = key
    return slots


def _string_letter(p: Placement | None) -> str:
    return p.string if p is not None else "?"


def annotate(score: stream.Score, part_index: int, mode: str, weights: Weights | None = None) -> stream.Score:
    """A new single-part score with solfège lyrics or fingering technicals."""
    if mode not in ("solfege", "fingering"):
        raise ValueError(f"unknown mode {mode!r}")
    part = copy.deepcopy(score.parts[part_index])
    out = stream.Score()
    if score.metadata is not None:
        out.metadata = copy.deepcopy(score.metadata)
    out.insert(0, part)

    for n in part.recurse().notes:  # drop OMR'd / existing lyrics so ours are readable
        n.lyrics = []

    slots = _collect(part)
    if mode == "solfege":
        for slot in slots:
            _annotate_solfege(slot)
    else:
        if weights is None:
            from .config import load_weights

            weights = load_weights()
        _annotate_fingering(out, slots, weights)
    return out


def _annotate_solfege(slot: _Slot) -> None:
    # Top note first so the lyric lines read like the chord, high to low.
    pairs = sorted(zip(slot.notes, slot.owner), key=lambda t: -t[0].pitch.ps)
    for n, owner in pairs:
        owner.addLyric(solfege_name(n.pitch))


# Fingering export goes through a token pass: music21 only distributes Fingering
# objects across the notes of a chord (a StringIndication would land on the first
# note only), so each note first gets a unique token as its fingering text, and
# _apply_fingering_tokens() swaps in the finger and adds <string> after export.
TOKEN = "cello-tok:"
FINGERING_TABLE_ATTR = "cello_fingering_table"


def _annotate_fingering(out: stream.Score, slots: list[_Slot], weights: Weights) -> None:
    events = [Event(tuple(n.pitch.midi for n in s.notes), s.after_break) for s in slots]
    solution = solve(events, weights)
    # token group -> [(midi, finger | "?" | None, musicxml string number | None)]
    table: dict[int, list[tuple[int, object, int | None]]] = {}
    current_frame: str | None = None
    for slot, placements in zip(slots, solution):
        # Label the position when the stopping hand moves.
        stopped = [p for p in placements if p is not None and not p.is_open]
        if stopped and stopped[0].position != current_frame:
            current_frame = stopped[0].position
            owner = slot.owner[0]
            label = expressions.TextExpression(POSITION_LABELS.get(current_frame, current_frame))
            label.placement = "above"
            label.style.fontSize = 8
            owner.activeSite.insert(owner.offset, label)

        chosen = {id(n): p for n, p in zip(slot.notes, placements)}
        owners = list({id(o): o for o in slot.owner}.values())
        for owner in owners:
            members = list(owner.notes) if isinstance(owner, chord.Chord) else [owner]
            group = len(table)
            table[group] = []
            for i, n in enumerate(members):
                if id(n) not in chosen:  # tied continuation inside a chord
                    table[group].append((n.pitch.midi, None, None))
                else:
                    p = chosen[id(n)]
                    table[group].append(
                        (n.pitch.midi, p.finger if p else "?", MUSICXML_STRING_NUMBER[p.string] if p else None)
                    )
                owner.articulations.append(articulations.Fingering(f"{TOKEN}{group}.{i}"))
            # String letters under the note, top note first (like the solfège lines).
            for n in sorted(members, key=lambda n: -n.pitch.ps):
                if id(n) in chosen:
                    owner.addLyric(_string_letter(chosen[id(n)]))
    setattr(out, FINGERING_TABLE_ATTR, table)


_STEP_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _xml_midi(note_el: ET.Element) -> int | None:
    p = note_el.find("pitch")
    if p is None:
        return None
    alter = float(p.findtext("alter") or 0)
    return 12 * (int(p.findtext("octave")) + 1) + _STEP_PC[p.findtext("step")] + round(alter)


def _apply_fingering_tokens(xml: bytes, table: dict) -> bytes:
    head, sep, body = xml.partition(b"<score-partwise")
    root = ET.fromstring(sep + body)
    used: set[tuple[int, int]] = set()
    for note_el in root.iter("note"):
        technical = note_el.find("notations/technical")
        fing = technical.find("fingering") if technical is not None else None
        if fing is None or not (fing.text or "").startswith(TOKEN):
            continue
        group, idx = (int(x) for x in fing.text[len(TOKEN):].split("."))
        entries = table[group]
        # music21 may reorder chord members on export; match on pitch within the group.
        midi = _xml_midi(note_el)
        k = next(
            (j for j, e in enumerate(entries) if e[0] == midi and (group, j) not in used),
            idx,
        )
        used.add((group, k))
        _, finger, string_no = entries[k]
        for attr in ("alternate", "substitution"):
            fing.attrib.pop(attr, None)
        if finger is None:
            technical.remove(fing)
        else:
            fing.text = str(finger)
            if string_no is not None:
                ET.SubElement(technical, "string").text = str(string_no)
        if len(technical) == 0:
            notations = note_el.find("notations")
            notations.remove(technical)
            if len(notations) == 0:
                note_el.remove(notations)
    return head + ET.tostring(root, encoding="unicode").encode()


def to_musicxml(s: stream.Score) -> bytes:
    xml = GeneralObjectExporter(s).parse()
    table = getattr(s, FINGERING_TABLE_ATTR, None)
    if table:
        xml = _apply_fingering_tokens(xml, table)
    return xml


def fingering_table(score: stream.Score, part_index: int, weights: Weights) -> list[dict]:
    """Plain-data view of the fingering (used by tests and the JSON API)."""
    part = score.parts[part_index]
    slots = _collect(part)
    events = [Event(tuple(n.pitch.midi for n in s.notes), s.after_break) for s in slots]
    rows = []
    for slot, placements in zip(slots, solve(events, weights)):
        for n, p in zip(slot.notes, placements):
            rows.append(
                {
                    "pitch": n.pitch.nameWithOctave,
                    "finger": p.finger if p else "?",
                    "string": p.string if p else "?",
                    "position": p.position if p else "?",
                    "shape": p.shape if p else None,
                }
            )
    return rows
