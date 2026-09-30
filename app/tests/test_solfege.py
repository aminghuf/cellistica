import pytest
from music21 import pitch

from cello import score as sc
from cello.solfege import solfege_name


@pytest.mark.parametrize(
    "name, expected",
    [
        ("C4", "Do"), ("D4", "Re"), ("E4", "Mi"), ("F4", "Fa"),
        ("G4", "Sol"), ("A4", "La"), ("B4", "Si"),
        ("G#3", "Sol♯"), ("A-3", "La♭"), ("B-2", "Si♭"), ("E#4", "Mi♯"),
        ("C-5", "Do♭"), ("F##3", "Fa♯♯"), ("B--3", "Si♭♭"),
    ],
)
def test_fixed_do_names(name, expected):
    assert solfege_name(pitch.Pitch(name)) == expected


def test_enharmonics_keep_their_spelling():
    assert solfege_name(pitch.Pitch("G#4")) != solfege_name(pitch.Pitch("A-4"))


def test_explicit_natural_has_no_sign():
    p = pitch.Pitch("B4")
    p.accidental = pitch.Accidental("natural")
    assert solfege_name(p) == "Si"


def test_octave_is_ignored():
    assert {solfege_name(pitch.Pitch(f"D{o}")) for o in range(1, 6)} == {"Re"}


def _lyrics(s):
    out = []
    for el in s.parts[0].recurse().notes:
        if el.lyrics:
            out.append([ly.text for ly in el.lyrics])
    return out


def test_sample_lyrics_from_musicxml(fixtures):
    s = sc.load(fixtures["sample"])
    annotated = sc.annotate(s, 0, "solfege")
    # Round-trip through MusicXML, as the browser will see it.
    back = sc.load_bytes(sc.to_musicxml(annotated))
    assert _lyrics(back) == [
        ["Do"], ["Sol"], ["Re"], ["La"],  # m1
        ["Mi"], ["Fa♯"], ["Sol♯"],  # m2: F# comes from the key signature
        ["Re"], ["Si♭"],  # m3: the tied continuation D4 gets nothing
        ["La", "Re"], ["Re", "Fa"],  # m4 double stops, top note first
        ["Sol"], ["La"], ["La♭"],  # m5
        ["Do"],  # m6
    ]
