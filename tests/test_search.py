import pytest
from fakes import FakeConsole, FakeTerminal

from pyvz.editor.editor import Editor
from pyvz.editor.layout import Layout
from pyvz.editor.search import Finder, Options, compile_search, literal
from pyvz.editor.window import Window
from pyvz.keys.commands import Cmd
from pyvz.keys.keymap import default_keymap
from pyvz.text.document import Document
from pyvz.ui.loop import Loop


def found(text: str, search: str, options: Options | None = None) -> list[str]:
    finder = Finder(text.split("\n"))
    return [m.group() for m in finder.matches(compile_search(search, options))]


# Search strings


def test_plain_search_finds_inside_words():
    assert found("cat concat cats", "cat") == ["cat", "cat", "cat"]


def test_word_search_needs_boundaries():
    word = Options(word=True)
    assert found("cat concat cats cat.", "cat", word) == ["cat", "cat"]
    assert found("cat concat cats", "*cat", word) == ["cat", "cat"]  # concat too
    assert found("cat concat cats", "cat*", word) == ["cat", "cat"]  # cats too


def test_star_without_word_search_asks_for_a_boundary():
    assert found("cat concat cats", "*cat") == ["cat", "cat"]  # not concat


def test_word_search_next_to_kanji_and_symbols():
    word = Options(word=True)
    assert found("漢字cat漢字 xcat", "cat", word) == ["cat"]
    assert found("a.b", ".", word) == ["."]


def test_options_written_in_the_string():
    assert found("Cat cat CAT", "\\C cat") == ["Cat", "cat", "CAT"]
    assert found("Cat cat", "cat", Options(ignore_case=True)) == ["Cat", "cat"]
    assert found("Cat cat", "\\W cat", Options(ignore_case=True)) == ["cat"]  # just W


def test_escapes():
    assert found("a*b a\\b", "a\\*b") == ["a*b"]
    assert found("a*b a\\b", "a\\\\b") == ["a\\b"]
    assert found("end\nstart", "d\\ns") == ["d\ns"]
    assert found("a\\nb", "\\I a\\nb") == ["a\\nb"]


def test_regular_expressions():
    assert found("item1 item22", "\\X item(\\d+)") == ["item1", "item22"]
    with pytest.raises(ValueError):
        compile_search("\\X (")


def test_full_and_half_width_the_same():
    assert found("ＡＢＣ abc ABC", "ABC", Options(zenhan=True)) == ["ＡＢＣ", "ABC"]


def test_empty_search_string_is_refused():
    with pytest.raises(ValueError):
        compile_search("")


def test_literal_escapes_the_marks():
    assert found("a*b\\c", literal("a*b\\c")) == ["a*b\\c"]


def test_finder_forward_and_backward_across_lines():
    finder = Finder(["one two", "two one"])
    pattern = compile_search("two")
    assert finder.pos(finder.forward(pattern, (0, 0)).start()) == (0, 4)
    assert finder.pos(finder.forward(pattern, (0, 4)).start()) == (1, 0)
    assert finder.forward(pattern, (1, 0)) is None
    assert finder.pos(finder.backward(pattern, (1, 0)).start()) == (0, 4)
    assert finder.backward(pattern, (0, 4)) is None


# The editor


def editor_with(*lines: str, answers=()) -> Editor:
    editor = Editor(FakeConsole(*answers))
    editor.resize(40, 10)
    editor.add(Window(Document(lines=list(lines)), Layout(width=40)))
    return editor


def at(editor: Editor) -> tuple[int, int]:
    return editor.window.line, editor.window.index


def test_set_search_then_page_keys_search():
    editor = editor_with("one two", "two one", answers=("two",))
    editor.run(Cmd.SET_SEARCH)
    assert editor.paging == "S"
    assert editor.console.messages == ["two"]
    editor.run(Cmd.PAGE_DOWN)
    assert at(editor) == (0, 4)
    editor.run(Cmd.PAGE_DOWN)
    assert at(editor) == (1, 0)
    editor.run(Cmd.PAGE_DOWN)
    assert editor.console.messages[-1] == "文字列が見つかりません"
    assert at(editor) == (1, 0)
    editor.run(Cmd.PAGE_UP)
    assert at(editor) == (0, 4)


def test_empty_search_string_goes_back_to_paging():
    editor = editor_with("abc", answers=("abc", ""))
    editor.run(Cmd.SET_SEARCH)
    editor.run(Cmd.SET_SEARCH)
    assert editor.paging == "P"


def test_paging_mode_toggles_only_with_a_search_string():
    editor = editor_with("abc", answers=("b",))
    editor.run(Cmd.PAGING_MODE)
    assert editor.paging == "P"
    editor.run(Cmd.SET_SEARCH)
    editor.run(Cmd.PAGING_MODE)
    assert editor.paging == "P"
    editor.run(Cmd.PAGING_MODE)
    assert editor.paging == "S"


