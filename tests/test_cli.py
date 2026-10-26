from pathlib import Path

import pytest

from pyvz.cli import Launch, Mode, parse_args


def test_no_arguments_opens_filer_at_current_directory():
    assert parse_args([]) == Launch(Mode.FILER)


def test_directory_opens_filer_there(tmp_path: Path):
    assert parse_args([str(tmp_path)]) == Launch(Mode.FILER, directory=tmp_path)


def test_files_are_edited(tmp_path: Path):
    a = tmp_path / "a.txt"
    b = tmp_path / "new.txt"  # files that do not exist yet are new files
    a.write_text("a\n")
    assert parse_args([str(a), str(b)]) == Launch(Mode.EDIT, files=(a, b))


def test_cc_mode_takes_the_prompt_file():
    prompt = "/tmp/claude-1000/claude-prompt-0123.md"
    assert parse_args(["-c", prompt]) == Launch(Mode.CC, files=(Path(prompt),))


def test_cc_mode_rejects_extra_paths():
    with pytest.raises(SystemExit):
        parse_args(["-c", "prompt.md", "other.txt"])


def test_directory_cannot_be_mixed_with_files(tmp_path: Path):
    with pytest.raises(SystemExit):
        parse_args([str(tmp_path), "file.txt"])
