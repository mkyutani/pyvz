import stat
from pathlib import Path

import pytest
from fakes import FakeTerminal

from pyvz.cc import drafts, session
from pyvz.cc.drafts import Draft
from pyvz.cc.prompt import SEPARATOR, PromptFile, split
from pyvz.cc.session import Session
from pyvz.editor.editor import Editor
from pyvz.editor.layout import Layout
from pyvz.keys.commands import Cmd
from pyvz.keys.keymap import default_keymap
from pyvz.ui.loop import Loop

CC = Session(100, 5000)


def fake_proc(root: Path, *processes: tuple[int, str, int, int]) -> Path:
    """Processes as (pid, name, parent pid, start time)."""
    for pid, name, ppid, start in processes:
        (root / str(pid)).mkdir(parents=True)
        rest = ["S", str(ppid)] + ["0"] * 17 + [str(start)] + ["0"] * 5
        (root / str(pid) / "stat").write_text(f"{pid} ({name}) {' '.join(rest)}\n")
    return root


# Sessions


def test_session_is_the_claude_ancestor(tmp_path: Path):
    proc = fake_proc(
        tmp_path,
        (300, "python3", 200, 9),
        (200, "uv", 100, 8),
        (100, "claude", 50, 5000),
        (50, "bash", 1, 7),
    )
    assert session.current(proc, parent=200) == CC


def test_no_session_without_claude(tmp_path: Path):
    proc = fake_proc(tmp_path, (200, "git", 50, 8), (50, "bash (login)", 1, 7))
    assert session.current(proc, parent=200) is None


def test_parent_stands_for_the_session_without_proc(tmp_path: Path):
    assert session.current(tmp_path / "none", parent=200) == Session(200, None)


def test_without_a_session_there_are_no_drafts(tmp_path: Path):
    drafts.save(Draft(text="old", cwd="/w", pid=7, start=7), tmp_path / "drafts")
    path = tmp_path / "COMMIT_EDITMSG"
    path.write_text("message")
    prompt = PromptFile(path, None, directory=tmp_path / "drafts", cwd="/w")
    assert prompt.open(Layout()).lines == ["message"]


def test_alive_needs_the_same_start_time(tmp_path: Path):
    proc = fake_proc(tmp_path, (100, "claude", 1, 5000))
    assert session.alive(CC, proc)
    assert not session.alive(Session(100, 4999), proc)  # the PID was given to another
    assert not session.alive(Session(101, 5000), proc)


# Draft files


def test_draft_round_trip_and_privacy(tmp_path: Path):
    directory = tmp_path / "drafts"
    draft = Draft(text="memo\n\udcff", line=1, index=2, original="x", pid=100, start=5000)
    path = drafts.save(draft, directory)
    assert path.name == "100-5000.json"
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert drafts.find(CC, directory) == (path, draft)


def test_broken_draft_is_ignored(tmp_path: Path):
    (tmp_path / "100-5000.json").write_text("{not json")
    assert drafts.find(CC, tmp_path) is None


def test_drafts_left_behind_prefer_the_same_directory(tmp_path: Path):
    old_here = Draft(text="a", cwd="/w", pid=1, start=1, updated=10)
    new_elsewhere = Draft(text="b", cwd="/x", pid=2, start=2, updated=30)
    new_here = Draft(text="c", cwd="/w", pid=3, start=3, updated=20)
    running = Draft(text="d", cwd="/w", pid=4, start=4, updated=40)
    for draft in (old_here, new_elsewhere, new_here, running):
        drafts.save(draft, tmp_path)
    found = drafts.left_behind("/w", tmp_path, is_alive=lambda s: s.pid == 4)
    assert [d.text for _, d in found] == ["c", "a", "b"]


# The prologue


def test_split_follows_claude_code():
    prologue = f"# ─── Claude's last response ───\n# Hi\n#\n# Done.\n{SEPARATOR}\n\n"
    assert split(prologue + "my reply") == (prologue, "my reply")
    assert split("just text") == ("", "just text")
    assert split(f"{SEPARATOR}\nx") == (f"{SEPARATOR}\n", "x")


# Opening and holding


def prompt_file(tmp_path: Path, text: str, name: str = "claude-prompt-1.md", **kw) -> PromptFile:
    path = tmp_path / name
    path.write_text(text)
    kw.setdefault("cwd", "/w")
    kw.setdefault("is_alive", lambda s: s == CC)
    return PromptFile(path, CC, directory=tmp_path / "drafts", **kw)


def test_first_call_shows_the_input_with_the_cursor_at_the_end(tmp_path: Path):
    prompt = prompt_file(tmp_path, "line 1\nline 2")
    window = prompt.open(Layout())
    assert window.lines == ["line 1", "line 2"]
    assert (window.line, window.index) == (1, 6)
    assert window.cc and not window.draft and not window.doc.modified
    assert prompt.message == ""


def test_hold_then_resume(tmp_path: Path):
    first = prompt_file(tmp_path, "")
    window = first.open(Layout())
    window.insert("meeting notes\n- item")
    first.hold(window)
    assert first.path.read_text() == ""  # the input box stays as it was

    second = prompt_file(tmp_path, "", name="claude-prompt-2.md")
    window = second.open(Layout())
    assert window.lines == ["meeting notes", "- item"]
    assert (window.line, window.index) == (1, 6)
    assert window.draft and window.doc.modified
    assert second.message == "下書きを開きました"


