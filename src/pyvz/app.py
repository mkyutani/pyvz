"""The main loop: runs the editor and the filer on the terminal."""

from __future__ import annotations

import contextlib
import sys

from pyvz.cc import session
from pyvz.cc.prompt import PromptFile
from pyvz.cli import Launch, Mode
from pyvz.editor.editor import Editor
from pyvz.keys.keymap import default_keymap
from pyvz.ui.loop import Loop
from pyvz.ui.tty import Terminal


def run(launch: Launch) -> int:
    try:
        terminal = Terminal()
        with terminal:
            loop = Loop(terminal, default_keymap())
            editor = Editor(loop)
            loop.editor = editor
            if launch.mode == Mode.CC:
                return _run_prompt(loop, editor, PromptFile(launch.files[0], session.current()))
            if launch.mode == Mode.FILER:
                editor.keep_open = True
                return loop.run(launch.directory)
            for path in launch.files:
                editor.open(path)
            editor.show(0)
            return loop.run()
    except OSError as e:
        print(f"pyvz: {e}", file=sys.stderr)
        return 1
    except EOFError:
        return 1


def _run_prompt(loop: Loop, editor: Editor, prompt: PromptFile) -> int:
    window = editor.add(prompt.open(editor.layout))
    if prompt.session is not None:
        editor.prompt = prompt
    if prompt.message:
        loop.message(prompt.message)
    try:
        return loop.run()
    except BaseException:
        # Whatever ends pyvz before the text went back (a bug, the terminal closing, a
        # signal), keep the text as the draft, so the next call shows it again.
        if editor.exit_code is None and editor.prompt is not None:
            with contextlib.suppress(Exception):
                prompt.hold(window)
        raise
