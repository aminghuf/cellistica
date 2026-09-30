import re
import xml.etree.ElementTree as ET

import pytest

from cello import score as sc
from cello.fingering import Event, solve
from cello.positions import POSITIONS, neck_range, placements_for


def _rows(fixtures, name, weights):
    s = sc.load(fixtures[name])
    return sc.fingering_table(s, 0, weights)


# --- position table ---------------------------------------------------------

def test_neck_range_is_c2_to_g_sharp_4():
    assert neck_range() == (36, 68)  # C2 .. G#4 (4th position, forward extension)


def test_open_strings_are_available_in_every_position():
    opens = [p for p in placements_for(50) if p.is_open]  # D3
    assert {p.string for p in opens} == {"D"}
    assert {p.position for p in opens} == set(POSITIONS)


def test_extensions_only_where_they_change_the_finger():
    for p in placements_for(59):  # B3
        if p.shape != "closed":
            assert p.extended


# --- whole-phrase search ----------------------------------------------------

def test_c_major_two_octaves_first_position(fixtures, weights):
    rows = _rows(fixtures, "c_major_two_octaves", weights)
    assert [r["pitch"] for r in rows][0] == "C2" and len(rows) == 15
    assert [r["finger"] for r in rows] == [0, 1, 3, 4, 0, 1, 3, 4, 0, 1, 2, 4, 0, 1, 2]
    assert "".join(r["string"] for r in rows) == "CCCCGGGGDDDDAAA"
    # Open strings exactly on C2, G2, D3, A3.
    assert [r["pitch"] for r in rows if r["finger"] == 0] == ["C2", "G2", "D3", "A3"]
    assert {r["position"] for r in rows if r["finger"] != 0} == {"1st"}


def test_passage_stays_in_third_position(fixtures, weights):
    rows = _rows(fixtures, "third_position", weights)
    stopped = [r for r in rows if r["finger"] != 0]
    assert {r["position"] for r in stopped} == {"3rd"}
    assert all(r["shape"] == "closed" for r in stopped)
    by_pitch = {r["pitch"]: (r["string"], r["finger"]) for r in stopped}
    assert by_pitch["D4"] == ("A", 1)
    assert by_pitch["F4"] == ("A", 4)
    assert by_pitch["G3"] == ("D", 1)
    assert by_pitch["B-3"] == ("D", 4)


def test_third_position_is_a_phrase_decision(weights):
    """On its own, D4 is a 1st-position 4th finger; only context moves it."""
    [(alone,)] = solve([Event((62,))], weights)
    assert (alone.position, alone.finger) == ("1st", 4)


def test_shifting_back_and_forth_is_avoided(fixtures, weights):
    rows = _rows(fixtures, "third_position", weights)
    positions = [r["position"] for r in rows if r["finger"] != 0]
    changes = sum(a != b for a, b in zip(positions, positions[1:]))
    assert changes == 0


def test_weights_change_the_result(weights):
    """With open strings made expensive, A3 in a 3rd-position run becomes 3rd finger on D."""
    from dataclasses import replace

    run = [Event((m,)) for m in (55, 57, 58, 57, 55)]  # G3 A3 Bb3 A3 G3
    default = solve(run, weights)
    assert default[1][0].is_open
    no_open = solve(run, replace(weights, open_string=5.0))
    assert (no_open[1][0].string, no_open[1][0].finger) == ("D", 3)


def test_out_of_range_is_question_mark(weights):
    events = [Event((m,)) for m in (62, 69, 64, 35)]  # D4 A4 E4 B1
    res = solve(events, weights)
    assert res[1] == (None,) and res[3] == (None,)
    assert res[0][0] is not None and res[2][0] is not None


# --- double stops, ties, rests ------------------------------------------------

def test_double_stops_use_different_strings(weights):
    for chord in [(50, 57), (53, 62), (57, 59), (43, 50), (48, 55), (55, 62)]:
        [notes] = solve([Event(chord)], weights)
        assert all(p is not None for p in notes), chord
        strings = [p.string for p in notes]
        assert len(set(strings)) == len(strings), (chord, strings)


