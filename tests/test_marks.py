from fakes import FakeConsole, FakeTerminal

from pyvz.editor.editor import Editor
from pyvz.editor.layout import Layout
from pyvz.editor.window import Window
from pyvz.keys.commands import Cmd
from pyvz.keys.keymap import default_keymap
from pyvz.text.document import Document
from pyvz.ui.loop import Loop


def editor_with(*lines: str, answers=()) -> Editor:
    editor = Editor(FakeConsole(*answers))
    editor.resize(40, 10)
    editor.add(Window(Document(lines=list(lines), path=None), Layout(width=40)))
    return editor


def at(editor: Editor) -> tuple[int, int]:
    return editor.window.line, editor.window.index


# Marks


def test_qp_goes_back_and_forth_after_a_long_jump():
    editor = editor_with(*[f"line {i}" for i in range(30)])
    editor.window.line, editor.window.index = 5, 3
    editor.run(Cmd.TEXT_END)
    editor.run(Cmd.LAST_POSITION)
    assert at(editor) == (5, 3)
    editor.run(Cmd.LAST_POSITION)
    assert at(editor) == (29, 7)


def test_qm_keeps_the_position_for_qp():
    editor = editor_with("abc", "def")
    editor.window.index = 2
    editor.run(Cmd.MARK_POSITION)
    assert editor.console.messages == ["マークしました"]
    editor.run(Cmd.DOWN)
    editor.run(Cmd.LAST_POSITION)
    assert at(editor) == (0, 2)


def test_numbered_marks():
    editor = editor_with("abc", "def", "ghi")
    editor.window.line = 1
    editor.run(Cmd.MARK_POSITION, 2)  # ^K2
    assert editor.console.messages == ["マーク #2"]
    editor.run(Cmd.TEXT_TOP)
    editor.run(Cmd.LAST_POSITION, 2)  # ^Q2
    assert at(editor) == (1, 0)
    editor.run(Cmd.LAST_POSITION, 3)  # not set: nothing
    assert at(editor) == (1, 0)
    editor.run(Cmd.LAST_POSITION)  # back to where ^Q2 came from
    assert at(editor) == (0, 0)


def test_marks_move_with_the_text():
    editor = editor_with("abc", "def")
    editor.window.line, editor.window.index = 1, 1
    editor.run(Cmd.MARK_POSITION, 1)
    editor.run(Cmd.TEXT_TOP)
    editor.run(Cmd.RETURN)
    editor.run(Cmd.LAST_POSITION, 1)
    assert at(editor) == (2, 1)


def test_setting_the_search_string_keeps_the_position():
    editor = editor_with("one", "two", "one", answers=("one",))
    editor.window.line = 1
    editor.run(Cmd.SET_SEARCH)
    editor.run(Cmd.PAGE_DOWN)
    assert at(editor) == (2, 0)
    editor.run(Cmd.LAST_POSITION)
    assert at(editor) == (1, 0)


# Jumps


def test_jump_to_a_line_number():
    editor = editor_with("a", "b", "c", answers=("2", "99", "x"))
    editor.window.index = 1
    editor.run(Cmd.JUMP_LINE)
    assert at(editor) == (1, 0)
    editor.run(Cmd.JUMP_LINE)
    assert at(editor) == (2, 0)
    editor.run(Cmd.JUMP_LINE)
    assert editor.console.messages[-1] == "x は行番号ではありません"
    editor.run(Cmd.LAST_POSITION)
    assert at(editor) == (1, 0)


def test_matching_brackets_across_lines_and_nesting():
    editor = editor_with("f(a, (b))", "{", "  [x]", "}")
    editor.window.index = 1
    editor.run(Cmd.MATCH_BRACKET)
    assert at(editor) == (0, 8)
    editor.run(Cmd.MATCH_BRACKET)
    assert at(editor) == (0, 1)
    editor.window.line, editor.window.index = 1, 0
    editor.run(Cmd.MATCH_BRACKET)
    assert at(editor) == (3, 0)
    editor.run(Cmd.MATCH_BRACKET)
    assert at(editor) == (1, 0)


def test_no_matching_bracket():
    editor = editor_with("(open", "x")
    editor.run(Cmd.MATCH_BRACKET)
    assert editor.console.messages == ["括弧が見つかりません"]
    editor.run(Cmd.DOWN)
    editor.run(Cmd.MATCH_BRACKET)
    assert editor.console.messages[-1] == "括弧が見つかりません"


# Small edits


def test_change_case_of_the_word_at_the_cursor():
    editor = editor_with("Hello_World2 more")
    editor.run(Cmd.CHANGE_CASE)
    assert editor.window.lines == ["hello_world2 more"]
    editor.run(Cmd.CHANGE_CASE)
    assert editor.window.lines == ["HELLO_WORLD2 more"]
    assert at(editor) == (0, 0)


def test_control_char_and_file_name():
    editor = editor_with("x", answers=("\x01",))
    editor.run(Cmd.CONTROL_CHAR)
    assert editor.window.lines == ["\x01x"]
    editor.window.doc.path = None
    editor.run(Cmd.COPY_FILE_NAME)  # no name: nothing
    assert editor.window.lines == ["\x01x"]


def test_control_char_keys_from_the_terminal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "a.txt"
    path.write_text("\n")
    # ^P ^A, ^P B (a letter), ^P [TAB], ^P ^J (refused), then ^QN types the file name.
    keys = [b"\x10\x01", b"\x10b", b"\x10\t", b"\x10\n", b"\x11n", b"\x1bs\r\x1bc"]
    loop = Loop(FakeTerminal(*keys), default_keymap())
    editor = Editor(loop)
    loop.editor = editor
    editor.open(path)
    loop.run()
    assert path.read_text() == "\x01\x02\ta.txt\n"
