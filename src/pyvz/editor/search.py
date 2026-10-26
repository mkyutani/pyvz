"""Search strings in VZ's notation, and finding them in a text.

A search string may start with options in VZ's way, "\\WC " for example, which hold
for that search only: W word search, C ignore case, Z full and half width the same,
X regular expression (VZ needed the VWX add-on; pyvz uses Python's), I no special
meaning for "\\". Without X, "\\*" and "\\\\" stand for "*" and "\\", and "\\n" (or
"\\l") for a line end. A "*" at either end turns over the word boundary rule at that
end: with word search it lets the match be part of a longer word, and without it, it
asks for a word boundary there.
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right
from collections.abc import Iterator
from dataclasses import dataclass

from pyvz.text import chartype

Pos = tuple[int, int]
OPTION_LETTERS = "WCZXI"


@dataclass(frozen=True)
class Options:
    word: bool = False
    ignore_case: bool = False
    zenhan: bool = False
    regex: bool = False
    plain_backslash: bool = False

    @classmethod
    def from_letters(cls, letters: str) -> Options:
        letters = letters.upper()
        return cls(*(ch in letters for ch in OPTION_LETTERS))

    def letters(self) -> str:
        flags = (self.word, self.ignore_case, self.zenhan, self.regex, self.plain_backslash)
        return "".join(ch for ch, on in zip(OPTION_LETTERS, flags, strict=True) if on)


@dataclass(frozen=True)
class Pattern:
    regex: re.Pattern[str]
    options: Options
    head_boundary: bool = False  # the character before a match must not be a letter
    tail_boundary: bool = False  # nor the one after it


def _split_options(text: str) -> tuple[str | None, str]:
    if text.startswith("\\"):
        letters, space, rest = text[1:].partition(" ")
        if space and letters and all(ch.upper() in OPTION_LETTERS for ch in letters):
            return letters, rest
    return None, text


def _word_like(ch: str) -> bool:
    return chartype.char_class(ch) == chartype.ALNUM


# Full width ASCII (U+FF01-FF5E) and the ideographic space, for the Z option.
_HALF_OF = {chr(code + 0xFEE0): chr(code) for code in range(0x21, 0x7F)} | {"\u3000": " "}
_FULL_OF = {half: full for full, half in _HALF_OF.items()}


def _char_regex(ch: str, zenhan: bool) -> str:
    if zenhan:
        other = _HALF_OF.get(ch) or _FULL_OF.get(ch)
        if other is None:
            folded = unicodedata.normalize("NFKC", ch)
            other = folded if len(folded) == 1 and folded != ch else None
        if other is not None:
            return f"[{re.escape(ch)}{re.escape(other)}]"
    return re.escape(ch)


def compile_search(text: str, defaults: Options | None = None) -> Pattern:
    """Raises ValueError for an empty string or a bad regular expression."""
    letters, text = _split_options(text)
    if letters is not None:
        options = Options.from_letters(letters)
    else:
        options = defaults or Options()
    if not text:
        raise ValueError("検索文字列がありません")
    flags = re.IGNORECASE if options.ignore_case else 0
    if options.regex:
        try:
            regex = re.compile(text, flags | re.MULTILINE)
        except re.error as e:
            raise ValueError(f"正規表現の誤り: {e}") from None
        return Pattern(regex, options, options.word, options.word)

    star_head = text.startswith("*")
    star_tail = len(text) > 1 and text.endswith("*") and not text.endswith("\\*")
    body = text[1 if star_head else 0 : len(text) - 1 if star_tail else len(text)]
    chars = _unescape(body, options.plain_backslash)
    if not chars:
        raise ValueError("検索文字列がありません")
    if options.word:
        head = not star_head and _word_like(chars[0])
        tail = not star_tail and _word_like(chars[-1])
    else:
        head, tail = star_head, star_tail
    regex = re.compile("".join(_char_regex(ch, options.zenhan) for ch in chars), flags)
    return Pattern(regex, options, head, tail)


def _unescape(text: str, plain: bool) -> str:
    if plain:
        return text
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            following = text[i + 1]
            if following in "*\\":
                out.append(following)
                i += 2
                continue
            if following in "nlr":
                out.append("\n")
                i += 2
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def unescape_replacement(text: str) -> str:
    """The replacement string: "\\n" for a line end, "\\\\" and "\\*" as in search strings."""
    return _unescape(text, False)


def literal(text: str) -> str:
    """A search string that finds `text` itself."""
    return text.replace("\\", "\\\\").replace("*", "\\*").replace("\n", "\\n")


class Finder:
    """A text joined into one string, to find patterns across lines."""

    def __init__(self, lines: list[str]) -> None:
        self.text = "\n".join(lines)
        self.starts = [0]
        for line in lines[:-1]:
            self.starts.append(self.starts[-1] + len(line) + 1)

    def offset(self, pos: Pos) -> int:
        return self.starts[pos[0]] + pos[1]

    def pos(self, offset: int) -> Pos:
        line = bisect_right(self.starts, offset) - 1
        return line, offset - self.starts[line]

    def _fits(self, pattern: Pattern, start: int, end: int) -> bool:
        text = self.text
        if end == start:
            return False
        if pattern.head_boundary and start > 0 and _word_like(text[start - 1]):
            return False
        if pattern.tail_boundary and end < len(text) and _word_like(text[end]):
            return False
        return True

    def matches(self, pattern: Pattern, start: int = 0) -> Iterator[re.Match[str]]:
        """Matches from `start` on, overlapping ones too, that keep the boundary rules."""
        offset = start
        while offset <= len(self.text):
            m = pattern.regex.search(self.text, offset)
            if m is None:
                return
            if self._fits(pattern, m.start(), m.end()):
                yield m
            offset = m.start() + 1

    def forward(self, pattern: Pattern, after: Pos) -> re.Match[str] | None:
        """The first match that starts after `after` (VZ: from the next character)."""
        return next(self.matches(pattern, self.offset(after) + 1), None)

    def backward(self, pattern: Pattern, before: Pos) -> re.Match[str] | None:
        """The last match that starts before `before`."""
        limit = self.offset(before)
        found = None
        for m in self.matches(pattern):
            if m.start() >= limit:
                break
            found = m
        return found
