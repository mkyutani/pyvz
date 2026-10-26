from pathlib import Path

from fakes import FakeTerminal

from pyvz.editor.editor import Editor
from pyvz.history import History
from pyvz.keys.commands import Cmd
from pyvz.keys.keymap import default_keymap
from pyvz.ui.loop import Loop
from pyvz.ui.screen import Screen
from pyvz.ui.widgets import InputBox, Item, LineInput, Menu, frame


def loop_with(*chunks: bytes | None, history: History | None = None) -> Loop:
    loop = Loop(FakeTerminal(*chunks), default_keymap(), history)
    editor = Editor(loop)
    loop.editor = editor
    loop.resize()
    return loop


def test_frame_with_title_and_footer():
    screen = Screen(12, 3)
    frame(screen, 0, 0, 3, 12, title="【名】", footer=" 3 ")
    assert screen.text(0) == "┌【名】" + "─" * 4 + "┐"  # 【名】 takes 6 columns
    assert screen.text(1) == "│" + " " * 10 + "│"
    assert screen.text(2) == "└ 3 " + "─" * 7 + "┘"


def test_line_input_edits_with_line_commands():
    line = LineInput("hello world")
    line.run(Cmd.WORD_LEFT)
    line.run(Cmd.DELETE_TO_LINE_END)
    line.type("there")
    assert line.text == "hello there"
    line.run(Cmd.LINE_TOP)
    line.run(Cmd.DELETE)
    assert line.text == "ello there"
    line.type("a\nb")
    assert line.text == "a bello there"


def test_line_input_history():
    line = LineInput("typed", ["old", "new"])
    line.run(Cmd.UP)
    assert line.text == "new"
    line.run(Cmd.UP)
    line.run(Cmd.UP)
    assert line.text == "old"
    line.run(Cmd.DOWN)
    line.run(Cmd.DOWN)
    assert line.text == "typed"


def test_input_box_scrolls_to_show_the_cursor():
    screen = Screen(30, 5)
    line = LineInput("x" * 40)
    InputBox("【入力ファイル】", line, width=20).draw(screen)
    assert screen.text(2).strip() == "│" + "x" * 17 + " │"  # a column for the cursor
    assert screen.cursor == (2, 5 + 1 + 17)


def test_menu_draws_items_with_the_current_one_reversed():
    screen = Screen(20, 6)
    menu = Menu([Item("C", "コピー"), Item("D", "削除")], current=1)
    menu.draw(screen)
    assert screen.text(2).startswith("│ C コピー")
    assert screen.styles[3][2].reverse
    assert menu.find("d") == 1


def test_gets_returns_the_line_and_keeps_history(tmp_path: Path):
    history = History(tmp_path / "history.json")
    loop = loop_with(b"abc", b"\x7f", b"d\r", history=history)
    assert loop.gets("【入力ファイル】", kind="file") == "abd"
    assert History(tmp_path / "history.json").get("file") == ["abd"]


def test_gets_is_cancelled_with_esc():
    loop = loop_with(b"abc", b"\x1b", None)
    assert loop.gets("【入力ファイル】") is None


def test_gets_recalls_history(tmp_path: Path):
    history = History(tmp_path / "history.json")
    history.add("file", "first.txt")
    loop = loop_with(b"\x1b[A", b"\r", history=history)
    assert loop.gets("【入力ファイル】", kind="file") == "first.txt"


def test_menu_by_letter_cursor_and_sideways():
    items = [Item("C", "コピー"), Item("M", "移動"), Item("D", "削除")]
    assert loop_with(b"m").menu(items) == 1
    assert loop_with(b"\x1b[B", b"\x1b[B", b"\r").menu(items) == 2
    assert loop_with(b"\x1b[A", b"\r").menu(items) == 2  # wraps around
    assert loop_with(b"\x1b[C").menu(items, sideways=True) == "right"
    assert loop_with(b"\x1b", None).menu(items) is None


def test_choose_among_several_answers():
    assert loop_with(b"a").choose("上書きしますか？ (Y/N/A/S) ", "YNAS") == "A"
    assert loop_with(b"\r").choose("? ", "YNAS") == "Y"
    assert loop_with(b"\x1b", None).choose("? ", "YNAS") is None


def test_menu_takes_plain_pairs():
    assert loop_with(b"d").menu([("C", "コピー"), ("D", "削除")]) == 1
