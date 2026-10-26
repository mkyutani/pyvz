"""A text document, and reading and writing its file."""

from __future__ import annotations

import contextlib
import os
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ENCODING = "utf-8"
# Bytes that are not valid UTF-8 are kept as lone surrogates and written back as they
# were, so opening and saving a file never changes the bytes pyvz did not edit.
ERRORS = "surrogateescape"
BOM = "﻿"


@dataclass(frozen=True)
class FileFormat:
    """How the lines of a document are written back to its file."""

    newline: str = "\n"
    final_newline: bool = True
    bom: bool = False


def decode(data: bytes) -> tuple[list[str], FileFormat]:
    """Split file contents into lines and find out how to write them back.

    The line ending is the one most of the file uses. In a file that mostly uses
    CR LF, a line ending with a bare LF is written back with CR LF. In a file that
    mostly uses LF, a CR before LF stays in the line as a character.
    """
    text = data.decode(ENCODING, ERRORS)
    bom = text.startswith(BOM)
    if bom:
        text = text[1:]
    crlf = text.count("\r\n")
    newline = "\r\n" if crlf > text.count("\n") - crlf else "\n"

    lines = text.split("\n")
    final_newline = len(lines) > 1 and lines[-1] == ""
    if final_newline:
        lines.pop()
    if newline == "\r\n":
        lines = [line.removesuffix("\r") for line in lines]
    return lines, FileFormat(newline, final_newline, bom)


def encode(lines: list[str], fmt: FileFormat) -> bytes:
    text = fmt.newline.join(lines)
    if fmt.final_newline:
        text += fmt.newline
    if fmt.bom:
        text = BOM + text
    return text.encode(ENCODING, ERRORS)


def _default_mode() -> int:
    umask = os.umask(0)
    os.umask(umask)
    return 0o666 & ~umask


def write_file(path: Path, data: bytes, *, mode: int | None = None) -> None:
    """Write `data` to `path` without leaving a half-written file behind.

    The data goes to a temporary file in the same directory, which then replaces the
    file. The permission bits of the file are kept, unless `mode` is given. A symbolic
    link is followed, so the file it points to is replaced and the link stays.
    """
    target = Path(os.path.realpath(path))
    if mode is None:
        try:
            mode = stat.S_IMODE(target.stat().st_mode)
        except FileNotFoundError:
            mode = _default_mode()
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


@dataclass
class Document:
    """The lines of a text and the file they belong to."""

    lines: list[str] = field(default_factory=lambda: [""])
    path: Path | None = None
    format: FileFormat = field(default_factory=FileFormat)
    modified: bool = False
    readonly: bool = False
    # The file did not exist when the document was opened.
    new_file: bool = False

    @classmethod
    def load(cls, path: Path, *, readonly: bool = False) -> Document:
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return cls(path=path, readonly=readonly, new_file=True)
        lines, fmt = decode(data)
        return cls(lines=lines, path=path, format=fmt, readonly=readonly)

    def save(self, path: Path | None = None) -> None:
        """Write the document to its file, or to `path`, which then becomes its file.

        Saving under another name renames the document, as VZ's save command does.
        """
        if path is not None:
            self.path = path
        if self.path is None:
            raise ValueError("the document has no file name")
        write_file(self.path, encode(self.lines, self.format))
        self.modified = False
        self.new_file = False
