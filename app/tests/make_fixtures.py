"""Generate the MusicXML test fixtures with music21 (all original material).

    python -m tests.make_fixtures      # from app/, rewrites tests/fixtures/*.musicxml
"""

from __future__ import annotations

from pathlib import Path

from music21 import chord, clef, instrument, key, meter, metadata, note, stream, tie

FIXTURES = Path(__file__).parent / "fixtures"


def _part(name: str, measures: list[list], inst=None) -> stream.Part:
    p = stream.Part()
    p.partName = name
    p.insert(0, inst or instrument.Violoncello())
    for i, items in enumerate(measures, start=1):
        m = stream.Measure(number=i)
        for it in items:
            m.append(it)
        p.append(m)
    return p


def _notes(names: str, ql: float = 1.0) -> list[note.Note]:
    return [note.Note(n, quarterLength=ql) for n in names.split()]


def _score(title: str, *parts: stream.Part) -> stream.Score:
    s = stream.Score()
    s.metadata = metadata.Metadata(title=title, composer="cello-reader fixtures")
    for p in parts:
        s.insert(0, p)
    return s


def c_major_two_octaves() -> stream.Score:
    names = "C2 D2 E2 F2 G2 A2 B2 C3 D3 E3 F3 G3 A3 B3 C4"
    ns = _notes(names)
    measures = [[clef.BassClef(), meter.TimeSignature("4/4"), *ns[:4]], ns[4:8], ns[8:12], [*ns[12:], note.Rest()]]
    return _score("C major, two octaves", _part("Violoncello", measures))


def third_position_passage() -> stream.Score:
    # D4 and G3 alone would sit in 1st position; the F4/E4/Bb3 around them want 3rd.
    ns = _notes("D4 F4 E4 D4 G3 B-3 A3 G3 D4 E4 F4 E4 D4", ql=0.5)
    measures = [
        [clef.TenorClef(), meter.TimeSignature("4/4"), *ns[:8]],
        [*ns[8:], note.Rest(quarterLength=1.5)],
    ]
    return _score("Stay in third", _part("Violoncello", measures))


def sample() -> stream.Score:
    """A short cello part exercising clef changes, key-signature accidentals,
    ties, rests, double stops and a note above the neck."""
    d_tied_a = note.Note("D4", quarterLength=2.0)
    d_tied_a.tie = tie.Tie("start")
    d_tied_b = note.Note("D4", quarterLength=1.0)
    d_tied_b.tie = tie.Tie("stop")
    measures = [
        # m1 bass clef, G major (F#)
        [clef.BassClef(), key.KeySignature(1), meter.TimeSignature("4/4"), *_notes("C2 G2 D3 A3")],
        # m2: F#3 from the key signature, G#3 and A-flat spelled as written
        [*_notes("E3 F#3 G#3"), note.Rest()],
        # m3 tenor clef: tie across beats, then B-flat
        [clef.TenorClef(), d_tied_a, d_tied_b, note.Note("B-3")],
        # m4 double stops: open fifth D3+A3, sixth F3+D4
        [chord.Chord(["D3", "A3"], quarterLength=2.0), chord.Chord(["F3", "D4"], quarterLength=2.0)],
        # m5 treble clef: A4 is above 4th position -> "?"
        [clef.TrebleClef(), *_notes("G4 A4 A-4"), note.Rest()],
        # m6 back to bass clef
        [clef.BassClef(), note.Note("C3", quarterLength=4.0)],
    ]
    return _score("cello-reader sample", _part("Violoncello", measures))


def duet() -> stream.Score:
    """Violin over cello, cello listed second, for part selection."""
    vn = _part("Violin", [[clef.TrebleClef(), *_notes("G4 A4 B4 C5")]], inst=instrument.Violin())
    vc = _part("Violoncello", [[clef.BassClef(), *_notes("C3 D3 E3 F3")]])
    return _score("Duet", vn, vc)


def unnamed_parts() -> stream.Score:
    """No instrument names: the lowest part should win."""
    hi = _part("", [[clef.TrebleClef(), *_notes("E5 F5 G5 A5")]], inst=instrument.Instrument())
    lo = _part("", [[clef.BassClef(), *_notes("C3 D3 E3 F3")]], inst=instrument.Instrument())
    mid = _part("", [[clef.AltoClef(), *_notes("C4 D4 E4 F4")]], inst=instrument.Instrument())
    return _score("Anonymous", hi, lo, mid)


ALL = {
    "c_major_two_octaves": c_major_two_octaves,
    "third_position": third_position_passage,
    "sample": sample,
    "duet": duet,
    "unnamed_parts": unnamed_parts,
}


def write_all(dest: Path = FIXTURES) -> dict[str, Path]:
    dest.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, build in ALL.items():
        path = dest / f"{name}.musicxml"
        build().write("musicxml", fp=path)
        out[name] = path
    return out


if __name__ == "__main__":
    for name, path in write_all().items():
        print(f"{name}: {path}")
