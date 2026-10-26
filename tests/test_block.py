from pathlib import Path

import pytest
from fakes import FakeConsole, FakeTerminal

from pyvz.editor.editor import Editor
from pyvz.editor.layout import Layout
from pyvz.editor.stack import TextStack
from pyvz.editor.window import BLOCK, CHAR, LINE, Window
from pyvz.keys.commands import Cmd
from pyvz.keys.keymap import default_keymap
from pyvz.text.document import Document
from pyvz.ui import view
from pyvz.ui.loop import Loop
from pyvz.ui.screen import Screen


def window(*lines: str) -> Window:
    w = Window(Document(lines=list(lines)), Layout(width=40))
    w.height = 10
    return w


def editor_with(*lines: str, answers=()) -> Editor:
    editor = Editor(FakeConsole(*answers))
    editor.resize(40, 10)
    editor.add(window(*lines))
    return editor


def at(w: Window) -> tuple[int, int]:
    return w.line, w.index


# Marks move with the text


def test_marks_move_with_inserts_and_deletes():
    w = window("abcdef", "ghi")
    w.marks["m"] = (0, 4)  # before "e"
    w.marks["n"] = (1, 1)  # before "h"
    w.index = 1
    w.insert("XY")  # aXYbcdef
    assert w.marks == {"m": (0, 6), "n": (1, 1)}
    w.insert("\n")  # aXY / bcdef / ghi
    assert w.marks == {"m": (1, 3), "n": (2, 1)}
    w.line, w.index = 0, 3
    w.delete()  # joins: aXYbcdef / ghi
    assert w.lines[:2] == ["aXYbcdef", "ghi"]
    assert w.marks == {"m": (0, 6), "n": (1, 1)}


def test_a_mark_inside_deleted_text_goes_to_where_it_was_deleted():
    w = window("abcdef")
    w.marks["m"] = (0, 3)
    w.index = 5
    w.delete_to_line_top()
    assert w.marks["m"] == (0, 0)


# Block ranges


def test_block_on_the_start_line_is_a_character_block():
    w = window("abcdef", "ghi")
    w.index = 1
    w.start_block()
    w.index = 4
    assert w.block_range() == (CHAR, (0, 1), (0, 4))
    assert w.text_between((0, 1), (0, 4)) == "bcd"


def test_line_block_takes_the_lines_before_the_cursor_line():
    w = window("one", "two", "three", "four")
    w.line, w.index = 1, 2
    w.start_block()
    w.line = 3
    assert w.block_range() == (LINE, (1, 0), (3, 0))
    assert w.text_between((1, 0), (3, 0)) == "two\nthree\n"
    w.line = 0  # upwards: from the cursor line to the line before the start
    assert w.block_range() == (LINE, (0, 0), (1, 0))


def test_character_block_across_lines():
    w = window("one", "two")
    w.index = 1
    w.start_block()
    w.block = CHAR
    w.line, w.index = 1, 2
    assert w.block_range() == (CHAR, (0, 1), (1, 2))
    assert w.text_between((0, 1), (1, 2)) == "ne\ntw"


def test_take_block_ends_it_and_keeps_the_mark():
    w = window("abcdef")
    w.start_block()
    w.index = 3
    assert w.take_block(delete=True) == (CHAR, "abc")
    assert w.lines == ["def"]
    assert w.block is None
    assert w.marks[BLOCK] == (0, 0)


def test_take_line():
    w = window("a", "b", "")
    w.line = 1
    assert w.take_line(delete=True) == "b\n"
    assert w.lines == ["a", ""]
    assert at(w) == (1, 0)
    assert w.take_line(delete=True) == ""  # the end of the text: nothing
    w.line = 0
    assert w.take_line(delete=False) == "a\n"
    assert w.lines == ["a", ""]


def test_take_the_last_line_without_a_line_end():
    w = window("a", "b")
    w.line = 1
    assert w.take_line(delete=True) == "b\n"
    assert w.lines == ["a", ""]


def test_put_lines_and_characters():
    w = window("abc", "def")
    w.line, w.index = 1, 2
    w.put(LINE, "x\ny\n")
    assert w.lines == ["abc", "x", "y", "def"]
    assert at(w) == (1, 1)  # on the first line put, at the same column
    assert w.marks[BLOCK] == (3, 0)  # where the lines end
    w.put(CHAR, "ZZ")
    assert w.lines[1] == "xZZ"
    assert at(w) == (1, 1)
    assert w.jump_block()
    assert at(w) == (1, 3)
    assert w.jump_block()
    assert at(w) == (1, 1)


# The editor


def test_cut_and_paste_lines():
    editor = editor_with("one", "two", "three", "")
    w = editor.window
    editor.run(Cmd.CUT)  # no block: the cursor line
    editor.run(Cmd.CUT)
    assert w.lines == ["three", ""]
    editor.run(Cmd.DOWN)
    editor.run(Cmd.PASTE)
    editor.run(Cmd.PASTE)
    assert w.lines == ["three", "one", "two", ""]
    assert len(editor.stack) == 0


