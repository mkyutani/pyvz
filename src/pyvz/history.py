"""Histories of the input boxes: file names, copy destinations, search strings.

They are kept in the state directory, so they last from one run to the next, as VZ
kept them in its profile.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

from pyvz import paths
from pyvz.text.document import write_file

LIMIT = 50  # entries kept of each kind

FILE = "file"
COPY = "copy"
SEARCH = "search"
REPLACE = "replace"


class History:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._lists: dict[str, list[str]] | None = None

    def _all(self) -> dict[str, list[str]]:
        if self._lists is None:
            self._lists = {}
            path = self.path or paths.history_file()
            with contextlib.suppress(OSError, ValueError):
                data = json.loads(path.read_text("utf-8"))
                if isinstance(data, dict):
                    self._lists = {
                        kind: [s for s in items if isinstance(s, str)]
                        for kind, items in data.items()
                        if isinstance(items, list)
                    }
        return self._lists

    def get(self, kind: str) -> list[str]:
        """The entries of a kind, oldest first. The list is the history's own."""
        return self._all().setdefault(kind, [])

    def add(self, kind: str, text: str) -> None:
        if not text:
            return
        items = self.get(kind)
        if text in items:
            items.remove(text)
        items.append(text)
        del items[:-LIMIT]
        self._save()

    def _save(self) -> None:
        path = self.path or paths.history_file()
        with contextlib.suppress(OSError):
            paths.ensure_private_dir(path.parent)
            data = json.dumps(self._all(), ensure_ascii=False, indent=1)
            write_file(path, data.encode("utf-8", "surrogateescape") + b"\n", mode=0o600)
