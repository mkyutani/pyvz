"""Drafts on hold: the prompt text kept between two calls from Claude Code.

There is a draft file for each Claude Code session, named after the session. The
files hold prompt text, so the directory is made private to the user and the files
are written with mode 0600.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pyvz import paths
from pyvz.cc.session import Session, alive
from pyvz.text.document import write_file

VERSION = 1


@dataclass
class Draft:
    text: str  # the text below the prologue that Claude Code writes, if any
    line: int = 0  # the cursor, with lines counted from the start of `text`
    index: int = 0
    # The text of the prompt file, below the prologue, when the draft was put on hold.
    # That is what Claude Code's input box held then.
    original: str = ""
    cwd: str = ""  # the current directory of Claude Code
    pid: int = 0
    start: int | None = None
    updated: float = field(default_factory=time.time)

    @property
    def session(self) -> Session:
        return Session(self.pid, self.start)


def draft_path(session: Session, directory: Path | None = None) -> Path:
    return (directory or paths.drafts_dir()) / f"{session.key}.json"


def save(draft: Draft, directory: Path | None = None) -> Path:
    directory = paths.ensure_private_dir(directory or paths.drafts_dir())
    path = draft_path(draft.session, directory)
    data = {"version": VERSION, **asdict(draft)}
    # ASCII only: lone surrogates (bytes that were not UTF-8) survive as \u escapes.
    write_file(path, json.dumps(data, indent=1).encode("ascii") + b"\n", mode=0o600)
    return path


def load(path: Path) -> Draft | None:
    """Read a draft file. None if it cannot be read or is not a draft."""
    try:
        data = json.loads(path.read_text("ascii"))
        if data.pop("version") != VERSION:
            return None
        return Draft(**data)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def remove(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


def find(session: Session, directory: Path | None = None) -> tuple[Path, Draft] | None:
    path = draft_path(session, directory)
    draft = load(path)
    return (path, draft) if draft is not None else None


def left_behind(
    cwd: str,
    directory: Path | None = None,
    is_alive: Callable[[Session], bool] = alive,
) -> list[tuple[Path, Draft]]:
    """Drafts of sessions that have ended, best first.

    Drafts from the same directory come first, newest first within each group.
    """
    directory = directory or paths.drafts_dir()
    found = []
    for path in directory.glob("*.json"):
        draft = load(path)
        if draft is not None and not is_alive(draft.session):
            found.append((path, draft))
    found.sort(key=lambda item: (item[1].cwd == cwd, item[1].updated), reverse=True)
    return found
