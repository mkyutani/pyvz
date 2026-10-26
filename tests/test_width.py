import pytest

from pyvz.text.width import char_width, columns, index_at_column, next_tab_stop


@pytest.mark.parametrize(
    ("ch", "width"),
    [
        ("a", 1),
        ("あ", 2),
        ("漢", 2),
        ("Ａ", 2),  # full-width
        ("ｱ", 1),  # half-width katakana
        ("😀", 2),
        ("\x01", 2),  # ^A
        ("\x7f", 2),  # ^?
        ("\x85", 4),  # C1 control, shown as \x85
        ("\udcff", 4),  # a raw byte, shown as \xff
        ("́", 0),  # combining mark
        ("​", 0),  # zero width space
    ],
)
def test_char_width(ch: str, width: int):
    assert char_width(ch) == width


def test_ambiguous_width_follows_the_setting():
    assert char_width("─") == 1
    assert char_width("─", ambiguous_wide=True) == 2


def test_next_tab_stop():
    assert next_tab_stop(0, 8) == 8
    assert next_tab_stop(7, 8) == 8
    assert next_tab_stop(8, 8) == 16
    assert next_tab_stop(1, 4) == 4


def test_columns_with_tabs_and_wide_characters():
    assert columns("a\tあb", tab_size=4) == [0, 1, 4, 6, 7]


def test_index_at_column():
    line = "a\tあb"  # columns: a=0, tab=1..3, あ=4..5, b=6
    assert index_at_column(line, 0, tab_size=4) == 0
    assert index_at_column(line, 2, tab_size=4) == 1  # inside the tab
    assert index_at_column(line, 5, tab_size=4) == 2  # right half of あ
    assert index_at_column(line, 6, tab_size=4) == 3
    assert index_at_column(line, 7, tab_size=4) == 4  # past the end
