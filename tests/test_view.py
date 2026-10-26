from pathlib import Path

from pyvz.editor.editor import Editor
from pyvz.editor.window import Window
from pyvz.text.document import Document
from pyvz.ui import view
from pyvz.ui.screen import Screen


class Quiet:
    def message(self, text: str) -> None:
        pass

    def ask(self, question: str) -> bool | None:
        return None


def drawn(*lines: str, width: int = 40, height: int = 8, **kw):
    editor = Editor(Quiet())
    doc = Document(lines=list(lines), path=Path("/x/a.txt"))
    editor.windows.append(Window(doc, editor.layout, **kw))
    editor.resize(width, view.text_rows(height))
    screen = Screen(width, height)
    overlay = view.Overlay()
    view.draw(screen, editor, overlay)
    return screen, editor, overlay


def test_rows_of_the_screen():
    screen, _, _ = drawn("abc", "de", "")  # a text that ends with a line end
    assert screen.text(0).startswith(" 1 /x/a.txt")
    assert "P 挿入" in screen.text(0)
    assert screen.text(1).startswith("abc↵")
    assert screen.text(2).startswith("de↵")
    assert screen.text(3).startswith("[EOF]")
    assert screen.text(7).startswith("1フ ")  # labels cut to the width of 4 columns a key


def test_end_mark_without_a_final_newline_follows_the_text():
    screen, _, _ = drawn("abc", "de")
    assert screen.text(2).startswith("de[EOF]")
    assert screen.text(3).strip() == ""


def test_folded_line_has_one_line_end_mark():
    screen, _, _ = drawn("a" * 35, "", width=30)
    assert screen.text(1) == "a" * 30
    assert screen.text(2).startswith("aaaaa↵")


def test_control_characters_and_tabs():
    screen, _, _ = drawn("\x01\tb", "")
    assert screen.text(1).startswith("^A      b↵")


def test_cursor_position():
    screen, editor, _ = drawn("abc", "dあf")
    editor.window.line, editor.window.index = 1, 2
    view.draw(screen, editor, view.Overlay())
    assert screen.cursor == (2, 3)


def test_status_marks_and_position():
    screen, editor, _ = drawn("abc", cc=True)
    editor.window.doc.modified = True
    editor.window.index = 2
    view.draw(screen, editor, view.Overlay())
    assert screen.text(0).startswith(" 1 a.txt (CC) *")  # the prompt file: its name only
    assert screen.text(0).rstrip().endswith("1:3")


def test_long_name_keeps_its_end_and_the_text_number():
    screen, _, _ = drawn("abc", width=34)
    editor = Editor(Quiet())
    path = Path("/very/long/directory/name/for/the/file.txt")
    editor.windows.append(Window(Document(lines=["x"], path=path), editor.layout))
    view.draw(screen, editor, view.Overlay())
    assert screen.text(0).startswith(" 1 …")
    assert "file.txt" in screen.text(0)


def test_question_keeps_its_end_and_takes_the_cursor():
    screen, editor, overlay = drawn("abc", width=20)
    overlay.question = "/long/path/to/some/file.txt を出力しますか？ (Y/N) "
    view.draw(screen, editor, overlay)
    row = view.text_rows(8) + 1
    assert screen.text(row).startswith("…")
    assert "(Y/N)" in screen.text(row)
    assert screen.cursor[0] == row
