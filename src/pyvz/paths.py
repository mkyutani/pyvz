"""Where pyvz keeps its files, following the XDG Base Directory Specification.

Settings that the user writes go under $XDG_CONFIG_HOME (~/.config), and state that
pyvz writes (filer position, histories, drafts on hold) under $XDG_STATE_HOME
(~/.local/state).
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "pyvz"


def _base(env: str, default: str) -> Path:
    value = os.environ.get(env, "")
    # The specification says a relative path in these variables is invalid and should
    # be ignored.
    if value and os.path.isabs(value):
        return Path(value)
    return Path.home() / default


def config_dir() -> Path:
    return _base("XDG_CONFIG_HOME", ".config") / APP_NAME


def state_dir() -> Path:
    return _base("XDG_STATE_HOME", ".local/state") / APP_NAME


def config_file() -> Path:
    return config_dir() / "config.toml"


def filer_state_file() -> Path:
    return state_dir() / "filer.json"


def history_file() -> Path:
    return state_dir() / "history.json"


def drafts_dir() -> Path:
    return state_dir() / "drafts"


def ensure_private_dir(path: Path) -> Path:
    """Create `path` if needed, make it accessible only to the user, and return it.

    Drafts hold prompt text, so their directory must not be readable by others.
    """
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def shown(path: Path, base: Path | None = None) -> str:
    """How `path` is written for the user to read.

    A path under `base` (the current directory by default) is made relative to it,
    and a path under the home directory starts with ~. Symbolic links are not
    resolved, so the path stays the way the user spelled it.
    """
    absolute = Path(os.path.abspath(path))
    base = Path(os.path.abspath(base if base is not None else Path.cwd()))
    if absolute.is_relative_to(base) and absolute != base:
        return str(absolute.relative_to(base))
    return tilde(absolute)


def tilde(path: Path) -> str:
    """The absolute path, with ~ for the home directory."""
    absolute = Path(os.path.abspath(path))
    home = Path.home()
    if absolute.is_relative_to(home):
        rest = absolute.relative_to(home)
        return "~" if rest == Path(".") else f"~/{rest}"
    return str(absolute)
