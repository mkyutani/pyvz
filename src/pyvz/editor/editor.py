"""The editor: the texts being edited, and the commands that keys run on them."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from pyvz import paths
from pyvz.editor.layout import Layout
from pyvz.editor.window import Window
from pyvz.keys.commands import Cmd
from pyvz.text.document import Document


class Console(Protocol):
    """What the editor needs from the screen: messages and Y/N questions."""

    def message(self, text: str) -> None: ...

    def ask(self, question: str) -> bool | None:
        """Ask "question か？ (Y/N)". True for yes, False for no, None if cancelled."""
        ...


# Commands that change the text, refused for a read-only text.
_EDITS = {Cmd.RETURN, Cmd.BACKSPACE, Cmd.DELETE, Cmd.TAB}


class Editor:
    def __init__(self, console: Console, layout: Layout | None = None) -> None:
        self.console = console
        self.layout = layout or Layout()
        self.height = 1
        self.windows: list[Window] = []
        self.current = 0
        self.insert_mode = True
        # Set when the editor is to end, to the exit status of the program.
        self.exit_code: int | None = None
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
            Cmd.TAB: lambda _: self.window.tab(overwrite=not self.insert_mode),
            Cmd.ROLL_UP: lambda _: self.window.scroll(-1),
            Cmd.ROLL_DOWN: lambda _: self.window.scroll(1),
            Cmd.ROLL_UP2: lambda _: self.window.scroll(-2),
            Cmd.ROLL_DOWN2: lambda _: self.window.scroll(2),
            Cmd.PAGE_UP: lambda _: self.window.scroll(-self._page()),
            Cmd.PAGE_DOWN: lambda _: self.window.scroll(self._page()),
            # VZ scrolls smoothly until a key is pressed. pyvz scrolls a row.
            Cmd.SMOOTH_UP: lambda _: self.window.scroll(-1),
            Cmd.SMOOTH_DOWN: lambda _: self.window.scroll(1),
            Cmd.WINDOW_TOP: lambda _: self.window.window_top(),
            Cmd.WINDOW_END: lambda _: self.window.window_end(),
            Cmd.TEXT_TOP: lambda _: self.window.text_top(),
            Cmd.TEXT_END: lambda _: self.window.text_end(),
            Cmd.READ_ONLY: lambda _: self._toggle_read_only(),
            Cmd.CLOSE: lambda _: self.close(),
            Cmd.SAVE: lambda _: self.save(self.window),
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
        window = Window(doc, self.layout, cc=cc)
        window.height = self.height
        self.windows.append(window)
        self.current = len(self.windows) - 1
        if doc.new_file and not cc:
            self.console.message("新規ファイルです")
        return window

    def resize(self, width: int, height: int) -> None:
        """Set the size of the text area of the window."""
        self.layout = replace(self.layout, width=width)
        self.height = height
        for window in self.windows:
            window.layout = self.layout
            window.height = height
            window.keep_visible()

    def name(self, window: Window) -> str:
        path = window.doc.path
        return paths.shown(path) if path is not None else "(無題)"

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
        action(digit)
        if self.exit_code is None and self.windows:
            self.window.keep_visible()
        return True

    def type(self, text: str) -> None:
        """Type or paste text at the cursor."""
        if not self._writable():
            return
        window = self.window
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
        return max(self.height - 1, 1)

    def _toggle_insert(self) -> None:
        self.insert_mode = not self.insert_mode

    def _toggle_read_only(self) -> None:
        doc = self.window.doc
        doc.readonly = not doc.readonly

    # Files

    def save(self, window: Window) -> bool:
        doc = window.doc
        name = self.name(window)
        if doc.readonly:
            self.console.message(f"{name} はリードオンリーです")
            return False
        try:
            doc.save()
        except ValueError:
            self.console.message("ファイル名がありません")
            return False
        except OSError as e:
            self.console.message(f"{name} は出力できません（{e.strerror or e}）")
            return False
        return True

    def close(self) -> None:
        """Close the text, asking whether to save it if it was changed.

        The prompt file of Claude Code is saved without asking: closing it is how the
        text goes back to Claude Code.
        """
        window = self.window
        if window.doc.modified:
            if window.cc:
                if not self.save(window):
                    return
            else:
                answer = self.console.ask(f"{self.name(window)} を出力します")
                if answer is None or (answer and not self.save(window)):
                    return
        self._remove(window)

    def _remove(self, window: Window) -> None:
        index = self.windows.index(window)
        del self.windows[index]
        if not self.windows:
            self.exit_code = 0
            return
        if self.current >= index:
            self.current = max(self.current - 1, 0)

    def quit(self) -> None:
        modified = [w for w in self.windows if w.doc.modified]
        if modified:
            answer = self.console.ask("修正テキストを出力します")
            if answer is None:
                return
            if answer and not all(self.save(w) for w in modified):
                return
        if self.console.ask("エディタを終了します"):
            self.exit_code = 0

    def escape(self) -> None:
        """Quit without saving, asking first if a text was changed."""
        if any(w.doc.modified for w in self.windows):
            if not self.console.ask("編集テキストを放棄します"):
                return
        self.exit_code = 0

    def hold(self) -> None:
        if not self.window.cc:
            self.console.message("Claude Code から呼ばれていません")
            return
        self.console.message("下書きの保留はまだできません")
