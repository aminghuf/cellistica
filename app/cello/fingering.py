"""Phrase-level cello fingering by dynamic programming (Viterbi).

Input is a sequence of *events*; each event is one note or a double stop, as MIDI
numbers. Every event gets a set of candidate states: one Placement per note that
share a hand position (the "frame"). The search then minimises

    sum(node cost of each chosen state) + sum(transition cost between neighbours)

over the whole sequence, so a note may take a slightly worse fingering if it
avoids a shift later on. Notes with no neck placement come back as ``None``
(rendered as "?").
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from .config import Weights
from .positions import POSITIONS, Placement, placements_for


@dataclass(frozen=True, slots=True)
class Event:
    pitches: tuple[int, ...]  # MIDI numbers; one for a single note, 2+ for a double stop
    after_break: bool = False  # preceded by a rest (or an unplayable note)


@dataclass(frozen=True, slots=True)
class State:
    frame: str  # hand position for this event
    notes: tuple[Placement | None, ...]  # aligned with Event.pitches; None = "?"
    penalty: float  # chord-shape penalty (impossible stretches)

    @property
    def played(self) -> list[Placement]:
        return [p for p in self.notes if p is not None]

    @property
    def all_open(self) -> bool:
        return all(p.is_open for p in self.played)

    @property
    def mean_string(self) -> float:
        played = self.played
        return sum(p.string_index for p in played) / len(played)


def _chord_penalty(combo: tuple[Placement, ...], w: Weights) -> float | None:
    """None if the combination is physically meaningless, else its extra cost."""
    strings = [p.string_index for p in combo]
    if len(set(strings)) != len(strings):
        return None  # two notes on one string
    stopped = [p for p in combo if not p.is_open]
    penalty = 0.0
    if len({p.position for p in stopped}) > 1:
        penalty += w.impossible_stretch
    if {"back", "fwd"} <= {p.shape for p in stopped}:
        penalty += w.impossible_stretch
    by_finger: dict[int, list[Placement]] = {}
    for p in stopped:
        by_finger.setdefault(p.finger, []).append(p)
    for same in by_finger.values():
        # One finger may stop two adjacent strings (a fifth); anything else can't work.
        if len(same) > 1:
            idx = sorted(p.string_index for p in same)
            if idx[-1] - idx[0] != len(idx) - 1 or len(same) > 2:
                penalty += w.impossible_stretch
    return penalty


def candidate_states(event: Event, w: Weights) -> list[State]:
    options = [placements_for(m) for m in event.pitches]
    playable = [i for i, o in enumerate(options) if o]
    if not playable:
        return []
    states: list[State] = []
    for combo in itertools.product(*(options[i] for i in playable)):
        stopped = [p for p in combo if not p.is_open]
        frame = stopped[0].position if stopped else combo[0].position
        # Open strings are listed once per position; keep only the copy that
        # matches the hand frame so each physical fingering appears once.
        if any(p.is_open and p.position != frame for p in combo):
            continue
        penalty = _chord_penalty(combo, w) if len(combo) > 1 else 0.0
        if penalty is None:
            continue
        notes: list[Placement | None] = [None] * len(event.pitches)
        for i, p in zip(playable, combo):
            notes[i] = p
        states.append(State(frame, tuple(notes), penalty))
    return states


def node_cost(s: State, w: Weights) -> float:
    cost = s.penalty + w.position_bias.get(s.frame, 0.0)
    for p in s.played:
        if p.is_open:
            cost += w.open_string
            continue
        cost += w.fingered
        if p.extended:
            cost += w.extension_back if p.shape == "back" else w.extension_fwd
    return cost


def transition_cost(prev: State, cur: State, cur_event: Event, w: Weights) -> float:
    cost = w.crossing_per_string * abs(prev.mean_string - cur.mean_string)
    if prev.frame != cur.frame:
        distance = abs(POSITIONS[prev.frame] - POSITIONS[cur.frame])
        shift = w.shift_base + w.shift_per_semitone * distance
        factor = 1.0
        if prev.all_open:
            factor = min(factor, w.shift_after_open_factor)
        if cur_event.after_break:
            factor = min(factor, w.shift_after_rest_factor)
        cost += shift * factor
    return cost


def solve(events: list[Event], w: Weights) -> list[tuple[Placement | None, ...]]:
    """Best fingering for each event (tuple aligned with its pitches)."""
    result: list[tuple[Placement | None, ...]] = [
        (None,) * len(e.pitches) for e in events
    ]
    # Unplayable events drop out of the chain; the next playable event is then
    # treated as coming after a break (the hand is free to move).
    chain: list[tuple[int, Event, list[State]]] = []
    pending_break = False
    for i, e in enumerate(events):
        states = candidate_states(e, w)
        if not states:
            pending_break = True
            continue
        if pending_break and not e.after_break:
            e = Event(e.pitches, after_break=True)
        pending_break = False
        chain.append((i, e, states))
    if not chain:
        return result

    # Viterbi: best[k][j] = cheapest cost of any path ending in state j of chain[k].
    _, _, first_states = chain[0]
    best = [node_cost(s, w) for s in first_states]
    back: list[list[int]] = [[-1] * len(first_states)]
    for k in range(1, len(chain)):
        _, event, states = chain[k]
        prev_states = chain[k - 1][2]
        new_best: list[float] = []
        pointers: list[int] = []
        for s in states:
            nc = node_cost(s, w)
            j_best, c_best = 0, float("inf")
            for j, ps in enumerate(prev_states):
                c = best[j] + transition_cost(ps, s, event, w)
                if c < c_best:
                    j_best, c_best = j, c
            new_best.append(c_best + nc)
            pointers.append(j_best)
        best = new_best
        back.append(pointers)

    j = min(range(len(best)), key=best.__getitem__)
    for k in range(len(chain) - 1, -1, -1):
        idx, _, states = chain[k]
        result[idx] = states[j].notes
        j = back[k][j]
    return result
