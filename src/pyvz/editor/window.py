"""A text being edited and its window: the document, the cursor, and the rows shown.

As in VZ, each text has its own window record, so the cursor and the rows shown stay
with the text when another text is shown.

A position in the text is (line, index). A screen row is (line, row), where row
counts the rows that a long line is folded into.
"""

from __future__ import annotations

from pyvz.editor.layout import Folded, Layout
from pyvz.editor.stack import Deleted
from pyvz.text import chartype
from pyvz.text.document import Document
from pyvz.text.width import next_tab_stop

Row = tuple[int, int]
Pos = tuple[int, int]

# Kinds of blocks, and of what the text stack holds.
LINE = "line"
CHAR = "char"
BLOCK = "block"  # the mark where the block starts
LAST = "last"  # the position to go back to with ^QP (VZ's tretp)

_OPENING = {"(": ")", "[": "]", "{": "}", "<": ">"}
_CLOSING = {close: open_ for open_, close in _OPENING.items()}


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
        # Positions that move with the text when it changes, such as "block", the
        # start of a block.
        self.marks: dict[str, Pos] = {}
        self.block: str | None = None  # LINE or CHAR while marking a block
        self.deleted: Deleted | None = None  # where deletions go for ^U, shared
        self.found: tuple[Pos, Pos] | None = None  # a match shown while asking about it
        # The cursor line as it was before the edits made in it since the cursor came
        # to it, with the modified flag then: VZ's line buffer, which ^QL drops.
        self._line_before: tuple[int, str, bool] | None = None

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

    def go_to(self, pos: Pos) -> None:
        self._go(*self.clamp(pos))

    # Marks and jumps

    def set_return(self) -> None:
        """Keep the cursor position for ^QP. VZ does this before the long jumps."""
        self.marks[LAST] = (self.line, self.index)

    def jump_mark(self, name: str) -> bool:
        """Go to a mark, keeping where the cursor was for ^QP. So ^QP, which goes to
        LAST, goes back and forth between two places."""
        if name not in self.marks:
            return False
        target = self.clamp(self.marks[name])
        self.set_return()
        self._go(*target)
        return True

    def jump_line(self, number: int) -> None:
        """^QJ: go to the start of a line, counted from 1."""
        self.set_return()
        self._go(max(0, min(number - 1, len(self.lines) - 1)), 0)

    def match_bracket(self) -> bool:
        """^QK: go to the bracket that matches the one at the cursor, ()[]{}<>, counting
        the brackets of the same kind in between (VZ)."""
        current = self.lines[self.line]
        ch = current[self.index] if self.index < len(current) else ""
        if ch in _OPENING:
            found = self._find_bracket(ch, _OPENING[ch], 1)
        elif ch in _CLOSING:
            found = self._find_bracket(ch, _CLOSING[ch], -1)
        else:
            return False
        if found is None:
            return False
        self._go(*found)
        return True

    def _find_bracket(self, same: str, other: str, step: int) -> Pos | None:
        depth = 0
        line, index = self.line, self.index
        while True:
            index += step
            while index < 0 or index >= len(self.lines[line]):
                line += step
                if not 0 <= line < len(self.lines):
                    return None
                index = 0 if step > 0 else len(self.lines[line]) - 1
            ch = self.lines[line][index]
            if ch == same:
                depth += 1
            elif ch == other:
                if depth == 0:
                    return line, index
                depth -= 1

    def change_case(self) -> bool:
        """^QU: the word from the cursor in lower case if it starts in upper case, and
        in upper case if it starts in lower case. ASCII letters only, as in VZ."""
        text = self.lines[self.line]
        start = self.index
        if start >= len(text) or not (text[start].isascii() and text[start].isalpha()):
            return False
        convert = str.lower if text[start].isupper() else str.upper
        end = start
        while end < len(text) and text[end].isascii():
            if not text[end].isalpha() and chartype.char_class(text[end]) != chartype.ALNUM:
                break
            end += 1
        cursor = (self.line, self.index)
        self.replace_between((self.line, start), (self.line, end), convert(text[start:end]))
        self._go(*cursor)
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
        self.set_return()
        self._go(0, 0)
        self.top = (0, 0)

    def text_end(self) -> None:
        self.set_return()
        last = len(self.lines) - 1
        self._go(last, len(self.lines[last]))
        self.top, _ = self.step(self.cursor_row(), -(self.height - 1))

    # Editing
    #
    # Every change goes through _insert_at and _delete_between, which move the cursor
    # and the marks (the start of a block) along with the text.

    def _touch(self) -> None:
        self.doc.modified = True

    def text_between(self, start: Pos, end: Pos) -> str:
        (l1, i1), (l2, i2) = start, end
        if l1 == l2:
            return self.lines[l1][i1:i2]
        return "\n".join([self.lines[l1][i1:], *self.lines[l1 + 1 : l2], self.lines[l2][:i2]])

    def _insert_at(self, pos: Pos, text: str) -> Pos:
        """Insert text at `pos`. Returns the end of it. Positions at `pos` or after it
        (the cursor among them) move past the text."""
        line, index = pos
        self._remember_line(line, within=len(text.split("\n")) == 1)
        current = self.lines[line]
        parts = text.split("\n")
        if len(parts) == 1:
            self.lines[line] = current[:index] + text + current[index:]
            end = (line, index + len(text))
        else:
            self.lines[line : line + 1] = (
                [current[:index] + parts[0], *parts[1:-1], parts[-1] + current[index:]]
            )  # fmt: skip
            end = (line + len(parts) - 1, len(parts[-1]))

        def moved(p: Pos) -> Pos:
            if p < pos:
                return p
            if p[0] == line:
                return end[0], end[1] + p[1] - index
            return p[0] + len(parts) - 1, p[1]

        self._move_positions(moved)
        self._touch()
        return end

    def _delete_between(self, start: Pos, end: Pos) -> str:
        """Delete from `start` to `end`. Positions inside go to `start`."""
        text = self.text_between(start, end)
        (l1, i1), (l2, i2) = start, end
        self._remember_line(l1, within=l1 == l2)
        self.lines[l1 : l2 + 1] = [self.lines[l1][:i1] + self.lines[l2][i2:]]

        def moved(p: Pos) -> Pos:
            if p <= start:
                return p
            if p <= end:
                return start
            if p[0] == l2:
                return l1, i1 + p[1] - i2
            return p[0] - (l2 - l1), p[1]

        self._move_positions(moved)
        if text:
            self._touch()
        return text

    def _move_positions(self, moved) -> None:
        self.line, self.index = moved((self.line, self.index))
        self.want = None
        for name, pos in self.marks.items():
            self.marks[name] = moved(pos)

    def _remember_line(self, line: int, *, within: bool) -> None:
        """Before a change: keep the line for ^QL. A change across lines writes the
        line back in VZ, so there is nothing to go back to after it."""
        if not within:
            self._line_before = None
        elif self._line_before is None or self._line_before[0] != line:
            self._line_before = (line, self.lines[line], self.doc.modified)

    def left_line(self) -> None:
        """The cursor may have moved: forget the line kept for ^QL if it did."""
        if self._line_before is not None and self._line_before[0] != self.line:
            self._line_before = None

    def cancel_line(self) -> bool:
        """^QL: put the cursor line back as it was when the cursor came to it."""
        kept = self._line_before
        if kept is None or kept[0] != self.line:
            return False
        line, text, modified = kept
        index = self.index
        self._delete_between((line, 0), (line, len(self.lines[line])))
        self._insert_at((line, 0), text)
        self._go(line, min(index, len(text)))
        self._line_before = None
        self.doc.modified = modified
        return True

    def clamp(self, pos: Pos) -> Pos:
        line = max(0, min(pos[0], len(self.lines) - 1))
        return line, max(0, min(pos[1], len(self.lines[line])))

    def insert(self, text: str) -> None:
        """Insert text at the cursor and move past it. LF in `text` splits lines."""
        self._insert_at((self.line, self.index), text)

    def overwrite(self, ch: str) -> None:
        if self.index < len(self.lines[self.line]):
            self._delete_between((self.line, self.index), (self.line, self.index + 1))
        self.insert(ch)

    def newline(self, *, overwrite: bool = False) -> None:
        """The return key: split the line, with the indent of the line before.

        In overwrite mode the line is not split, and the cursor goes to the start of
        the next line, adding one at the end of the text (VZ).
        """
        if overwrite:
            line = self.line
            if line + 1 == len(self.lines):
                self._insert_at((line, len(self.lines[line])), "\n")
            self._go(line + 1, 0)
            return
        head = self.lines[self.line][: self.index]
        indent = head[: len(head) - len(head.lstrip(" \t"))]
        self.insert("\n" + indent)

    def _erase(self, start: Pos, end: Pos, *, back: bool) -> str | None:
        """Delete as the delete commands do: what goes is kept for ^U."""
        text = self._delete_between(start, end)
        if not text:
            return None
        if self.deleted is not None:
            self.deleted.store(text, back=back)
        return text

    def backspace(self) -> str | None:
        """Delete the character before the cursor, or join the line to the one above.

        Returns what was deleted ("\\n" for a join), or None at the top of the text.
        """
        if self.index > 0:
            return self._erase((self.line, self.index - 1), (self.line, self.index), back=True)
        if self.line > 0:
            above = (self.line - 1, len(self.lines[self.line - 1]))
            return self._erase(above, (self.line, 0), back=True)
        return None

    def delete(self) -> str | None:
        """Delete the character at the cursor, or join the next line to this one."""
        here = (self.line, self.index)
        if self.index < len(self.lines[self.line]):
            return self._erase(here, (self.line, self.index + 1), back=False)
        if self.line + 1 < len(self.lines):
            return self._erase(here, (self.line + 1, 0), back=False)
        return None

    def undelete(self) -> bool:
        """^U: put back what was deleted last. What BS deleted goes before the cursor,
        and what DEL deleted after it (VZ)."""
        item = self.deleted.pop() if self.deleted is not None else None
        if item is None:
            return False
        text, back = item
        start = (self.line, self.index)
        self._insert_at(start, text)  # the cursor goes past the text
        if not back:
            self._go(*start)
        return True

    def tab(self, *, overwrite: bool = False) -> None:
        """Insert a tab, or in overwrite mode move to the next tab stop (VZ)."""
        if not overwrite:
            self.insert("\t")
            return
        folded = self.folded(self.line)
        row = folded.row_of(self.index)
        column = next_tab_stop(self.cursor_column(), self.layout.tab_size)
        self._go(self.line, folded.index_at(row, column))

    def _delete_range(self, start: int, end: int, *, back: bool) -> str | None:
        """Delete from `start` to `end` in the cursor line, leaving the cursor at `start`."""
        self._go(self.line, start)
        return self._erase((self.line, start), (self.line, end), back=back)

    def replace_between(self, start: Pos, end: Pos, text: str) -> Pos:
        """Put `text` in place of what is between `start` and `end`. Returns its end."""
        self._delete_between(start, end)
        return self._insert_at(start, text)

    def insert_line(self) -> None:
        """^N: a new line above the cursor line, with its indent (VZ)."""
        current = self.lines[self.line]
        indent = current[: len(current) - len(current.lstrip(" \t"))]
        line = self.line
        self._insert_at((line, 0), indent + "\n")
        self._go(line, len(indent))

    def same_class_end(self) -> int:
        """Where the run of characters of one class from the cursor ends."""
        if self.index >= len(self.lines[self.line]):
            return self.index
        return self._same_class_run(1)

    def _same_class_run(self, step: int) -> int:
        """Where the run of characters of the class next to the cursor ends."""
        text = self.lines[self.line]
        i = self.index if step > 0 else self.index - 1
        kind = chartype.char_class(text[i])
        while 0 <= i + step < len(text) and chartype.char_class(text[i + step]) == kind:
            i += step
        return i + 1 if step > 0 else i

    def delete_word_back(self) -> str | None:
        """Delete the characters before the cursor of one class, back to where the
        class changes (VZ). At the line top, as BS."""
        if self.index == 0:
            return self.backspace()
        return self._delete_range(self._same_class_run(-1), self.index, back=True)

    def delete_word(self) -> str | None:
        """Delete the characters after the cursor of one class (VZ). At the line end,
        as DEL."""
        if self.index == len(self.lines[self.line]):
            return self.delete()
        return self._delete_range(self.index, self._same_class_run(1), back=False)

    def delete_to_line_top(self) -> str | None:
        return self._delete_range(0, self.index, back=True)

    def delete_to_line_end(self) -> str | None:
        return self._delete_range(self.index, len(self.lines[self.line]), back=False)

    # Blocks

    def start_block(self) -> None:
        """^B: the block starts at the cursor. It is a line block until the cursor
        moves along a line (VZ starts with the line kind too)."""
        self.block = LINE
        self.marks[BLOCK] = (self.line, self.index)

    def block_range(self) -> tuple[str, Pos, Pos] | None:
        """The kind, start and end of the block, or None without a block.

        A character block runs from the start point to the cursor. A line block takes
        the lines from one of them to the line before the other, as both points go to
        the start of their lines. With the cursor on the line where the block starts,
        it is a character block.
        """
        if self.block is None or BLOCK not in self.marks:
            return None
        anchor = self.clamp(self.marks[BLOCK])
        cursor = (self.line, self.index)
        if self.block == CHAR or anchor[0] == cursor[0]:
            start, end = sorted((anchor, cursor))
            return CHAR, start, end
        first, last = sorted((anchor[0], cursor[0]))
        return LINE, (first, 0), (last, 0)

    def jump_block(self) -> bool:
        """^QB: go to the other end of the block, or of the text pasted last."""
        if BLOCK not in self.marks:
            return False
        other = self.clamp(self.marks[BLOCK])
        self.marks[BLOCK] = (self.line, self.index)
        self._go(*other)
        return True

    def take_line(self, *, delete: bool) -> str:
        """The cursor line with its line end, deleted if `delete` (^Y without a block).

        On the empty last line, the end of the text, there is nothing to take (VZ).
        A last line without a line end is taken as a line all the same.
        """
        line = self.line
        current = self.lines[line]
        if line == len(self.lines) - 1:
            if not current:
                return ""
            end = (line, len(current))
        else:
            end = (line + 1, 0)
        if delete:
            self._delete_between((line, 0), end)
            self._go(line, 0)
        return current + "\n"

    def put(self, kind: str, text: str) -> None:
        """Insert text from the text stack: lines before the cursor line, characters
        at the cursor. The cursor stays where the text starts, and the mark of the
        block goes to where it ends, for ^QB (VZ with Ek-)."""
        start = (self.line, 0) if kind == LINE else (self.line, self.index)
        cursor = (self.line, self.index)
        end = self._insert_at(start, text)
        self.marks[BLOCK] = end
        if kind == LINE:
            self._go(start[0], min(cursor[1], len(self.lines[start[0]])))
        else:
            self._go(*start)

    def take_block(self, *, delete: bool) -> tuple[str, str] | None:
        """The kind and text of the block, deleted if `delete`. The block ends.

        None without a block. The mark of the block stays, for ^QB.
        """
        found = self.block_range()
        self.block = None
        if found is None:
            return None
        kind, start, end = found
        text = self.text_between(start, end)
        if delete and text:
            self._delete_between(start, end)
        return kind, text
