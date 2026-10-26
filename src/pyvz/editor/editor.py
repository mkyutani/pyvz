"""The editor: the texts being edited, and the commands that keys run on them."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from pyvz import history, paths
from pyvz.editor.layout import Layout
from pyvz.editor.stack import TextStack
from pyvz.editor.window import CHAR, LINE, Window
from pyvz.filer.filer import Insert, Open
from pyvz.keys.commands import Cmd
from pyvz.text.document import Document, encode, write_file


class Console(Protocol):
    """What the editor needs from the screen: messages, questions, input and menus."""

    def message(self, text: str) -> None: ...

    def ask(self, question: str) -> bool | None:
        """Ask "question か？ (Y/N)". True for yes, False for no, None if cancelled."""
        ...

    def gets(self, title: str, text: str = "", *, kind: str = "") -> str | None:
        """Read a line in an input box, with the history named `kind`."""
        ...

    def menu(self, items: list[tuple[str, str]], *, title: str = "") -> int | str | None:
        """Show (key, label) items. The index of the chosen one, or None."""
        ...

    def filer(
        self, start: Path | None = None, *, pattern: str = "*", readonly: bool = False
    ) -> Open | Insert | None:
        """Run the filer, at `start` or where it was last time."""
        ...


class Prompt(Protocol):
    """The prompt file of Claude Code, which can be put on hold as a draft."""

    def hold(self, window: Window) -> None:
        """Keep the text as the draft, leaving the prompt file as it was."""
        ...

    def passed(self, window: Window) -> None:
        """The text was saved to the prompt file, so the draft is done."""
        ...


# Commands that change the text, refused for a read-only text.
_EDITS = {
    Cmd.CUT,
    Cmd.PASTE,
    Cmd.LOAD,
    Cmd.RETURN,
    Cmd.BACKSPACE,
    Cmd.DELETE,
    Cmd.DELETE_WORD_BACK,
    Cmd.DELETE_WORD,
    Cmd.DELETE_TO_LINE_TOP,
    Cmd.DELETE_TO_LINE_END,
    Cmd.TAB,
}

# Moving up and down makes a block of characters a block of lines (VZ: CMF_VMOVE),
# and the line editing commands make it a block of characters again.
_VERTICAL = {
    Cmd.UP,
    Cmd.DOWN,
    *range(Cmd.ROLL_UP, Cmd.LAST_POSITION + 1),
    Cmd.JUMP_LINE,
}
_ALONG_LINE = {*range(Cmd.LEFT, Cmd.REDRAW_LINE + 1), Cmd.SCREEN_LINE_LEFT, Cmd.SCREEN_LINE_RIGHT}


class Editor:
    def __init__(self, console: Console, layout: Layout | None = None) -> None:
        self.console = console
        self.layout = layout or Layout()
        self.height = 1
        self.windows: list[Window] = []
        self.current = 0
        self._previous = 0  # the text shown before, for switching back
        self.insert_mode = True
        # Set when the editor is to end, to the exit status of the program.
        self.exit_code: int | None = None
        # Started from the filer: closing the last text goes back to it (VZ).
        self.keep_open = False
        self.prompt: Prompt | None = None
        self.stack = TextStack()
        self._last: tuple[int, int | None] | None = None
        self._commands: dict[int, Callable[[int | None], object]] = {
            Cmd.REPEAT: self._repeat,
            Cmd.ESCAPE: lambda _: self.escape(),
            Cmd.RETURN: lambda _: self.window.newline(overwrite=not self.insert_mode),
            Cmd.UP: lambda _: self.window.up(),
            Cmd.DOWN: lambda _: self.window.down(),
            Cmd.LEFT: lambda _: self.window.left(),
            Cmd.RIGHT: lambda _: self.window.right(),
            Cmd.WORD_LEFT: lambda _: self.window.word_left(),
            Cmd.WORD_RIGHT: lambda _: self.window.word_right(),
            Cmd.LINE_TOP: lambda _: self.window.line_top(),
            Cmd.LINE_END: lambda _: self.window.line_end(),
            Cmd.INSERT_MODE: lambda _: self._toggle_insert(),
            Cmd.BACKSPACE: lambda _: self.window.backspace(),
            Cmd.DELETE: lambda _: self.window.delete(),
            Cmd.DELETE_WORD_BACK: lambda _: self.window.delete_word_back(),
            Cmd.DELETE_WORD: lambda _: self.window.delete_word(),
            Cmd.DELETE_TO_LINE_TOP: lambda _: self.window.delete_to_line_top(),
            Cmd.DELETE_TO_LINE_END: lambda _: self.window.delete_to_line_end(),
            Cmd.TAB: lambda _: self.window.tab(overwrite=not self.insert_mode),
            Cmd.ROLL_UP: lambda _: self.window.scroll(-1),
            Cmd.ROLL_DOWN: lambda _: self.window.scroll(1),
            Cmd.ROLL_UP2: lambda _: self.window.scroll(-2),
            Cmd.ROLL_DOWN2: lambda _: self.window.scroll(2),
            Cmd.PAGE_UP: lambda _: self.window.scroll(-self._page()),
            Cmd.PAGE_DOWN: lambda _: self.window.scroll(self._page()),
            # VZ scrolls smoothly until a key is pressed. pyvz scrolls a row.
            Cmd.SMOOTH_UP: lambda _: self.window.scroll(-1),
            Cmd.SMOOTH_DOWN: lambda _: self.window.scroll(1),
            Cmd.WINDOW_TOP: lambda _: self.window.window_top(),
            Cmd.WINDOW_END: lambda _: self.window.window_end(),
            Cmd.TEXT_TOP: lambda _: self.window.text_top(),
            Cmd.TEXT_END: lambda _: self.window.text_end(),
            Cmd.BLOCK: lambda _: self.toggle_block(),
            Cmd.CUT: lambda _: self.cut(delete=True),
            Cmd.PASTE: lambda _: self.paste(pop=True),
            Cmd.STORE: lambda _: self.cut(delete=False),
            Cmd.LOAD: lambda _: self.paste(pop=False),
            Cmd.CLEAR_STACK: lambda _: self.clear_stack(),
            Cmd.BLOCK_JUMP: lambda _: self.window.jump_block(),
            Cmd.READ_ONLY: lambda _: self._toggle_read_only(),
            Cmd.OPEN: lambda _: self.open_command(),
            Cmd.OPEN_READ_ONLY: lambda _: self.open_command(readonly=True),
            Cmd.CLOSE_OPEN: lambda _: self.close_open(),
            Cmd.SWITCH_WINDOW: lambda _: self.switch_back(),
            Cmd.SWITCH_TEXT: lambda _: self.choose_text(),
            Cmd.NEW_FILE: lambda _: self.new_file(),
            Cmd.CLOSE: lambda _: self.close(),
            Cmd.SAVE: lambda _: self.save_as(),
            Cmd.RENAME: lambda _: self.rename(),
            Cmd.QUIT: lambda _: self.quit(),
            Cmd.COMMAND_LINE: lambda _: self.hold(),
            Cmd.SCREEN_LINE_LEFT: lambda _: self.window.row_left(),
            Cmd.SCREEN_LINE_RIGHT: lambda _: self.window.row_right(),
        }

    @property
    def window(self) -> Window:
        return self.windows[self.current]

    def open(self, path: Path, *, cc: bool = False, readonly: bool = False) -> Window:
        doc = Document.load(path, readonly=readonly)
        window = self.add(Window(doc, self.layout, cc=cc))
        if doc.new_file and not cc:
            self.console.message("新規ファイルです")
        return window

    def add(self, window: Window) -> Window:
        """Show a window made elsewhere, such as the prompt file of Claude Code."""
        window.layout = self.layout
        window.height = self.height
        self.windows.append(window)
        self.show(len(self.windows) - 1)
        return window

    def show(self, index: int) -> None:
        if index != self.current:
            self._previous = self.current
        self.current = index

    def find(self, path: Path) -> int | None:
        """The index of the text of a file, if it is open."""
        target = os.path.abspath(path)
        for i, window in enumerate(self.windows):
            if window.doc.path is not None and os.path.abspath(window.doc.path) == target:
                return i
        return None

    def resize(self, width: int, height: int) -> None:
        """Set the size of the text area of the window."""
        self.layout = replace(self.layout, width=width)
        self.height = height
        for window in self.windows:
            window.layout = self.layout
            window.height = height
            window.keep_visible()

    def name(self, window: Window) -> str:
        path = window.doc.path
        if path is None:
            return "(無題)"
        # Claude Code's prompt files are in its temporary directory: the name is enough.
        return path.name if window.cc else paths.shown(path)

    # Keys

    def has(self, command: int) -> bool:
        return command in self._commands

    def run(self, command: int, digit: int | None = None) -> bool:
        """Run a command. Returns False if pyvz does not have the command yet."""
        action = self._commands.get(command)
        if action is None:
            return False
        if command != Cmd.REPEAT:
            self._last = (command, digit)
        if command in _EDITS and not self._writable():
            return True
        window = self.window
        if window.block == CHAR and command in _VERTICAL:
            window.block = LINE
        elif window.block == LINE and command in _ALONG_LINE:
            window.block = CHAR
        action(digit)
        if self.exit_code is None and self.windows:
            self.window.keep_visible()
        return True

    def type(self, text: str) -> None:
        """Type or paste text at the cursor."""
        if not self._writable():
            return
        window = self.window
        if window.block == LINE:
            window.block = CHAR
        if self.insert_mode or "\n" in text:
            window.insert(text)
        else:
            for ch in text:
                window.overwrite(ch)
        window.keep_visible()

    def _writable(self) -> bool:
        if self.window.doc.readonly:
            self.console.message(f"{self.name(self.window)} はリードオンリーです")
            return False
        return True

    def _repeat(self, _digit: int | None) -> None:
        if self._last is not None:
            self.run(*self._last)

    def _page(self) -> int:
        return max(self.height - 1, 1)

    def _toggle_insert(self) -> None:
        self.insert_mode = not self.insert_mode

    def _toggle_read_only(self) -> None:
        doc = self.window.doc
        doc.readonly = not doc.readonly

    # Blocks and the text stack

    def toggle_block(self) -> None:
        window = self.window
        if window.block is None:
            window.start_block()
        else:
            window.block = None

    def cut(self, *, delete: bool) -> None:
        """^Y (delete) and ^KK (store): push the block, or the cursor line, onto the
        text stack."""
        window = self.window
        taken = window.take_block(delete=delete)
        if taken is None:
            text = window.take_line(delete=delete)
            taken = (LINE, text)
        if taken[1]:
            self.stack.push(*taken)

    def paste(self, *, pop: bool) -> None:
        """^J (pop) and ^KC (copy without popping): insert the top of the text stack."""
        item = self.stack.pop() if pop else self.stack.top()
        if item is None:
            self.console.message("テキストスタックは空です")
            return
        window = self.window
        window.block = None
        window.put(*item)

    def clear_stack(self) -> None:
        if self.console.ask("テキストスタックを消去します"):
            self.stack.clear()

    # Files

    def save(self, window: Window, path: Path | None = None) -> bool:
        """Save the text, under `path` if given, which renames it (VZ)."""
        doc = window.doc
        name = self.name(window)
        if doc.readonly:
            self.console.message(f"{name} はリードオンリーです")
            return False
        try:
            doc.save(path)
        except ValueError:
            self.console.message("ファイル名がありません")
            return False
        except OSError as e:
            self._cannot_write(path or doc.path, e)
            return False
        return True

    def _cannot_write(self, path: Path | None, error: OSError) -> None:
        name = paths.shown(path) if path is not None else "(無題)"
        self.console.message(f"{name} は出力できません（{error.strerror or error}）")

    def save_as(self) -> None:
        """[ESC]S: save under the name in 【出力ファイル】, the current name to start with.

        For the prompt file of Claude Code, another name writes a copy, and the text
        stays the prompt.
        """
        window = self.window
        doc = window.doc
        if window.block_range() is not None:
            self._save_block(window)
            return
        if doc.readonly:
            self.console.message(f"{self.name(window)} はリードオンリーです")
            return
        current = self.name(window) if doc.path is not None else ""
        name = self.console.gets("【出力ファイル】", current, kind=history.FILE)
        if not name:
            return
        path = Path(os.path.expanduser(name))
        same = doc.path is not None and os.path.abspath(path) == os.path.abspath(doc.path)
        if not same and path.exists():
            if not self.console.ask(f"{paths.shown(path)} はすでに存在します. 出力します"):
                return
        if window.cc and not same:
            self._write_copy(path, doc.lines, doc)
            return
        self.save(window, None if same else path)

    def _save_block(self, window: Window) -> None:
        """[ESC]S with a block: write the block to a file (VZ). The text stays."""
        name = self.console.gets("【出力ファイル】", kind=history.FILE)
        if not name:
            return
        path = Path(os.path.expanduser(name))
        if path.exists() and not self.console.ask(
            f"{paths.shown(path)} はすでに存在します. 出力します"
        ):
            return
        taken = window.take_block(delete=False)
        if taken is not None:
            self._write_copy(path, taken[1].split("\n"), window.doc)

    def _write_copy(self, path: Path, lines: list[str], doc: Document) -> None:
        """Write lines to a file that is not the text's own, in the text's format."""
        fmt = replace(doc.format, final_newline=False)
        try:
            write_file(path, encode(lines, fmt))
        except OSError as e:
            self._cannot_write(path, e)
            return
        self.console.message(f"{paths.shown(path)} に出力しました")

    def new_file(self) -> None:
        """[ESC]N: a new text, with the name given in 【新規ファイル】."""
        name = self.console.gets("【新規ファイル】", kind=history.FILE)
        if not name:
            return
        self.open_file(Path(os.path.expanduser(name)))

    def open_file(self, path: Path, *, readonly: bool = False) -> None:
        """Show the text of a file, opening it unless it is open already."""
        found = self.find(path)
        if found is not None:
            self.show(found)
            self.console.message(f"{self.name(self.window)} はオープンされています")
            return
        if path.is_dir():
            self.console.message(f"{paths.shown(path)} はディレクトリです")
            return
        try:
            self.open(path, readonly=readonly)
        except OSError as e:
            self.console.message(f"{paths.shown(path)} は入力できません（{e.strerror or e}）")

    def open_command(self, *, readonly: bool = False) -> None:
        """[ESC]O, [ESC]R: open the file named in 【入力ファイル】.

        Enter alone opens the filer, as does a directory or a pattern such as *.md.
        """
        name = self.console.gets("【入力ファイル】", kind=history.FILE)
        if name is not None:
            self.open_name(name, readonly=readonly)

    def open_name(self, name: str, *, readonly: bool = False) -> None:
        name = name.strip()
        if not name:
            self.take(self.console.filer(readonly=readonly))
            return
        path = Path(os.path.expanduser(name))
        if any(ch in path.name for ch in "*?["):
            self.take(self.console.filer(path.parent, pattern=path.name, readonly=readonly))
        elif path.is_dir():
            self.take(self.console.filer(path, readonly=readonly))
        else:
            self.open_file(path, readonly=readonly)

    def take(self, result: Open | Insert | None) -> None:
        """Do what the filer ended with."""
        if isinstance(result, Open):
            for path in result.paths:
                self.open_file(path, readonly=result.readonly)
        elif isinstance(result, Insert):
            if self.windows:
                self.type(result.text)
            else:
                self.console.message("挿入先のテキストがありません")

    def close_open(self) -> None:
        """[ESC]L: open another file in place of this text."""
        old = self.window
        if old.cc:
            self.console.message("変更できません")
            return
        self.open_command()
        if old in self.windows and self.window is not old:
            self._close_text(old)

    def rename(self) -> None:
        """[ESC]P: change the file name of the text. It is written on the next save."""
        window = self.window
        if window.cc:
            self.console.message("変更できません")
            return
        current = self.name(window) if window.doc.path is not None else ""
        name = self.console.gets("【ファイル名】", current, kind=history.FILE)
        if not name or name == current:
            return
        window.doc.path = Path(os.path.expanduser(name))
        window.doc.modified = True

    def switch_back(self) -> None:
        """Show the text shown before. VZ switches split windows with this key."""
        if len(self.windows) > 1:
            self.show(self._previous if self._previous < len(self.windows) else 0)

    def choose_text(self) -> None:
        """@T: choose the text to show from 【編集テキスト】."""
        keys = "123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        items = []
        for i, window in enumerate(self.windows[: len(keys)]):
            marks = (" (CC)" if window.cc else "") + (" *" if window.doc.modified else "")
            items.append((keys[i], self.name(window) + marks))
        chosen = self.console.menu(items, title="【編集テキスト】")
        if isinstance(chosen, int):
            self.show(chosen)

    def close(self) -> None:
        """Close the text, asking whether to save it if it was changed.

        The prompt file of Claude Code is saved without asking: closing it is how the
        text goes back to Claude Code, and the editor ends with it.
        """
        window = self.window
        if window.cc:
            if self._save_others() and self._pass(window):
                self.exit_code = 0
            return
        self._close_text(window)

    def _close_text(self, window: Window) -> bool:
        """Close a text, asking whether to save it if it was changed."""
        if window.doc.modified:
            answer = self.console.ask(f"{self.name(window)} を出力します")
            if answer is None or (answer and not self.save(window)):
                return False
        self._remove(window)
        return True

    def _remove(self, window: Window) -> None:
        index = self.windows.index(window)
        del self.windows[index]
        if not self.windows:
            if not self.keep_open:
                self.exit_code = 0
            return
        # Back to the text shown before, as when a peeked file is closed.
        before = self._previous if self._previous != index else self.current
        self.current = min(before - (before > index), len(self.windows) - 1)
        self._previous = self.current

    def _changed_files(self) -> list[Window]:
        """Changed texts other than the prompt file of Claude Code."""
        return [w for w in self.windows if w.doc.modified and not w.cc]

    def _save_others(self) -> bool:
        """Ask whether to save the changed texts, and save them. False if cancelled."""
        changed = self._changed_files()
        if not changed:
            return True
        answer = self.console.ask("修正テキストを出力します")
        if answer is None:
            return False
        return not answer or all(self.save(w) for w in changed)

    def _pass(self, window: Window) -> bool:
        """Save the prompt file of Claude Code, which hands the text to Claude Code."""
        if window.doc.modified and not self.save(window):
            return False
        if self.prompt is not None:
            self.prompt.passed(window)
        return True

    def _pass_prompts(self) -> bool:
        return all(self._pass(w) for w in self.windows if w.cc)

    def quit(self) -> None:
        """Quit, asking whether to save the changed texts and whether to quit.

        The prompt file of Claude Code is saved without asking, as on closing it.
        """
        if not self._save_others():
            return
        if self.console.ask("エディタを終了します") and self._pass_prompts():
            self.exit_code = 0

    def escape(self) -> None:
        """Quit without saving, asking first if a text was changed.

        The prompt file of Claude Code is still saved: the way to leave its text out of
        Claude Code's input box is putting it on hold.
        """
        if self._changed_files() and not self.console.ask("編集テキストを放棄します"):
            return
        if self._pass_prompts():
            self.exit_code = 0

    def hold(self) -> None:
        """Put the prompt text on hold and go back to Claude Code (VZ: go to DOS).

        Claude Code's input box stays as it was, and the next call from Claude Code
        shows the draft again.
        """
        window = self.window
        if not window.cc or self.prompt is None:
            self.console.message("Claude Code から呼ばれていません")
            return
        if not self._save_others():
            return
        try:
            self.prompt.hold(window)
        except OSError as e:
            self.console.message(f"下書きを保存できません（{e.strerror or e}）")
            return
        self.exit_code = 0