def test_double_stop_a3_b3(weights):
    """A second: B3 can't share the A string, so it goes on D in 4th with A open."""
    [(a, b)] = solve([Event((57, 59))], weights)
    assert (a.string, a.finger) == ("A", 0)
    assert (b.string, b.position) == ("D", "4th")


def test_sample_annotations(fixtures, weights):
    rows = _rows(fixtures, "sample", weights)
    pitches = [r["pitch"] for r in rows]
    # The tied D4 appears once; rests are absent.
    assert pitches.count("D4") == 2  # tied D4 (once) + the D4 in the m4 double stop
    by = {(r["pitch"]): r for r in rows}
    assert by["A4"]["finger"] == "?"
    assert (by["D3"]["finger"], by["A3"]["finger"]) == (0, 0)


def test_musicxml_has_fingering_string_and_position(fixtures):
    s = sc.load(fixtures["sample"])
    xml = sc.to_musicxml(sc.annotate(s, 0, "fingering")).decode()
    fingerings = re.findall(r"<fingering[^>]*>([^<]*)</fingering>", xml)
    strings = re.findall(r"<string[^>]*>(\d)</string>", xml)
    # 18 sounding notes, minus the tied continuation = 17 fingered notes
    assert len(fingerings) == 17
    assert "?" in fingerings
    assert len(strings) == 16  # all but the "?"
    assert set(strings) <= {"1", "2", "3", "4"}
    assert re.search(r"<words[^>]*>[^<]*pos\.</words>", xml)


@pytest.mark.parametrize("mode", ["solfege", "fingering"])
def test_chord_annotations_land_on_both_notes(fixtures, mode):
    s = sc.load(fixtures["sample"])
    back = sc.load_bytes(sc.to_musicxml(sc.annotate(s, 0, mode)))
    chords = [c for c in back.parts[0].recurse().notes if c.isChord]
    assert len(chords) == 2
    for c in chords:
        assert len(c.lyrics) == 2


def _chord_notes(xml: bytes):
    """<note> elements of each chord in the exported MusicXML, grouped."""
    root = ET.fromstring(xml.partition(b"<score-partwise")[1] + xml.partition(b"<score-partwise")[2])
    groups, current = [], None
    for n in root.iter("note"):
        if n.find("chord") is not None:
            current.append(n)
        else:
            current = [n]
            groups.append(current)
    return [g for g in groups if len(g) > 1]


def test_each_double_stop_note_gets_finger_and_string(fixtures, weights):
    s = sc.load(fixtures["sample"])
    xml = sc.to_musicxml(sc.annotate(s, 0, "fingering", weights))
    chords = _chord_notes(xml)
    assert len(chords) == 2
    for notes in chords:
        strings = [n.findtext("notations/technical/string") for n in notes]
        fingers = [n.findtext("notations/technical/fingering") for n in notes]
        assert None not in strings and None not in fingers
        assert len(set(strings)) == len(strings)  # different strings
    # D3+A3 is the open fifth: D string (2) and A string (1), both 0.
    first = {n.findtext("pitch/step"): (n.findtext("notations/technical/fingering"),
                                         n.findtext("notations/technical/string")) for n in chords[0]}
    assert first == {"D": ("0", "2"), "A": ("0", "1")}
    # F3+D4: F on the D string with 2, D on the A string with 4 (1st position).
    second = {n.findtext("pitch/step"): (n.findtext("notations/technical/fingering"),
                                          n.findtext("notations/technical/string")) for n in chords[1]}
    assert second == {"F": ("2", "2"), "D": ("4", "1")}


def test_no_tokens_leak_into_output(fixtures):
    s = sc.load(fixtures["sample"])
    xml = sc.to_musicxml(sc.annotate(s, 0, "fingering"))
    assert sc.TOKEN.encode() not in xml
    assert b"<!DOCTYPE score-partwise" in xml
