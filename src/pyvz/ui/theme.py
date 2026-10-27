"""The colors of the screen, by name, so that the settings file can change them."""

from __future__ import annotations

from dataclasses import fields, replace

from pyvz.ui.screen import Style

DEFAULTS = {
    "text": Style(),
    "status": Style(reverse=True),
    "status_other": Style(reverse=True, dim=True),  # of the window without the cursor
    "control": Style(fg=6),  # control characters, and bytes that are not UTF-8
    "mark": Style(fg=8),  # line ends and the end of the text
    "message": Style(fg=3, bold=True),
    "key_label": Style(reverse=True),
    "frame": Style(fg=6),
    "title": Style(fg=6, bold=True),
    "hot": Style(fg=3, bold=True),  # the key letter of a menu item
    "chosen": Style(reverse=True),
    "chosen_hot": Style(fg=3, bold=True, reverse=True),
    "directory": Style(fg=6),
    "executable": Style(fg=3),
    "hidden": Style(fg=8),
    "link": Style(fg=5),
    "origin_title": Style(fg=6, bold=True, reverse=True),  # the start directory
}

_BASIC = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]
COLOR_NAMES = (
    {name: i for i, name in enumerate(_BASIC)}
    | {f"bright_{name}": i + 8 for i, name in enumerate(_BASIC)}
    | {"gray": 8, "grey": 8}
)

_styles = dict(DEFAULTS)


def style(name: str) -> Style:
    return _styles[name]


def reset() -> None:
    _styles.clear()
    _styles.update(DEFAULTS)


def _color(value: object) -> int | None:
    if value is None or value == "default":
        return None
    if isinstance(value, bool):
        raise ValueError(value)
    if isinstance(value, int) and 0 <= value <= 255:
        return value
    if isinstance(value, str) and value.lower() in COLOR_NAMES:
        return COLOR_NAMES[value.lower()]
    raise ValueError(value)


def configure(colors: dict[str, object]) -> list[str]:
    """Take colors from the settings, such as {"status": {"fg": "black", "bg": 6}}.

    A name not given keeps its default; so does each attribute not given, except that
    giving fg or bg turns reverse off unless reverse is given too: the colors are then
    meant as written. Returns what could not be used.
    """
    errors = []
    flags = {f.name for f in fields(Style)} - {"fg", "bg"}
    for name, value in colors.items():
        if name not in DEFAULTS:
            errors.append(f"colors.{name}: そういう名前の色はありません")
            continue
        if not isinstance(value, dict):
            errors.append(f"colors.{name}: 表（{{ fg = ..., bold = true }}）で書きます")
            continue
        changes: dict[str, object] = {}
        for key, item in value.items():
            try:
                if key in ("fg", "bg"):
                    changes[key] = _color(item)
                elif key in flags and isinstance(item, bool):
                    changes[key] = item
                else:
                    raise ValueError(item)
            except ValueError:
                errors.append(f"colors.{name}.{key}: {item!r} は使えません")
        if ("fg" in changes or "bg" in changes) and "reverse" not in changes:
            changes["reverse"] = False
        _styles[name] = replace(DEFAULTS[name], **changes)
    return errors
