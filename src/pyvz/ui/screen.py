"""A grid of character cells, written to the terminal as the changes from the last one.

pyvz draws the whole screen into a grid each time, and sends only the cells that
changed. Widths come from pyvz.text.width, the same as the folding of lines, so the
two agree on where every character goes.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyvz.text.width import char_width

CSI = "\x1b["


@dataclass(frozen=True)
class Style:
    """Colors are the terminal's 256 colors (0-15 are its own palette), or None."""

    fg: int | None = None
    bg: int | None = None
    bold: bool = False
    dim: bool = False
    underline: bool = False
    reverse: bool = False

    def sgr(self) -> str:
        codes = ["0"]
        if self.bold:
            codes.append("1")
        if self.dim:
            codes.append("2")
        if self.underline:
            codes.append("4")
        if self.reverse:
            codes.append("7")
        if self.fg is not None:
            codes.append(_color(30, self.fg))
        if self.bg is not None:
            codes.append(_color(40, self.bg))
        return f"{CSI}{';'.join(codes)}m"


def _color(base: int, color: int) -> str:
    if color < 8:
        return str(base + color)
    if color < 16:
        return str(base + 60 + color - 8)
    return f"{base + 8};5;{color}"


PLAIN = Style()


def text_width(text: str, *, ambiguous_wide: bool = False) -> int:
    """Columns that `text` takes. It must not hold tabs or control characters."""
    return sum(char_width(ch, ambiguous_wide=ambiguous_wide) for ch in text)


def clip(text: str, width: int, *, ambiguous_wide: bool = False) -> str:
    """The longest start of `text` that fits in `width` columns."""
    used = 0
    for i, ch in enumerate(text):
        used += char_width(ch, ambiguous_wide=ambiguous_wide)
        if used > width:
            return text[:i]
    return text


def clip_start(text: str, width: int, *, ambiguous_wide: bool = False) -> str:
    """`text`, or "…" and the longest end of it that fits in `width` columns."""
    if text_width(text, ambiguous_wide=ambiguous_wide) <= width:
        return text
    if width < 1:
        return ""
    return "…" + clip(text[::-1], width - 1, ambiguous_wide=ambiguous_wide)[::-1]


# The text of the cell after a wide character, which the wide character covers.
COVERED = ""


class Screen:
    def __init__(self, width: int, height: int, *, ambiguous_wide: bool = False) -> None:
        self.width = width
        self.height = height
        self.ambiguous_wide = ambiguous_wide
        self.chars = [[" "] * width for _ in range(height)]
        self.styles = [[PLAIN] * width for _ in range(height)]
        # Where the terminal's cursor is shown, or None to hide it.
        self.cursor: tuple[int, int] | None = None

    def put(self, row: int, column: int, text: str, style: Style = PLAIN) -> int:
        """Write text from `column`, clipped at the right edge. Returns the end column.

        Characters of zero width join the character before them. A wide character that
        does not fit at the right edge leaves a space.
        """
        if not 0 <= row < self.height:
            return column
        chars = self.chars[row]
        for ch in text:
            w = char_width(ch, ambiguous_wide=self.ambiguous_wide)
            if w == 0:
                if 0 < column <= self.width:
                    lead = column - 1
                    while lead > 0 and chars[lead] == COVERED:
                        lead -= 1
                    chars[lead] += ch
                continue
            if column < 0:
                column += w
                continue
            if column + w > self.width:
                if column < self.width:
                    self._set(row, column, " ", style)
                return self.width
            self._set(row, column, ch, style)
            if w == 2:
                self._set(row, column + 1, COVERED, style)
            column += w
        return column

    def fill(self, row: int, column: int, end: int, style: Style = PLAIN) -> None:
        """Fill the columns from `column` up to `end` with spaces."""
        if 0 <= row < self.height:
            for c in range(max(column, 0), min(end, self.width)):
                self._set(row, c, " ", style)

    def _set(self, row: int, column: int, ch: str, style: Style) -> None:
        chars = self.chars[row]
        # Writing over half of a wide character leaves a space in its other half.
        if chars[column] == COVERED and ch != COVERED and column > 0:
            chars[column - 1] = " "
        if column + 1 < self.width and chars[column + 1] == COVERED:
            chars[column + 1] = " "
        chars[column] = ch
        self.styles[row][column] = style

    def render(self, before: Screen | None) -> str:
        """The output that turns the terminal from `before` (None: unknown) into this."""
        out = [f"{CSI}?2026h{CSI}?25l"]  # synchronized update, cursor hidden
        same_size = (
            before is not None and before.width == self.width and before.height == self.height
        )
        if not same_size:
            out.append(f"{CSI}0m{CSI}2J")
        style: Style | None = None
        pen: tuple[int, int] | None = None  # where the terminal will put the next character
        for row in range(self.height):
            chars, styles = self.chars[row], self.styles[row]
            old_chars = before.chars[row] if same_size and before else None
            old_styles = before.styles[row] if same_size and before else None
            for column in range(self.width):
                ch = chars[column]
                if ch == COVERED:
                    continue
                if (
                    old_chars is not None
                    and old_styles is not None
                    and old_chars[column] == ch
                    and old_styles[column] == styles[column]
                ):
                    continue
                if pen != (row, column):
                    out.append(f"{CSI}{row + 1};{column + 1}H")
                if styles[column] != style:
                    style = styles[column]
                    out.append(style.sgr())
                out.append(ch)
                # After anything but ASCII, the terminal may disagree on the width, so the
                # next character is placed explicitly.
                pen = (row, column + 1) if ch.isascii() else None
        out.append(f"{CSI}0m")
        if self.cursor is not None:
            row, column = self.cursor
            out.append(f"{CSI}{row + 1};{column + 1}H{CSI}?25h")
        out.append(f"{CSI}?2026l")
        return "".join(out)

    def text(self, row: int) -> str:
        """The characters of a row, for tests."""
        return "".join(self.chars[row])
