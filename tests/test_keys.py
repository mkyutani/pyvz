import pytest

from pyvz.keys import codes
from pyvz.keys.codes import (
    ALT,
    CTRL,
    PREFIX_DIGIT,
    SHIFT,
    ctrl,
    format_key,
    parse_key,
    parse_keys,
    special,
    stroke2,
)
from pyvz.keys.commands import Cmd
from pyvz.keys.keymap import Mode, default_keymap, follow, parse_command_keys

PREFIXES = [ctrl("Q"), ctrl("K"), codes.ESC]


def test_two_stroke_codes_follow_vz():
    assert stroke2(0, "S") == 0x53  # ^QS
    assert stroke2(1, "K") == 0x6B  # ^KK
    assert stroke2(2, "O") == 0x8F  # [ESC]O, same low byte as F15
    assert stroke2(0, 0x13) == stroke2(0, "S")  # ^Q ^S


def test_special_codes():
    assert special("F1") == codes.SPECIAL | 0x81
    assert special("F05", SHIFT) == codes.SPECIAL | 0xA5
    assert special("UP") == codes.SPECIAL | 0x94
    assert special("<--", CTRL) == codes.SPECIAL | 0xD5
    assert special("RLDN") == codes.PGUP  # IBM aliases
    assert special("CLR") == codes.HOME
    assert special("DEL", ALT) == codes.SPECIAL | 0xF3


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("^E", 0x05),
        ("^[", 0x1B),
        ("^@", 0x00),
        ("[UP]", codes.UP),
        ("[F05]", special("F5")),
        ("\\[<--]", special("<--", SHIFT)),
        ("^[-->]", special("-->", CTRL)),
        ("@[INS]", special("INS", ALT)),
        ("@X", stroke2(2, "X")),  # Alt+X is [ESC]X when ESC is a prefix key
        ("^QS", stroke2(0, "S")),
        ("[ESC]O", stroke2(2, "O")),
        ("^K0", PREFIX_DIGIT | 1),
    ],
)
def test_parse_and_format(text: str, code: int):
    assert parse_keys(text, PREFIXES) == (code, "")
    expected = "[ESC]X" if text == "@X" else text
    assert format_key(code, PREFIXES) == expected


def test_alt_without_esc_prefix_stays_alt():
    assert parse_key("@X", [ctrl("Q")]) == (0x38, "")


def test_shift_needs_a_special_key():
    with pytest.raises(ValueError):
        parse_key("\\A", PREFIXES)


def test_parse_command_keys_reads_numbers_keys_and_messages():
    keymap = parse_command_keys(
        "* C\n"
        "00\t^Q ^K [ESC]\t;prefix keys\n"
        "05\t^E   [UP]\t:↑\n"
        "11\t^QS ^[<--]\t:論理行頭\n"
        "70\t[ESC]O\t@O\t:O ファイルのオープン\n"
    )
    assert keymap.prefixes == PREFIXES
    assert keymap.keys[5] == [0x05, codes.UP]
    assert keymap.keys[11] == [stroke2(0, "S"), special("<--", CTRL)]
    assert keymap.keys[70] == [stroke2(2, "O"), stroke2(2, "O")]
    assert keymap.messages[5] == "↑"


@pytest.fixture(scope="module")
def keymap():
    return default_keymap()


def test_default_keymap_has_vz_keys(keymap):
    assert keymap.prefixes == PREFIXES
    assert keymap.command([0x05], Mode.EDIT) == Cmd.UP
    assert keymap.command([stroke2(1, "K")], Mode.EDIT) == Cmd.STORE
    assert keymap.command([stroke2(2, "S")], Mode.EDIT) == Cmd.SAVE
    assert keymap.messages[Cmd.SAVE] == "S ファイルのセーブ"


def test_esc_esc_repeats_the_last_command(keymap):
    assert keymap.command([stroke2(2, 0x1B)], Mode.EDIT) == Cmd.REPEAT
    assert keymap.command([0x1B], Mode.EDIT) is None  # ^[ is no longer bound


def test_alt_w_switches_the_window(keymap):
    # [ESC]W was also #83 (write profile); the lower number wins, as in VZ.
    assert keymap.command([stroke2(2, "W")], Mode.EDIT) == Cmd.SWITCH_WINDOW


def test_tab_depends_on_the_mode(keymap):
    tab = [codes.TAB, 0x09]
    assert keymap.command(tab, Mode.EDIT) == Cmd.TAB
    assert keymap.command(tab, Mode.FILER) == Cmd.FILER_SWITCH_WINDOW


def test_shift_left_selects_in_the_filer(keymap):
    key = [special("<--", SHIFT)]
    assert keymap.command(key, Mode.EDIT) == Cmd.WORD_LEFT
    assert keymap.command(key, Mode.FILER) == Cmd.FILER_SELECT_LEFT


def test_backspace_in_the_filer_goes_to_the_parent(keymap):
    assert keymap.command([codes.BS, 0x08], Mode.FILER) == Cmd.FILER_PARENT
    assert keymap.command([codes.BS, 0x08], Mode.EDIT) == Cmd.BACKSPACE


def test_line_input_has_only_line_editing_commands(keymap):
    assert keymap.command([0x05], Mode.GETS) == Cmd.UP
    assert keymap.command([stroke2(2, "S")], Mode.GETS) is None


def test_pyvz_additions(keymap):
    assert keymap.command([codes.HOME], Mode.EDIT) == Cmd.SCREEN_LINE_LEFT
    assert keymap.command([codes.HOME], Mode.FILER) == Cmd.FILER_TOP_END
    assert keymap.command([PREFIX_DIGIT | 1], Mode.EDIT) == Cmd.MARK_POSITION
    assert keymap.command([PREFIX_DIGIT | 0], Mode.EDIT) == Cmd.LAST_POSITION


def test_follow_a_prefix_key():
    assert follow(0, None, "s") == (stroke2(0, "S"), None)
    assert follow(1, None, "3") == (PREFIX_DIGIT | 1, 3)
    assert follow(0, [0x13], None) == (stroke2(0, "S"), None)  # ^Q ^S
    assert follow(2, [codes.ESC, 0x1B], None) == (stroke2(2, 0x1B), None)  # ESC ESC
    assert follow(0, [codes.UP], None) is None
    assert follow(0, None, "あ") is None
