from pathlib import Path

import pytest
from fakes import FakeConsole

from pyvz.editor.editor import Editor
from pyvz.editor.window import Window
from pyvz.keys.commands import Cmd
from pyvz.text.document import Document


@pytest.fixture
def chdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def editor_with(path: Path, *answers: bool | None, cc: bool = False):
    console = FakeConsole(*answers)
    editor = Editor(console)
    editor.resize(80, 20)
    editor.open(path, cc=cc)
    return editor, console


def test_typing_and_saving(chdir: Path):
    path = chdir / "a.txt"
    path.write_text("abc\n")
    editor, console = editor_with(path, "a.txt")
    editor.type("X")
    editor.run(Cmd.LINE_END)
    editor.run(Cmd.RETURN)
    editor.type("de")
    assert editor.run(Cmd.SAVE)
    assert console.boxes == [("【出力ファイル】", "a.txt")]
    assert path.read_text() == "Xabc\nde\n"
    assert not editor.window.doc.modified


def test_save_under_another_name_renames_the_text(chdir: Path):
    path = chdir / "a.txt"
    path.write_text("abc\n")
    editor, _ = editor_with(path, "b.txt")
    editor.run(Cmd.SAVE)
    assert (chdir / "b.txt").read_text() == "abc\n"
    assert editor.name(editor.window) == "b.txt"


def test_save_over_another_file_asks(chdir: Path):
    (chdir / "a.txt").write_text("a\n")
    (chdir / "b.txt").write_text("b\n")
    editor, console = editor_with(chdir / "a.txt", "b.txt", False)
    editor.run(Cmd.SAVE)
    assert console.questions == ["b.txt はすでに存在します. 出力します"]
    assert (chdir / "b.txt").read_text() == "b\n"


def test_save_of_the_cc_prompt_under_another_name_writes_a_copy(chdir: Path):
    prompt = chdir / "claude-prompt-1.md"
    prompt.write_text("memo")
    editor, console = editor_with(prompt, "notes.md", cc=True)
    editor.run(Cmd.SAVE)
    assert (chdir / "notes.md").read_text() == "memo"
    assert editor.window.doc.path == prompt
    assert console.messages == ["notes.md に出力しました"]


def test_new_file_and_switching_texts(chdir: Path):
    (chdir / "a.txt").write_text("a\n")
    editor, console = editor_with(chdir / "a.txt", "b.txt", 0)
    editor.run(Cmd.NEW_FILE)
    assert editor.name(editor.window) == "b.txt"
    assert editor.window.doc.new_file
    editor.run(Cmd.SWITCH_TEXT)
    assert console.menus == [[("1", "a.txt"), ("2", "b.txt")]]
    assert editor.name(editor.window) == "a.txt"
    editor.run(Cmd.SWITCH_WINDOW)  # back to the text shown before
    assert editor.name(editor.window) == "b.txt"


def test_opening_an_open_file_shows_it(chdir: Path):
    (chdir / "a.txt").write_text("a\n")
    (chdir / "b.txt").write_text("b\n")
    editor, console = editor_with(chdir / "a.txt")
    editor.open_file(chdir / "b.txt")
    editor.open_file(chdir / "a.txt")
    assert len(editor.windows) == 2
    assert editor.current == 0
    assert console.messages[-1] == "a.txt はオープンされています"


def test_closing_a_text_goes_back_to_the_one_shown_before(chdir: Path):
    for name in "abc":
        (chdir / name).write_text(name)
    editor, _ = editor_with(chdir / "a")
    editor.open_file(chdir / "b")
    editor.open_file(chdir / "c")
    editor.show(0)
    editor.show(2)
    editor.run(Cmd.CLOSE)
    assert editor.name(editor.window) == "a"


def test_rename(chdir: Path):
    path = chdir / "a.txt"
    path.write_text("abc\n")
    editor, _ = editor_with(path, "c.txt")
    editor.run(Cmd.RENAME)
    assert editor.name(editor.window) == "c.txt"
    assert editor.window.doc.modified
    assert not (chdir / "c.txt").exists()


def test_overwrite_mode():
    editor = Editor(FakeConsole())
    editor.windows.append(Window(Document(lines=["abc"]), editor.layout))
    editor.run(Cmd.INSERT_MODE)
    editor.type("XY")
    assert editor.window.lines == ["XYc"]


def test_close_asks_to_save_a_changed_text(chdir: Path):
    path = chdir / "a.txt"
    path.write_text("abc\n")
    editor, console = editor_with(path, True)
    editor.type("X")
    editor.run(Cmd.CLOSE)
    assert console.questions == ["a.txt を出力します"]
    assert path.read_text() == "Xabc\n"
    assert editor.exit_code == 0


