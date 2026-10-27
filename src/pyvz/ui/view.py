"""Drawing the editor: the status line, the text, the message line and the function
key labels.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, replace

from pyvz.editor.editor import LEFT_RIGHT, Editor, Region
from pyvz.editor.layout import shown_as
from pyvz.ui import theme
from pyvz.ui.screen import PLAIN, Screen, Style, clip, clip_middle, clip_start, text_width

LINE_END_MARK = "↵"
END_MARK = "[EOF]"

# The labels of F1-F10, from the "* F" section of VZIBMJ.DEF (in half-width katakana
# there).
FUNCTION_LABELS = [
    unicodedata.normalize("NFKC", label)
    for label in ["ﾌｧｲﾙ", "窓換", "文換", "窓割", "記憶", "検索", "置換", "ｶｯﾄ", "ｲﾝｻｰﾄ", "ﾌﾞﾛｯｸ"]
]


@dataclass
class Overlay:
    """What the main loop shows over the editor."""

    message: str = ""
    prefix: str = ""  # a prefix key waiting for the next key
    question: str = ""  # a Y/N question waiting for the answer


def draw(screen: Screen, editor: Editor, overlay: Overlay) -> None:
    """The windows, each with its status line, then the message line and the
    function keys on the last two rows."""
    cursor = None
    regions = editor.regions()
    for region in regions:
        active = region.window is editor.window
        _status(screen, editor, region, active)
        at = _text(screen, region)
        if active:
            cursor = at
    if editor.split == LEFT_RIGHT and len(regions) == 2:
        column = regions[1].left - 1
        for row in range(regions[0].rows + 1):
            screen.put(row, column, "│", theme.style("frame"))
    message_row = max(screen.height - editor.bottom_rows, 0)
    end = draw_message(screen, overlay, message_row)
    if editor.function_keys:
        _function_keys(screen, message_row + 1)
    screen.cursor = (message_row, end) if overlay.question else cursor


def _status(screen: Screen, editor: Editor, region: Region, active: bool) -> None:
    window = region.window
    doc = window.doc
    number = f" {editor.windows.index(window) + 1} "
    marks = (" (CC 下書き)" if window.draft else " (CC)") if window.cc else ""
    marks += " *" if doc.modified else ""
    folded = window.folded(window.line)
    column = sum(folded.widths[: window.index]) + 1
    flags = ("R " if doc.readonly else "") + editor.paging + " "
    flags += "挿入" if editor.insert_mode else "上書"
    right = f"{flags} {window.line + 1:>5}:{column:<3}"
    wide = screen.ambiguous_wide
    right_width = text_width(right, ambiguous_wide=wide)
    room = region.width - right_width - 1
    room -= text_width(number, ambiguous_wide=wide) + text_width(marks, ambiguous_wide=wide)
    # The end of a long path is kept, which tells the files apart.
    name = clip_start(editor.name(window), max(room, 0), ambiguous_wide=wide)
    style = theme.style("status") if active else theme.style("status_other")
    left, row = region.left, region.top
    screen.fill(row, left, left + region.width, style)
    screen.put(row, left, number + name + marks, style)
    if right_width < region.width:
        screen.put(row, left + region.width - right_width, right, style)


def _text(screen: Screen, region: Region) -> tuple[int, int] | None:
    """Draw the rows of the text of a window. Returns where the cursor is."""
    window = region.window
    lines = window.lines
    cursor_pos = window.cursor_row()
    first, rows, left = region.top + 1, region.rows, region.left
    block = window.block_range()
    marked = [(b[1], b[2]) for b in [block] if b is not None]
    if window.found is not None:
        marked.append(window.found)

    def styled(style: Style, line: int, index: int) -> Style:
        if any(start <= (line, index) < end for start, end in marked):
            return replace(style, reverse=True)
        return style

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
                screen.put(y, left + folded.columns[i], ch, styled(PLAIN, line_no, i))
            else:
                style = PLAIN if ch == "\t" else theme.style("control")
                screen.put(y, left + folded.columns[i], alt, styled(style, line_no, i))
        if pos == cursor_pos:
            cursor = (y, left + folded.columns[window.index])
        if row == folded.rows - 1:
            column = left + folded.columns[len(text)]
            if line_no < len(lines) - 1:
                screen.put(
                    y, column, LINE_END_MARK, styled(theme.style("mark"), line_no, len(text))
                )
            else:
                screen.put(y, column, END_MARK, theme.style("mark"))
        following = window.next_row(pos)
        if following is None:
            break
        pos = following
        y += 1
    return cursor


def draw_message(screen: Screen, overlay: Overlay, row: int) -> int:
    """Draw the message line. Returns the column after the text.

    A long question keeps its end, where it asks (Y/N), and a long message its start
    and end, around a long path. A column is left for the cursor.
    """
    width, wide = screen.width - 1, screen.ambiguous_wide
    if overlay.question:
        text = clip_start(overlay.question, width, ambiguous_wide=wide)
    else:
        text = clip_middle(overlay.prefix or overlay.message, width, ambiguous_wide=wide)
    return screen.put(row, 0, text, theme.style("message"))


def _function_keys(screen: Screen, row: int) -> None:
    slot = screen.width // len(FUNCTION_LABELS)
    if slot < 3:
        return
    for i, label in enumerate(FUNCTION_LABELS):
        column = i * slot
        screen.put(row, column, str((i + 1) % 10))
        screen.fill(row, column + 1, column + slot - 1, theme.style("key_label"))
        label = clip(label, slot - 2, ambiguous_wide=screen.ambiguous_wide)
        screen.put(row, column + 1, label, theme.style("key_label"))
