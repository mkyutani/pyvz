import os
from pathlib import Path

import pytest

from pyvz.filer import ops
from pyvz.filer.filer import LEFT, RIGHT, Filer
from pyvz.filer.listing import Entry, Order, read_dir, shown, size_text, sort_entries
from pyvz.filer.pane import Pane


def make(root: Path, *names: str) -> Path:
    """Make root, and files and directories (names ending in /) under it."""
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        path = root / name
        if name.endswith("/"):
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
    return root


def names(pane: Pane) -> list[str]:
    return [e.name for e in pane.entries]


# Listing


def test_read_dir_tells_kinds(tmp_path: Path):
    make(tmp_path, "dir/", "file.txt", "run.sh")
    (tmp_path / "run.sh").chmod(0o755)
    (tmp_path / "link").symlink_to("dir")
    (tmp_path / "broken").symlink_to("nowhere")
    found = {e.name: e for e in read_dir(tmp_path)}
    assert found["dir"].is_dir and not found["dir"].is_link
    assert found["link"].is_dir and found["link"].is_link
    assert found["broken"].is_link and not found["broken"].is_dir
    assert found["run.sh"].executable and not found["file.txt"].executable


def entry(name: str, size: int = 0, mtime: float = 0, is_dir: bool = False) -> Entry:
    return Entry(name, is_dir, size, mtime)


def test_sort_keeps_directories_first():
    entries = [
        entry("b", 10, 3),
        entry("A", 30, 1),
        entry("z", is_dir=True, mtime=1),
        entry("c", 20, 2),
        entry("y", is_dir=True, mtime=2),
    ]
    by = {order: [e.name for e in sort_entries(entries, order)] for order in Order}
    assert by[Order.NAME] == ["y", "z", "A", "b", "c"]
    assert by[Order.NEWEST] == ["y", "z", "b", "c", "A"]
    assert by[Order.OLDEST] == ["z", "y", "A", "c", "b"]
    assert by[Order.LARGEST] == ["y", "z", "A", "c", "b"]
    assert by[Order.SMALLEST] == ["y", "z", "b", "c", "A"]


def test_mask():
    assert shown(entry("a.md"), "*.md *.txt", True)
    assert not shown(entry("a.py"), "*.md *.txt", True)
    assert shown(entry("src", is_dir=True), "*.md", True)
    assert not shown(entry(".git", is_dir=True), "*", False)
    assert shown(entry(".git", is_dir=True), "*", True)


def test_size_text():
    assert [size_text(n) for n in (0, 242, 999, 1000, 1234, 35_000_000, 130 * 2**30)] == [
        "0",
        "242",
        "999",
        "1.0K",
        "1.2K",
        "33M",
        "130G",
    ]


# Panes


def test_pane_lists_the_parent_first_and_goes_up_to_where_it_was(tmp_path: Path):
    make(tmp_path, "sub/a.txt", "sub/b.txt", "top.txt")
    pane = Pane(tmp_path / "sub")
    pane.load()
    assert names(pane) == ["..", "a.txt", "b.txt"]
    pane.parent()
    assert pane.path == tmp_path
    assert pane.current.name == "sub"
    assert pane.enter()
    assert pane.path == tmp_path / "sub"


def test_pane_keeps_the_cursor_on_reload(tmp_path: Path):
    make(tmp_path, "a", "b", "c")
    pane = Pane(tmp_path)
    pane.load()
    pane.move(2)
    assert pane.current.name == "b"
    (tmp_path / "a").unlink()
    pane.load()
    assert pane.current.name == "b"


def test_pane_selection_and_targets(tmp_path: Path):
    make(tmp_path, "a", "b", "c")
    pane = Pane(tmp_path)
    pane.load()
    pane.toggle()  # on ".." does nothing
    assert pane.targets() == []
    pane.move(1)
    assert [e.name for e in pane.targets()] == ["a"]
    pane.invert_all()
    pane.toggle()
    assert [e.name for e in pane.targets()] == ["b", "c"]
    pane.clear()
    assert pane.selected == set()


