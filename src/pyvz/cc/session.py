"""Which Claude Code session pyvz was called from.

Claude Code runs $EDITOR as its child, but not always directly: through `uv run` the
parent is uv. So the session is the nearest ancestor process named "claude", which is
the name Claude Code gives its process. With no such ancestor, pyvz was not called
from Claude Code (git reads $VISUAL too), and there is no session.

A process is identified by its PID and its start time, so that a new process that
gets the PID of a finished one is not taken for it. Both come from /proc, so this
works on Linux (WSL included). Elsewhere the start time is unknown.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROC = Path("/proc")
NAME = "claude"


@dataclass(frozen=True)
class Session:
    pid: int
    start: int | None  # clock ticks after boot, None if unknown

    @property
    def key(self) -> str:
        return f"{self.pid}-{self.start if self.start is not None else 'x'}"


def _stat(pid: int, proc: Path) -> tuple[str, int, int] | None:
    """The name, parent PID and start time of a process, or None if it is gone."""
    try:
        data = (proc / str(pid) / "stat").read_text()
    except OSError:
        return None
    # The name is in parentheses and may itself hold spaces and parentheses.
    open_paren, close_paren = data.find("("), data.rfind(")")
    fields = data[close_paren + 2 :].split()
    try:
        return data[open_paren + 1 : close_paren], int(fields[1]), int(fields[19])
    except (IndexError, ValueError):
        return None


def current(proc: Path = PROC, parent: int | None = None) -> Session | None:
    """The Claude Code session that pyvz runs under, or None.

    Without /proc, the parent process stands for the session, with no start time.
    """
    parent = os.getppid() if parent is None else parent
    if not proc.is_dir():
        return Session(parent, None)
    pid = parent
    for _ in range(64):  # a loop in the table would be a bug, but do not hang on it
        info = _stat(pid, proc)
        if info is None:
            return None
        name, ppid, start = info
        if name == NAME:
            return Session(pid, start)
        if ppid <= 1:
            return None
        pid = ppid
    return None


def alive(session: Session, proc: Path = PROC) -> bool:
    if not proc.is_dir():
        try:
            os.kill(session.pid, 0)  # signal 0 only checks that the process exists
        except ProcessLookupError:
            return False
        except PermissionError:
            pass  # it exists, but belongs to another user
        return True
    info = _stat(session.pid, proc)
    if info is None:
        return False
    return session.start is None or info[2] == session.start