def test_store_and_copy_leave_things_where_they_are():
    editor = editor_with("one", "")
    editor.run(Cmd.STORE)
    editor.run(Cmd.LOAD)
    editor.run(Cmd.LOAD)
    assert editor.window.lines == ["one", "one", "one", ""]
    assert len(editor.stack) == 1


def test_moving_decides_the_kind_of_block():
    editor = editor_with("abcdef", "ghijkl", "mnopqr", "")
    w = editor.window
    editor.run(Cmd.RIGHT)
    editor.run(Cmd.BLOCK)
    editor.run(Cmd.DOWN)  # vertical: a line block
    assert w.block_range() == (LINE, (0, 0), (1, 0))
    editor.run(Cmd.RIGHT)  # along the line: a character block
    assert w.block_range() == (CHAR, (0, 1), (1, 2))
    editor.run(Cmd.DOWN)
    assert w.block == LINE
    editor.run(Cmd.CUT)
    assert w.lines == ["mnopqr", ""]
    editor.run(Cmd.PASTE)
    assert w.lines == ["abcdef", "ghijkl", "mnopqr", ""]


def test_block_toggles_off():
    editor = editor_with("abc")
    editor.run(Cmd.BLOCK)
    editor.run(Cmd.BLOCK)
    assert editor.window.block_range() is None


def test_typing_makes_a_line_block_a_character_block():
    editor = editor_with("abc", "def")
    editor.run(Cmd.BLOCK)
    editor.run(Cmd.DOWN)
    editor.type("X")
    assert editor.window.block == CHAR


def test_the_stack_is_shared_by_the_texts():
    editor = editor_with("from first", "")
    editor.run(Cmd.CUT)
    editor.add(window("second"))
    editor.run(Cmd.PASTE)
    assert editor.window.lines == ["from first", "second"]


def test_empty_stack():
    editor = editor_with("abc")
    editor.run(Cmd.PASTE)
    assert editor.console.messages == ["テキストスタックは空です"]


def test_clear_stack_asks():
    editor = editor_with("abc", "", answers=(False, True))
    editor.run(Cmd.STORE)
    editor.run(Cmd.CLEAR_STACK)
    assert len(editor.stack) == 1
    editor.run(Cmd.CLEAR_STACK)
    assert len(editor.stack) == 0
    assert editor.console.questions == ["テキストスタックを消去します"] * 2


def test_read_only_text_can_be_stored_but_not_cut():
    editor = editor_with("abc", "")
    editor.window.doc.readonly = True
    editor.window.doc.path = Path("a.txt")
    editor.run(Cmd.CUT)
    assert editor.window.lines == ["abc", ""]
    assert len(editor.stack) == 0
    editor.run(Cmd.STORE)
    assert editor.stack.top() == (LINE, "abc\n")


def test_save_with_a_block_writes_the_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    editor = editor_with("one", "two", "three", "", answers=("part.txt",))
    editor.run(Cmd.DOWN)
    editor.run(Cmd.BLOCK)
    editor.run(Cmd.DOWN)
    editor.run(Cmd.DOWN)
    editor.run(Cmd.SAVE)
    assert (tmp_path / "part.txt").read_text() == "two\nthree\n"
    assert editor.window.block is None
    assert editor.console.messages == ["part.txt に出力しました"]


def test_stack_limit_drops_the_oldest():
    stack = TextStack(limit=10)
    stack.push(LINE, "12345\n")
    stack.push(LINE, "678\n")
    stack.push(CHAR, "abcd")
    assert [t for _, t in stack.items] == ["678\n", "abcd"]
    stack.push(CHAR, "x" * 20)  # too big alone: kept, the rest go
    assert len(stack) == 1


# On the screen and from the keys


def test_block_is_reversed_on_the_screen():
    editor = editor_with("abcdef", "")
    editor.run(Cmd.RIGHT)
    editor.run(Cmd.BLOCK)
    editor.run(Cmd.RIGHT)
    editor.run(Cmd.RIGHT)
    screen = Screen(40, 8)
    view.draw(screen, editor, view.Overlay())
    reversed_ = [screen.styles[1][c].reverse for c in range(5)]
    assert reversed_ == [False, True, True, False, False]


def test_vz_keys_for_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "a.txt"
    path.write_text("one\ntwo\nthree\n")
    # ^B ^X ^X ^Y: cut two lines; ^X ^J: put them after "three"; save and close.
    loop = Loop(FakeTerminal(b"\x02\x18\x18\x19", b"\x18\x0a", b"\x1bs\r\x1bc"), default_keymap())
    editor = Editor(loop)
    loop.editor = editor
    editor.open(path)
    loop.run()
    assert path.read_text() == "three\none\ntwo\n"
