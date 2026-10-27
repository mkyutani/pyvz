from pathlib import Path

from fakes import FakeTerminal

from pyvz import config as settings
from pyvz.app import configured, keymap_of
from pyvz.editor.window import Window
from pyvz.filer.filer import Filer, FilerSettings
from pyvz.keys import codes
from pyvz.keys.commands import Cmd
from pyvz.keys.keymap import Mode, command_section, read_def, vz_keymap
from pyvz.text.document import Document
from pyvz.ui import theme, view
from pyvz.ui.filerui import FilerLayer
from pyvz.ui.screen import Screen, Style

FULL = """
[editor]
tab_size = 4
ambiguous_wide = true
auto_indent = false
function_keys = false
esc_delay_ms = 120

[search]
options = "WC"

[keys]
75 = "[ESC]S ^KS"
SET_SEARCH = "^QF [F06]"

[filer]
places = ["~/notes", "~"]
masks = ["*.md", "*.py *.toml"]
single = "left"

[colors]
status = { fg = "black", bg = "cyan" }
"""


def load(tmp_path: Path, text: str) -> settings.Config:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return settings.load(path)


def test_no_file_gives_the_defaults(tmp_path: Path):
    config = settings.load(tmp_path / "none.toml")
    assert config == settings.Config()


def test_everything(tmp_path: Path):
    config = load(tmp_path, FULL)
    assert config.errors == []
    assert (config.tab_size, config.ambiguous_wide, config.auto_indent) == (4, True, False)
    assert (config.function_keys, config.esc_delay_ms) == (False, 120)
    assert config.search_options == "WC"
    assert config.keys == {"75": "[ESC]S ^KS", "SET_SEARCH": "^QF [F06]"}
    assert config.places == ["~/notes", "~"]
    assert config.single == "left"
    assert config.colors == {"status": {"fg": "black", "bg": "cyan"}}


def test_mistakes_are_reported_and_defaults_kept(tmp_path: Path):
    text = """
[editor]
tab_size = "eight"
tabsize = 4
esc_delay_ms = -1
[search]
options = "Q"
[filer]
single = "top"
places = "~"
[other]
x = 1
"""
    config = load(tmp_path, text)
    assert config.tab_size == 8 and config.single == "right"
    assert config.places == settings.Config().places
    assert len(config.errors) == 7
    assert "editor.tabsize: そういう項目はありません" in config.errors


def test_broken_toml(tmp_path: Path):
    config = load(tmp_path, "[editor\n")
    assert config.errors and config.errors[0].startswith("config.toml:")


# Colors


def test_colors_by_name():
    errors = theme.configure(
        {"status": {"fg": "black", "bg": 6}, "mark": {"bold": True}, "nope": {}}
    )
    assert theme.style("status") == Style(fg=0, bg=6)  # as written, not reversed
    assert theme.style("mark") == Style(fg=8, bold=True)
    assert errors == ["colors.nope: そういう名前の色はありません"]
    assert theme.configure({"title": {"fg": "pink"}}) == ["colors.title.fg: 'pink' は使えません"]
    theme.configure({"chosen": {"fg": "red", "reverse": True}})
    assert theme.style("chosen") == Style(fg=1, reverse=True)


# Keys


def test_command_section_takes_the_ibm_side():
    text = (
        "* C コマンドキー\n00 ^Q ^K [ESC]\n"
        "#if 98\n05 ^E [UP] :98\n#else\n05 ^E [UP] :IBM\n#endif\n"
        "* F\n1 x\n"
    )
    assert command_section(text) == "00 ^Q ^K [ESC]\n05 ^E [UP] :IBM"


def test_read_def_in_shift_jis(tmp_path: Path):
    path = tmp_path / "VZ.DEF"
    path.write_bytes("* C\n05 ^E :上\n".encode("cp932"))
    assert ":上" in read_def(path)


