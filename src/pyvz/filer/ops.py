"""File operations of the filer: copy, move, delete, rename, and making directories
and files.

VZ ran an external program (ZCOPY) to copy and move. pyvz does them itself, keeping
the modification times. Symbolic links are copied as links.
"""

from __future__ import annotations

import errno
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# Answers to "it exists already: overwrite?". None cancels the rest.
YES = "Y"
NO = "N"
ALL = "A"  # overwrite this and the rest
SKIP_ALL = "S"  # skip this and the rest that exist


@dataclass
class Result:
    done: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False


def _is_dir(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink()


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _error(name: str, e: OSError) -> str:
    return f"{name}: {e.strerror or e}"


def transfer(
    sources: list[Path],
    destination: Path,
    *,
    move: bool,
    ask: Callable[[Path], str | None],
    progress: Callable[[Path], None] | None = None,
) -> Result:
    """Copy or move files and directories into the directory `destination`.

    `ask` is asked about each file that exists in the destination, unless an earlier
    answer was ALL or SKIP_ALL. A directory onto a directory merges them.
    """
    result = Result()
    policy: str | None = None
    for source in sources:
        name = source.name
        target = destination / name
        if os.path.abspath(source) == os.path.abspath(target):
            result.errors.append(f"{name}: 同じ場所です")
            continue
        if _is_dir(source) and Path(os.path.abspath(destination)).is_relative_to(
            os.path.abspath(source)
        ):
            result.errors.append(f"{name}: 自分の中へは{'移動' if move else 'コピー'}できません")
            continue
        if _exists(target):
            if _is_dir(source) != _is_dir(target):
                result.errors.append(f"{name}: 種類の違うものがあるので上書きできません")
                continue
            answer = policy or ask(target)
            if answer is None:
                result.cancelled = True
                break
            if answer in (ALL, SKIP_ALL):
                policy = answer
            if answer in (NO, SKIP_ALL):
                result.skipped.append(name)
                continue
        if progress is not None:
            progress(source)
        try:
            if move:
                _move(source, target)
            else:
                _copy(source, target)
        except OSError as e:
            result.errors.append(_error(name, e))
        else:
            result.done.append(name)
    return result


def _copy(source: Path, target: Path) -> None:
    if _is_dir(source):
        shutil.copytree(source, target, symlinks=True, dirs_exist_ok=True)
        return
    if target.is_symlink():
        target.unlink()  # replace the link, not the file it points to
    shutil.copy2(source, target, follow_symlinks=False)


def _move(source: Path, target: Path) -> None:
    if _is_dir(source) and _is_dir(target):
        _copy(source, target)  # merge, then remove what was moved
        shutil.rmtree(source)
        return
    try:
        os.replace(source, target)
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
        _copy(source, target)  # another file system
        remove(source)


def remove(path: Path) -> None:
    """Delete a file, a link, or a directory with everything in it."""
    if _is_dir(path):
        shutil.rmtree(path)
    else:
        path.unlink()


def delete(paths: list[Path]) -> Result:
    result = Result()
    for path in paths:
        try:
            remove(path)
        except OSError as e:
            result.errors.append(_error(path.name, e))
        else:
            result.done.append(path.name)
    return result


def has_contents(path: Path) -> bool:
    """Whether a directory (not a link to one) holds anything."""
    if not _is_dir(path):
        return False
    try:
        with os.scandir(path) as it:
            return next(it, None) is not None
    except OSError:
        return True


def check_name(name: str) -> str | None:
    """Why a new name cannot be used in a directory, or None."""
    if not name or name in (".", ".."):
        return "名前がありません"
    if "/" in name or "\0" in name:
        return "名前に / は使えません"
    return None


def rename(directory: Path, old: str, new: str) -> None:
    """Raises OSError, FileExistsError if the new name is taken."""
    target = directory / new
    if _exists(target):
        raise FileExistsError(errno.EEXIST, "すでに存在します", str(target))
    os.rename(directory / old, target)


def make_dir(directory: Path, name: str) -> bool:
    """Make a directory. False if it exists already."""
    try:
        (directory / name).mkdir()
    except FileExistsError:
        return False
    return True


def make_file(directory: Path, name: str) -> bool:
    """Make an empty file. False if it exists already."""
    try:
        with open(directory / name, "x"):
            pass
    except FileExistsError:
        return False
    return True