def test_pane_jump_by_first_letter(tmp_path: Path):
    make(tmp_path, "alpha", "beta", "Bravo", "gamma")
    pane = Pane(tmp_path)
    pane.load()
    assert pane.jump("B")
    assert pane.current.name == "beta"
    assert pane.jump("b")
    assert pane.current.name == "Bravo"
    assert not pane.jump("x")


def test_pane_go_to_a_missing_directory_changes_nothing(tmp_path: Path):
    pane = Pane(tmp_path)
    pane.load()
    with pytest.raises(OSError):
        pane.go(tmp_path / "missing")
    assert pane.path == tmp_path


def test_keep_visible():
    pane = Pane(Path("/"))
    pane.entries = [entry(str(i)) for i in range(20)]
    pane.cursor = 15
    pane.keep_visible(5)
    assert pane.top == 11
    pane.cursor = 3
    pane.keep_visible(5)
    assert pane.top == 3


# Operations


def test_copy_keeps_times_and_copies_directories(tmp_path: Path):
    src = make(tmp_path / "src", "a.txt", "d/inner.txt")
    os.utime(src / "a.txt", (1_000_000, 1_000_000))
    dst = make(tmp_path / "dst")
    result = ops.transfer([src / "a.txt", src / "d"], dst, move=False, ask=lambda p: None)
    assert result.done == ["a.txt", "d"]
    assert (dst / "a.txt").stat().st_mtime == 1_000_000
    assert (dst / "d/inner.txt").read_text() == "d/inner.txt"
    assert (src / "a.txt").exists()


def test_copy_asks_about_existing_files(tmp_path: Path):
    src = make(tmp_path / "src", "a", "b", "c", "d")
    dst = make(tmp_path / "dst", "a", "b", "c", "d")
    for name in "abcd":
        (dst / name).write_text("old")
    answers = iter([ops.NO, ops.YES, ops.SKIP_ALL])
    asked = []

    def ask(path: Path) -> str | None:
        asked.append(path.name)
        return next(answers)

    sources = [src / n for n in "abcd"]
    result = ops.transfer(sources, dst, move=False, ask=ask)
    assert asked == ["a", "b", "c"]
    assert result.done == ["b"]
    assert result.skipped == ["a", "c", "d"]
    assert [(dst / n).read_text() for n in "abcd"] == ["old", "b", "old", "old"]


def test_copy_cancelled(tmp_path: Path):
    src = make(tmp_path / "src", "a", "b")
    dst = make(tmp_path / "dst", "a")
    result = ops.transfer([src / "a", src / "b"], dst, move=False, ask=lambda p: None)
    assert result.cancelled
    assert not (dst / "b").exists()


def test_copy_a_link_as_a_link(tmp_path: Path):
    src = make(tmp_path / "src", "target")
    (src / "link").symlink_to("target")
    dst = make(tmp_path / "dst")
    ops.transfer([src / "link"], dst, move=False, ask=lambda p: None)
    assert (dst / "link").is_symlink()
    assert os.readlink(dst / "link") == "target"


def test_copy_into_itself_is_refused(tmp_path: Path):
    src = make(tmp_path, "d/inner/")
    result = ops.transfer([src / "d"], src / "d/inner", move=False, ask=lambda p: None)
    assert result.errors and not result.done


def test_move_files_and_merge_directories(tmp_path: Path):
    src = make(tmp_path / "src", "a", "d/new.txt")
    dst = make(tmp_path / "dst", "d/old.txt")
    result = ops.transfer([src / "a", src / "d"], dst, move=True, ask=lambda p: ops.YES)
    assert result.done == ["a", "d"]
    assert not (src / "a").exists() and not (src / "d").exists()
    assert sorted(p.name for p in (dst / "d").iterdir()) == ["new.txt", "old.txt"]


