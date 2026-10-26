"""Command line parsing."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pyvz import __version__


class Mode(Enum):
    EDIT = "edit"  # pyvz FILE...
    FILER = "filer"  # pyvz [DIR]
    CC = "cc"  # pyvz -c FILE, called by Claude Code's external editor (Ctrl-G)


@dataclass(frozen=True)
class Launch:
    """What pyvz was asked to do on this run."""

    mode: Mode
    files: tuple[Path, ...] = ()
    # Directory to open the filer at. None means the current directory.
    directory: Path | None = None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyvz",
        description="A VZ Editor-style text editor and file manager.",
    )
    parser.add_argument(
        "-c",
        metavar="FILE",
        dest="cc_file",
        help="edit a prompt file for Claude Code (set EDITOR='pyvz -c')",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="files to edit, or one directory to open in the filer",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def parse_args(argv: list[str]) -> Launch:
    parser = _parser()
    args = parser.parse_args(argv)

    if args.cc_file is not None:
        if args.paths:
            parser.error("-c takes exactly one file")
        return Launch(Mode.CC, files=(Path(args.cc_file),))

    paths = [Path(p) for p in args.paths]
    if not paths:
        return Launch(Mode.FILER)
    if len(paths) == 1 and paths[0].is_dir():
        return Launch(Mode.FILER, directory=paths[0])
    for path in paths:
        if path.is_dir():
            parser.error(f"a directory cannot be given together with other paths: {path}")
    return Launch(Mode.EDIT, files=tuple(paths))


def main(argv: list[str] | None = None) -> int:
    launch = parse_args(sys.argv[1:] if argv is None else argv)

    from pyvz.app import run

    return run(launch)
