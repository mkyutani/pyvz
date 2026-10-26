"""Key bindings: which keys run which commands in each mode."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from importlib import resources

from pyvz.keys import codes
from pyvz.keys.commands import Cmd


class Mode(IntEnum):
    """Where keys are read. The values are VZ's system modes (the macro variable s)."""

    EDIT = 0
    GETS = 1  # a one-line input box
    DOS = 2
    FILER = 3
    GETC = 4  # a one-key question such as Y/N, or a menu


# The commands each mode looks up, in the order VZ looks them up (KEY.ASM getkey and
# scancmkey). Every mode first looks at 1 (repeat) and 2 (keyboard macro).
# The order decides which command a key runs when it is bound to more than one:
# in the filer, [TAB] switches the window (93) rather than inserting a tab (21).
_FIRST = range(1, 3)
_LOOKUP = {
    Mode.EDIT: (_FIRST, range(3, 88), range(200, 256)),
    Mode.GETS: (_FIRST, range(3, 30)),
    Mode.DOS: (_FIRST, range(3, 30), range(95, 100)),
    Mode.FILER: (_FIRST, range(3, 9), range(88, 95), range(9, 43), range(53, 54)),
    Mode.GETC: (_FIRST, range(3, 88)),
}

# Commands whose keys may be two-stroke keys (INST.ASM storekey: CM_COMMON..CM_FILER-1).
_TWO_STROKE = range(9, 88)


@dataclass
class Keymap:
    prefixes: list[int] = field(default_factory=list)
    keys: dict[int, list[int]] = field(default_factory=dict)  # command -> key codes
    messages: dict[int, str] = field(default_factory=dict)  # command -> help text

    def command(self, key_codes: Sequence[int], mode: Mode) -> int | None:
        """The command that the key runs in `mode`, or None.

        `key_codes` are the codes of one key press, to try in order (a terminal sends
        the same byte for [TAB] and ^I).
        """
        for numbers in _LOOKUP[mode]:
            for number in numbers:
                bound = self.keys.get(number)
                if bound and any(code in bound for code in key_codes):
                    return number
        return None

    def bind(self, command: int, *key_codes: int) -> None:
        self.keys.setdefault(command, []).extend(key_codes)


_LINE = re.compile(r"\s*(\d+)(.*)")


def parse_command_keys(text: str) -> Keymap:
    """Read the "* C" (command keys) section of a VZ DEF file.

    Each line is a command number, its keys, and ":" followed by its help text.
    Number 00 lists the prefix keys. Lines that do not start with a number are
    skipped, and ";" starts a comment.
    """
    keymap = Keymap()
    for raw in text.splitlines():
        match = _LINE.match(raw.split(";", 1)[0])
        if not match:
            continue
        number = int(match.group(1))
        key_part, colon, message = match.group(2).partition(":")
        if colon and message.strip():
            keymap.messages[number] = message.strip()
        tokens = key_part.split()
        if number == 0:
            keymap.prefixes = [codes.parse_key(token, [])[0] for token in tokens]
            continue
        for token in tokens:
            rest = token
            while rest:
                if number in _TWO_STROKE:
                    code, rest = codes.parse_keys(rest, keymap.prefixes)
                else:
                    code, rest = codes.parse_key(rest, keymap.prefixes)
                keymap.bind(number, code)
    return keymap


def default_keymap() -> Keymap:
    """The key bindings of VZ.DEF (IBM version), with pyvz's changes."""
    text = resources.files("pyvz.keys").joinpath("vz_keys.def").read_text("utf-8")
    keymap = parse_command_keys(text)
    q = keymap.prefixes.index(codes.ctrl("Q"))
    k = keymap.prefixes.index(codes.ctrl("K"))
    esc = keymap.prefixes.index(codes.ESC)

    # A terminal sends the same byte for ^[ and ESC, and ESC is a prefix key, so the
    # last command is repeated with ESC ESC instead of ^[.
    keymap.keys[Cmd.REPEAT] = [codes.stroke2(esc, 0x1B)]
    # VZ.DEF did these with macros 12, 13, 16 and 17.
    keymap.bind(Cmd.SCREEN_LINE_LEFT, codes.HOME, codes.stroke2(q, "["))
    keymap.bind(Cmd.SCREEN_LINE_RIGHT, codes.END, codes.stroke2(q, "]"))
    keymap.bind(Cmd.MARK_POSITION, codes.PREFIX_DIGIT | k)  # ^K1-^K4: set a mark
    keymap.bind(Cmd.LAST_POSITION, codes.PREFIX_DIGIT | q)  # ^Q1-^Q4: jump to a mark
    keymap.messages[Cmd.SCREEN_LINE_LEFT] = "画面の左端"
    keymap.messages[Cmd.SCREEN_LINE_RIGHT] = "画面の右端"
    return keymap


def follow(prefix_index: int, key_codes: Sequence[int] | None, ch: str | None):
    """The key made by pressing a key or typing `ch` after a prefix key.

    Returns (key code, digit). The digit is set when a digit followed the prefix key
    (VZ passes 0-15 for 0-9 and :;<=>?). Returns None when the key cannot follow a
    prefix key.
    """
    if ch is not None and len(ch) == 1:
        if "0" <= ch <= "?":
            return codes.PREFIX_DIGIT | prefix_index, ord(ch) - ord("0")
        if "@" <= ch.upper() <= "_":
            return codes.stroke2(prefix_index, ch.upper()), None
        return None
    if key_codes:
        control = key_codes[-1]  # [TAB] also comes as ^I, ESC as ^[
        if 0 <= control < 0x20:
            return codes.stroke2(prefix_index, control), None
    return None
