"""The main loop: reading keys, running commands, and drawing the screen."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pyvz.editor.editor import Editor
from pyvz.filer.filer import Filer, Insert, Open
from pyvz.history import History
from pyvz.keys import codes
from pyvz.keys.commands import Cmd
from pyvz.keys.keymap import Keymap, Mode, follow
from pyvz.keys.terminal import Alt, Char, Decoder, Event, Key, Paste
from pyvz.ui import view
from pyvz.ui.screen import Screen
from pyvz.ui.widgets import InputBox, Item, LineInput, Menu

# How long to wait after ESC for the rest of an escape sequence, or for the character
# of Alt+character. Terminals send these at once, and people do not type that fast.
ESC_DELAY = 0.05

_CURSOR_INSERT = "\x1b[6 q"  # a bar
_CURSOR_OVERWRITE = "\x1b[2 q"  # a block


class Layer(Protocol):
    """Something drawn over the editor: an input box, a menu, the filer."""

    def draw(self, screen: Screen, overlay: view.Overlay) -> None: ...


class Terminal(Protocol):
    def size(self) -> tuple[int, int]: ...
    def take_resized(self) -> bool: ...
    def read(self, timeout: float | None) -> bytes | None: ...
    def write(self, text: str) -> None: ...


@dataclass(frozen=True)
class Typed:
    text: str


@dataclass(frozen=True)
class Command:
    number: int
    digit: int | None = None
    key: tuple[int, ...] = ()  # the key codes it came from


Press = Typed | Command


class Loop:
    """Runs the editor on a terminal. It is also the editor's console."""

    def __init__(self, terminal: Terminal, keymap: Keymap, history: History | None = None) -> None:
        self.terminal = terminal
        self.keymap = keymap
        self.history = history or History()
        self.editor: Editor | None = None
        self.overlay = view.Overlay()
        self.layers: list[Layer] = []
        # The directory pyvz started in: Claude Code's. Inserted paths are relative to it.
        self.origin = Path.cwd()
        self._filer: Filer | None = None
        self.ambiguous_wide = False
        self._decoder = Decoder()
        self._events: deque[Event] = deque()
        self._size = (80, 24)
        self._shown: Screen | None = None
        self._cursor_shape = ""

    # The console of the editor

    def message(self, text: str) -> None:
        self.overlay.message = text

    def ask(self, question: str) -> bool | None:
        answer = self.choose(f"{question}か？ (Y/N) ", "YN", space="N")
        return None if answer is None else answer == "Y"

    def choose(self, question: str, keys: str, *, space: str = "") -> str | None:
        """Ask a question answered with one of `keys` (letters in upper case).

        Enter gives the first key and Space gives `space`, as VZ's Sy+ option does.
        ESC gives None.
        """
        self.overlay.question = question
        try:
            while True:
                self.draw()
                event = self.next_event()
                if isinstance(event, Char):
                    answer = event.ch.upper()
                    if answer in keys:
                        return answer
                    if answer == " " and space:
                        return space
                elif isinstance(event, Key):
                    if codes.CR in event.codes:
                        return keys[0]
                    if codes.ESC in event.codes:
                        return None
        finally:
            self.overlay.question = ""

    def gets(self, title: str, text: str = "", *, kind: str = "") -> str | None:
        """Read a line in an input box. None if cancelled with ESC.

        `kind` names the history that up and down go through, and that the line goes
        into.
        """
        editor = self._editor()
        line = LineInput(text, self.history.get(kind) if kind else [], editor.deleted)
        box = InputBox(title, line)
        self.layers.append(box)
        try:
            while True:
                self.draw()
                press = self.read_press(Mode.GETS)
                self.overlay.message = ""
                if isinstance(press, Typed):
                    line.type(press.text, insert=editor.insert_mode)
                elif isinstance(press, Command):
                    if press.number == Cmd.ESCAPE:
                        return None
                    if press.number == Cmd.RETURN:
                        if kind:
                            self.history.add(kind, line.text)
                        return line.text
                    if press.number == Cmd.INSERT_MODE:
                        editor.insert_mode = not editor.insert_mode
                    elif press.number == Cmd.COPY_FILE_NAME and editor.windows:
                        line.type(editor.name(editor.window))
                    else:
                        line.run(press.number)
        finally:
            self.layers.remove(box)

    def remember(self, kind: str, text: str) -> None:
        self.history.add(kind, text)

    def menu(
        self,
        items: list[Item] | list[tuple[str, str]],
        *,
        title: str = "",
        top: int = 1,
        left: int = 0,
        current: int = 0,
        sideways: bool = False,
    ) -> int | str | None:
        """Show a menu and return the index of the chosen item, or None for ESC.

        With `sideways`, left and right give "left" and "right", for moving to the next
        menu of a menu bar.
        """
        menu = Menu([Item(*item) for item in items], title, top, left, current)
        self.layers.append(menu)
        try:
            while True:
                self.draw()
                press = self.read_press(Mode.GETC)
                if isinstance(press, Typed):
                    found = menu.find(press.text[:1]) if press.text else None
                    if found is not None:
                        return found
                elif isinstance(press, Command):
                    number = press.number
                    if number == Cmd.ESCAPE:
                        return None
                    if number == Cmd.RETURN:
                        return menu.current
                    if number == Cmd.UP:
                        menu.current = (menu.current - 1) % len(items)
                    elif number == Cmd.DOWN:
                        menu.current = (menu.current + 1) % len(items)
                    elif sideways and number in (Cmd.LEFT, Cmd.RIGHT):
                        return "left" if number == Cmd.LEFT else "right"
        finally:
            self.layers.remove(menu)

    # Running

    def filer(
        self, start: Path | None = None, *, pattern: str = "*", readonly: bool = False
    ) -> Open | Insert | None:
        from pyvz.ui.filerui import FilerScreen  # it builds on this module

        if self._filer is None:
            self._filer = Filer(self.origin)
            self._filer.restore_state()
        if start is not None:
            pane = self._filer.pane
            old = pane.pattern
            pane.pattern = pattern
            try:
                pane.go(start)
            except OSError as e:
                pane.pattern = old
                self.message(f"{start}: {e.strerror or e}")
        return FilerScreen(self, self._filer, readonly=readonly).run()

    def run(self, start: Path | None = None) -> int:
        """Run until the editor ends. With no text, the filer comes first, at `start`."""
        editor = self._editor()
        self.resize()
        while editor.exit_code is None:
            if not editor.windows:  # started from the filer, or back to it
                result = self.filer(start)
                start = None
                if result is None:
                    editor.exit_code = 0
                else:
                    editor.take(result)
                continue
            self.draw()
            press = self.read_press(Mode.EDIT)
            self.overlay.message = ""
            if isinstance(press, Typed):
                editor.type(press.text)
            elif isinstance(press, Command) and not editor.run(press.number, press.digit):
                name = self.keymap.messages.get(press.number, f"#{press.number}")
                self.message(f"{name}: まだありません")
        return editor.exit_code

    def _editor(self) -> Editor:
        if self.editor is None:
            raise RuntimeError("no editor to run")
        return self.editor

    @property
    def size(self) -> tuple[int, int]:
        """Columns and rows of the terminal."""
        return self._size

    def resize(self) -> None:
        self._size = self.terminal.size()
        columns, rows = self._size
        self._editor().resize(columns, view.text_rows(rows))
        self._shown = None

    def draw(self) -> None:
        columns, rows = self._size
        screen = Screen(columns, rows, ambiguous_wide=self.ambiguous_wide)
        editor = self._editor()
        # A layer that has its own message line (the filer) shows the messages there.
        owned = any(getattr(layer, "owns_message", False) for layer in self.layers)
        view.draw(screen, editor, view.Overlay() if owned else self.overlay)
        for layer in self.layers:
            layer.draw(screen, self.overlay)
        shape = _CURSOR_INSERT if editor.insert_mode else _CURSOR_OVERWRITE
        out = screen.render(self._shown)
        if shape != self._cursor_shape:
            out += shape
            self._cursor_shape = shape
        self.terminal.write(out)
        self._shown = screen

    # Keys

    def next_event(self) -> Event:
        while not self._events:
            timeout = ESC_DELAY if self._decoder.pending else None
            data = self.terminal.read(timeout)
            if self.terminal.take_resized():
                self.resize()
                self.draw()
            if data is None:
                self._events.extend(self._decoder.flush())
            elif data:
                self._events.extend(self._decoder.feed(data))
        return self._events.popleft()

    def read_press(self, mode: Mode) -> Press | None:
        """Read one key press, with the key after it when it is a prefix key."""
        event = self.next_event()
        if isinstance(event, Paste):
            return Typed(event.text)
        if isinstance(event, Char):
            return Typed(event.ch)
        if isinstance(event, Alt):
            esc = self._prefix_index((codes.ESC,), Mode.EDIT)
            if esc is None:
                return None
            return self._after_prefix(esc, Char(event.ch), mode)
        prefix = self._prefix_index(event.codes, mode)
        if prefix is None:
            number = self.keymap.command(event.codes, mode)
            return Command(number, key=event.codes) if number is not None else None
        self.overlay.prefix = codes.format_key(self.keymap.prefixes[prefix], self.keymap.prefixes)
        try:
            self.draw()
            following = self.next_event()
        finally:
            self.overlay.prefix = ""
        return self._after_prefix(prefix, following, mode)

    def _prefix_index(self, key_codes: tuple[int, ...], mode: Mode) -> int | None:
        for i, prefix in enumerate(self.keymap.prefixes):
            # ESC is a prefix key only while editing. Elsewhere it cancels.
            if prefix == codes.ESC and mode != Mode.EDIT:
                continue
            if prefix in key_codes:
                return i
        return None

    def _after_prefix(self, prefix: int, event: Event, mode: Mode) -> Press | None:
        if isinstance(event, Key):
            result = follow(prefix, event.codes, None)
        elif isinstance(event, Char | Alt):
            result = follow(prefix, None, event.ch)
        else:
            result = None
        if result is None:
            return None
        code, digit = result
        number = self.keymap.command((code,), mode)
        return Command(number, digit, (code,)) if number is not None else None
