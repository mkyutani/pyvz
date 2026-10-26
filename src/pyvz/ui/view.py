"""Drawing the editor: the status line, the text, the message line and the function
key labels.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from pyvz.editor.editor import Editor
from pyvz.editor.layout import shown_as
from pyvz.ui.screen import PLAIN, Screen, Style, clip, clip_start, text_width

STATUS = Style(reverse=True)
CONTROL = Style(fg=6)  # control characters and bytes that are not UTF-8
MARK = Style(fg=8)  # line ends and the end of the text
MESSAGE = Style(fg=3, bold=True)
KEY_LABEL = Style(reverse=True)

LINE_END_MARK = "↵"
END_MARK = "[EOF]"

# The labels of F1-F10, from the "* F" section of VZIBMJ.DEF (in half-width katakana
# there).
FUNCTION_LABELS = [
    unicodedata.normalize("NFKC", label)
    for label in ["ﾌｧｲﾙ", "窓換", "文換", "窓割", "記憶", "検索", "置換", "ｶｯﾄ", "ｲﾝｻｰﾄ", "ﾌﾞﾛｯｸ"]
]

# Rows other than the text: the status line, the message line, the function keys.
OTHER_ROWS = 3


@dataclass
class Overlay:
    """What the main loop shows over the editor."""

    message: str = ""
    prefix: str = ""  # a prefix key waiting for the next key
    question: str = ""  # a Y/N question waiting for the answer


def text_rows(height: int) -> int:
    return max(height - OTHER_ROWS, 1)


def draw(screen: Screen, editor: Editor, overlay: Overlay) -> None:
    rows = text_rows(screen.height)
    if editor.windows:
        _status(screen, editor)
        cursor = _text(screen, editor, 1, rows)
    else:
        cursor = None
    end = _message(screen, overlay, rows + 1)
    _function_keys(screen, rows + 2)
    screen.cursor = (rows + 1, end) if overlay.question else cursor


def _status(screen: Screen, editor: Editor) -> None:
    window = editor.window
    doc = window.doc
    number = f" {editor.current + 1} "
    marks = (" (CC)" if window.cc else "") + (" *" if doc.modified else "")
    folded = window.folded(window.line)
    column = sum(folded.widths[: window.index]) + 1
    flags = ("R " if doc.readonly else "") + "P " + ("挿入" if editor.insert_mode else "上書")
    right = f"{flags} {window.line + 1:>5}:{column:<3}"
    wide = screen.ambiguous_wide
    right_width = text_width(right, ambiguous_wide=wide)
    room = screen.width - right_width - 1
    room -= text_width(number, ambiguous_wide=wide) + text_width(marks, ambiguous_wide=wide)
    # The end of a long path is kept, which tells the files apart.
    name = clip_start(editor.name(window), room, ambiguous_wide=wide)
    screen.fill(0, 0, screen.width, STATUS)
    screen.put(0, 0, number + name + marks, STATUS)
    screen.put(0, max(screen.width - right_width, 0), right, STATUS)


def _text(screen: Screen, editor: Editor, first: int, rows: int) -> tuple[int, int] | None:
    """Draw the rows of the text. Returns where the cursor is on the screen."""
    window = editor.window
    lines = window.lines
    final_newline = window.doc.format.final_newline
    cursor_pos = window.cursor_row()
    cursor = None
    pos = window.top
    y = first
    while y < first + rows:
        line_no, row = pos
        folded = window.folded(line_no)
        text = folded.line
        start, end = folded.row_range(row)
        for i in range(start, end):
            ch = text[i]
            alt = shown_as(ch, folded.widths[i])
            if alt is None:
                screen.put(y, folded.columns[i], ch)
            else:
                screen.put(y, folded.columns[i], alt, PLAIN if ch == "\t" else CONTROL)
        if pos == cursor_pos:
            cursor = (y, folded.columns[window.index])
        if row == folded.rows - 1:
            column = folded.columns[len(text)]
            last = line_no == len(lines) - 1
            if not last or final_newline:
                screen.put(y, column, LINE_END_MARK, MARK)
            if last:
                if not final_newline:
                    screen.put(y, column, END_MARK, MARK)
                elif y + 1 < first + rows:
                    screen.put(y + 1, 0, END_MARK, MARK)
        following = window.next_row(pos)
        if following is None:
            break
        pos = following
        y += 1
    return cursor


def _message(screen: Screen, overlay: Overlay, row: int) -> int:
    """Draw the message line. Returns the column after the text.

    A long message keeps its end, where a question asks (Y/N), and a column is left
    for the cursor after it.
    """
    text = overlay.question or overlay.prefix or overlay.message
    text = clip_start(text, screen.width - 1, ambiguous_wide=screen.ambiguous_wide)
    return screen.put(row, 0, text, MESSAGE)


def _function_keys(screen: Screen, row: int) -> None:
    slot = screen.width // len(FUNCTION_LABELS)
    if slot < 3:
        return
    for i, label in enumerate(FUNCTION_LABELS):
        column = i * slot
        screen.put(row, column, str((i + 1) % 10))
        screen.fill(row, column + 1, column + slot - 1, KEY_LABEL)
        label = clip(label, slot - 2, ambiguous_wide=screen.ambiguous_wide)
        screen.put(row, column + 1, label, KEY_LABEL)
