"""The prompt file that Claude Code hands to `pyvz -c`, and putting its text on hold.

Claude Code writes the text of its input box to a new file each time and reads the
file back when pyvz exits with status 0. To put the text on hold, pyvz keeps it in a
draft file and leaves the prompt file as it was, so the input box stays unchanged. The
next call shows the draft again, in the new prompt file.

With the setting externalEditorContext, the file starts with Claude's last response
as comment lines and a separator line (the prologue). Claude Code drops everything up
to the separator when it reads the file back, so only the text below it is the draft.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

from pyvz.cc import drafts
from pyvz.cc.drafts import Draft
from pyvz.cc.session import Session, alive
from pyvz.editor.layout import Layout
from pyvz.editor.window import Window
from pyvz.text.document import ENCODING, ERRORS, Document, FileFormat, encode

# The separator, exactly as Claude Code writes and looks for it (2.1.310).
SEPARATOR = "# ─── Write your reply below this line " + "─" * 26
_AFTER_SEPARATOR = re.compile(r"\r?\n\r?\n?")


def split(text: str) -> tuple[str, str]:
    """The prologue, and the text below it, which Claude Code reads back."""
    found = text.find(SEPARATOR)
    if found < 0:
        return "", text
    end = found + len(SEPARATOR)
    after = _AFTER_SEPARATOR.match(text, end)
    if after:
        end = after.end()
    return text[:end], text[end:]


def _join(draft: str, typed: str) -> str:
    """The draft followed by text typed into the input box meanwhile, a blank line apart."""
    if not draft:
        return typed
    gap = "" if draft.endswith("\n\n") else "\n" if draft.endswith("\n") else "\n\n"
    return draft + gap + typed


class PromptFile:
    def __init__(
        self,
        path: Path,
        session: Session | None,
        *,
        directory: Path | None = None,
        cwd: str | None = None,
        is_alive: Callable[[Session], bool] = alive,
    ) -> None:
        self.path = path
        self.session = session
        self.directory = directory
        self.cwd = cwd if cwd is not None else os.getcwd()
        self.is_alive = is_alive
        self.prologue = ""
        self.original = ""  # what the input box held this time
        self.message = ""  # what to tell the user once the text is shown
        self._draft_paths: list[Path] = []  # drafts that this text took over

    def open(self, layout: Layout) -> Window:
        try:
            text = self.path.read_bytes().decode(ENCODING, ERRORS)
        except FileNotFoundError:
            text = ""
        self.prologue, self.original = split(text)
        found, left_behind = None, False
        if self.session is not None:
            found = drafts.find(self.session, self.directory)
            if found is None:
                candidates = drafts.left_behind(self.cwd, self.directory, self.is_alive)
                if candidates:
                    found, left_behind = candidates[0], True
        if found is None:
            window = self._window(text, layout)
            window.line = len(window.lines) - 1
            window.index = len(window.lines[-1])
            return window

        path, draft = found
        self._draft_paths.append(path)
        opened = "下書きを開きました"
        if left_behind:
            opened = "前のセッションで保留した" + opened
        if self.original.strip() and self.original not in (draft.text, draft.original):
            body = _join(draft.text, self.original)
            self.message = f"{opened}。入力欄の文は後ろに足しました"
        else:
            body = draft.text
            self.message = opened
        window = self._window(self.prologue + body, layout)
        window.draft = True
        window.doc.modified = self.prologue + body != text
        line = self.prologue.count("\n") + draft.line
        window.line = min(line, len(window.lines) - 1)
        window.index = min(draft.index, len(window.lines[window.line]))
        return window

    def _window(self, text: str, layout: Layout) -> Window:
        # Kept as the exact text: a final line end is an empty last line.
        fmt = FileFormat(final_newline=False)
        doc = Document(lines=text.split("\n"), path=self.path, format=fmt)
        return Window(doc, layout, cc=True)

    def _text(self, window: Window) -> str:
        return encode(window.lines, window.doc.format).decode(ENCODING, ERRORS)

    def hold(self, window: Window) -> None:
        """Keep the text below the prologue as the draft of this session.

        An empty text needs no draft; any draft there was is removed. Raises OSError
        if the draft cannot be written.
        """
        if self.session is None:
            raise ValueError("not called from Claude Code")
        text = self._text(window)
        if self.prologue and text.startswith(self.prologue):
            prologue, body = self.prologue, text[len(self.prologue) :]
        else:
            prologue, body = split(text)
        if not body.strip():
            self.passed(window)
            return
        line = window.line - prologue.count("\n")
        index = window.index if line >= 0 else 0
        draft = Draft(
            text=body,
            line=max(line, 0),
            index=index,
            original=self.original,
            cwd=self.cwd,
            pid=self.session.pid,
            start=self.session.start,
        )
        saved = drafts.save(draft, self.directory)
        for path in self._draft_paths:
            if path != saved:
                drafts.remove(path)
        self._draft_paths = [saved]

    def passed(self, window: Window) -> None:
        """The text went back to Claude Code: the drafts it came from are done."""
        for path in self._draft_paths:
            drafts.remove(path)
        if self.session is not None:
            drafts.remove(drafts.draft_path(self.session, self.directory))
        self._draft_paths = []
