"""The main loop: runs the editor and the filer on the terminal."""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

from pyvz import config as settings
from pyvz.cc import session
from pyvz.cc.prompt import PromptFile
from pyvz.cli import Launch, Mode
from pyvz.editor.editor import Editor
from pyvz.editor.layout import Layout
from pyvz.editor.search import Options
from pyvz.filer.filer import FilerSettings
from pyvz.keys.keymap import Keymap, command_number, default_keymap, read_def, rebind, vz_keymap
from pyvz.ui import theme
from pyvz.ui.loop import Loop
from pyvz.ui.tty import Terminal


def keymap_of(config: settings.Config) -> Keymap:
    """The key bindings: VZ.DEF's, or those of the DEF file of the settings, then the
    keys given one by one. What cannot be read goes to config.errors."""
    keymap = default_keymap()
    if config.keys_def:
        path = Path(os.path.expanduser(config.keys_def))
        try:
            keymap = vz_keymap(read_def(path))
        except (OSError, ValueError) as e:
            config.errors.append(f"keys.def: {path} を使えません（{e}）")
    for name, keys in config.keys.items():
        try:
            rebind(keymap, command_number(name), keys)
        except ValueError as e:
            config.errors.append(f"keys.{name}: {e}")
    return keymap


def configured(terminal: Terminal, config: settings.Config) -> tuple[Loop, Editor]:
    keymap = keymap_of(config)
    config.errors.extend(theme.configure(config.colors))
    loop = Loop(terminal, keymap)
    loop.ambiguous_wide = config.ambiguous_wide
    loop.esc_delay = config.esc_delay_ms / 1000
    loop.filer_settings = FilerSettings(config.places, config.masks, config.single)
    layout = Layout(tab_size=config.tab_size, ambiguous_wide=config.ambiguous_wide)
    editor = Editor(loop, layout)
    editor.auto_indent = config.auto_indent
    editor.function_keys = config.function_keys
    editor.search_options = Options.from_letters(config.search_options)
    loop.editor = editor
    if config.errors:
        more = f"（ほか {len(config.errors) - 1} 件）" if len(config.errors) > 1 else ""
        loop.message(f"設定: {config.errors[0]}{more}")
    return loop, editor


def run(launch: Launch) -> int:
    config = settings.load()
    try:
        terminal = Terminal()
        with terminal:
            loop, editor = configured(terminal, config)
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
        before = loop.overlay.message
        loop.message(prompt.message + (f" / {before}" if before else ""))
    try:
        return loop.run()
    except BaseException:
        # Whatever ends pyvz before the text went back (a bug, the terminal closing, a
        # signal), keep the text as the draft, so the next call shows it again.
        if editor.exit_code is None and editor.prompt is not None:
            with contextlib.suppress(Exception):
                prompt.hold(window)
        raise
