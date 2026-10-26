from pyvz.editor.layout import Layout, shown_as


def fold(line: str, width: int = 10, tab_size: int = 8):
    return Layout(width=width, tab_size=tab_size).fold(line)


def test_short_line_is_one_row():
    folded = fold("abc")
    assert folded.starts == (0,)
    assert folded.columns == (0, 1, 2, 3)
    assert folded.row_range(0) == (0, 3)


def test_long_line_folds_at_the_width():
    folded = fold("abcdefghijklm")
    assert folded.starts == (0, 10)
    assert folded.columns[10] == 0
    assert folded.row_of(9) == 0
    assert folded.row_of(10) == 1
    assert folded.row_of(13) == 1  # the line end


def test_wide_character_that_does_not_fit_goes_to_the_next_row():
    folded = fold("abcdefghi" + "あ")
    assert folded.starts == (0, 9)
    assert folded.columns[9] == 0


def test_full_last_row_puts_the_line_end_on_a_row_of_its_own():
    folded = fold("abcdefghij")
    assert folded.starts == (0, 10)
    assert folded.row_of(10) == 1
    assert folded.columns[10] == 0
    assert fold("").starts == (0,)


def test_tabs_go_to_the_next_stop_and_are_cut_at_the_edge():
    folded = fold("a\tb", tab_size=4)
    assert folded.columns == (0, 1, 4, 5)
    assert folded.widths[1] == 3
    folded = fold("abcdefgh\tx", width=10, tab_size=8)
    assert folded.widths[8] == 2  # from column 8 to the edge
    assert folded.starts == (0, 9)


def test_zero_width_characters_take_no_column():
    folded = fold("éx")
    assert folded.columns == (0, 1, 1, 2)


def test_index_at_column():
    folded = fold("aあb")
    assert folded.index_at(0, 0) == 0
    assert folded.index_at(0, 1) == 1
    assert folded.index_at(0, 2) == 1  # inside the wide character
    assert folded.index_at(0, 3) == 2
    assert folded.index_at(0, 9) == 3  # past the end: the line end


def test_index_at_past_the_end_of_a_folded_row_stays_on_the_row():
    folded = fold("abcdefghi" + "あ" + "x")
    assert folded.index_at(0, 9) == 8  # the row has columns 0-8 only
    assert folded.index_at(1, 9) == 11


def test_shown_as():
    assert shown_as("a", 1) is None
    assert shown_as("\t", 3) == "   "
    assert shown_as("\x01", 2) == "^A"
    assert shown_as("\x7f", 2) == "^?"
    assert shown_as("\x85", 4) == "\\x85"
    assert shown_as("\udcff", 4) == "\\xFF"
