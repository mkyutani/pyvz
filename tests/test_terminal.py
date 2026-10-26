import pytest

from pyvz.keys import codes
from pyvz.keys.codes import ALT, CTRL, SHIFT, special
from pyvz.keys.terminal import Alt, Char, Decoder, Key, Paste


def decode(data: bytes) -> list:
    decoder = Decoder()
    events = decoder.feed(data)
    return events + decoder.flush()


def test_text_and_utf8():
    assert decode("aあ😀".encode()) == [Char("a"), Char("あ"), Char("😀")]


def test_utf8_split_across_reads():
    decoder = Decoder()
    data = "あ".encode()
    assert decoder.feed(data[:1]) == []
    assert decoder.pending
    assert decoder.feed(data[1:]) == [Char("あ")]


def test_invalid_utf8_becomes_a_surrogate():
    assert decode(b"\xff") == [Char("\udcff")]


@pytest.mark.parametrize(
    ("byte", "key"),
    [
        (0x05, Key((0x05,))),  # ^E
        (0x00, Key((0x00,))),  # ^@ (Ctrl+Space)
        (0x09, Key((codes.TAB, 0x09))),
        (0x0D, Key((codes.CR, 0x0D))),
        (0x0A, Key((0x0A,))),  # ^J, not Enter
        (0x7F, Key((codes.BS, 0x08))),
        (0x08, Key((0x08, codes.BS))),
    ],
)
def test_control_bytes(byte: int, key: Key):
    assert decode(bytes([byte])) == [key]


def test_lone_esc_waits_then_is_esc():
    decoder = Decoder()
    assert decoder.feed(b"\x1b") == []
    assert decoder.pending
    assert decoder.flush() == [Key((codes.ESC, 0x1B))]


def test_esc_then_letter_at_once_is_alt():
    assert decode(b"\x1bo") == [Alt("o")]
    assert decode(b"\x1bO") == [Alt("O")]  # not an SS3 sequence when nothing follows


def test_esc_typed_slowly_is_esc_then_the_letter():
    decoder = Decoder()
    assert decoder.feed(b"\x1b") == []
    assert decoder.flush() == [Key((codes.ESC, 0x1B))]
    assert decoder.feed(b"o") == [Char("o")]


def test_esc_esc():
    assert decode(b"\x1b\x1b") == [Key((codes.ESC, 0x1B)), Key((codes.ESC, 0x1B))]


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"\x1b[A", codes.UP),
        (b"\x1b[D", codes.LEFT),
        (b"\x1bOA", codes.UP),  # application cursor mode
        (b"\x1b[1;2A", special("UP", SHIFT)),
        (b"\x1b[1;5D", special("<--", CTRL)),
        (b"\x1b[1;3C", special("-->", ALT)),
        (b"\x1b[1;6B", special("DOWN", CTRL)),  # Ctrl+Shift: Ctrl wins
        (b"\x1b[H", codes.HOME),
        (b"\x1b[4~", codes.END),
        (b"\x1b[2~", codes.INS),
        (b"\x1b[3;5~", special("DEL", CTRL)),
        (b"\x1b[5~", codes.PGUP),
        (b"\x1b[6;2~", special("PGDN", SHIFT)),
        (b"\x1bOP", special("F1")),
        (b"\x1b[1;2P", special("F1", SHIFT)),
        (b"\x1b[15~", special("F5")),
        (b"\x1b[24~", special("F12")),
        (b"\x1b[20;2~", special("F9", SHIFT)),
        (b"\x1b[Z", special("TAB", SHIFT)),
    ],
)
def test_escape_sequences(data: bytes, code: int):
    assert decode(data) == [Key((code,))]


def test_escape_sequence_split_across_reads():
    decoder = Decoder()
    assert decoder.feed(b"\x1b[1;") == []
    assert decoder.feed(b"5A") == [Key((special("UP", CTRL),))]


def test_unknown_sequences_are_dropped():
    assert decode(b"\x1b[<0;10;5Mx") == [Char("x")]  # a mouse report


def test_bracketed_paste():
    data = b"\x1b[200~line 1\r\nline 2\x1b[201~"
    assert decode(data) == [Paste("line 1\nline 2")]


def test_paste_waits_for_its_end_even_after_a_flush():
    decoder = Decoder()
    assert decoder.feed(b"\x1b[200~part") == []
    assert decoder.flush() == []
    assert decoder.feed(b" two\x1b[201~a") == [Paste("part two"), Char("a")]
