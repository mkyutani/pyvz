"""A text being edited and its window: the document, the cursor, and the rows shown.

As in VZ, each text has its own window record, so the cursor and the rows shown stay
with the text when another text is shown.

A position in the text is (line, index). A screen row is (line, row), where row
counts the rows that a long line is folded into.
"""

from __future__ import annotations

from pyvz.editor.layout import Folded, Layout
from pyvz.text import chartype
from pyvz.text.document import Document
from pyvz.text.width import next_tab_stop

Row = tuple[int, int]


class Window:
    def __init__(self, doc: Document, layout: Layout, *, cc: bool = False) -> None:
        self.doc = doc
        self.layout = layout
        self.height = 1  # rows of text in the window
        self.cc = cc  # the prompt file of Claude Code
        self.draft = False  # the text came from a draft on hold
        self.line = 0
        self.index = 0
        # The column that up and down keep to, while the lines on the way are shorter.
        self.want: int | None = None
        self.top: Row = (0, 0)

    @property
    def lines(self) -> list[str]:
        return self.doc.lines

    def folded(self, line: int) -> Folded:
        return self.layout.fold(self.lines[line])

    # Rows

    def cursor_row(self) -> Row:
        return self.line, self.folded(self.line).row_of(self.index)

    def cursor_column(self) -> int:
        """The column of the cursor in its row."""
        return self.folded(self.line).columns[self.index]

    def next_row(self, pos: Row) -> Row | None:
        line, row = pos
        if row + 1 < self.folded(line).rows:
            return line, row + 1
        if line + 1 < len(self.lines):
            return line + 1, 0
        return None

    def prev_row(self, pos: Row) -> Row | None:
        line, row = pos
        if row > 0:
            return line, row - 1
        if line > 0:
            return line - 1, self.folded(line - 1).rows - 1
        return None

    def step(self, pos: Row, count: int) -> tuple[Row, int]:
        """Move `pos` by `count` rows (up if negative), stopping at either end.

        Returns the new position and how many rows it moved.
        """
        move = self.next_row if count > 0 else self.prev_row
        moved = 0
        while moved < abs(count):
            following = move(pos)
            if following is None:
                break
            pos = following
            moved += 1
        return pos, moved

    def screen_row(self) -> int:
        """The row of the window that the cursor is on, counted from 0."""
        target = self.cursor_row()
        pos, rows = self.top, 0
        while pos < target:
            following = self.next_row(pos)
            if following is None:
                break
            pos = following
            rows += 1
        return rows

    def keep_visible(self) -> None:
        """Scroll the window as little as needed to show the cursor."""
        self._clamp_top()
        cursor = self.cursor_row()
        if cursor < self.top:
            self.top = cursor
            return
        pos = cursor
        for _ in range(self.height - 1):
            if pos == self.top:
                return
            before = self.prev_row(pos)
            if before is None:
                break
            pos = before
        if pos != self.top:
            self.top = pos  # the cursor goes on the last row

    def _clamp_top(self) -> None:
        line = min(self.top[0], len(self.lines) - 1)
        row = min(self.top[1], self.folded(line).rows - 1) if line == self.top[0] else 0
        self.top = (line, row)

    def _go_row(self, pos: Row, column: int) -> None:
        self.line = pos[0]
        self.index = self.folded(pos[0]).index_at(pos[1], column)
        self.want = column

    def _wanted_column(self) -> int:
        return self.want if self.want is not None else self.cursor_column()

    def _go(self, line: int, index: int) -> None:
        self.line = line
        self.index = index
        self.want = None

    # Moving the cursor

    def up(self) -> bool:
        before = self.prev_row(self.cursor_row())
        if before is None:
            return False
        self._go_row(before, self._wanted_column())
        return True

    def down(self) -> bool:
        following = self.next_row(self.cursor_row())
        if following is None:
            return False
        self._go_row(following, self._wanted_column())
        return True

    def left(self) -> bool:
        if self.index > 0:
            self._go(self.line, self.index - 1)
        elif self.line > 0:
            self._go(self.line - 1, len(self.lines[self.line - 1]))
        else:
            return False
        return True

    def right(self) -> bool:
        if self.index < len(self.lines[self.line]):
            self._go(self.line, self.index + 1)
        elif self.line + 1 < len(self.lines):
            self._go(self.line + 1, 0)
        else:
            return False
        return True

    def word_right(self) -> bool:
        """Move to the start of the next word.

        As VZ does, the cursor stops where the character class rises, so spaces and
        symbols after a word are skipped, and kanji followed by hiragana is one word.
        """
        text = self.lines[self.line]
        if self.index == len(text):
            return self.right()
        i = self.index
        previous = chartype.char_class(text[i])
        for i in range(self.index + 1, len(text)):
            current = chartype.char_class(text[i])
            if current > previous:
                break
            previous = current
        else:
            i = len(text)
        self._go(self.line, i)
        return True

    def word_left(self) -> bool:
        """Move to the start of the word before the cursor (VZ's rule, backwards)."""
        if self.index == 0:
            return self.left()
        text = self.lines[self.line]
        i = self.index - 1
        previous = chartype.char_class(text[i])
        while i > 0:
            current = chartype.char_class(text[i - 1])
            if current < previous:
                break
            previous = current
            i -= 1
        self._go(self.line, i)
        return True

    def line_top(self) -> None:
        self._go(self.line, 0)

    def line_end(self) -> None:
        self._go(self.line, len(self.lines[self.line]))

    def row_left(self) -> None:
        folded = self.folded(self.line)
        self._go(self.line, folded.row_range(folded.row_of(self.index))[0])

    def row_right(self) -> None:
        folded = self.folded(self.line)
        row = folded.row_of(self.index)
        self._go(self.line, folded.index_at(row, self.layout.width))

    def scroll(self, count: int) -> bool:
        """Move the cursor and the window together by `count` rows (VZ's roll and page).

        The cursor stays on the same row of the window.
        """
        column = self._wanted_column()
        pos, moved = self.step(self.cursor_row(), count)
        if moved == 0:
            return False
        self.top, _ = self.step(self.top, moved if count > 0 else -moved)
        self._go_row(pos, column)
        return True

    def window_top(self) -> None:
        """Go to the first row of the window, or scroll up a row if already there."""
        self._clamp_top()
        if self.cursor_row() == self.top:
            self.scroll(-1)
        else:
            self._go_row(self.top, self._wanted_column())

    def window_end(self) -> None:
        """Go to the last row of the window, or scroll down a row if already there."""
        self._clamp_top()
        last, _ = self.step(self.top, self.height - 1)
        if self.cursor_row() == last:
            self.scroll(1)
        else:
            self._go_row(last, self._wanted_column())

    def text_top(self) -> None:
        self._go(0, 0)
        self.top = (0, 0)

    def text_end(self) -> None:
        last = len(self.lines) - 1
        self._go(last, len(self.lines[last]))
        self.top, _ = self.step(self.cursor_row(), -(self.height - 1))

    # Editing

    def _touch(self) -> None:
        self.doc.modified = True

    def insert(self, text: str) -> None:
        """Insert text at the cursor and move past it. LF in `text` splits lines."""
        current = self.lines[self.line]
        before, after = current[: self.index], current[self.index :]
        parts = text.split("\n")
        if len(parts) == 1:
            self.lines[self.line] = before + text + after
            self._go(self.line, self.index + len(text))
        else:
            self.lines[self.line : self.line + 1] = (
                [before + parts[0], *parts[1:-1], parts[-1] + after]
            )  # fmt: skip
            self._go(self.line + len(parts) - 1, len(parts[-1]))
        self._touch()

    def overwrite(self, ch: str) -> None:
        current = self.lines[self.line]
        if self.index < len(current):
            self.lines[self.line] = current[: self.index] + ch + current[self.index + 1 :]
            self._go(self.line, self.index + 1)
            self._touch()
        else:
            self.insert(ch)

    def newline(self, *, overwrite: bool = False) -> None:
        """The return key: split the line, with the indent of the line before.

        In overwrite mode the line is not split, and the cursor goes to the start of
        the next line, adding one at the end of the text (VZ).
        """
        if overwrite:
            if self.line + 1 == len(self.lines):
                self.lines.append("")
                self._touch()
            self._go(self.line + 1, 0)
            return
        current = self.lines[self.line]
        head = current[: self.index]
        indent = head[: len(head) - len(head.lstrip(" \t"))]
        self.insert("\n" + indent)

    def backspace(self) -> str | None:
        """Delete the character before the cursor, or join the line to the one above.

        Returns what was deleted ("\\n" for a join), or None at the top of the text.
        """
        if self.index > 0:
            current = self.lines[self.line]
            deleted = current[self.index - 1]
            self.lines[self.line] = current[: self.index - 1] + current[self.index :]
            self._go(self.line, self.index - 1)
        elif self.line > 0:
            above = self.lines[self.line - 1]
            self.lines[self.line - 1] = above + self.lines.pop(self.line)
            self._go(self.line - 1, len(above))
            deleted = "\n"
        else:
            return None
        self._touch()
        return deleted

    def delete(self) -> str | None:
        """Delete the character at the cursor, or join the next line to this one."""
        current = self.lines[self.line]
        if self.index < len(current):
            deleted = current[self.index]
            self.lines[self.line] = current[: self.index] + current[self.index + 1 :]
        elif self.line + 1 < len(self.lines):
            self.lines[self.line] = current + self.lines.pop(self.line + 1)
            deleted = "\n"
        else:
            return None
        self.want = None
        self._touch()
        return deleted

    def tab(self, *, overwrite: bool = False) -> None:
        """Insert a tab, or in overwrite mode move to the next tab stop (VZ)."""
        if not overwrite:
            self.insert("\t")
            return
        folded = self.folded(self.line)
        row = folded.row_of(self.index)
        column = next_tab_stop(self.cursor_column(), self.layout.tab_size)
        self._go(self.line, folded.index_at(row, column))

    def _delete_range(self, start: int, end: int) -> str | None:
        """Delete from `start` to `end` in the cursor line, leaving the cursor at `start`."""
        current = self.lines[self.line]
        deleted = current[start:end]
        self._go(self.line, start)
        if not deleted:
            return None
        self.lines[self.line] = current[:start] + current[end:]
        self._touch()
        return deleted

    def delete_word_back(self) -> str | None:
        """Delete back to where the word left command goes. At the line top, as BS."""
        if self.index == 0:
            return self.backspace()
        end = self.index
        self.word_left()
        return self._delete_range(self.index, end)

    def delete_word(self) -> str | None:
        """Delete up to where the word right command goes. At the line end, as DEL."""
        if self.index == len(self.lines[self.line]):
            return self.delete()
        start = self.index
        self.word_right()
        return self._delete_range(start, self.index)

    def delete_to_line_top(self) -> str | None:
        return self._delete_range(0, self.index)

    def delete_to_line_end(self) -> str | None:
        return self._delete_range(self.index, len(self.lines[self.line]))
