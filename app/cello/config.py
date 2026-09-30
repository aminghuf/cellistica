"""Loads fingering weights from TOML (path from $CELLO_FINGERING_CONFIG)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "fingering.toml"


@dataclass(frozen=True)
class Weights:
    open_string: float = 0.0
    fingered: float = 1.0
    extension_back: float = 1.5
    extension_fwd: float = 1.5
    position_bias: dict[str, float] = field(default_factory=dict)
    shift_base: float = 2.0
    shift_per_semitone: float = 0.5
    shift_after_open_factor: float = 0.5
    shift_after_rest_factor: float = 0.3
    crossing_per_string: float = 0.3
    impossible_stretch: float = 50.0


def load_weights(path: str | os.PathLike | None = None) -> Weights:
    path = Path(path or os.environ.get("CELLO_FINGERING_CONFIG") or DEFAULT_PATH)
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    note = raw.get("note", {})
    shift = raw.get("shift", {})
    d = Weights()
    return Weights(
        open_string=note.get("open_string", d.open_string),
        fingered=note.get("fingered", d.fingered),
        extension_back=note.get("extension_back", d.extension_back),
        extension_fwd=note.get("extension_fwd", d.extension_fwd),
        position_bias=dict(raw.get("position_bias", {})),
        shift_base=shift.get("base", d.shift_base),
        shift_per_semitone=shift.get("per_semitone", d.shift_per_semitone),
        shift_after_open_factor=shift.get("after_open_factor", d.shift_after_open_factor),
        shift_after_rest_factor=shift.get("after_rest_factor", d.shift_after_rest_factor),
        crossing_per_string=raw.get("crossing", {}).get("per_string", d.crossing_per_string),
        impossible_stretch=raw.get("chord", {}).get("impossible_stretch", d.impossible_stretch),
    )
