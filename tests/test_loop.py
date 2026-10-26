from pathlib import Path

import pytest
from fakes import FakeTerminal

from pyvz.editor.editor import Editor
from pyvz.keys.keymap import default_keymap
from pyvz.ui.loop import Loop


@pytest.fixture
def text_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "a.txt"
    path.write_text("abc\ndef\n")
    return path


def run(path: Path, *chunks: bytes | None, cc: bool = False) -> tuple[int, Editor]:
    terminal = FakeTerminal(*chunks)
    loop = Loop(terminal, default_keymap())
    editor = Editor(loop)
    loop.editor = editor
    editor.open(path, cc=cc)
    return loop.run(), editor


def test_type_save_and_close(text_file: Path):
    code, _ = run(text_file, b"X", b"\x1b", b"s", b"\r", b"\x1b", b"c")
    assert code == 0
    assert text_file.read_text() == "Xabc\ndef\n"


def test_alt_letter_is_the_same_as_esc_and_the_letter(text_file: Path):
    code, _ = run(text_file, b"X", b"\x1bs", b"\r", b"\x1bc")
    assert code == 0
    assert text_file.read_text() == "Xabc\ndef\n"


def test_esc_typed_slowly_still_works_as_a_prefix(text_file: Path):
    code, _ = run(text_file, b"X", b"\x1b", None, b"s", b"\r", b"\x1b", None, b"c")
    assert text_file.read_text() == "Xabc\ndef\n"


def test_two_stroke_keys_with_ctrl_q(text_file: Path):
    # ^X (down), ^Q D (line end), type, then ^Q ^S (line top, Ctrl held), type.
    code, editor = run(text_file, b"\x18", b"\x11d", b"!", b"\x11\x13", b"[", b"\x1bs\r\x1bc")
    assert text_file.read_text() == "abc\n[def!\n"


def test_esc_esc_repeats_the_last_command(text_file: Path):
    run(text_file, b"\x04", b"\x1b\x1b", None, b"\x1b\x1b", None, b"!", b"\x1bs\r\x1bc")
    assert text_file.read_text() == "abc!\ndef\n"


def test_close_question_answered_by_enter_and_cancelled_by_esc(text_file: Path):
    # [ESC]C asks; ESC (alone) cancels, then [ESC]C again and Enter saves.
    run(text_file, b"X", b"\x1bc", b"\x1b", None, b"\x1bc", b"\r")
    assert text_file.read_text() == "Xabc\ndef\n"


def test_close_answered_no(text_file: Path):
    code, _ = run(text_file, b"X", b"\x1bc", b"n")
    assert code == 0
    assert text_file.read_text() == "abc\ndef\n"


def test_paste_inserts_the_text(text_file: Path):
    run(text_file, b"\x1b[200~one\r\ntwo\x1b[201~", b"\x1bs\r\x1bc")
    assert text_file.read_text() == "one\ntwoabc\ndef\n"


def test_arrow_keys_and_enter(text_file: Path):
    run(text_file, b"\x1b[B", b"\x1b[C", b"\r", b"\x1bs\r\x1bc")
    assert text_file.read_text() == "abc\nd\nef\n"


def test_backspace_from_the_terminal(text_file: Path):
    run(text_file, b"\x1b[C\x7f", b"\x1bs\r\x1bc")
    assert text_file.read_text() == "bc\ndef\n"


def test_command_not_there_yet_shows_its_name(text_file: Path):
    terminal = FakeTerminal(b"\x11k")  # ^QK: the matching bracket
    loop = Loop(terminal, default_keymap())
    editor = Editor(loop)
    loop.editor = editor
    editor.open(text_file)
    with pytest.raises(AssertionError):
        loop.run()
    assert loop.overlay.message == "対応する()[]{}<>: まだありません"


def test_cc_prompt_goes_back_with_esc_c(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    prompt = tmp_path / "claude-prompt-1.md"
    prompt.write_text("draft")
    code, _ = run(prompt, b"\x11d", b" more", b"\x1bc", cc=True)
    assert code == 0
    assert prompt.read_text() == "draft more"
