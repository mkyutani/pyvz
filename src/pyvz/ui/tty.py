"""The terminal: raw input, the alternate screen, and notice of size changes.

pyvz talks to /dev/tty, so it works the same when its standard input or output is
redirected. Raw mode passes every key through, ^S ^Q ^C ^Z ^V included, which VZ
uses as editing keys.
"""

from __future__ import annotations

import contextlib
import os
import select
import signal
import termios
import tty

# Alternate screen, bracketed paste.
_ENTER = "\x1b[?1049h\x1b[?2004h"
# Bracketed paste off, the cursor shape back to the terminal's, the main screen.
_LEAVE = "\x1b[?2004l\x1b[0 q\x1b[?25h\x1b[0m\x1b[?1049l"


class Terminal:
    def __init__(self, path: str = "/dev/tty") -> None:
        self.path = path
        self.fd = -1
        self._saved: list | None = None
        self._wake_r = self._wake_w = -1
        self._resized = False
        self._old_handlers: dict[int, object] = {}
        self._old_wakeup = -1

    def __enter__(self) -> Terminal:
        self.fd = os.open(self.path, os.O_RDWR | os.O_NOCTTY)
        try:
            self._saved = termios.tcgetattr(self.fd)
            tty.setraw(self.fd)
            self._wake_r, self._wake_w = os.pipe()
            os.set_blocking(self._wake_r, False)
            os.set_blocking(self._wake_w, False)
            self._old_wakeup = signal.set_wakeup_fd(self._wake_w, warn_on_full_buffer=False)
            self._handle(signal.SIGWINCH, self._on_resize)
            self._handle(signal.SIGTERM, self._on_terminate)
            self._handle(signal.SIGHUP, self._on_terminate)
            self.write(_ENTER)
        except BaseException:
            self._restore()
            raise
        return self

    def __exit__(self, *exc: object) -> None:
        with contextlib.suppress(OSError):
            self.write(_LEAVE)
        self._restore()

    def _handle(self, signum: int, handler) -> None:
        self._old_handlers[signum] = signal.signal(signum, handler)

    def _restore(self) -> None:
        for signum, handler in self._old_handlers.items():
            signal.signal(signum, handler)
        self._old_handlers.clear()
        if self._wake_w >= 0:
            signal.set_wakeup_fd(self._old_wakeup)
            os.close(self._wake_r)
            os.close(self._wake_w)
            self._wake_r = self._wake_w = -1
        if self.fd >= 0:
            if self._saved is not None:
                with contextlib.suppress(termios.error):
                    termios.tcsetattr(self.fd, termios.TCSADRAIN, self._saved)
            os.close(self.fd)
            self.fd = -1

    def _on_resize(self, signum: int, frame: object) -> None:
        self._resized = True

    def _on_terminate(self, signum: int, frame: object) -> None:
        raise SystemExit(128 + signum)

    def size(self) -> tuple[int, int]:
        """Columns and rows."""
        size = os.get_terminal_size(self.fd)
        return size.columns, size.lines

    def take_resized(self) -> bool:
        """Whether the size changed since the last call."""
        resized, self._resized = self._resized, False
        return resized

    def read(self, timeout: float | None) -> bytes | None:
        """Bytes typed, b"" if a signal came first, or None after `timeout` seconds.

        Raises EOFError when the terminal is gone.
        """
        ready, _, _ = select.select([self.fd, self._wake_r], [], [], timeout)
        if not ready:
            return None
        if self._wake_r in ready:
            with contextlib.suppress(BlockingIOError):
                while os.read(self._wake_r, 64):
                    pass
        if self.fd not in ready:
            return b""
        data = os.read(self.fd, 4096)
        if not data:
            raise EOFError("the terminal was closed")
        return data

    def write(self, text: str) -> None:
        data = text.encode("utf-8", "replace")
        while data:
            written = os.write(self.fd, data)
            data = data[written:]
