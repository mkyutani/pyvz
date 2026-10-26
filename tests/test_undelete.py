from fakes import FakeConsole, FakeTerminal

from pyvz.editor.editor import Editor
from pyvz.editor.layout import Layout
from pyvz.editor.stack import Deleted
from pyvz.editor.window import Window
from pyvz.keys.commands import Cmd
from pyvz.keys.keymap import default_keymap
from pyvz.text.document import Document
from pyvz.ui.loop import Loop
from pyvz.ui.widgets import LineInput


def editor_with(*lines: str) -> Editor:
    editor = Editor(FakeConsole())
    editor.resize(40, 10)
    editor.add(Window(Document(lines=list(lines)), Layout(width=40)))
    return editor


def at(editor: Editor) -> tuple[int, int]:
    return editor.window.line, editor.window.index


# ^U


def test_backspaced_characters_come_back_one_at_a_time_before_the_cursor():
    editor = editor_with("abcdef")
    editor.window.index = 4
    for _ in range(3):
        editor.run(Cmd.BACKSPACE)
    assert editor.window.lines == ["aef"]
    editor.run(Cmd.UNDELETE)
    assert (editor.window.lines, at(editor)) == (["abef"], (0, 2))
    editor.run(Cmd.UNDELETE)
    editor.run(Cmd.UNDELETE)
    assert (editor.window.lines, at(editor)) == (["abcdef"], (0, 4))


def test_deleted_characters_come_back_after_the_cursor():
    editor = editor_with("abcdef")
    editor.window.index = 1
    editor.run(Cmd.DELETE)
    editor.run(Cmd.DELETE)
    editor.run(Cmd.UNDELETE)
    assert (editor.window.lines, at(editor)) == (["acdef"], (0, 1))


def test_undelete_puts_text_where_the_cursor_is_now():
    editor = editor_with("abc def")
    editor.window.index = 3
    editor.run(Cmd.DELETE_TO_LINE_TOP)  # "abc"
    editor.run(Cmd.LINE_END)
    editor.run(Cmd.UNDELETE)
    assert editor.window.lines == [" defabc"]


def test_joined_lines_come_apart_again():
    editor = editor_with("ab", "cd")
    editor.window.line = 1
    editor.run(Cmd.BACKSPACE)  # joins: abcd
    editor.run(Cmd.UNDELETE)
    assert (editor.window.lines, at(editor)) == (["ab", "cd"], (1, 0))
    editor.run(Cmd.LINE_TOP)
    editor.run(Cmd.UP)
    editor.run(Cmd.LINE_END)
    editor.run(Cmd.DELETE)  # joins from the end of the line
    editor.run(Cmd.UNDELETE)
    assert (editor.window.lines, at(editor)) == (["ab", "cd"], (0, 2))


def test_words_and_line_ends_come_back():
    editor = editor_with("hello world")
    editor.run(Cmd.DELETE_WORD)
    editor.run(Cmd.DELETE_TO_LINE_END)
    assert editor.window.lines == [""]
    editor.run(Cmd.UNDELETE)
    editor.run(Cmd.UNDELETE)
    assert editor.window.lines == ["hello world"]


def test_nothing_to_undelete():
    editor = editor_with("abc")
    editor.run(Cmd.UNDELETE)
    assert editor.window.lines == ["abc"]


def test_the_buffer_is_shared_by_the_texts():
    editor = editor_with("first")
    editor.run(Cmd.DELETE_WORD)
    editor.add(Window(Document(lines=["second "]), editor.layout))
    editor.run(Cmd.LINE_END)
    editor.run(Cmd.UNDELETE)
    assert editor.window.lines == ["second first"]


def test_cutting_a_block_does_not_go_to_the_buffer():
    editor = editor_with("abc", "")
    editor.run(Cmd.CUT)
    assert len(editor.deleted) == 0


def test_buffer_limit_drops_the_oldest():
    deleted = Deleted(limit=5)
    deleted.store("abc", back=True)
    deleted.store("de", back=True)
    deleted.store("f", back=False)
    assert deleted.items == [("de", True), ("f", False)]


def test_input_box_shares_the_buffer():
    editor = editor_with("x")
    line = LineInput("name.txt", deleted=editor.deleted)
    line.run(Cmd.DELETE_TO_LINE_TOP)
    assert line.text == ""
    editor.run(Cmd.UNDELETE)
    assert editor.window.lines == ["name.txtx"]


# ^QL


def test_cancel_puts_the_line_back_and_the_modified_flag_too():
    editor = editor_with("original", "next")
    editor.run(Cmd.LINE_END)
    editor.type("!!")
    editor.run(Cmd.BACKSPACE)
    editor.run(Cmd.LINE_TOP)
    editor.run(Cmd.DELETE)
    assert editor.window.lines[0] == "riginal!"
    assert editor.window.doc.modified
    editor.run(Cmd.CANCEL_LINE)
    assert editor.window.lines == ["original", "next"]
    assert not editor.window.doc.modified


def test_cancel_after_leaving_the_line_does_nothing():
    editor = editor_with("abc", "def")
    editor.type("X")
    editor.run(Cmd.DOWN)
    editor.run(Cmd.UP)
    editor.run(Cmd.CANCEL_LINE)
    assert editor.window.lines == ["Xabc", "def"]


def test_cancel_after_joining_lines_does_nothing():
    editor = editor_with("abc", "def")
    editor.window.line = 1
    editor.type("X")
    editor.run(Cmd.LINE_TOP)
    editor.run(Cmd.BACKSPACE)  # joins: abcXdef
    editor.run(Cmd.CANCEL_LINE)
    assert editor.window.lines == ["abcXdef"]


def test_cancel_keeps_the_cursor_in_the_line():
    editor = editor_with("abc")
    editor.run(Cmd.LINE_END)
    editor.type("defgh")
    editor.run(Cmd.CANCEL_LINE)
    assert at(editor) == (0, 3)


def test_vz_keys(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "a.txt"
    path.write_text("keep this\n")
    # ^T deletes "keep", ^QD goes to the line end, and ^U puts "keep" back after the
    # cursor. ^X ^E leave the line and come back, so ^QL takes back only the "!".
    keys = [b"\x14", b"\x11d", b"\x15", b"\x18\x05", b"!", b"\x11l", b"\x1bs\r\x1bc"]
    loop = Loop(FakeTerminal(*keys), default_keymap())
    editor = Editor(loop)
    loop.editor = editor
    editor.open(path)
    loop.run()
    assert path.read_text() == " thiskeep\n"