def test_keymap_from_a_def_with_other_prefix_keys():
    keymap = vz_keymap("* C\n00 ^Q ^K\n05 ^E\n75 ^KS\n")
    assert keymap.command([codes.stroke2(1, "S")], Mode.EDIT) == Cmd.SAVE
    assert keymap.command([codes.HOME], Mode.EDIT) == Cmd.SCREEN_LINE_LEFT


def test_keys_of_the_settings(tmp_path: Path):
    config = load(tmp_path, '[keys]\n75 = "^KS"\nSET_SEARCH = "[F06]"\nNOPE = "^A"\n76 = "@"\n')
    keymap = keymap_of(config)
    assert keymap.command([codes.stroke2(1, "S")], Mode.EDIT) == Cmd.SAVE
    assert keymap.command([codes.stroke2(2, "S")], Mode.EDIT) is None  # [ESC]S is gone
    assert keymap.command([codes.stroke2(0, "F")], Mode.EDIT) is None
    assert len(config.errors) == 2


def test_keys_from_a_def_file(tmp_path: Path):
    (tmp_path / "MY.DEF").write_text("* C\n00 ^Q ^K [ESC]\n75 ^KS\n")
    config = load(tmp_path, f'[keys]\ndef = "{tmp_path / "MY.DEF"}"\n')
    keymap = keymap_of(config)
    assert keymap.command([codes.stroke2(1, "S")], Mode.EDIT) == Cmd.SAVE
    assert keymap.command([codes.stroke2(2, 0x1B)], Mode.EDIT) == Cmd.REPEAT  # ESC ESC
    config = load(tmp_path, '[keys]\ndef = "/no/such.def"\n')
    keymap_of(config)
    assert config.errors and config.errors[0].startswith("keys.def:")


# Applied


def test_settings_reach_the_editor_and_the_loop(tmp_path: Path):
    config = load(tmp_path, FULL)
    loop, editor = configured(FakeTerminal(), config)
    assert loop.esc_delay == 0.12 and loop.ambiguous_wide
    assert editor.layout.tab_size == 4 and editor.layout.ambiguous_wide
    assert editor.search_options.word and editor.search_options.ignore_case
    assert loop.filer_settings == FilerSettings(["~/notes", "~"], ["*.md", "*.py *.toml"], "left")
    assert theme.style("status").bg == 6


def test_errors_are_shown_at_start(tmp_path: Path):
    config = load(tmp_path, "[editor]\nx = 1\ny = 2\n")
    loop, _ = configured(FakeTerminal(), config)
    assert loop.overlay.message.startswith("設定: editor.")
    assert loop.overlay.message.endswith("（ほか 1 件）")


def test_without_function_keys_the_windows_get_the_row(tmp_path: Path):
    config = load(tmp_path, "[editor]\nfunction_keys = false\n")
    _, editor = configured(FakeTerminal(), config)
    editor.resize(40, 10)
    editor.add(Window(Document(lines=["x"]), editor.layout))
    assert editor.regions()[0].rows == 8
    screen = Screen(40, 10)
    view.draw(screen, editor, view.Overlay(message="hello"))
    assert screen.text(9).startswith("hello")


def test_auto_indent_off(tmp_path: Path):
    config = load(tmp_path, "[editor]\nauto_indent = false\n")
    _, editor = configured(FakeTerminal(), config)
    editor.add(Window(Document(lines=["  x"]), editor.layout))
    editor.window.index = 3
    editor.run(Cmd.RETURN)
    assert editor.window.lines == ["  x", ""]


def test_filer_places_masks_and_where_one_window_goes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "notes").mkdir()
    filer = Filer(tmp_path, settings=FilerSettings(["~/notes", "~/none"], ["*.md"], "left"))
    assert filer.places() == [("1", tmp_path / "notes"), ("3", tmp_path)]
    assert FilerLayer(filer).geometry(100) == [(filer.panes[1], 0, 50)]
    filer.settings.single = "full"
    assert FilerLayer(filer).geometry(100) == [(filer.panes[1], 0, 100)]
