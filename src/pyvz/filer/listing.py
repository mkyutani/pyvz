"""Reading a directory for the filer, and sorting and masking its entries."""

from __future__ import annotations

import fnmatch
import os
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

PARENT = ".."


@dataclass(frozen=True)
class Entry:
    name: str
    is_dir: bool  # a directory, or a symbolic link to one
    size: int
    mtime: float
    is_link: bool = False
    executable: bool = False

    @property
    def hidden(self) -> bool:
        return self.name.startswith(".") and self.name != PARENT

    @property
    def is_parent(self) -> bool:
        return self.name == PARENT


def entry(directory: Path, name: str) -> Entry | None:
    """The entry of a name in a directory, or None if it went away meanwhile."""
    path = directory / name
    try:
        info = os.lstat(path)
    except OSError:
        return None
    is_link = stat.S_ISLNK(info.st_mode)
    if is_link:
        try:
            info = os.stat(path)
        except OSError:
            pass  # a broken link: shown as the link itself
    is_dir = stat.S_ISDIR(info.st_mode)
    executable = not is_dir and stat.S_ISREG(info.st_mode) and bool(info.st_mode & 0o111)
    return Entry(name, is_dir, 0 if is_dir else info.st_size, info.st_mtime, is_link, executable)


def read_dir(directory: Path) -> list[Entry]:
    """The entries of a directory, unsorted. Raises OSError if it cannot be read."""
    found = []
    with os.scandir(directory) as it:
        for item in it:
            e = entry(directory, item.name)
            if e is not None:
                found.append(e)
    return found


class Order(Enum):
    NAME = "name"
    NEWEST = "newest"
    OLDEST = "oldest"
    LARGEST = "largest"
    SMALLEST = "smallest"


def _name_key(e: Entry) -> tuple[str, str]:
    return e.name.casefold(), e.name


def sort_entries(entries: list[Entry], order: Order) -> list[Entry]:
    """Sorted with the directories first. Sizes of directories do not count."""
    if order == Order.NAME:
        key = _name_key
        reverse = False
    elif order in (Order.NEWEST, Order.OLDEST):
        key = lambda e: e.mtime  # noqa: E731
        reverse = order == Order.NEWEST
    else:
        key = lambda e: e.size  # noqa: E731
        reverse = order == Order.LARGEST
    dirs = sorted((e for e in entries if e.is_dir), key=_name_key)
    files = sorted((e for e in entries if not e.is_dir), key=_name_key)
    # The sorts are stable, so ties stay in the order by name.
    if order in (Order.NEWEST, Order.OLDEST):
        dirs.sort(key=key, reverse=reverse)
    if order != Order.NAME:
        files.sort(key=key, reverse=reverse)
    return dirs + files


def shown(e: Entry, pattern: str, show_hidden: bool) -> bool:
    """Whether the mask lets an entry through. Directories are always shown."""
    if e.hidden and not show_hidden:
        return False
    if e.is_dir:
        return True
    return any(fnmatch.fnmatchcase(e.name, p) for p in pattern.split())


def size_text(size: int) -> str:
    """A size in at most 5 characters: 242, 1.2K, 34M, 120G."""
    if size < 1000:
        return str(size)
    value = float(size)
    for unit in "KMGTPE":
        value /= 1024
        if value < 9.95:
            return f"{value:.1f}{unit}"
        if value < 999.5:
            return f"{value:.0f}{unit}"
    return f"{value:.0f}Z"