def test_delete_directories_with_contents_and_links_without_following(tmp_path: Path):
    root = make(tmp_path, "keep/precious.txt", "d/x/y.txt", "f")
    (root / "link").symlink_to("keep")
    assert ops.has_contents(root / "d")
    assert not ops.has_contents(root / "link")
    result = ops.delete([root / "d", root / "f", root / "link"])
    assert result.done == ["d", "f", "link"]
    assert (root / "keep/precious.txt").exists()
    assert sorted(p.name for p in root.iterdir()) == ["keep"]


def test_rename_and_make(tmp_path: Path):
    make(tmp_path, "a", "b")
    with pytest.raises(FileExistsError):
        ops.rename(tmp_path, "a", "b")
    ops.rename(tmp_path, "a", "c")
    assert (tmp_path / "c").read_text() == "a"
    assert ops.make_dir(tmp_path, "new")
    assert not ops.make_dir(tmp_path, "new")
    assert ops.make_file(tmp_path, "empty")
    assert not ops.make_file(tmp_path, "empty")
    assert (tmp_path / "empty").read_text() == ""
    assert ops.check_name("a/b") is not None
    assert ops.check_name("..") is not None
    assert ops.check_name("ok.txt") is None


# The filer


def test_dual_windows(tmp_path: Path):
    make(tmp_path, "a/", "b/")
    filer = Filer(tmp_path)
    filer.load()
    assert filer.visible() == [filer.panes[RIGHT]]
    filer.show_other(tmp_path / "a")  # opens the second window on the left
    assert filer.dual and filer.active == RIGHT
    assert filer.panes[LEFT].path == tmp_path / "a"
    filer.switch()
    assert filer.pane.path == tmp_path / "a"
    filer.toggle_dual()  # the active window stays, alone on the right
    assert not filer.dual
    assert filer.panes[RIGHT].path == tmp_path / "a"


def test_places_skip_missing_directories_and_keep_their_numbers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    make(tmp_path, "windocuments/", "work/")
    filer = Filer(tmp_path / "work")
    assert filer.places() == [
        ("2", tmp_path / "windocuments"),
        ("4", tmp_path),
        ("5", tmp_path / "work"),
    ]


def test_ret_cd_goes_to_the_start_and_back(tmp_path: Path):
    make(tmp_path, "start/", "elsewhere/")
    filer = Filer(tmp_path / "start")
    filer.load()
    filer.pane.go(tmp_path / "elsewhere")
    filer.ret_cd()
    assert filer.pane.path == tmp_path / "start"
    filer.ret_cd()
    assert filer.pane.path == tmp_path / "elsewhere"


def test_state_round_trip(tmp_path: Path):
    make(tmp_path, "a/x", "a/y", "b/")
    filer = Filer(tmp_path)
    filer.load()
    filer.pane.go(tmp_path / "a")
    filer.pane.move(2)
    filer.pane.pattern = "y"
    filer.pane.load()
    filer.show_other(tmp_path / "b")
    filer.set_order(Order.NEWEST)
    filer.save_state(tmp_path / "filer.json")

    again = Filer(tmp_path)
    again.restore_state(tmp_path / "filer.json")
    assert again.dual and again.order == Order.NEWEST
    assert again.panes[RIGHT].path == tmp_path / "a"
    assert again.panes[RIGHT].pattern == "y"
    assert again.panes[RIGHT].current.name == "y"
    assert again.panes[LEFT].path == tmp_path / "b"


def test_state_with_a_missing_directory_keeps_the_start(tmp_path: Path):
    make(tmp_path, "gone/")
    filer = Filer(tmp_path)
    filer.load()
    filer.pane.go(tmp_path / "gone")
    filer.save_state(tmp_path / "filer.json")
    (tmp_path / "gone").rmdir()
    again = Filer(tmp_path)
    again.restore_state(tmp_path / "filer.json")
    assert again.pane.path == tmp_path
