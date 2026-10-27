"""The editor: the texts being edited, and the commands that keys run on them."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from pyvz import history, paths
from pyvz.editor.layout import Layout
from pyvz.editor.search import (
    Finder,
    Options,
    Pattern,
    compile_search,
    literal,
    unescape_replacement,
)
from pyvz.editor.stack import Deleted, TextStack
from pyvz.editor.window import CHAR, LAST, LINE, Window
from pyvz.filer.filer import Insert, Open
from pyvz.keys.commands import Cmd
from pyvz.text.document import Document, encode, write_file


class Console(Protocol):
    """What the editor needs from the screen: messages, questions, input and menus."""

    def message(self, text: str) -> None: ...

    def ask(self, question: str) -> bool | None:
        """Ask "question か？ (Y/N)". True for yes, False for no, None if cancelled."""
        ...

    def gets(self, title: str, text: str = "", *, kind: str = "") -> str | None:
        """Read a line in an input box, with the history named `kind`."""
        ...

    def menu(self, items: list[tuple[str, str]], *, title: str = "") -> int | str | None:
        """Show (key, label) items. The index of the chosen one, or None."""
        ...

    def filer(
        self, start: Path | None = None, *, pattern: str = "*", readonly: bool = False
    ) -> Open | Insert | None:
        """Run the filer, at `start` or where it was last time."""
        ...

    def remember(self, kind: str, text: str) -> None:
        """Put text in the history named `kind`, as if typed into an input box."""
        ...

    def control_char(self) -> str | None:
        """^P: read a key and give the control character it stands for."""
        ...

    def key_command(self) -> int | None:
        """Draw the screen, read a key and give its command, or None."""
        ...


class Prompt(Protocol):
    """The prompt file of Claude Code, which can be put on hold as a draft."""

    def hold(self, window: Window) -> None:
        """Keep the text as the draft, leaving the prompt file as it was."""
        ...

    def passed(self, window: Window) -> None:
        """The text was saved to the prompt file, so the draft is done."""
        ...


# Commands that change the text, refused for a read-only text.
_EDITS = {
    Cmd.CONTROL_CHAR,
    Cmd.CHANGE_CASE,
    Cmd.COPY_FILE_NAME,
    Cmd.INSERT_LINE,
    Cmd.REPLACE,
    Cmd.REPLACE_AGAIN,
    Cmd.COPY_STRING,
    Cmd.UNDELETE,
    Cmd.CANCEL_LINE,
    Cmd.CUT,
    Cmd.PASTE,
    Cmd.LOAD,
    Cmd.RETURN,
    Cmd.BACKSPACE,
    Cmd.DELETE,
    Cmd.DELETE_WORD_BACK,
    Cmd.DELETE_WORD,
    Cmd.DELETE_TO_LINE_TOP,
    Cmd.DELETE_TO_LINE_END,
    Cmd.TAB,
}

# Moving up and down makes a block of characters a block of lines (VZ: CMF_VMOVE),
# and the line editing commands make it a block of characters again.
_VERTICAL = {
    Cmd.UP,
    Cmd.DOWN,
    *range(Cmd.ROLL_UP, Cmd.LAST_POSITION + 1),
    Cmd.JUMP_LINE,
}
_ALONG_LINE = {*range(Cmd.LEFT, Cmd.REDRAW_LINE + 1), Cmd.SCREEN_LINE_LEFT, Cmd.SCREEN_LINE_RIGHT}


# Rows of the screen besides the windows: the message line and the function keys.
BOTTOM_ROWS = 2
# Split modes (VZ: full, upper and lower, left and right).
UPPER_LOWER = "upper-lower"
LEFT_RIGHT = "left-right"
MIN_ROWS = 1  # text rows of a window, at least
MIN_COLUMNS = 10


@dataclass(frozen=True)
class Region:
    """Where a window is on the screen. Its status line is on row `top`, and its text
    takes `rows` rows below it."""

    window: Window
    top: int
    left: int
    width: int
    rows: int


class Editor:
    def __init__(self, console: Console, layout: Layout | None = None) -> None:
        self.console = console
        self.layout = layout or Layout()
        self.screen = (self.layout.width, 24)  # columns and rows of the terminal
        self.windows: list[Window] = []
        # The split: None, UPPER_LOWER or LEFT_RIGHT, the two windows shown (upper or
        # left first), and where the split is (None: in the middle).
        self.split: str | None = None
        self.split_windows: list[Window] = []
        self.split_row: int | None = None
        self.split_column: int | None = None
        self.current = 0
        self._previous = 0  # the text shown before, for switching back
        self.insert_mode = True
        # Set when the editor is to end, to the exit status of the program.
        self.exit_code: int | None = None
        # Started from the filer: closing the last text goes back to it (VZ).
        self.keep_open = False
        self.prompt: Prompt | None = None
        self.stack = TextStack()
        self.deleted = Deleted()  # for ^U, shared by the texts and the input boxes
        # Search: the string as typed, the options it starts with (VZ: Ew, Ec, ZH, RX),
        # and the paging mode, P (by screens) or S (^R and ^C search).
        self.search: str | None = None
        self.search_options = Options()
        self.paging = "P"
        self._pattern: Pattern | None = None
        self._replace: tuple[Pattern, str, str, bool] | None = None
        self._last: tuple[int, int | None] | None = None
        self._commands: dict[int, Callable[[int | None], object]] = {
            Cmd.REPEAT: self._repeat,
            Cmd.ESCAPE: lambda _: self.escape(),
            Cmd.RETURN: lambda _: self.window.newline(overwrite=not self.insert_mode),
            Cmd.UP: lambda _: self.window.up(),
            Cmd.DOWN: lambda _: self.window.down(),
            Cmd.LEFT: lambda _: self.window.left(),
            Cmd.RIGHT: lambda _: self.window.right(),
            Cmd.WORD_LEFT: lambda _: self.window.word_left(),
            Cmd.WORD_RIGHT: lambda _: self.window.word_right(),
            Cmd.LINE_TOP: lambda _: self.window.line_top(),
            Cmd.LINE_END: lambda _: self.window.line_end(),
            Cmd.INSERT_MODE: lambda _: self._toggle_insert(),
            Cmd.BACKSPACE: lambda _: self.window.backspace(),
            Cmd.DELETE: lambda _: self.window.delete(),
            Cmd.DELETE_WORD_BACK: lambda _: self.window.delete_word_back(),
            Cmd.DELETE_WORD: lambda _: self.window.delete_word(),
            Cmd.DELETE_TO_LINE_TOP: lambda _: self.window.delete_to_line_top(),
            Cmd.DELETE_TO_LINE_END: lambda _: self.window.delete_to_line_end(),
            Cmd.UNDELETE: lambda _: self.window.undelete(),
            Cmd.CONTROL_CHAR: lambda _: self.control_char(),
            Cmd.CHANGE_CASE: lambda _: self.window.change_case(),
            Cmd.COPY_FILE_NAME: lambda _: self.copy_file_name(),
            Cmd.TAB: lambda _: self.window.tab(overwrite=not self.insert_mode),
            Cmd.ROLL_UP: lambda _: self.window.scroll(-1),
            Cmd.ROLL_DOWN: lambda _: self.window.scroll(1),
            Cmd.ROLL_UP2: lambda _: self.window.scroll(-2),
            Cmd.ROLL_DOWN2: lambda _: self.window.scroll(2),
            Cmd.PAGING_MODE: lambda _: self.toggle_paging(),
            Cmd.PAGE_UP: lambda _: self.page(-1),
            Cmd.PAGE_DOWN: lambda _: self.page(1),
            Cmd.COPY_STRING: lambda _: self.copy_string(),
            Cmd.INSERT_LINE: lambda _: self.window.insert_line(),
            Cmd.SET_SEARCH: lambda _: self.set_search(),
            Cmd.GET_WORD: lambda _: self.get_word(),
            Cmd.REPLACE: lambda _: self.replace(),
            Cmd.REPLACE_AGAIN: lambda _: self.replace_again(),
            # VZ scrolls smoothly until a key is pressed. pyvz scrolls a row.
            Cmd.SMOOTH_UP: lambda _: self.window.scroll(-1),
            Cmd.SMOOTH_DOWN: lambda _: self.window.scroll(1),
            Cmd.WINDOW_TOP: lambda _: self.window.window_top(),
            Cmd.WINDOW_END: lambda _: self.window.window_end(),
            Cmd.TEXT_TOP: lambda _: self.window.text_top(),
            Cmd.TEXT_END: lambda _: self.window.text_end(),
            Cmd.LAST_POSITION: self.last_position,
            Cmd.MARK_POSITION: self.mark_position,
            Cmd.JUMP_LINE: lambda _: self.jump_line(),
            Cmd.MATCH_BRACKET: lambda _: self.match_bracket(),
            Cmd.BLOCK: lambda _: self.toggle_block(),
            Cmd.CUT: lambda _: self.cut(delete=True),
            Cmd.PASTE: lambda _: self.paste(pop=True),
            Cmd.STORE: lambda _: self.cut(delete=False),
            Cmd.LOAD: lambda _: self.paste(pop=False),
            Cmd.CLEAR_STACK: lambda _: self.clear_stack(),
            Cmd.BLOCK_JUMP: lambda _: self.window.jump_block(),
            Cmd.CANCEL_LINE: lambda _: self.window.cancel_line(),
            Cmd.READ_ONLY: lambda _: self._toggle_read_only(),
            Cmd.OPEN: lambda _: self.open_command(),
            Cmd.OPEN_READ_ONLY: lambda _: self.open_command(readonly=True),
            Cmd.CLOSE_OPEN: lambda _: self.close_open(),
            Cmd.SWITCH_WINDOW: lambda _: self.switch_back(),
            Cmd.SPLIT_MODE: lambda _: self.split_mode(),
            Cmd.SPLIT_POSITION: lambda _: self.split_position(),
            Cmd.SWITCH_TEXT: lambda _: self.choose_text(),
            Cmd.NEW_FILE: lambda _: self.new_file(),
            Cmd.CLOSE: lambda _: self.close(),
            Cmd.SAVE: lambda _: self.save_as(),
            Cmd.RENAME: lambda _: self.rename(),
            Cmd.QUIT: lambda _: self.quit(),
            Cmd.COMMAND_LINE: lambda _: self.hold(),
            Cmd.SCREEN_LINE_LEFT: lambda _: self.window.row_left(),
            Cmd.SCREEN_LINE_RIGHT: lambda _: self.window.row_right(),
        }

    @property
    def window(self) -> Window:
        return self.windows[self.current]

    def open(self, path: Path, *, cc: bool = False, readonly: bool = False) -> Window:
        doc = Document.load(path, readonly=readonly)
        window = self.add(Window(doc, self.layout, cc=cc))
        if doc.new_file and not cc:
            self.console.message("新規ファイルです")
        return window

    def add(self, window: Window) -> Window:
        """Show a window made elsewhere, such as the prompt file of Claude Code."""
        window.layout = self.layout
        window.deleted = self.deleted
        self.windows.append(window)
        self.show(len(self.windows) - 1)
        return window

    def show(self, index: int) -> None:
        """Make a text the one edited. The one before is kept for @W (VZ's back text).

        With a split screen, the text goes in the window where the cursor is, unless it
        is shown in the other one already; then the cursor goes there.
        """
        if index == self.current or not self.windows:
            self.current = index
            self._relayout()
            return
        new, old = self.windows[index], self.windows[self.current]
        if self.split and new not in self.split_windows and old in self.split_windows:
            self.split_windows[self.split_windows.index(old)] = new
            other = next(w for w in self.split_windows if w is not new)
            self._previous = self.windows.index(other)
        else:
            self._previous = self.current
        self.current = index
        self._relayout()

    def find(self, path: Path) -> int | None:
        """The index of the text of a file, if it is open."""
        target = os.path.abspath(path)
        for i, window in enumerate(self.windows):
            if window.doc.path is not None and os.path.abspath(window.doc.path) == target:
                return i
        return None

    def resize(self, columns: int, rows: int) -> None:
        """Set the size of the terminal."""
        self.screen = (columns, rows)
        self.layout = replace(self.layout, width=columns)
        self._relayout()

    def regions(self) -> list[Region]:
        """The windows on the screen, the one being edited among them."""
        if not self.windows:
            return []
        columns, rows = self.screen
        area = max(rows - BOTTOM_ROWS, 2)  # rows for the windows with their status lines
        if self.split is None or len(self.split_windows) != 2:
            return [Region(self.window, 0, 0, columns, area - 1)]
        first, second = self.split_windows
        if self.split == UPPER_LOWER:
            row = self.split_row if self.split_row is not None else area // 2
            row = max(1 + MIN_ROWS, min(row, area - 1 - MIN_ROWS))
            return [
                Region(first, 0, 0, columns, row - 1),
                Region(second, row, 0, columns, area - row - 1),
            ]
        column = self.split_column if self.split_column is not None else columns // 2
        column = max(MIN_COLUMNS, min(column, columns - 1 - MIN_COLUMNS))
        return [
            Region(first, 0, 0, column, area - 1),
            Region(second, 0, column + 1, columns - column - 1, area - 1),
        ]

    def _relayout(self) -> None:
        """Give each window shown its width and height."""
        for region in self.regions():
            window = region.window
            window.layout = replace(self.layout, width=max(region.width, 1))
            window.height = max(region.rows, 1)
            window.keep_visible()

    def split_mode(self) -> None:
        """@Y: full screen, then upper and lower, then left and right (VZ).

        The text being edited goes on top or on the left, the one before it below or
        on the right. With one text there is nothing to split.
        """
        if len(self.windows) < 2:
            return
        if self.split is None:
            self.split = UPPER_LOWER
        elif self.split == UPPER_LOWER:
            self.split = LEFT_RIGHT
        else:
            self.split = None
        back = self._previous if self._previous != self.current else (self.current + 1)
        back %= len(self.windows)
        self._previous = back
        self.split_windows = [self.window, self.windows[back]] if self.split else []
        self._relayout()

    def split_position(self) -> None:
        """^KF: move where the screen is split with the cursor keys, until Enter."""
        if self.split is None:
            return
        columns, rows = self.screen
        regions = self.regions()
        while True:
            self.console.message("カーソルキーで位置を移動して[Enter]")
            number = self.console.key_command()
            if number in (Cmd.RETURN, Cmd.ESCAPE):
                self.console.message("")
                return
            if self.split == UPPER_LOWER and number in (Cmd.UP, Cmd.DOWN):
                self.split_row = regions[1].top + (-1 if number == Cmd.UP else 1)
            elif self.split == LEFT_RIGHT and number in (Cmd.LEFT, Cmd.RIGHT):
                self.split_column = regions[0].width + (-2 if number == Cmd.LEFT else 2)
            self._relayout()
            regions = self.regions()

    def name(self, window: Window) -> str:
        path = window.doc.path
        if path is None:
            return "(無題)"
        # Claude Code's prompt files are in its temporary directory: the name is enough.
        return path.name if window.cc else paths.shown(path)

    # Keys

    def has(self, command: int) -> bool:
        return command in self._commands

    def run(self, command: int, digit: int | None = None) -> bool:
        """Run a command. Returns False if pyvz does not have the command yet."""
        action = self._commands.get(command)
        if action is None:
            return False
        if command != Cmd.REPEAT:
            self._last = (command, digit)
        if command in _EDITS and not self._writable():
            return True
        window = self.window
        if window.block == CHAR and command in _VERTICAL:
            window.block = LINE
        elif window.block == LINE and command in _ALONG_LINE:
            window.block = CHAR
        action(digit)
        if self.exit_code is None and self.windows:
            self.window.left_line()
            self.window.keep_visible()
        return True

    def type(self, text: str) -> None:
        """Type or paste text at the cursor."""
        if not self._writable():
            return
        window = self.window
        if window.block == LINE:
            window.block = CHAR
        if self.insert_mode or "\n" in text:
            window.insert(text)
        else:
            for ch in text:
                window.overwrite(ch)
        window.keep_visible()

    def _writable(self) -> bool:
        if self.window.doc.readonly:
            self.console.message(f"{self.name(self.window)} はリードオンリーです")
            return False
        return True

    def _repeat(self, _digit: int | None) -> None:
        if self._last is not None:
            self.run(*self._last)

    def _page(self) -> int:
        return max(self.window.height - 1, 1)

    def _toggle_insert(self) -> None:
        self.insert_mode = not self.insert_mode

    def _toggle_read_only(self) -> None:
        doc = self.window.doc
        doc.readonly = not doc.readonly

    # Marks and jumps

    def mark_position(self, digit: int | None) -> None:
        """^QM: keep the cursor position for ^QP. ^K1-^K4 (VZ.DEF macro 16): set mark
        1-4."""
        window = self.window
        if digit is None:
            window.set_return()
            self.console.message("マークしました")
        elif digit == 0:
            window.set_return()
        elif digit <= 4:
            window.marks[str(digit)] = (window.line, window.index)
            self.console.message(f"マーク #{digit}")

    def last_position(self, digit: int | None) -> None:
        """^QP: back to the position kept, keeping this one. ^Q1-^Q4 (VZ.DEF macro 17):
        go to mark 1-4."""
        if digit is None or digit == 0:
            self.window.jump_mark(LAST)
        elif digit <= 4:
            self.window.jump_mark(str(digit))

    def jump_line(self) -> None:
        """^QJ: go to the line numbered in 【行番号】."""
        text = self.console.gets("【行番号】")
        if not text:
            return
        try:
            number = int(text.strip())
        except ValueError:
            self.console.message(f"{text} は行番号ではありません")
            return
        self.window.jump_line(number)

    def match_bracket(self) -> None:
        if not self.window.match_bracket():
            self.console.message("括弧が見つかりません")

    def control_char(self) -> None:
        ch = self.console.control_char()
        if ch:
            self.type(ch)

    def copy_file_name(self) -> None:
        """^QN: type the file name of the text."""
        window = self.window
        if window.doc.path is not None:
            self.type(self.name(window))

    # Search and replace

    def _search_title(self) -> str:
        letters = self.search_options.letters()
        return "【検索文字列】" + (f" <OPT:{letters}>" if letters else "")

    def _use_search(self, text: str) -> bool:
        try:
            self._pattern = compile_search(text, self.search_options)
        except ValueError as e:
            self.console.message(str(e))
            return False
        self.window.set_return()  # VZ: ^QP goes back to where the search started
        self.search = text
        self.paging = "S"
        self.console.message(text)  # VZ shows the search string
        return True

    def set_search(self) -> None:
        """^QF: set the search string. ^R and ^C then search backward and forward."""
        text = self.console.gets(self._search_title(), self.search or "", kind=history.SEARCH)
        if not text:
            self.paging = "P"
            self._pattern = None
            return
        self._use_search(text)

    def get_word(self) -> None:
        """^L: the word at the cursor, or the block, becomes the search string."""
        window = self.window
        found = window.block_range()
        if found is not None and found[0] == CHAR and found[1] != found[2]:
            text = window.text_between(found[1], found[2])
            window.block = None
        else:
            end = window.same_class_end()
            text = window.lines[window.line][window.index : end]
        if not text:
            return
        text = literal(text)
        self.console.remember(history.SEARCH, text)
        self._use_search(text)

    def toggle_paging(self) -> None:
        """^@: P (page by screens) and S (search with ^R and ^C)."""
        if self.paging == "S":
            self.paging = "P"
        elif self._pattern is not None and self.search is not None:
            self.paging = "S"
            self.console.message(self.search)

    def page(self, direction: int) -> None:
        if self.paging == "S" and self._pattern is not None:
            self.search_next(backward=direction < 0)
        else:
            self.window.scroll(direction * self._page())

    def search_next(self, *, backward: bool) -> bool:
        """Go to the next match of the search string (VZ: ^R and ^C in S mode)."""
        window = self.window
        if self._pattern is None:
            return False
        finder = Finder(window.lines)
        here = (window.line, window.index)
        if backward:
            m = finder.backward(self._pattern, here)
        else:
            m = finder.forward(self._pattern, here)
        if m is None:
            self.console.message("文字列が見つかりません")
            return False
        window.go_to(finder.pos(m.start()))
        return True

    def copy_string(self) -> None:
        """^QI: type a string, the search string to start with, from 【複写文字列】."""
        text = self.console.gets("【複写文字列】", self.search or "", kind=history.SEARCH)
        if text:
            self.type(text)

    def replace(self) -> None:
        """^QA: replace, in the block or a range chosen from a menu, all at once or
        asking about each (VZ)."""
        window = self.window
        while True:
            text = self.console.gets(self._search_title(), self.search or "", kind=history.SEARCH)
            if not text:
                return
            try:
                pattern = compile_search(text, self.search_options)
            except ValueError as e:
                self.console.message(str(e))
                return
            replacement = self.console.gets("【置換文字列】", kind=history.REPLACE)
            if replacement is not None:
                break  # ESC goes back to the search string
        self.search, self._pattern = text, pattern
        if window.block_range() is not None:
            scope = "block"
        else:
            items = [("A", "テキスト全体"), ("F", "カーソル以降"), ("B", "カーソル以前")]
            chosen = self.console.menu(items, title="【置換範囲】")
            if not isinstance(chosen, int):
                return
            scope = "AFB"[chosen]
        at_once = self.console.ask("全部一度に置換します")
        if at_once is None:
            return
        self._replace = (pattern, replacement, scope, at_once)
        self._run_replace()

    def replace_again(self) -> None:
        """^QO: the last replace again, from where the cursor is now."""
        if self._replace is None:
            self.replace()
        else:
            self._run_replace()

    def _scope(self, scope: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
        window = self.window
        cursor = (window.line, window.index)
        end_of_text = (len(window.lines) - 1, len(window.lines[-1]))
        if scope == "block":
            found = window.block_range()
            return (found[1], found[2]) if found is not None else None
        if scope == "F":
            return cursor, end_of_text
        if scope == "B":
            return (0, 0), cursor
        return (0, 0), end_of_text

    def _replacement(self, pattern: Pattern, replacement: str, m) -> str:
        if pattern.options.regex:
            return m.expand(replacement)
        return unescape_replacement(replacement)

    def _run_replace(self) -> None:
        assert self._replace is not None
        pattern, replacement, scope, at_once = self._replace
        window = self.window
        found_scope = self._scope(scope)
        if found_scope is None:
            return
        finder = Finder(window.lines)
        start, end = finder.offset(found_scope[0]), finder.offset(found_scope[1])
        count = 0
        try:
            if at_once:
                count = self._replace_all(pattern, replacement, finder, start, end)
            else:
                count = self._replace_asking(pattern, replacement, start, end)
        except (re.error, IndexError) as e:
            self.console.message(f"置換文字列の誤り: {e}")
            return
        finally:
            window.found = None
        self.console.message(f"{count} 個の文字列を置換しました")

    def _replace_all(self, pattern, replacement, finder: Finder, start: int, end: int) -> int:
        chosen, last_end = [], start
        for m in finder.matches(pattern, start):
            if m.end() > end:
                break
            if m.start() >= last_end:
                chosen.append(m)
                last_end = m.end()
        window = self.window
        # From the end, so that the offsets of the matches before stay right.
        for m in reversed(chosen):
            text = self._replacement(pattern, replacement, m)
            window.replace_between(finder.pos(m.start()), finder.pos(m.end()), text)
        return len(chosen)

    def _replace_asking(self, pattern, replacement, start: int, end: int) -> int:
        window = self.window
        count, offset = 0, start
        while True:
            finder = Finder(window.lines)
            m = next(finder.matches(pattern, offset), None)
            if m is None or m.end() > end:
                return count
            first, last = finder.pos(m.start()), finder.pos(m.end())
            window.go_to(first)
            window.found = (first, last)
            window.keep_visible()
            answer = self.console.ask("置換します")
            window.found = None
            if answer is None:
                return count
            if not answer:
                offset = m.start() + 1
                continue
            text = self._replacement(pattern, replacement, m)
            window.replace_between(first, last, text)
            window.go_to(first)
            count += 1
            end += len(text) - (m.end() - m.start())
            offset = m.start() + len(text)

    # Blocks and the text stack

    def toggle_block(self) -> None:
        window = self.window
        if window.block is None:
            window.start_block()
        else:
            window.block = None

    def cut(self, *, delete: bool) -> None:
        """^Y (delete) and ^KK (store): push the block, or the cursor line, onto the
        text stack."""
        window = self.window
        taken = window.take_block(delete=delete)
        if taken is None:
            text = window.take_line(delete=delete)
            taken = (LINE, text)
        if taken[1]:
            self.stack.push(*taken)

    def paste(self, *, pop: bool) -> None:
        """^J (pop) and ^KC (copy without popping): insert the top of the text stack."""
        item = self.stack.pop() if pop else self.stack.top()
        if item is None:
            self.console.message("テキストスタックは空です")
            return
        window = self.window
        window.block = None
        window.put(*item)

    def clear_stack(self) -> None:
        if self.console.ask("テキストスタックを消去します"):
            self.stack.clear()

    # Files

    def save(self, window: Window, path: Path | None = None) -> bool:
        """Save the text, under `path` if given, which renames it (VZ)."""
        doc = window.doc
        name = self.name(window)
        if doc.readonly:
            self.console.message(f"{name} はリードオンリーです")
            return False
        try:
            doc.save(path)
        except ValueError:
            self.console.message("ファイル名がありません")
            return False
        except OSError as e:
            self._cannot_write(path or doc.path, e)
            return False
        return True

    def _cannot_write(self, path: Path | None, error: OSError) -> None:
        name = paths.shown(path) if path is not None else "(無題)"
        self.console.message(f"{name} は出力できません（{error.strerror or error}）")

    def save_as(self) -> None:
        """[ESC]S: save under the name in 【出力ファイル】, the current name to start with.

        For the prompt file of Claude Code, another name writes a copy, and the text
        stays the prompt.
        """
        window = self.window
        doc = window.doc
        if window.block_range() is not None:
            self._save_block(window)
            return
        if doc.readonly:
            self.console.message(f"{self.name(window)} はリードオンリーです")
            return
        current = self.name(window) if doc.path is not None else ""
        name = self.console.gets("【出力ファイル】", current, kind=history.FILE)
        if not name:
            return
        path = Path(os.path.expanduser(name))
        same = doc.path is not None and os.path.abspath(path) == os.path.abspath(doc.path)
        if not same and path.exists():
            if not self.console.ask(f"{paths.shown(path)} はすでに存在します. 出力します"):
                return
        if window.cc and not same:
            self._write_copy(path, doc.lines, doc)
            return
        self.save(window, None if same else path)

    def _save_block(self, window: Window) -> None:
        """[ESC]S with a block: write the block to a file (VZ). The text stays."""
        name = self.console.gets("【出力ファイル】", kind=history.FILE)
        if not name:
            return
        path = Path(os.path.expanduser(name))
        if path.exists() and not self.console.ask(
            f"{paths.shown(path)} はすでに存在します. 出力します"
        ):
            return
        taken = window.take_block(delete=False)
        if taken is not None:
            self._write_copy(path, taken[1].split("\n"), window.doc)

    def _write_copy(self, path: Path, lines: list[str], doc: Document) -> None:
        """Write lines to a file that is not the text's own, in the text's format."""
        fmt = replace(doc.format, final_newline=False)
        try:
            write_file(path, encode(lines, fmt))
        except OSError as e:
            self._cannot_write(path, e)
            return
        self.console.message(f"{paths.shown(path)} に出力しました")

    def new_file(self) -> None:
        """[ESC]N: a new text, with the name given in 【新規ファイル】."""
        name = self.console.gets("【新規ファイル】", kind=history.FILE)
        if not name:
            return
        self.open_file(Path(os.path.expanduser(name)))

    def open_file(self, path: Path, *, readonly: bool = False) -> None:
        """Show the text of a file, opening it unless it is open already."""
        found = self.find(path)
        if found is not None:
            self.show(found)
            self.console.message(f"{self.name(self.window)} はオープンされています")
            return
        if path.is_dir():
            self.console.message(f"{paths.shown(path)} はディレクトリです")
            return
        try:
            self.open(path, readonly=readonly)
        except OSError as e:
            self.console.message(f"{paths.shown(path)} は入力できません（{e.strerror or e}）")

    def open_command(self, *, readonly: bool = False) -> None:
        """[ESC]O, [ESC]R: open the file named in 【入力ファイル】.

        Enter alone opens the filer, as does a directory or a pattern such as *.md.
        """
        name = self.console.gets("【入力ファイル】", kind=history.FILE)
        if name is not None:
            self.open_name(name, readonly=readonly)

    def open_name(self, name: str, *, readonly: bool = False) -> None:
        name = name.strip()
        if not name:
            self.take(self.console.filer(readonly=readonly))
            return
        path = Path(os.path.expanduser(name))
        if any(ch in path.name for ch in "*?["):
            self.take(self.console.filer(path.parent, pattern=path.name, readonly=readonly))
        elif path.is_dir():
            self.take(self.console.filer(path, readonly=readonly))
        else:
            self.open_file(path, readonly=readonly)

    def take(self, result: Open | Insert | None) -> None:
        """Do what the filer ended with."""
        if isinstance(result, Open):
            for path in result.paths:
                self.open_file(path, readonly=result.readonly)
        elif isinstance(result, Insert):
            if self.windows:
                self.type(result.text)
            else:
                self.console.message("挿入先のテキストがありません")

    def close_open(self) -> None:
        """[ESC]L: open another file in place of this text."""
        old = self.window
        if old.cc:
            self.console.message("変更できません")
            return
        self.open_command()
        if old in self.windows and self.window is not old:
            self._close_text(old)

    def rename(self) -> None:
        """[ESC]P: change the file name of the text. It is written on the next save."""
        window = self.window
        if window.cc:
            self.console.message("変更できません")
            return
        current = self.name(window) if window.doc.path is not None else ""
        name = self.console.gets("【ファイル名】", current, kind=history.FILE)
        if not name or name == current:
            return
        window.doc.path = Path(os.path.expanduser(name))
        window.doc.modified = True

    def switch_back(self) -> None:
        """Show the text shown before. VZ switches split windows with this key."""
        if len(self.windows) > 1:
            self.show(self._previous if self._previous < len(self.windows) else 0)

    def choose_text(self) -> None:
        """@T: choose the text to show from 【編集テキスト】."""
        keys = "123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        items = []
        for i, window in enumerate(self.windows[: len(keys)]):
            marks = (" (CC)" if window.cc else "") + (" *" if window.doc.modified else "")
            items.append((keys[i], self.name(window) + marks))
        chosen = self.console.menu(items, title="【編集テキスト】")
        if isinstance(chosen, int):
            self.show(chosen)

    def close(self) -> None:
        """Close the text, asking whether to save it if it was changed.

        The prompt file of Claude Code is saved without asking: closing it is how the
        text goes back to Claude Code, and the editor ends with it.
        """
        window = self.window
        if window.cc:
            if self._save_others() and self._pass(window):
                self.exit_code = 0
            return
        self._close_text(window)

    def _close_text(self, window: Window) -> bool:
        """Close a text, asking whether to save it if it was changed."""
        if window.doc.modified:
            answer = self.console.ask(f"{self.name(window)} を出力します")
            if answer is None or (answer and not self.save(window)):
                return False
        self._remove(window)
        return True

    def _remove(self, window: Window) -> None:
        index = self.windows.index(window)
        del self.windows[index]
        if window in self.split_windows:
            self.split, self.split_windows = None, []
        if not self.windows:
            if not self.keep_open:
                self.exit_code = 0
            return
        # Back to the text shown before, as when a peeked file is closed.
        before = self._previous if self._previous != index else self.current
        self.current = min(before - (before > index), len(self.windows) - 1)
        self._previous = self.current
        self._relayout()

    def _changed_files(self) -> list[Window]:
        """Changed texts other than the prompt file of Claude Code."""
        return [w for w in self.windows if w.doc.modified and not w.cc]

    def _save_others(self) -> bool:
        """Ask whether to save the changed texts, and save them. False if cancelled."""
        changed = self._changed_files()
        if not changed:
            return True
        answer = self.console.ask("修正テキストを出力します")
        if answer is None:
            return False
        return not answer or all(self.save(w) for w in changed)

    def _pass(self, window: Window) -> bool:
        """Save the prompt file of Claude Code, which hands the text to Claude Code."""
        if window.doc.modified and not self.save(window):
            return False
        if self.prompt is not None:
            self.prompt.passed(window)
        return True

    def _pass_prompts(self) -> bool:
        return all(self._pass(w) for w in self.windows if w.cc)

    def quit(self) -> None:
        """Quit, asking whether to save the changed texts and whether to quit.

        The prompt file of Claude Code is saved without asking, as on closing it.
        """
        if not self._save_others():
            return
        if self.console.ask("エディタを終了します") and self._pass_prompts():
            self.exit_code = 0

    def escape(self) -> None:
        """Quit without saving, asking first if a text was changed.

        The prompt file of Claude Code is still saved: the way to leave its text out of
        Claude Code's input box is putting it on hold.
        """
        if self._changed_files() and not self.console.ask("編集テキストを放棄します"):
            return
        if self._pass_prompts():
            self.exit_code = 0

    def hold(self) -> None:
        """Put the prompt text on hold and go back to Claude Code (VZ: go to DOS).

        Claude Code's input box stays as it was, and the next call from Claude Code
        shows the draft again.
        """
        window = self.window
        if not window.cc or self.prompt is None:
            self.console.message("Claude Code から呼ばれていません")
            return
        if not self._save_others():
            return
        try:
            self.prompt.hold(window)
        except OSError as e:
            self.console.message(f"下書きを保存できません（{e.strerror or e}）")
            return
        self.exit_code = 0
