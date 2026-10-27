"""Frames, the one-line input box and menus, drawn over the editor or the filer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from pyvz.editor.layout import Layout
from pyvz.editor.stack import Deleted
from pyvz.editor.window import Window
from pyvz.keys.commands import Cmd
from pyvz.text.document import Document
from pyvz.ui import theme
from pyvz.ui.screen import PLAIN, Screen, Style, clip, text_width
from pyvz.ui.view import Overlay


def frame(
    screen: Screen,
    top: int,
    left: int,
    height: int,
    width: int,
    *,
    title: str = "",
    title_style: Style | None = None,
    footer: str = "",
    style: Style | None = None,
) -> None:
    """Draw a box and clear its inside."""
    if height < 2 or width < 2:
        return
    style = style or theme.style("frame")
    title_style = title_style or theme.style("title")
    right, bottom = left + width - 1, top + height - 1
    screen.put(top, left, "┌" + "─" * (width - 2) + "┐", style)
    for row in range(top + 1, bottom):
        screen.put(row, left, "│", style)
        screen.fill(row, left + 1, right)
        screen.put(row, right, "│", style)
    screen.put(bottom, left, "└" + "─" * (width - 2) + "┘", style)
    wide = screen.ambiguous_wide
    if title:
        screen.put(top, left + 1, clip(title, width - 2, ambiguous_wide=wide), title_style)
    if footer:
        screen.put(bottom, left + 1, clip(footer, width - 2, ambiguous_wide=wide), style)


class LineInput:
    """The text of a one-line input box, edited with the line editing commands of VZ.

    The text is a one-line window, so the commands move and delete as in a text. Up and
    down go through the history instead.
    """

    def __init__(
        self, text: str = "", history: list[str] | None = None, deleted: Deleted | None = None
    ) -> None:
        self.window = Window(Document(lines=[text]), Layout(width=1 << 20))
        self.window.index = len(text)
        self.window.deleted = deleted
        self.history = history if history is not None else []
        self._recall = len(self.history)
        self._typed = text

    @property
    def text(self) -> str:
        return self.window.lines[0]

    @property
    def index(self) -> int:
        return self.window.index

    def set(self, text: str) -> None:
        self.window.lines[0] = text
        self.window.index = len(text)

    def type(self, text: str, *, insert: bool = True) -> None:
        text = text.replace("\n", " ")
        if insert:
            self.window.insert(text)
        else:
            for ch in text:
                self.window.overwrite(ch)

    def run(self, command: int) -> bool:
        """Run a line editing command. False if it is not one."""
        w = self.window
        if command == Cmd.UP:
            if self._recall > 0:
                if self._recall == len(self.history):
                    self._typed = self.text
                self._recall -= 1
                self.set(self.history[self._recall])
        elif command == Cmd.DOWN:
            if self._recall < len(self.history):
                self._recall += 1
                recalled = self._recall < len(self.history)
                self.set(self.history[self._recall] if recalled else self._typed)
        elif command in _LINE_COMMANDS:
            _LINE_COMMANDS[command](w)
        else:
            return False
        return True


_LINE_COMMANDS = {
    Cmd.LEFT: Window.left,
    Cmd.RIGHT: Window.right,
    Cmd.WORD_LEFT: Window.word_left,
    Cmd.WORD_RIGHT: Window.word_right,
    Cmd.LINE_TOP: Window.line_top,
    Cmd.LINE_END: Window.line_end,
    Cmd.BACKSPACE: Window.backspace,
    Cmd.DELETE: Window.delete,
    Cmd.DELETE_WORD_BACK: Window.delete_word_back,
    Cmd.DELETE_WORD: Window.delete_word,
    Cmd.DELETE_TO_LINE_TOP: Window.delete_to_line_top,
    Cmd.DELETE_TO_LINE_END: Window.delete_to_line_end,
    Cmd.UNDELETE: Window.undelete,
}


@dataclass
class InputBox:
    """A layer: an input box with a title such as 【入力ファイル】."""

    title: str
    line: LineInput
    width: int = 0  # 0: half the screen, at least 44 columns

    def draw(self, screen: Screen, overlay: Overlay | None = None) -> None:
        width = self.width or max(44, screen.width // 2)
        width = min(width, screen.width - 2)
        left = max((screen.width - width) // 2, 0)
        top = 1
        frame(screen, top, left, 3, width, title=self.title)
        inner = width - 2
        text, index = self.line.text, self.line.index
        wide = screen.ambiguous_wide
        # Scroll sideways to keep the cursor inside, with a column for it at the end.
        start = 0
        while text_width(text[start:index], ambiguous_wide=wide) > inner - 1:
            start += 1
        shown = clip(text[start:], inner, ambiguous_wide=wide)
        screen.put(top + 1, left + 1, shown)
        cursor = left + 1 + text_width(text[start:index], ambiguous_wide=wide)
        screen.cursor = (top + 1, cursor)


class Item(NamedTuple):
    key: str  # the letter or digit that chooses it
    label: str


@dataclass
class Menu:
    """A layer: a menu of items chosen by their key letters or with the cursor."""

    items: list[Item]
    title: str = ""
    top: int = 1
    left: int = 0
    current: int = 0

    def size(self, screen: Screen) -> tuple[int, int]:
        wide = screen.ambiguous_wide
        inner = max(text_width(f"{i.key} {i.label}", ambiguous_wide=wide) for i in self.items)
        inner = max(inner, text_width(self.title, ambiguous_wide=wide)) + 2
        return len(self.items) + 2, min(inner + 2, screen.width)

    def draw(self, screen: Screen, overlay: Overlay | None = None) -> None:
        height, width = self.size(screen)
        top = max(min(self.top, screen.height - height), 0)
        left = max(min(self.left, screen.width - width), 0)
        frame(screen, top, left, height, width, title=self.title)
        for i, item in enumerate(self.items):
            row = top + 1 + i
            chosen = i == self.current
            if chosen:
                screen.fill(row, left + 1, left + width - 1, theme.style("chosen"))
            column = screen.put(
                row, left + 2, item.key, theme.style("chosen_hot") if chosen else theme.style("hot")
            )
            label = clip(item.label, width - 6, ambiguous_wide=screen.ambiguous_wide)
            screen.put(row, column + 1, label, theme.style("chosen") if chosen else PLAIN)
        screen.cursor = None

    def find(self, ch: str) -> int | None:
        for i, item in enumerate(self.items):
            if item.key.upper() == ch.upper():
                return i
        return None
