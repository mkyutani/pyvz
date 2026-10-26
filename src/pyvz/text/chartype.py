"""Character classes for moving and deleting by words.

The values are VZ's character types, which macros see as the variable ``ct``. A word
boundary is where the class changes. VZ decided the class from Shift_JIS codes; here
it is decided from Unicode properties.
"""

from __future__ import annotations

import unicodedata

EOF = 0  # the cursor is at the end of the text
EOL = 1  # the cursor is at the end of a line
SPACE = 2  # spaces (including U+3000), tabs and control characters
SYMBOL = 3  # punctuation, brackets and other symbols
HIRAGANA = 4
WIDE = 5  # kanji, katakana, full-width letters and digits
ALNUM = 6  # letters and digits of other scripts, and "_"


def char_class(ch: str) -> int:
    """The class of a character in a line. EOF and EOL are for cursor positions."""
    code = ord(ch)
    if ch.isspace() or code < 0x20 or code == 0x7F:
        return SPACE
    if 0x3041 <= code <= 0x309F:
        return HIRAGANA
    if ch == "_":
        return ALNUM
    category = unicodedata.category(ch)
    if category[0] in "LN" or category in ("Mn", "Mc"):
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            return WIDE
        return ALNUM
    return SYMBOL
