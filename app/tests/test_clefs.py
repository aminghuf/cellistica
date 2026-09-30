"""Clef changes must not affect pitch: music21's absolute pitches are the only source."""

from music21 import clef

from cello import score as sc


def _clef_by_measure(part):
    out = {}
    for c in part.recurse().getElementsByClass(clef.Clef):
        out[c.getContextByClass("Measure").number] = (c.sign, c.line)
    return out


def test_fixture_really_changes_clef(fixtures):
    s = sc.load(fixtures["sample"])
    assert _clef_by_measure(s.parts[0]) == {1: ("F", 4), 3: ("C", 4), 5: ("G", 2), 6: ("F", 4)}


def test_pitches_across_bass_tenor_treble(fixtures):
    s = sc.load(fixtures["sample"])
    by_measure = {}
    for n in s.parts[0].recurse().notes:
        m = n.getContextByClass("Measure").number
        by_measure.setdefault(m, []).extend(p.nameWithOctave for p in n.pitches)
    assert by_measure[1] == ["C2", "G2", "D3", "A3"]  # bass
    assert by_measure[3] == ["D4", "D4", "B-3"]  # tenor
    assert by_measure[5] == ["G4", "A4", "A-4"]  # treble
    assert by_measure[6] == ["C3"]  # bass again


def test_annotation_keeps_clefs_and_pitches(fixtures):
    s = sc.load(fixtures["sample"])
    before = [p.nameWithOctave for p in s.parts[0].recurse().stream().pitches]
    for mode in ("solfege", "fingering"):
        back = sc.load_bytes(sc.to_musicxml(sc.annotate(s, 0, mode)))
        assert [p.nameWithOctave for p in back.parts[0].recurse().stream().pitches] == before
        assert _clef_by_measure(back.parts[0]) == _clef_by_measure(s.parts[0])


def test_solfege_follows_pitch_not_clef(fixtures):
    """Each clef puts a pitch on a different staff line; the name must follow the pitch."""
    s = sc.load(fixtures["sample"])
    annotated = sc.annotate(s, 0, "solfege")
    names = {}
    for n in annotated.parts[0].recurse().notes:
        c = n.getContextByClass(clef.Clef)
        if n.lyrics and not n.isChord:
            names.setdefault(n.pitch.nameWithOctave, set()).add((c.sign, n.lyrics[0].text))
    assert names["D4"] == {("C", "Re")}
    assert names["G4"] == {("G", "Sol")}
    assert names["C2"] == {("F", "Do")}
