"""Turning the bytes a terminal sends into key events.

The decoder understands xterm's escape sequences, which current terminals (Windows
Terminal included) send for special keys with Shift, Ctrl and Alt, and bracketed
paste. A lone ESC and ESC followed by a character (Alt) cannot be told apart from
the bytes alone: the caller waits a short time when `pending` is true, and calls
`flush` if nothing more arrives.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyvz.keys import codes


@dataclass(frozen=True)
class Key:
    """A key other than text. `codes` are its key codes, to look up in order."""

    codes: tuple[int, ...]


@dataclass(frozen=True)
class Char:
    """A typed character."""

    ch: str


@dataclass(frozen=True)
class Alt:
    """ESC followed at once by a character, which is what Alt+character sends."""

    ch: str


@dataclass(frozen=True)
class Paste:
    """Text pasted into the terminal (bracketed paste). Line ends are LF."""

    text: str


Event = Key | Char | Alt | Paste

_PASTE_START = "200"
_PASTE_END = b"\x1b[201~"

_FINAL_KEYS = {
    "A": codes.UP,
    "B": codes.DOWN,
    "C": codes.RIGHT,
    "D": codes.LEFT,
    "H": codes.HOME,
    "F": codes.END,
    "P": codes.special("F1"),
    "Q": codes.special("F2"),
    "R": codes.special("F3"),
    "S": codes.special("F4"),
}
_SS3_KEYS = {ord(k): v for k, v in _FINAL_KEYS.items()} | {ord("M"): codes.CR}
_TILDE_KEYS = {
    1: codes.HOME,
    2: codes.INS,
    3: codes.DEL,
    4: codes.END,
    5: codes.PGUP,
    6: codes.PGDN,
    7: codes.HOME,
    8: codes.END,
    11: codes.special("F1"),
    12: codes.special("F2"),
    13: codes.special("F3"),
    14: codes.special("F4"),
    15: codes.special("F5"),
    17: codes.special("F6"),
    18: codes.special("F7"),
    19: codes.special("F8"),
    20: codes.special("F9"),
    21: codes.special("F10"),
    23: codes.special("F11"),
    24: codes.special("F12"),
}


def control_key(byte: int) -> Key:
    """The key for a control byte. Some bytes are also VZ special keys."""
    if byte == 0x09:
        return Key((codes.TAB, 0x09))
    if byte == 0x0D:
        return Key((codes.CR, 0x0D))
    if byte == 0x1B:
        return Key((codes.ESC, 0x1B))
    if byte == 0x7F:  # the BS key on most terminals
        return Key((codes.BS, 0x08))
    if byte == 0x08:
        return Key((0x08, codes.BS))
    return Key((byte,))


def _with_modifier(key: int, parameter: int) -> int:
    """Apply xterm's modifier parameter (1 + Shift 1, Alt 2, Ctrl 4) to a special key.

    VZ has one modifier per key, so Ctrl wins over Alt, and Alt over Shift.
    """
    bits = parameter - 1
    if bits & 4:
        return key + codes.CTRL
    if bits & 2:
        return key + codes.ALT
    if bits & 1:
        return key + codes.SHIFT
    return key


def _csi_key(parameters: str, final: str) -> int | None:
    parts = parameters.split(";") if parameters else []
    if not all(part.isdigit() for part in parts):
        return None  # private sequences such as mouse reports
    numbers = [int(part) for part in parts]
    modifier = numbers[1] if len(numbers) >= 2 else 1
    if final == "Z":
        return codes.special("TAB", codes.SHIFT)
    if final == "~":
        key = _TILDE_KEYS.get(numbers[0]) if numbers else None
    else:
        key = _FINAL_KEYS.get(final)
    return None if key is None else _with_modifier(key, modifier)


def _utf8_length(lead: int) -> int:
    if 0xC2 <= lead <= 0xDF:
        return 2
    if 0xE0 <= lead <= 0xEF:
        return 3
    if 0xF0 <= lead <= 0xF4:
        return 4
    return 0


class Decoder:
    def __init__(self) -> None:
        self._buffer = bytearray()

    @property
    def pending(self) -> bool:
        """Some bytes wait for more to decide what they are."""
        return bool(self._buffer)

    def feed(self, data: bytes) -> list[Event]:
        self._buffer += data
        return self._drain(final=False)

    def flush(self) -> list[Event]:
        """Decide the waiting bytes, when no more came within the ESC delay.

        A paste that has not ended keeps waiting.
        """
        return self._drain(final=True)

    def _drain(self, final: bool) -> list[Event]:
        events: list[Event] = []
        while self._buffer:
            used, decoded = self._decode(final)
            if used == 0:
                break
            del self._buffer[:used]
            events.extend(decoded)
        return events

    def _decode(self, final: bool) -> tuple[int, list[Event]]:
        byte = self._buffer[0]
        if byte == 0x1B:
            return self._escape(final)
        if byte < 0x20 or byte == 0x7F:
            return 1, [control_key(byte)]
        used, ch = self._char(0, final)
        return used, ([Char(ch)] if used else [])

    def _char(self, start: int, final: bool) -> tuple[int, str]:
        """Decode one UTF-8 character at `start`. A bad byte becomes a lone surrogate."""
        buffer = self._buffer
        lead = buffer[start]
        if lead < 0x80:
            return 1, chr(lead)
        length = _utf8_length(lead)
        available = bytes(buffer[start : start + length])
        if length and len(available) < length:
            if not final and all(0x80 <= b <= 0xBF for b in available[1:]):
                return 0, ""
        elif length:
            try:
                return length, available.decode("utf-8")
            except UnicodeDecodeError:
                pass
        return 1, chr(0xDC00 + lead)

    def _escape(self, final: bool) -> tuple[int, list[Event]]:
        buffer = self._buffer
        if len(buffer) == 1:
            return (1, [control_key(0x1B)]) if final else (0, [])
        second = buffer[1]
        if second == ord("["):
            return self._csi(final)
        if second == ord("O"):
            if len(buffer) == 2:
                return (2, [Alt("O")]) if final else (0, [])
            key = _SS3_KEYS.get(buffer[2])
            if key is not None:
                return 3, [Key((key,))]
            return 2, [Alt("O")]
        if second < 0x20 or second == 0x7F:
            # ESC ESC, or ESC and a control key: the ESC key on its own.
            return 1, [control_key(0x1B)]
        used, ch = self._char(1, final)
        if used == 0:
            return 0, []
        return 1 + used, [Alt(ch)]

    def _csi(self, final: bool) -> tuple[int, list[Event]]:
        buffer = self._buffer
        end = next((i for i in range(2, len(buffer)) if 0x40 <= buffer[i] <= 0x7E), None)
        if end is None:
            return (2, [Alt("[")]) if final else (0, [])
        parameters = bytes(buffer[2:end]).decode("ascii", "replace")
        final_char = chr(buffer[end])
        used = end + 1
        if final_char == "~" and parameters == _PASTE_START:
            close = buffer.find(_PASTE_END, used)
            if close < 0:
                return 0, []  # wait for the rest of the paste, however long it takes
            text = bytes(buffer[used:close]).decode("utf-8", "surrogateescape")
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            return close + len(_PASTE_END), [Paste(text)]
        key = _csi_key(parameters, final_char)
        return used, ([Key((key,))] if key is not None else [])
