"""Folding lines into screen rows, and how characters look on the screen."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache

from pyvz.text.width import char_width, is_raw_byte, next_tab_stop


@dataclass(frozen=True)
class Layout:
    """How lines are folded: the window width and how wide tabs and characters are."""

    width: int = 80
    tab_size: int = 8
    ambiguous_wide: bool = False

    def fold(self, line: str) -> Folded:
        return _fold(line, max(self.width, 1), self.tab_size, self.ambiguous_wide)


@dataclass(frozen=True)
class Folded:
    """A line folded into rows, as VZ folds long lines at the window width.

    `starts` holds the index where each row starts. `columns` holds the column of each
    character within its row, followed by the column of the line end. `widths` holds
    the width of each character on the screen.
    """

    line: str
    starts: tuple[int, ...]
    columns: tuple[int, ...]
    widths: tuple[int, ...]

    @property
    def rows(self) -> int:
        return len(self.starts)

    def row_of(self, index: int) -> int:
        """The row that the cursor at `index` is on."""
        return bisect_right(self.starts, index) - 1

    def row_range(self, row: int) -> tuple[int, int]:
        """The indexes of the first character of the row and of the next row."""
        end = self.starts[row + 1] if row + 1 < len(self.starts) else len(self.line)
        return self.starts[row], end

    def index_at(self, row: int, column: int) -> int:
        """Where the cursor goes on `row` when it moves up or down to `column`.

        A column inside a wide character or a tab gives that character. Past the end
        of the row, the cursor goes to the line end on the last row, and to the last
        character on the other rows (the next index would be on the next row).
        """
        start, end = self.row_range(row)
        for i in range(start, end):
            if self.widths[i] and column < self.columns[i] + self.widths[i]:
                return i
        if row == len(self.starts) - 1:
            return len(self.line)
        return max(start, end - 1)


@lru_cache(maxsize=4096)
def _fold(line: str, width: int, tab_size: int, ambiguous_wide: bool) -> Folded:
    starts = [0]
    columns = []
    widths = []
    column = 0
    for i, ch in enumerate(line):
        w = _width(ch, column, width, tab_size, ambiguous_wide)
        if column + w > width and column > 0:
            starts.append(i)
            column = 0
            w = _width(ch, column, width, tab_size, ambiguous_wide)
        columns.append(column)
        widths.append(w)
        column += w
    if line and column >= width:
        # A full last row: the line end goes on a row of its own, so that the cursor
        # and the line end mark stay inside the window.
        starts.append(len(line))
        column = 0
    columns.append(column)
    return Folded(line, tuple(starts), tuple(columns), tuple(widths))


def _width(ch: str, column: int, width: int, tab_size: int, ambiguous_wide: bool) -> int:
    if ch == "\t":
        if column >= width:
            return 1  # does not fit: folds to the next row
        return min(next_tab_stop(column, tab_size), width) - column
    return char_width(ch, ambiguous_wide=ambiguous_wide)


def shown_as(ch: str, width: int) -> str | None:
    """The text shown for a character that is not shown as itself, or None.

    Tabs are spaces, control characters ``^X``, and bytes that are not UTF-8 and C1
    control characters ``\\xNN``. `width` is the width the character takes.
    """
    if ch == "\t":
        return " " * width
    if is_raw_byte(ch):
        return f"\\x{ord(ch) - 0xDC00:02X}"
    code = ord(ch)
    if code < 0x20:
        return "^" + chr(code + 0x40)
    if code == 0x7F:
        return "^?"
    if 0x80 <= code < 0xA0:
        return f"\\x{code:02X}"
    return None
