from datetime import datetime
from pathlib import Path

import pytest
from fakes import FakeTerminal

from pyvz.editor.editor import Editor
from pyvz.filer.filer import LEFT, RIGHT, Filer, Insert, Open
from pyvz.keys.keymap import default_keymap
from pyvz.ui.filerui import FilerLayer, FilerScreen, date_text
from pyvz.ui.loop import Loop
from pyvz.ui.screen import Screen
from pyvz.ui.view import Overlay

DOWN = b"\x1b[B"
END = b"\x1b[F"
ENTER = b"\r"
ESC = b"\x1b"


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home directory with a project in it, the project being the start directory."""
    monkeypatch.setenv("HOME", str(tmp_path))
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    (work / "src/main.py").write_text("main")
    (work / "README.md").write_text("readme")
    (work / "notes and ideas.txt").write_text("notes")
    (tmp_path / "windownloads").mkdir()
    monkeypatch.chdir(work)
    return work


def filer_run(*chunks: bytes | None, readonly: bool = False, filer: Filer | None = None):
    loop = Loop(FakeTerminal(*chunks), default_keymap())
    loop.editor = Editor(loop)
    loop.resize()
    filer = filer or Filer(Path.cwd())
    return FilerScreen(loop, filer, readonly=readonly).run(), filer, loop


# Entries in the start directory: .., src/, notes and ideas.txt, README.md


def test_enter_goes_into_directories_and_opens_files(tree: Path):
    result, filer, _ = filer_run(DOWN, ENTER, DOWN, ENTER)
    assert result == Open([tree / "src/main.py"])
    assert filer.pane.path == tree / "src"


def test_read_only_from_esc_r(tree: Path):
    result, _, _ = filer_run(DOWN, DOWN, DOWN, ENTER, readonly=True)
    assert result == Open([tree / "README.md"], readonly=True)


def test_selected_files_are_opened_together(tree: Path):
    result, _, _ = filer_run(DOWN, DOWN, b" ", b" ", ENTER)
    assert result == Open([tree / "notes and ideas.txt", tree / "README.md"])


def test_insert_paths_relative_to_the_start(tree: Path):
    result, _, _ = filer_run(DOWN, b" ", b" ", b"i")
    assert result == Insert('src/ "notes and ideas.txt"')


def test_insert_from_outside_the_start_uses_tilde(tree: Path):
    result, _, _ = filer_run(b"\x7f", b"i")  # BS: up to the home directory, on work/
    assert result == Insert("~/work/")


def test_esc_closes_and_saves_the_state(tree: Path):
    result, filer, _ = filer_run(DOWN, DOWN, DOWN, ESC, None)
    assert result is None
    again = Filer(tree)
    again.restore_state()
    assert again.pane.current.name == "README.md"


def test_upper_case_letter_jumps(tree: Path):
    _, filer, _ = filer_run(b"N", ESC, None)
    assert filer.pane.current.name == "notes and ideas.txt"


def test_digit_shows_the_dir_menu_place_in_the_other_window(tree: Path):
    _, filer, _ = filer_run(b"1", ESC, None)
    assert filer.dual and filer.active == RIGHT
    assert filer.panes[LEFT].path == tree.parent / "windownloads"
    assert filer.panes[RIGHT].path == tree


def test_copy_to_the_other_window(tree: Path):
    downloads = tree.parent / "windownloads"
    _, filer, loop = filer_run(b"1", DOWN, DOWN, b" ", b" ", b"f", b"c", ESC, None)
    assert sorted(p.name for p in downloads.iterdir()) == ["README.md", "notes and ideas.txt"]
    assert (tree / "README.md").exists()
    assert filer.pane.selected == set()


def test_copy_menu_with_left_and_right(tree: Path):
    # F, then right twice (Dir, Mask), left twice back to File, then C.
    right, left = b"\x1b[C", b"\x1b[D"
    filer_run(b"1", DOWN, DOWN, DOWN, b"f", right, right, left, left, b"c", ESC, None)
    assert (tree.parent / "windownloads/README.md").exists()


def test_copy_with_one_window_asks_for_the_destination(tree: Path):
    (tree / "out").mkdir()
    filer_run(DOWN, DOWN, DOWN, DOWN, b"f", b"c", b"out", ENTER, ESC, None)  # out/ is 2nd
    assert (tree / "out/README.md").read_text() == "readme"


def test_move_asks_before_overwriting(tree: Path):
    downloads = tree.parent / "windownloads"
    (downloads / "README.md").write_text("old")
    _, _, loop = filer_run(b"1", DOWN, DOWN, DOWN, b"f", b"m", b"y", ESC, None)
    assert (downloads / "README.md").read_text() == "readme"
    assert not (tree / "README.md").exists()


def test_delete_after_asking(tree: Path):
    _, _, loop = filer_run(DOWN, b"f", b"d", b"n", b"f", b"d", b"y", ESC, None)
    assert not (tree / "src").exists()


def test_rename_and_make(tree: Path):
    keys = [DOWN, DOWN, DOWN, b"f", b"r", b"\x11t", b"READ.md", ENTER, b"k", b"new", ENTER]
    _, filer, _ = filer_run(*keys, b"n", b"empty.txt", ENTER, ESC, None)
    assert (tree / "READ.md").read_text() == "readme"
    assert (tree / "new").is_dir()
    assert (tree / "empty.txt").read_text() == ""
    assert filer.pane.current.name == "empty.txt"


def test_path_input_with_a_pattern(tree: Path):
    _, filer, _ = filer_run(b"p", b"\x11t", b"*.md", ENTER, ESC, None)
    assert filer.pane.pattern == "*.md"
    assert [e.name for e in filer.pane.entries] == ["..", "src", "README.md"]
    _, filer, _ = filer_run(b"*", ESC, None, filer=filer)
    assert filer.pane.pattern == "*"


def test_sort_and_hidden_files(tree: Path):
    (tree / ".env").write_text("x")
    _, filer, _ = filer_run(b"m", b"h", ESC, None)
    assert ".env" not in [e.name for e in filer.pane.entries]
    _, filer, _ = filer_run(b"s", b"l", ESC, None, filer=filer)
    assert [e.name for e in filer.pane.entries][2:] == ["README.md", "notes and ideas.txt"]


def test_ret_cd(tree: Path):
    _, filer, _ = filer_run(b"\x7f", b"r", ESC, None)
    assert filer.pane.path == tree
    _, filer, _ = filer_run(b"r", ESC, None, filer=filer)
    assert filer.pane.path == tree.parent


# Drawing


def test_one_window_is_on_the_right_half(tree: Path):
    filer = Filer(tree)
    filer.load()
    layer = FilerLayer(filer)
    assert layer.geometry(100) == [(filer.panes[RIGHT], 50, 50)]
    assert layer.geometry(50) == [(filer.panes[RIGHT], 0, 50)]  # narrow: all of it
    filer.toggle_dual()
    assert layer.geometry(100) == [(filer.panes[LEFT], 0, 50), (filer.panes[RIGHT], 50, 50)]


def test_drawn_window(tree: Path):
    filer = Filer(tree)
    filer.load()
    screen = Screen(100, 10)
    FilerLayer(filer).draw(screen, Overlay(message="hello"))
    assert screen.text(0).startswith(" File  Dir  Mask  Path  Sort  Window  All  RetCD")
    assert screen.text(1)[50:].startswith("┌ ~/work ")
    assert screen.text(2)[51:].startswith("../")
    assert screen.text(3)[51:].startswith("src/")
    assert "3 files" in screen.text(8)
    assert screen.text(9).startswith("hello")


def test_date_text():
    now = datetime(2026, 10, 27, 12, 0)
    assert date_text(datetime(2026, 3, 4, 5, 6).timestamp(), now) == "03-04 05:06"
    assert date_text(datetime(2025, 3, 4, 5, 6).timestamp(), now) == "2025-03-04"


# With the editor


def test_esc_o_enter_opens_the_filer_and_i_types_into_the_text(tree: Path):
    loop = Loop(FakeTerminal(b"\x1bo", ENTER, DOWN, b"i", b"\x1bq", b"n", b"y"), default_keymap())
    editor = Editor(loop)
    loop.editor = editor
    prompt = tree / "prompt.md"
    prompt.write_text("look at ")
    editor.open(prompt)
    editor.window.index = 8
    loop.run()
    assert editor.windows[0].lines == ["look at src/"]


def test_started_from_the_filer_comes_back_to_it(tree: Path):
    # Open README.md, close it, then ESC in the filer ends pyvz.
    loop = Loop(FakeTerminal(DOWN, DOWN, ENTER, b"\x1bc", ESC, None), default_keymap())
    editor = Editor(loop)
    editor.keep_open = True
    loop.editor = editor
    assert loop.run() == 0
    assert editor.windows == []
