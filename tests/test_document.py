import os
import stat
from pathlib import Path

import pytest

from pyvz.text.document import Document, FileFormat, decode, encode, write_file


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\n",
        b"one line",
        b"one\ntwo\n",
        b"one\r\ntwo\r\n",
        b"no final newline\r\nhere",
        b"\xef\xbb\xbfwith bom\n",
        "日本語\nテキスト\n".encode(),
        b"broken \xff\xfe utf-8\n",
        b"lf file\nwith a cr\r\nkept\n",
    ],
)
def test_decode_encode_round_trip(data: bytes):
    lines, fmt = decode(data)
    assert encode(lines, fmt) == data


def test_line_ending_follows_the_majority():
    lines, fmt = decode(b"a\r\nb\r\nc\n")
    assert fmt.newline == "\r\n"
    assert lines == ["a", "b", "c"]
    # The bare LF is written back as CR LF.
    assert encode(lines, fmt) == b"a\r\nb\r\nc\r\n"


def test_cr_stays_in_a_mostly_lf_file():
    lines, fmt = decode(b"a\nb\r\nc\n")
    assert fmt.newline == "\n"
    assert lines == ["a", "b\r", "c"]


def test_empty_file_is_one_empty_line():
    lines, fmt = decode(b"")
    assert lines == [""]
    assert fmt == FileFormat(newline="\n", final_newline=False, bom=False)


def test_invalid_bytes_are_kept_as_surrogates():
    lines, _ = decode(b"a\xffb")
    assert lines == ["a\udcffb"]


def test_load_missing_file_is_a_new_document(tmp_path: Path):
    doc = Document.load(tmp_path / "new.txt")
    assert doc.new_file
    assert doc.lines == [""]
    assert doc.format == FileFormat()


def test_save_keeps_the_format_and_clears_flags(tmp_path: Path):
    path = tmp_path / "dos.txt"
    path.write_bytes(b"a\r\nb")
    doc = Document.load(path)
    doc.lines.append("c")
    doc.modified = True
    doc.save()
    assert path.read_bytes() == b"a\r\nb\r\nc"
    assert not doc.modified


def test_new_file_is_saved_with_lf_and_final_newline(tmp_path: Path):
    path = tmp_path / "new.txt"
    doc = Document.load(path)
    doc.lines = ["hello"]
    doc.save()
    assert path.read_bytes() == b"hello\n"
    assert not doc.new_file


def test_save_under_another_name_renames_the_document(tmp_path: Path):
    doc = Document.load(tmp_path / "a.txt")
    doc.save(tmp_path / "b.txt")
    assert doc.path == tmp_path / "b.txt"
    assert (tmp_path / "b.txt").exists()
    assert not (tmp_path / "a.txt").exists()


def test_save_keeps_permission_bits(tmp_path: Path):
    path = tmp_path / "private.md"
    path.write_bytes(b"x\n")
    path.chmod(0o600)
    Document.load(path).save()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_save_through_a_symlink_replaces_the_target(tmp_path: Path):
    target = tmp_path / "real.txt"
    target.write_bytes(b"old\n")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    doc = Document.load(link)
    doc.lines = ["new"]
    doc.save()
    assert link.is_symlink()
    assert target.read_bytes() == b"new\n"


def test_save_leaves_no_temporary_file(tmp_path: Path):
    doc = Document.load(tmp_path / "a.txt")
    doc.save()
    assert os.listdir(tmp_path) == ["a.txt"]


def test_save_without_a_name_fails():
    with pytest.raises(ValueError):
        Document().save()


def test_write_file_with_explicit_mode(tmp_path: Path):
    path = tmp_path / "secret.json"
    path.write_text("old")
    path.chmod(0o644)
    write_file(path, b"new", mode=0o600)
    assert path.read_bytes() == b"new"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
