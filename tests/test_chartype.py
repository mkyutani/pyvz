import pytest

from pyvz.text.chartype import ALNUM, HIRAGANA, SPACE, SYMBOL, WIDE, char_class


@pytest.mark.parametrize(
    ("ch", "cls"),
    [
        (" ", SPACE),
        ("\t", SPACE),
        ("　", SPACE),  # ideographic space
        ("a", ALNUM),
        ("9", ALNUM),
        ("_", ALNUM),
        ("é", ALNUM),
        ("ｱ", ALNUM),  # half-width katakana
        ("あ", HIRAGANA),
        ("ゝ", HIRAGANA),
        ("ア", WIDE),
        ("ー", WIDE),  # prolonged sound mark joins katakana words
        ("漢", WIDE),
        ("々", WIDE),
        ("Ａ", WIDE),
        ("１", WIDE),
        ("。", SYMBOL),
        ("「", SYMBOL),
        ("$", SYMBOL),
        ("-", SYMBOL),
        ("😀", SYMBOL),
    ],
)
def test_char_class(ch: str, cls: int):
    assert char_class(ch) == cls
