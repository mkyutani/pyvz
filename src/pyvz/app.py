"""The main loop: runs the editor and the filer on the terminal."""

from __future__ import annotations

import sys

from pyvz.cli import Launch, Mode
from pyvz.editor.editor import Editor
from pyvz.keys.keymap import default_keymap
from pyvz.ui.loop import Loop
from pyvz.ui.tty import Terminal


def run(launch: Launch) -> int:
    if launch.mode == Mode.FILER:
        print("pyvz: the filer is not implemented yet", file=sys.stderr)
        return 1
    try:
        terminal = Terminal()
        with terminal:
            loop = Loop(terminal, default_keymap())
            editor = Editor(loop)
            loop.editor = editor
            for path in launch.files:
                editor.open(path, cc=launch.mode == Mode.CC)
            editor.current = 0
            return loop.run()
    except OSError as e:
        print(f"pyvz: {e}", file=sys.stderr)
        return 1
    except EOFError:
        return 1