def test_get_word_takes_the_run_of_one_class_at_the_cursor():
    editor = editor_with("foo_bar(x) foo_bar")
    editor.run(Cmd.GET_WORD)
    assert editor.search == "foo_bar"
    assert editor.console.remembered == [("search", "foo_bar")]
    editor.run(Cmd.PAGE_DOWN)
    assert at(editor) == (0, 11)


def test_get_word_takes_a_block():
    editor = editor_with("say a*b here, a*b")
    editor.window.index = 4
    editor.run(Cmd.BLOCK)
    for _ in range(3):
        editor.run(Cmd.RIGHT)
    editor.run(Cmd.GET_WORD)
    assert editor.search == "a\\*b"
    editor.run(Cmd.PAGE_DOWN)
    assert at(editor) == (0, 14)


def test_copy_string_types_it():
    editor = editor_with("x", answers=("abc", "abc"))
    editor.run(Cmd.SET_SEARCH)
    editor.run(Cmd.COPY_STRING)
    assert editor.window.lines == ["abcx"]
    assert editor.console.boxes[-1] == ("【複写文字列】", "abc")


def test_replace_all_at_once_in_the_whole_text():
    editor = editor_with("a cat", "cats", answers=("cat", "dog", 0, True))
    editor.window.line = 1
    editor.run(Cmd.REPLACE)
    assert editor.window.lines == ["a dog", "dogs"]
    assert editor.console.menus[-1][0] == ("A", "テキスト全体")
    assert editor.console.questions == ["全部一度に置換します"]
    assert editor.console.messages[-1] == "2 個の文字列を置換しました"


def test_replace_after_the_cursor():
    editor = editor_with("cat cat cat", answers=("cat", "dog", 1, True))
    editor.window.index = 4
    editor.run(Cmd.REPLACE)
    assert editor.window.lines == ["cat dog dog"]


def test_replace_before_the_cursor():
    editor = editor_with("cat cat cat", answers=("cat", "dog", 2, True))
    editor.window.index = 4
    editor.run(Cmd.REPLACE)
    assert editor.window.lines == ["dog cat cat"]


def test_replace_asking_about_each():
    editor = editor_with("cat cat cat", answers=("cat", "dog", 0, False, True, False, None))
    editor.run(Cmd.REPLACE)
    assert editor.window.lines == ["dog cat cat"]
    assert editor.console.questions[1:] == ["置換します"] * 3
    assert editor.console.messages[-1] == "1 個の文字列を置換しました"
    assert editor.window.found is None


def test_replace_in_a_block():
    editor = editor_with("x", "x", "x", "x", answers=("x", "y", True))
    editor.run(Cmd.DOWN)
    editor.run(Cmd.BLOCK)
    editor.run(Cmd.DOWN)
    editor.run(Cmd.DOWN)
    editor.run(Cmd.REPLACE)
    assert editor.window.lines == ["x", "y", "y", "x"]


def test_replace_with_regular_expression_groups_and_line_ends():
    editor = editor_with("key=value", answers=("\\X (\\w+)=(\\w+)", "\\2: \\1", 0, True))
    editor.run(Cmd.REPLACE)
    assert editor.window.lines == ["value: key"]
    editor = editor_with("a,b", answers=(",", "\\n", 0, True))
    editor.run(Cmd.REPLACE)
    assert editor.window.lines == ["a", "b"]


def test_replace_that_grows_does_not_loop():
    editor = editor_with("a a", answers=("a", "aa", 0, True))
    editor.run(Cmd.REPLACE)
    assert editor.window.lines == ["aa aa"]


def test_replace_again():
    editor = editor_with("cat", "", answers=("cat", "dog", 0, True))
    editor.run(Cmd.REPLACE)
    editor.window.lines[1] = "cat"
    editor.run(Cmd.REPLACE_AGAIN)
    assert editor.window.lines == ["dog", "dog"]


def test_esc_on_the_replacement_goes_back_to_the_search_string():
    editor = editor_with("cat", answers=("cat", None, "cat", "dog", 0, True))
    editor.run(Cmd.REPLACE)
    assert editor.window.lines == ["dog"]


def test_insert_line_keeps_the_indent():
    editor = editor_with("  indented")
    editor.window.index = 5
    editor.run(Cmd.INSERT_LINE)
    assert editor.window.lines == ["  ", "  indented"]
    assert at(editor) == (0, 2)


def test_vz_keys(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "a.txt"
    path.write_text("alpha beta\nbeta gamma\n")
    # ^QF beta Enter, ^C (forward) twice, then type "*" at the second "beta".
    keys = [b"\x11f", b"beta\r", b"\x03", b"\x03", b"*", b"\x1bs\r\x1bc"]
    loop = Loop(FakeTerminal(*keys), default_keymap())
    editor = Editor(loop)
    loop.editor = editor
    editor.open(path)
    loop.run()
    assert path.read_text() == "alpha beta\n*beta gamma\n"
