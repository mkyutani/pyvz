"""The filer: two windows, the directories of the Dir menu, and the state kept between
runs.

The right window is the one shown alone (on the right half of the terminal, so the
text that called the filer stays in sight on the left). With two windows, the second
one is on the left.
"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from pyvz import paths
from pyvz.filer.listing import Order
from pyvz.filer.pane import Pane
from pyvz.text.document import write_file

VERSION = 1
LEFT, RIGHT = 0, 1

# The Dir menu: VZ's drive menu, made into a menu of directories. The Windows folders
# are the links that the dotfiles put in the home directory.
PLACES = ["~/windownloads", "~/windocuments", "~/windropbox", "~"]


class Filer:
    def __init__(self, origin: Path, start: Path | None = None) -> None:
        # Where Claude Code (or pyvz) was started. Inserted paths are relative to it.
        self.origin = Path(os.path.abspath(origin))
        first = Path(os.path.abspath(start)) if start is not None else self.origin
        self.panes = [Pane(first), Pane(first)]
        self.active = RIGHT
        self.dual = False
        self.order = Order.NAME
        self.back: Path | None = None  # where RetCD came from

    @property
    def pane(self) -> Pane:
        return self.panes[self.active]

    @property
    def other(self) -> Pane:
        return self.panes[1 - self.active]

    def visible(self) -> list[Pane]:
        return self.panes if self.dual else [self.panes[RIGHT]]

    def load(self) -> list[str]:
        """Read the directories of the windows. Returns the errors."""
        errors = []
        for pane in self.panes:
            pane.order = self.order
            try:
                pane.load()
            except OSError as e:
                errors.append(f"{paths.shown(pane.path)}: {e.strerror or e}")
                with contextlib.suppress(OSError):
                    pane.go(self.origin)
        return errors

    def switch(self) -> None:
        if self.dual:
            self.active = 1 - self.active

    def toggle_dual(self) -> None:
        if self.dual:
            # The active window becomes the one shown alone.
            if self.active == LEFT:
                self.panes.reverse()
            self.active = RIGHT
            self.dual = False
        else:
            self.dual = True

    def show_other(self, path: Path) -> None:
        """Show a directory in the other window, making two windows if needed.

        Raises OSError if it cannot be read.
        """
        if not self.dual:
            self.dual = True
            self.active = RIGHT
        self.other.go(path)

    def places(self) -> list[tuple[str, Path]]:
        """The Dir menu: (key, directory), without those that do not exist.

        The keys are the positions, so they stay the same on every machine.
        """
        found = []
        for i, place in enumerate([*PLACES, str(self.origin)], start=1):
            path = Path(os.path.expanduser(place))
            if path.is_dir():
                found.append((str(i), path))
        return found

    def ret_cd(self) -> None:
        """Go to the start directory, or back to where RetCD came from."""
        pane = self.pane
        if pane.path != self.origin:
            self.back = pane.path
            pane.go(self.origin)
        elif self.back is not None:
            back, self.back = self.back, None
            pane.go(back)

    def set_order(self, order: Order) -> None:
        self.order = order
        for pane in self.panes:
            pane.order = order
            with contextlib.suppress(OSError):
                pane.load()

    # State

    def save_state(self, path: Path | None = None) -> None:
        data = {
            "version": VERSION,
            "dual": self.dual,
            "active": self.active,
            "order": self.order.value,
            "panes": [
                {
                    "path": str(pane.path),
                    "focus": pane.current.name if pane.current else None,
                    "pattern": pane.pattern,
                    "show_hidden": pane.show_hidden,
                }
                for pane in self.panes
            ],
        }
        path = path or paths.filer_state_file()
        with contextlib.suppress(OSError):
            paths.ensure_private_dir(path.parent)
            text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
            write_file(path, text.encode("utf-8", "surrogateescape"), mode=0o600)

    def restore_state(self, path: Path | None = None) -> None:
        """Take the windows of the last run, where their directories still exist."""
        try:
            data = json.loads((path or paths.filer_state_file()).read_text("utf-8"))
            if data.get("version") != VERSION:
                return
            self.dual = bool(data["dual"])
            self.active = RIGHT if not self.dual else int(data["active"]) % 2
            self.order = Order(data["order"])
            for pane, saved in zip(self.panes, data["panes"], strict=True):
                directory = Path(saved["path"])
                if directory.is_dir():
                    pane.path = directory
                    pane.pattern = str(saved.get("pattern") or "*")
                    pane.show_hidden = bool(saved.get("show_hidden", True))
                    pane.entries = []
                    focus = saved.get("focus")
                    with contextlib.suppress(OSError):
                        pane.order = self.order
                        pane.load(focus if isinstance(focus, str) else None)
        except (OSError, ValueError, KeyError, TypeError):
            return


@dataclass(frozen=True)
class Open:
    """What the filer ended with: files to open in the editor."""

    paths: list[Path]
    readonly: bool = False


@dataclass(frozen=True)
class Insert:
    """What the filer ended with: paths to type into the text that called it."""

    text: str


def insertion(paths_: list[Path], origin: Path) -> str:
    """Paths as typed into a prompt: relative to `origin` when under it, else with ~.

    Directories end with /, and a path with spaces is put in double quotes.
    """
    words = []
    for path in paths_:
        word = paths.shown(path, origin)
        if path.is_dir() and not word.endswith("/"):
            word += "/"
        if any(ch.isspace() for ch in word):
            word = f'"{word}"'
        words.append(word)
    return " ".join(words)
