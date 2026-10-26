"""How many terminal columns characters take."""

from __future__ import annotations

import unicodedata


def is_raw_byte(ch: str) -> bool:
    """Whether `ch` stands for a byte that was not valid UTF-8 (see document.ERRORS)."""
    return "\udc80" <= ch <= "\udcff"


def char_width(ch: str, *, ambiguous_wide: bool = False) -> int:
    """Columns that `ch` takes on the screen, other than a tab.

    Control characters are shown as ``^X`` and raw bytes as ``\\xNN``. Characters of
    ambiguous width (box drawing, circled digits, Greek, ...) take one column unless
    `ambiguous_wide` is set, matching how the terminal is configured.
    """
    if is_raw_byte(ch):
        return 4
    code = ord(ch)
    if code < 0x20 or code == 0x7F:
        return 2
    if 0x80 <= code < 0xA0:
        return 4
    if unicodedata.category(ch) in ("Mn", "Me", "Cf"):
        return 0
    eaw = unicodedata.east_asian_width(ch)
    if eaw in ("W", "F") or (eaw == "A" and ambiguous_wide):
        return 2
    return 1


def next_tab_stop(column: int, tab_size: int) -> int:
    return (column // tab_size + 1) * tab_size


def columns(line: str, *, tab_size: int = 8, ambiguous_wide: bool = False) -> list[int]:
    """The column where each character of `line` starts, followed by the end column."""
    result = [0]
    column = 0
    for ch in line:
        if ch == "\t":
            column = next_tab_stop(column, tab_size)
        else:
            column += char_width(ch, ambiguous_wide=ambiguous_wide)
        result.append(column)
    return result


def index_at_column(
    line: str, column: int, *, tab_size: int = 8, ambiguous_wide: bool = False
) -> int:
    """The index of the character that covers `column`, or len(line) past the end.

    A column in the middle of a wide character or a tab gives that character.
    """
    starts = columns(line, tab_size=tab_size, ambiguous_wide=ambiguous_wide)
    for i in range(len(line)):
        if column < starts[i + 1]:
            return i
    return len(line)