def test_close_without_saving(chdir: Path):
    path = chdir / "a.txt"
    path.write_text("abc\n")
    editor, _ = editor_with(path, False)
    editor.type("X")
    editor.run(Cmd.CLOSE)
    assert path.read_text() == "abc\n"
    assert editor.exit_code == 0


def test_close_cancelled(chdir: Path):
    path = chdir / "a.txt"
    path.write_text("abc\n")
    editor, _ = editor_with(path, None)
    editor.type("X")
    editor.run(Cmd.CLOSE)
    assert editor.exit_code is None
    assert editor.windows


def test_closing_the_cc_prompt_saves_without_asking(chdir: Path):
    path = chdir / "claude-prompt-x.md"
    path.write_text("draft")
    editor, console = editor_with(path, cc=True)
    editor.run(Cmd.LINE_END)
    editor.type(" more")
    editor.run(Cmd.CLOSE)
    assert console.questions == []
    assert path.read_text() == "draft more"
    assert editor.exit_code == 0


def test_closing_one_of_two_texts_keeps_editing(chdir: Path):
    (chdir / "a").write_text("a\n")
    (chdir / "b").write_text("b\n")
    editor = Editor(FakeConsole())
    editor.open(chdir / "a")
    editor.open(chdir / "b")
    editor.run(Cmd.CLOSE)
    assert editor.exit_code is None
    assert editor.window.lines == ["a", ""]


def test_quit_saves_changed_texts_then_asks_to_quit(chdir: Path):
    path = chdir / "a.txt"
    path.write_text("abc\n")
    editor, console = editor_with(path, True, True)
    editor.type("X")
    editor.run(Cmd.QUIT)
    assert console.questions == ["修正テキストを出力します", "エディタを終了します"]
    assert path.read_text() == "Xabc\n"
    assert editor.exit_code == 0


def test_quit_answered_no_stays(chdir: Path):
    path = chdir / "a.txt"
    path.write_text("abc\n")
    editor, _ = editor_with(path, False)
    editor.run(Cmd.QUIT)
    assert editor.exit_code is None


def test_escape_abandons_changes_after_asking(chdir: Path):
    path = chdir / "a.txt"
    path.write_text("abc\n")
    editor, console = editor_with(path, True)
    editor.type("X")
    editor.run(Cmd.ESCAPE)
    assert console.questions == ["編集テキストを放棄します"]
    assert path.read_text() == "abc\n"
    assert editor.exit_code == 0


def test_escape_without_changes_does_not_ask(chdir: Path):
    path = chdir / "a.txt"
    path.write_text("abc\n")
    editor, console = editor_with(path)
    editor.run(Cmd.ESCAPE)
    assert console.questions == []
    assert editor.exit_code == 0


def test_read_only_text_refuses_edits(chdir: Path):
    path = chdir / "a.txt"
    path.write_text("abc\n")
    editor, console = editor_with(path)
    editor.run(Cmd.READ_ONLY)
    editor.type("X")
    editor.run(Cmd.BACKSPACE)
    assert editor.window.lines == ["abc", ""]
    assert console.messages == ["a.txt はリードオンリーです"] * 2
    assert not editor.save(editor.window)


def test_repeat_runs_the_last_command_again(chdir: Path):
    path = chdir / "a.txt"
    path.write_text("abcdef\n")
    editor, _ = editor_with(path)
    editor.run(Cmd.RIGHT)
    editor.run(Cmd.REPEAT)
    editor.run(Cmd.REPEAT)
    assert editor.window.index == 3


def test_commands_not_there_yet():
    editor = Editor(FakeConsole())
    assert not editor.run(Cmd.READ_TAG)


def test_new_file_message(chdir: Path):
    editor, console = editor_with(chdir / "new.txt")
    assert console.messages == ["新規ファイルです"]
    assert editor.window.doc.new_file


def test_hold_outside_claude_code(chdir: Path):
    path = chdir / "a.txt"
    path.write_text("abc\n")
    editor, console = editor_with(path)
    editor.run(Cmd.COMMAND_LINE)
    assert console.messages == ["Claude Code から呼ばれていません"]


def test_file_menu_runs_the_command_chosen(chdir: Path):
    path = chdir / "a.txt"
    path.write_text("abc\n")
    editor, console = editor_with(path, 2, "a.txt")  # S, then the name in the box
    editor.type("X")
    editor.run(Cmd.FILE_MENU)
    assert console.menus[0][0] == ("O", "ファイルのオープン")
    assert ("E", "保留して Claude Code へ") not in console.menus[0]  # not a prompt file
    assert path.read_text() == "Xabc\n"


def test_help_lists_the_commands_and_runs_the_one_chosen(chdir: Path):
    path = chdir / "a.txt"
    path.write_text("abc\n")
    editor, console = editor_with(path, Cmd.LINE_END)
    editor.run(Cmd.HELP)
    assert Cmd.SAVE in console.helped and Cmd.HELP not in console.helped
    assert editor.window.index == 3