def test_resume_when_the_input_box_still_holds_what_it_held(tmp_path: Path):
    first = prompt_file(tmp_path, "start")
    window = first.open(Layout())
    window.insert(" and more")
    first.hold(window)
    second = prompt_file(tmp_path, "start", name="claude-prompt-2.md")
    assert second.open(Layout()).lines == ["start and more"]


def test_text_typed_meanwhile_goes_after_the_draft(tmp_path: Path):
    first = prompt_file(tmp_path, "")
    window = first.open(Layout())
    window.insert("long memo")
    first.hold(window)
    second = prompt_file(tmp_path, "a question", name="claude-prompt-2.md")
    window = second.open(Layout())
    assert window.lines == ["long memo", "", "a question"]
    assert second.message == "下書きを開きました。入力欄の文は後ろに足しました"


def test_draft_goes_below_the_new_prologue(tmp_path: Path):
    first = prompt_file(tmp_path, "")
    window = first.open(Layout())
    window.insert("memo")
    first.hold(window)
    prologue = f"# ─── Claude's last response ───\n# New answer\n{SEPARATOR}\n\n"
    second = prompt_file(tmp_path, prologue, name="claude-prompt-2.md")
    window = second.open(Layout())
    assert "\n".join(window.lines) == prologue + "memo"
    assert (window.line, window.index) == (4, 4)


def test_hold_keeps_only_the_text_below_the_prologue(tmp_path: Path):
    prologue = f"# ─── Claude's last response ───\n# Answer\n{SEPARATOR}\n\n"
    prompt = prompt_file(tmp_path, prologue)
    window = prompt.open(Layout())
    window.insert("reply")
    prompt.hold(window)
    _, draft = drafts.find(CC, tmp_path / "drafts")
    assert (draft.text, draft.line, draft.index) == ("reply", 0, 5)


def test_holding_an_empty_text_removes_the_draft(tmp_path: Path):
    drafts.save(Draft(text="old", pid=100, start=5000), tmp_path / "drafts")
    prompt = prompt_file(tmp_path, "")
    window = prompt.open(Layout())
    window.lines[:] = [""]
    prompt.hold(window)
    assert drafts.find(CC, tmp_path / "drafts") is None


def test_passing_the_text_removes_the_draft(tmp_path: Path):
    drafts.save(Draft(text="memo", pid=100, start=5000), tmp_path / "drafts")
    prompt = prompt_file(tmp_path, "")
    window = prompt.open(Layout())
    prompt.passed(window)
    assert drafts.find(CC, tmp_path / "drafts") is None


def test_draft_of_an_ended_session_is_taken_over(tmp_path: Path):
    gone = Draft(text="from before", cwd="/w", pid=7, start=7)
    old_path = drafts.save(gone, tmp_path / "drafts")
    prompt = prompt_file(tmp_path, "")
    window = prompt.open(Layout())
    assert window.lines == ["from before"]
    assert prompt.message == "前のセッションで保留した下書きを開きました"
    prompt.hold(window)
    assert not old_path.exists()
    assert drafts.find(CC, tmp_path / "drafts") is not None


def test_draft_of_another_running_session_is_left_alone(tmp_path: Path):
    other = Draft(text="other session", cwd="/w", pid=8, start=8)
    drafts.save(other, tmp_path / "drafts")
    prompt = prompt_file(tmp_path, "mine", is_alive=lambda s: True)
    assert prompt.open(Layout()).lines == ["mine"]


# Through the editor and the main loop


def run_prompt(prompt: PromptFile, *chunks: bytes | None) -> int:
    loop = Loop(FakeTerminal(*chunks), default_keymap())
    editor = Editor(loop)
    loop.editor = editor
    editor.add(prompt.open(editor.layout))
    editor.prompt = prompt
    return loop.run()


def test_round_trip_through_the_main_loop(tmp_path: Path):
    first = prompt_file(tmp_path, "")
    assert run_prompt(first, "会議メモ".encode(), b"\x1be") == 0  # [ESC]E: hold
    assert first.path.read_text() == ""

    second = prompt_file(tmp_path, "", name="claude-prompt-2.md")
    assert run_prompt(second, "の続き".encode(), b"\x1bc") == 0  # [ESC]C: pass
    assert second.path.read_text() == "会議メモの続き"
    assert drafts.find(CC, tmp_path / "drafts") is None


@pytest.mark.parametrize("keys", [b"\x1bx", b"\x1bq\r"])  # @X (abandon), [ESC]Q (quit)
def test_quitting_also_passes_the_text(tmp_path: Path, keys: bytes):
    prompt = prompt_file(tmp_path, "draft")
    assert run_prompt(prompt, b"!", keys) == 0
    assert prompt.path.read_text() == "draft!"


def test_hold_in_the_editor_without_claude_code(tmp_path: Path):
    path = tmp_path / "a.txt"
    path.write_text("x")
    loop = Loop(FakeTerminal(), default_keymap())
    editor = Editor(loop)
    loop.editor = editor
    editor.open(path)
    editor.run(Cmd.COMMAND_LINE)
    assert editor.exit_code is None
    assert loop.overlay.message == "Claude Code から呼ばれていません"
