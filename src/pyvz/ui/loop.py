"""The main loop: reading keys, running commands, and drawing the screen."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Protocol

from pyvz.editor.editor import Editor
from pyvz.keys import codes
from pyvz.keys.keymap import Keymap, Mode, follow
from pyvz.keys.terminal import Alt, Char, Decoder, Event, Key, Paste
from pyvz.ui import view
from pyvz.ui.screen import Screen

# How long to wait after ESC for the rest of an escape sequence, or for the character
# of Alt+character. Terminals send these at once, and people do not type that fast.
ESC_DELAY = 0.05

_CURSOR_INSERT = "\x1b[6 q"  # a bar
_CURSOR_OVERWRITE = "\x1b[2 q"  # a block


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


Press = Typed | Command


class Loop:
    """Runs the editor on a terminal. It is also the editor's console."""

    def __init__(self, terminal: Terminal, keymap: Keymap) -> None:
        self.terminal = terminal
        self.keymap = keymap
        self.editor: Editor | None = None
        self.overlay = view.Overlay()
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
        self.overlay.question = f"{question}か？ (Y/N) "
        try:
            while True:
                self.draw()
                event = self.next_event()
                if isinstance(event, Char):
                    answer = event.ch.upper()
                    if answer == "Y":
                        return True
                    if answer in ("N", " "):
                        return False
                elif isinstance(event, Key):
                    if codes.CR in event.codes:
                        return True
                    if codes.ESC in event.codes:
                        return None
        finally:
            self.overlay.question = ""

    # Running

    def run(self) -> int:
        editor = self._editor()
        self.resize()
        while editor.exit_code is None:
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

    def resize(self) -> None:
        self._size = self.terminal.size()
        columns, rows = self._size
        self._editor().resize(columns, view.text_rows(rows))
        self._shown = None

    def draw(self) -> None:
        columns, rows = self._size
        screen = Screen(columns, rows, ambiguous_wide=self.ambiguous_wide)
        editor = self._editor()
        view.draw(screen, editor, self.overlay)
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
            return Command(number) if number is not None else None
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
        return Command(number, digit) if number is not None else None
