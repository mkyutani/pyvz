"""The main loop: runs the editor and the filer on the terminal."""

from __future__ import annotations

import sys

from pyvz.cli import Launch


def run(launch: Launch) -> int:
    print(f"pyvz: not implemented yet ({launch.mode.value})", file=sys.stderr)
    return 1
