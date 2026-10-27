"""The settings file, ~/.config/pyvz/config.toml.

Everything in it can be left out. Mistakes do not stop pyvz: they are reported, and
the default is used for what is wrong.

    [editor]
    tab_size = 8
    ambiguous_wide = false    # true if the terminal shows box drawing etc. 2 wide
    auto_indent = true        # VZ: Ei
    function_keys = true      # the line of function key labels
    esc_delay_ms = 50         # how long to wait after ESC for the rest of a key

    [search]
    options = ""              # default options, letters of WCZXI (VZ: Ew Ec ZH RX)

    [keys]
    def = "~/vz/VZ.DEF"       # read the command keys ("* C") of a DEF file
    75 = "[ESC]S ^KS"         # keys of a command, by number or name, as in DEF files
    SET_SEARCH = "^QF [F06]"

    [filer]
    places = ["~/windownloads", "~/windocuments", "~/windropbox", "~"]
    masks = ["*.md", "*.py *.toml"]
    single = "right"          # where one window goes: right, left, full

    [colors]
    status = { fg = "black", bg = "cyan" }
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from pyvz import paths
from pyvz.filer.filer import PLACES

SINGLE_PLACES = ("right", "left", "full")


@dataclass
class Config:
    tab_size: int = 8
    ambiguous_wide: bool = False
    auto_indent: bool = True
    function_keys: bool = True
    esc_delay_ms: int = 50
    search_options: str = ""
    keys_def: str | None = None
    keys: dict[str, str] = field(default_factory=dict)  # command (number or name) -> keys
    places: list[str] = field(default_factory=lambda: list(PLACES))
    masks: list[str] = field(default_factory=list)
    single: str = "right"
    colors: dict[str, object] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


# The items each section may have.
KNOWN = {
    "editor": {"tab_size", "ambiguous_wide", "auto_indent", "function_keys", "esc_delay_ms"},
    "search": {"options"},
    "filer": {"places", "masks", "single"},
}


def _section(config: Config, data: dict, name: str) -> dict:
    table = data.get(name, {})
    if not isinstance(table, dict):
        config.errors.append(f"{name}: [{name}] の節として書きます")
        return {}
    for key in table.keys() - KNOWN.get(name, table.keys()):
        config.errors.append(f"{name}.{key}: そういう項目はありません")
    return table


def _take(config: Config, table: dict, key: str, attr: str, kind: type, where: str) -> None:
    if key not in table:
        return
    value = table[key]
    if (kind is int and isinstance(value, bool)) or not isinstance(value, kind):
        config.errors.append(f"{where}.{key}: {kind.__name__} で書きます")
        return
    setattr(config, attr, value)


def load(path: Path | None = None) -> Config:
    config = Config()
    path = path or paths.config_file()
    try:
        data = tomllib.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        return config
    except (OSError, UnicodeDecodeError) as e:
        config.errors.append(f"{path.name}: 読めません（{e}）")
        return config
    except tomllib.TOMLDecodeError as e:
        config.errors.append(f"{path.name}: {e}")
        return config

    editor = _section(config, data, "editor")
    for key, kind in (
        ("tab_size", int),
        ("ambiguous_wide", bool),
        ("auto_indent", bool),
        ("function_keys", bool),
        ("esc_delay_ms", int),
    ):
        _take(config, editor, key, key, kind, "editor")
    if not 1 <= config.tab_size <= 32:
        config.errors.append("editor.tab_size: 1 から 32 まで")
        config.tab_size = 8
    if not 0 <= config.esc_delay_ms <= 2000:
        config.errors.append("editor.esc_delay_ms: 0 から 2000 まで")
        config.esc_delay_ms = 50

    search = _section(config, data, "search")
    _take(config, search, "options", "search_options", str, "search")
    if any(ch.upper() not in "WCZXI" for ch in config.search_options):
        config.errors.append("search.options: W C Z X I の文字で書きます")
        config.search_options = ""

    keys = dict(_section(config, data, "keys"))
    if "def" in keys:
        value = keys.pop("def")
        if isinstance(value, str):
            config.keys_def = value
        else:
            config.errors.append("keys.def: DEF ファイルのパスを書きます")
    for name, value in keys.items():
        if isinstance(value, str):
            config.keys[name] = value
        else:
            config.errors.append(f"keys.{name}: キーを文字列で書きます")

    filer = _section(config, data, "filer")
    for key in ("places", "masks"):
        if key in filer:
            value = filer[key]
            if isinstance(value, list) and all(isinstance(v, str) for v in value):
                setattr(config, key, value)
            else:
                config.errors.append(f"filer.{key}: 文字列の並びで書きます")
    _take(config, filer, "single", "single", str, "filer")
    if config.single not in SINGLE_PLACES:
        config.errors.append("filer.single: right、left、full のどれか")
        config.single = "right"

    config.colors = _section(config, data, "colors")
    for section in data:
        if section not in ("editor", "search", "keys", "filer", "colors"):
            config.errors.append(f"[{section}]: そういう節はありません")
    return config
