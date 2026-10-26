"""One window of the filer: a directory, its entries, the cursor and the selection."""

from __future__ import annotations

import os
from pathlib import Path

from pyvz.filer.listing import PARENT, Entry, Order, entry, read_dir, shown, sort_entries


class Pane:
    def __init__(self, path: Path, *, pattern: str = "*", show_hidden: bool = True) -> None:
        self.path = Path(os.path.abspath(path))
        self.pattern = pattern
        self.show_hidden = show_hidden
        self.order = Order.NAME
        self.entries: list[Entry] = []
        self.cursor = 0
        self.top = 0
        self.selected: set[str] = set()

    @property
    def current(self) -> Entry | None:
        return self.entries[self.cursor] if self.entries else None

    def load(self, focus: str | None = None) -> None:
        """Read the directory again, keeping the cursor on `focus` or the same entry.

        Raises OSError if the directory cannot be read.
        """
        if focus is None and self.current is not None:
            focus = self.current.name
        found = [e for e in read_dir(self.path) if shown(e, self.pattern, self.show_hidden)]
        entries = sort_entries(found, self.order)
        if self.path.parent != self.path:
            parent = entry(self.path, PARENT)
            if parent is not None:
                entries.insert(0, parent)
        names = {e.name for e in entries}
        self.selected &= names
        old_cursor = self.cursor
        self.entries = entries
        self.cursor = 0
        if focus is not None:
            for i, e in enumerate(entries):
                if e.name == focus:
                    self.cursor = i
                    break
            else:
                self.cursor = min(old_cursor, len(entries) - 1)
        self.cursor = max(self.cursor, 0)

    def go(self, path: Path, focus: str | None = None) -> None:
        """Show another directory. Raises OSError if it cannot be read; then nothing
        changes."""
        before = (self.path, self.entries, self.cursor, self.top, self.selected)
        self.path = Path(os.path.abspath(path))
        self.entries, self.cursor, self.top, self.selected = [], 0, 0, set()
        try:
            self.load(focus)
        except OSError:
            self.path, self.entries, self.cursor, self.top, self.selected = before
            raise

    def parent(self) -> None:
        if self.path.parent != self.path:
            self.go(self.path.parent, focus=self.path.name)

    def enter(self) -> bool:
        """Go into the directory under the cursor. False if it is not a directory."""
        e = self.current
        if e is None or not e.is_dir:
            return False
        if e.is_parent:
            self.parent()
        else:
            self.go(self.path / e.name)
        return True

    # Moving

    def move(self, count: int) -> None:
        if self.entries:
            self.cursor = max(0, min(self.cursor + count, len(self.entries) - 1))

    def to_top(self) -> None:
        self.cursor = 0

    def to_end(self) -> None:
        self.cursor = max(len(self.entries) - 1, 0)

    def jump(self, letter: str) -> bool:
        """Move to the next entry whose name starts with `letter` (any case)."""
        count = len(self.entries)
        for step in range(1, count + 1):
            i = (self.cursor + step) % count
            if self.entries[i].name[:1].casefold() == letter.casefold():
                self.cursor = i
                return True
        return False

    def keep_visible(self, height: int) -> None:
        height = max(height, 1)
        if self.cursor < self.top:
            self.top = self.cursor
        elif self.cursor >= self.top + height:
            self.top = self.cursor - height + 1
        self.top = max(0, min(self.top, max(len(self.entries) - height, 0)))

    # Selecting

    def toggle(self) -> None:
        e = self.current
        if e is not None and not e.is_parent:
            self.selected ^= {e.name}

    def invert_all(self) -> None:
        names = {e.name for e in self.entries if not e.is_parent}
        self.selected = names - self.selected

    def clear(self) -> None:
        self.selected = set()

    def targets(self) -> list[Entry]:
        """The selected entries, or the one under the cursor if none is selected."""
        if self.selected:
            return [e for e in self.entries if e.name in self.selected]
        e = self.current
        return [e] if e is not None and not e.is_parent else []
