from pyvz.editor.layout import Layout
from pyvz.editor.window import Window
from pyvz.text.document import Document


def window(*lines: str, width: int = 10, height: int = 5) -> Window:
    w = Window(Document(lines=list(lines)), Layout(width=width))
    w.height = height
    return w


def at(w: Window) -> tuple[int, int]:
    return w.line, w.index


def test_up_and_down_keep_the_column_over_short_lines():
    w = window("abcdef", "ab", "abcdef")
    w.index = 5
    w.down()
    assert at(w) == (1, 2)
    w.down()
    assert at(w) == (2, 5)
    w.up()
    w.up()
    assert at(w) == (0, 5)


def test_up_and_down_go_by_folded_rows():
    w = window("abcdefghijklmn", "x")
    w.index = 3
    w.down()
    assert at(w) == (0, 13)
    w.down()
    assert at(w) == (1, 1)
    assert not w.down()


def test_left_and_right_cross_lines():
    w = window("ab", "cd")
    w.index = 2
    w.right()
    assert at(w) == (1, 0)
    w.left()
    assert at(w) == (0, 2)
    w.line, w.index = 0, 0
    assert not w.left()


def test_word_right_follows_vz():
    w = window("hello  world.txt", width=40)
    stops = []
    while w.index < len(w.lines[0]):
        w.word_right()
        stops.append(w.index)
    assert stops == [7, 13, 16]  # "world", "txt", the line end


def test_word_right_treats_kanji_and_hiragana_as_a_word():
    w = window("日本語のテキストです。漢字", width=40)
    w.word_right()
    assert w.index == 4  # テ
    w.word_right()
    assert w.index == 11  # 漢


def test_word_left_follows_vz():
    w = window("hello  world.txt", width=40)
    w.index = 16
    stops = []
    while w.index > 0:
        w.word_left()
        stops.append(w.index)
    assert stops == [13, 7, 0]


def test_word_moves_cross_lines():
    w = window("ab", "cd", width=40)
    w.index = 2
    w.word_right()
    assert at(w) == (1, 0)
    w.word_left()
    assert at(w) == (0, 2)


def test_row_left_and_right():
    w = window("abcdefghijklmn")
    w.index = 12
    w.row_left()
    assert w.index == 10
    w.index = 3
    w.row_right()
    assert w.index == 9
    w.index = 11
    w.row_right()
    assert w.index == 14


def test_keep_visible_scrolls_as_little_as_needed():
    w = window(*[str(i) for i in range(20)], height=5)
    w.line = 7
    w.keep_visible()
    assert w.top == (3, 0)  # the cursor on the last row
    w.line = 1
    w.keep_visible()
    assert w.top == (1, 0)


def test_scroll_keeps_the_cursor_on_the_same_row_of_the_window():
    w = window(*[str(i) for i in range(20)], height=5)
    w.line = 2
    w.scroll(4)
    assert w.line == 6
    assert w.top == (4, 0)
    assert w.screen_row() == 2
    w.scroll(-4)
    assert (w.line, w.top) == (2, (0, 0))


def test_scroll_stops_at_the_text_ends():
    w = window("0", "1", "2", height=5)
    assert not w.scroll(-1)
    w.scroll(10)
    assert w.line == 2


def test_window_top_and_end():
    w = window(*[str(i) for i in range(20)], height=5)
    w.top = (5, 0)
    w.line = 7
    w.window_end()
    assert w.line == 9
    w.window_end()  # already on the last row: scrolls
    assert (w.line, w.top) == (10, (6, 0))
    w.window_top()
    assert w.line == 6


def test_text_end_puts_the_cursor_on_the_last_row():
    w = window(*[str(i) for i in range(20)], height=5)
    w.text_end()
    assert at(w) == (19, 2)
    assert w.top == (15, 0)
    w.text_top()
    assert (at(w), w.top) == ((0, 0), (0, 0))


def test_insert_and_split_lines():
    w = window("abcd")
    w.index = 2
    w.insert("X\nY\nZ")
    assert w.lines == ["abX", "Y", "Zcd"]
    assert at(w) == (2, 1)
    assert w.doc.modified


def test_newline_copies_the_indent():
    w = window("\t  abc")
    w.index = 5
    w.newline()
    assert w.lines == ["\t  ab", "\t  c"]
    assert at(w) == (1, 3)


def test_newline_in_overwrite_mode_moves_to_the_next_line():
    w = window("ab", "cd")
    w.index = 1
    w.newline(overwrite=True)
    assert w.lines == ["ab", "cd"]
    assert at(w) == (1, 0)
    w.newline(overwrite=True)
    assert w.lines == ["ab", "cd", ""]
    assert at(w) == (2, 0)


def test_backspace_and_delete_join_lines():
    w = window("ab", "cd")
    w.line = 1
    assert w.backspace() == "\n"
    assert w.lines == ["abcd"]
    assert at(w) == (0, 2)
    assert w.backspace() == "b"
    assert w.delete() == "c"
    assert w.lines == ["ad"]
    w.index = 2
    assert w.delete() is None
    w.index = 0
    assert w.backspace() is None


def test_overwrite():
    w = window("abc")
    w.overwrite("X")
    w.index = 3
    w.overwrite("Y")
    assert w.lines == ["XbcY"]


def test_tab_in_overwrite_mode_moves_to_the_next_stop():
    w = window("abcdefghij", width=20)
    w.index = 1
    w.tab(overwrite=True)
    assert w.index == 8
    w.index = 0
    w.tab()
    assert w.lines[0] == "\tabcdefghij"


def test_delete_words_and_line_parts():
    # VZ deletes the run of characters of one class next to the cursor.
    w = window("hello  world.txt", width=40)
    w.index = 7
    assert w.delete_word() == "world"
    assert w.lines == ["hello  .txt"]
    assert w.delete_word_back() == "  "
    assert (w.lines, w.index) == (["hello.txt"], 5)
    assert w.delete_word() == "."
    w.index = 2
    assert w.delete_to_line_end() == "llotxt"
    assert w.delete_to_line_top() == "he"
    assert w.delete_to_line_top() is None


def test_delete_word_takes_kanji_and_hiragana_apart():
    w = window("漢字ひらがな", width=40)
    assert w.delete_word() == "漢字"


def test_delete_words_join_lines_at_the_ends():
    w = window("ab", "cd", width=40)
    w.index = 2
    assert w.delete_word() == "\n"
    assert w.lines == ["abcd"]
    w.index = 0
    assert w.delete_word_back() is None
