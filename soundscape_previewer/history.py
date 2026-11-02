"""Undo/redo history of a soundscape file, kept as text snapshots.

Every edit (forms, rule list, script tab, soundscape commands) ends up in the
file's text, so snapshots of that text cover all of them with one mechanism.
"""
from __future__ import annotations

from dataclasses import dataclass

MAX_STATES = 200


@dataclass
class State:
    text: str
    scape: str | None  # soundscape that was selected, to select it again


class History:
    def __init__(self, text: str, scape: str | None, saved: bool):
        self.states = [State(text, scape)]
        self.pos = 0
        self.saved_text: str | None = text if saved else None

    def record(self, text: str, scape: str | None) -> bool:
        """Add a state after an edit. Returns False if nothing changed."""
        if text == self.states[self.pos].text:
            self.states[self.pos].scape = scape
            return False
        del self.states[self.pos + 1 :]  # a new edit drops the redo states
        self.states.append(State(text, scape))
        if len(self.states) > MAX_STATES:
            del self.states[0]
        self.pos = len(self.states) - 1
        return True

    def can_undo(self) -> bool:
        return self.pos > 0

    def can_redo(self) -> bool:
        return self.pos < len(self.states) - 1

    def undo(self) -> State | None:
        if not self.can_undo():
            return None
        self.pos -= 1
        return self.states[self.pos]

    def redo(self) -> State | None:
        if not self.can_redo():
            return None
        self.pos += 1
        return self.states[self.pos]

    def is_saved(self, text: str) -> bool:
        return text == self.saved_text
