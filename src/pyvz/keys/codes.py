"""Key codes, and the key notation of VZ DEF files.

A key code is an int:

- 0x00-0x1F: Ctrl+@, Ctrl+A, ..., Ctrl+_ (``^@`` ... ``^_``)
- 0x20-0x3F: Alt+@ ... Alt+_ (``@X``). pyvz reads Alt+X from the terminal as ESC
  followed by X, so a DEF's ``@X`` is turned into ``[ESC]X`` when ESC is a prefix key.
- 0x40-0xFF: two-stroke keys, a prefix key followed by a letter. The n-th prefix key
  (from 0) gives (n + 2) * 0x20 + (letter - 0x40), as in VZ.
- SPECIAL | 0x80-0xFE: special keys (``[UP]``, ``[F01]`` ...), with Shift (+0x20),
  Ctrl (+0x40) or Alt (+0x60). VZ kept these in a separate byte of its key table,
  because they overlap the codes of the third and later prefix keys.
- PREFIX_DIGIT | n: the n-th prefix key followed by a digit. VZ binds such a key with
  a 0 (``^K0``) and passes the digit to the command or macro.
"""

from __future__ import annotations

SPECIAL = 0x100
PREFIX_DIGIT = 0x200

SHIFT = 0x20
CTRL = 0x40
ALT = 0x60

# Special key names, in the order of their codes from 0x90 (VZ's IBM version).
# F1-F15 are 0x81-0x8F.
NAMES = ["PGUP", "PGDN", "INS", "DEL", "UP", "<--", "-->", "DOWN", "HOME", "END",
         "ESC", "TAB", "BS", "CR", "NFER"]  # fmt: skip
# Other names that VZ accepts for the same keys.
ALIASES = {"RLDN": "PGUP", "RLUP": "PGDN", "CLR": "HOME", "HELP": "END"}


def special(name: str, modifier: int = 0) -> int:
    """The code of a special key, such as special("UP") or special("F5", SHIFT)."""
    name = ALIASES.get(name.upper(), name.upper())
    if name.startswith("F") and name[1:].isdigit():
        number = int(name[1:])
        if not 1 <= number <= 15:
            raise ValueError(f"no such function key: {name}")
        base = 0x80 + number
    else:
        base = 0x90 + NAMES.index(name)
    return SPECIAL | (base + modifier)


UP = special("UP")
DOWN = special("DOWN")
LEFT = special("<--")
RIGHT = special("-->")
PGUP = special("PGUP")
PGDN = special("PGDN")
HOME = special("HOME")
END = special("END")
INS = special("INS")
DEL = special("DEL")
ESC = special("ESC")
TAB = special("TAB")
BS = special("BS")
CR = special("CR")


def ctrl(ch: str) -> int:
    """The code of Ctrl+`ch`, where `ch` is one of @A-Z[\\]^_ (case does not matter)."""
    code = ord(ch.upper()) - 0x40
    if not 0 <= code <= 0x1F:
        raise ValueError(f"no Ctrl key for {ch!r}")
    return code


def stroke2(prefix_index: int, ch: str | int) -> int:
    """The code of the `prefix_index`-th prefix key followed by `ch`.

    `ch` is a letter or symbol (@A-Z[\\]^_) or a control code from holding Ctrl down,
    so ^Q S and ^Q ^S give the same key, as in VZ.
    """
    if not 0 <= prefix_index <= 5:
        raise ValueError("VZ allows up to six prefix keys")
    low = ch if isinstance(ch, int) else ctrl(ch)
    if not 0 <= low <= 0x1F:
        raise ValueError(f"not a key that can follow a prefix: {ch!r}")
    return (prefix_index + 2) * 0x20 + low


def is_special(code: int) -> bool:
    return code & SPECIAL != 0 and code & PREFIX_DIGIT == 0


def parse_key(text: str, prefixes: list[int]) -> tuple[int, str]:
    """Read one key in DEF notation from the start of `text`.

    Returns the key code and the rest of the text. Two-stroke keys are not composed
    here; see parse_keys. Raises ValueError for text that is not a key.
    """
    if text.startswith("["):
        return _parse_special(text[1:], 0)
    if text[:1] in ("^", "@", "\\") and len(text) >= 2:
        mark, rest = text[0], text[1:]
        modifier = {"^": CTRL, "@": ALT, "\\": SHIFT}[mark]
        # "^[" followed by a name is Ctrl with a special key; "^[" alone is ESC (^[).
        if rest.startswith("[") and len(rest) >= 3 and rest[1] > " " and rest[2] > " ":
            return _parse_special(rest[1:], modifier)
        if mark == "\\":
            raise ValueError(f"Shift can only be used with special keys: {text!r}")
        code = ctrl(rest[0])
        if mark == "@":
            code += 0x20
            esc = special("ESC")
            if esc in prefixes:
                code = stroke2(prefixes.index(esc), rest[0])
        return code, rest[1:]
    raise ValueError(f"not a key: {text!r}")


def _parse_special(text: str, modifier: int) -> tuple[int, str]:
    end = text.find("]")
    if end <= 0:
        raise ValueError(f"unterminated key name: [{text}")
    return special(text[:end], modifier), text[end + 1 :]


def parse_keys(text: str, prefixes: list[int]) -> tuple[int, str]:
    """Read a key, and the letter after it when it is a prefix key.

    A prefix key followed by 0 means the prefix key followed by any digit.
    """
    code, rest = parse_key(text, prefixes)
    if code in prefixes and rest[:1] > " ":
        index = prefixes.index(code)
        if rest[0] == "0":
            return PREFIX_DIGIT | index, rest[1:]
        return stroke2(index, rest[0]), rest[1:]
    return code, rest


def format_key(code: int, prefixes: list[int]) -> str:
    """The DEF notation of a key code."""
    if code & PREFIX_DIGIT:
        return format_key(prefixes[code & 0xFF], prefixes) + "0"
    if is_special(code):
        base = code & 0xFF
        modifier = (base - 0x80) & 0x60
        base -= modifier
        name = f"F{base - 0x80:02d}" if base < 0x90 else NAMES[base - 0x90]
        mark = {0: "", SHIFT: "\\", CTRL: "^", ALT: "@"}[modifier]
        return f"{mark}[{name}]"
    if code < 0x20:
        return "^" + chr(code + 0x40)
    if code < 0x40:
        return "@" + chr(code - 0x20 + 0x40)
    prefix = prefixes[code // 0x20 - 2]
    return format_key(prefix, prefixes) + chr(code % 0x20 + 0x40)
