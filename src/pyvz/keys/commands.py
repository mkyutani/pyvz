"""Command numbers.

The numbers are VZ's, which DEF files and macros use (``#05`` in a macro is the
cursor-up command). Numbers from 200 are commands that pyvz adds; VZ.DEF did these
with macros.
"""

from __future__ import annotations

from enum import IntEnum


class Cmd(IntEnum):
    REPEAT = 1  # run the last command again
    KEYBOARD_MACRO = 2
    ESCAPE = 3
    RETURN = 4
    UP = 5
    DOWN = 6
    LEFT = 7
    RIGHT = 8
    WORD_LEFT = 9
    WORD_RIGHT = 10
    LINE_TOP = 11
    LINE_END = 12
    INSERT_MODE = 13
    BACKSPACE = 14
    DELETE = 15
    DELETE_WORD_BACK = 16
    DELETE_WORD = 17
    DELETE_TO_LINE_TOP = 18
    DELETE_TO_LINE_END = 19
    UNDELETE = 20
    TAB = 21
    CONTROL_CHAR = 22
    CHANGE_CASE = 23
    COPY_STRING = 24  # type the search string
    COPY_FILE_NAME = 25  # type the file name of the text
    REDRAW_LINE = 29
    PAGING_MODE = 30
    ROLL_UP = 31
    ROLL_DOWN = 32
    ROLL_UP2 = 33
    ROLL_DOWN2 = 34
    PAGE_UP = 35
    PAGE_DOWN = 36
    SMOOTH_UP = 37
    SMOOTH_DOWN = 38
    WINDOW_TOP = 39
    WINDOW_END = 40
    TEXT_TOP = 41
    TEXT_END = 42
    LAST_POSITION = 43
    MARK_POSITION = 44
    JUMP_LINE = 45
    BLOCK = 46
    CUT = 47  # push the line or block onto the text stack, deleting it
    PASTE = 48  # pop from the text stack and insert
    STORE = 49  # push the line or block without deleting it
    LOAD = 50  # insert the top of the text stack without popping it
    CLEAR_STACK = 51
    BLOCK_JUMP = 52
    INSERT_LINE = 53
    CANCEL_LINE = 54
    SET_SEARCH = 55
    REPLACE = 56
    REPLACE_AGAIN = 57
    MATCH_BRACKET = 58
    GET_WORD = 59
    READ_TAG = 60
    SELECT_STRING = 61
    SWITCH_WINDOW = 62
    SWITCH_TEXT = 63
    SPLIT_MODE = 64
    SPLIT_POSITION = 65
    DISPLAY_LINES = 66
    READ_ONLY = 67
    CHANGE_INDENT = 68
    COMPARE_TEXT = 69
    OPEN = 70
    OPEN_READ_ONLY = 71
    NEW_FILE = 72
    CLOSE = 73
    CLOSE_OPEN = 74
    SAVE = 75
    APPEND = 76
    QUIT = 77
    COMMAND_LINE = 78  # VZ: run a DOS command. pyvz: put the draft on hold (CC)
    CONSOLE = 79
    RECUSTOMIZE = 80
    PRINT_KEYBOARD_MACRO = 81
    RENAME = 82
    WRITE_PROFILE = 83
    SET_TITLE_SEARCH = 84
    DUMMY = 85  # "#]": no operation, but the line buffer is written back
    FILER_SELECT_LEFT = 88
    FILER_SELECT_RIGHT = 89
    FILER_SELECT_UP = 90
    FILER_SELECT_DOWN = 91
    FILER_TOP_END = 92
    FILER_SWITCH_WINDOW = 93
    FILER_PARENT = 94
    DOS_CONSOLE = 95
    DOS_ALIASES = 96
    DOS_SPREAD = 97
    TO_FILER = 98
    # Added by pyvz.
    SCREEN_LINE_LEFT = 200  # VZ.DEF macro 12 "画面の左端"
    SCREEN_LINE_RIGHT = 201  # VZ.DEF macro 13 "画面の右端"
