from fakes import FakeConsole

from pyvz.editor.editor import LEFT_RIGHT, UPPER_LOWER, Editor, Region
from pyvz.editor.window import Window
from pyvz.keys.commands import Cmd
from pyvz.text.document import Document
from pyvz.ui import view
from pyvz.ui.screen import Screen


def editor_with(*texts: str, answers=(), size=(40, 12)) -> Editor:
    editor = Editor(FakeConsole(*answers))
    editor.resize(*size)
    for text in texts:
        editor.add(Window(Document(lines=text.split("\n")), editor.layout))
    return editor


def shape(regions: list[Region]) -> list[tuple[int, int, int, int]]:
    return [(r.top, r.left, r.width, r.rows) for r in regions]


def test_one_text_is_not_split():
    editor = editor_with("only")
    editor.run(Cmd.SPLIT_MODE)
    assert editor.split is None
    assert shape(editor.regions()) == [(0, 0, 40, 9)]


def test_split_mode_goes_full_upper_lower_left_right_full():
    editor = editor_with("first", "second")  # "second" is being edited
    editor.run(Cmd.SPLIT_MODE)
    assert editor.split == UPPER_LOWER
    regions = editor.regions()
    # 12 rows: 10 for the windows with their status lines, then message and keys.
    assert shape(regions) == [(0, 0, 40, 4), (5, 0, 40, 4)]
    assert [r.window.lines[0] for r in regions] == ["second", "first"]
    editor.run(Cmd.SPLIT_MODE)
    assert editor.split == LEFT_RIGHT
    assert shape(editor.regions()) == [(0, 0, 20, 9), (0, 21, 19, 9)]
    editor.run(Cmd.SPLIT_MODE)
    assert editor.split is None
    assert shape(editor.regions()) == [(0, 0, 40, 9)]


def test_windows_get_their_own_sizes():
    editor = editor_with("a" * 30, "b")
    editor.run(Cmd.SPLIT_MODE)
    editor.run(Cmd.SPLIT_MODE)
    left, right = editor.regions()  # "b" is being edited, so it is on the left
    assert left.window.layout.width == 20
    assert right.window.layout.width == 19
    assert right.window.folded(0).rows == 2  # "a" * 30 folded at its own width


def test_switch_window_moves_the_cursor_between_the_halves():
    editor = editor_with("first", "second")
    editor.run(Cmd.SPLIT_MODE)
    before = shape(editor.regions())
    editor.run(Cmd.SWITCH_WINDOW)
    assert editor.window.lines == ["first"]
    assert shape(editor.regions()) == before
    assert editor.regions()[1].window is editor.window


def test_choosing_another_text_puts_it_where_the_cursor_is():
    editor = editor_with("a", "b", "c", answers=(0,))  # c being edited, b before it
    editor.run(Cmd.SPLIT_MODE)
    assert [r.window.lines[0] for r in editor.regions()] == ["c", "b"]
    editor.run(Cmd.SWITCH_TEXT)  # choose "a"
    assert [r.window.lines[0] for r in editor.regions()] == ["a", "b"]
    editor.run(Cmd.SWITCH_WINDOW)
    assert editor.window.lines == ["b"]


def test_closing_a_text_shown_ends_the_split():
    editor = editor_with("a", "b")
    editor.run(Cmd.SPLIT_MODE)
    editor.run(Cmd.CLOSE)
    assert editor.split is None
    assert editor.window.lines == ["a"]


def test_page_keys_use_the_height_of_the_window():
    editor = editor_with("\n".join(str(i) for i in range(30)), "x")
    editor.run(Cmd.SWITCH_WINDOW)
    editor.run(Cmd.SPLIT_MODE)
    editor.run(Cmd.PAGE_DOWN)
    assert editor.window.line == 3  # 4 rows: 3 at a time


def test_split_position_moves_with_the_cursor_keys():
    answers = (Cmd.UP, Cmd.UP, Cmd.RETURN, Cmd.RIGHT, Cmd.RETURN)
    editor = editor_with("a", "b", answers=answers)
    editor.run(Cmd.SPLIT_MODE)
    editor.run(Cmd.SPLIT_POSITION)
    assert shape(editor.regions()) == [(0, 0, 40, 2), (3, 0, 40, 6)]
    editor.run(Cmd.SPLIT_MODE)
    editor.run(Cmd.SPLIT_POSITION)
    assert shape(editor.regions())[0] == (0, 0, 22, 9)


def test_drawn_split_screens():
    editor = editor_with("upper", "lower")
    editor.run(Cmd.SWITCH_WINDOW)
    editor.run(Cmd.SPLIT_MODE)
    screen = Screen(40, 12)
    view.draw(screen, editor, view.Overlay())
    assert screen.text(0).startswith(" 1 ")
    assert screen.text(1).startswith("upper")
    assert screen.text(5).startswith(" 2 ")
    assert screen.text(6).startswith("lower")
    assert screen.cursor == (1, 0)
    assert screen.styles[5][0].dim and not screen.styles[0][0].dim
    editor.run(Cmd.SPLIT_MODE)
    screen = Screen(40, 12)
    view.draw(screen, editor, view.Overlay())
    assert screen.text(1)[:22] == "upper[EOF]" + " " * 10 + "│l"
