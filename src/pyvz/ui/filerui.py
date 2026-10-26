"""The filer on the screen: the menu bar, the windows, and what its keys do.

As in VZ, lower case letters open the menus of the menu bar by their initials, upper
case letters move to the next file with that initial, Space selects, and digits pick
a directory of the Dir menu (VZ's drives).
"""

from __future__ import annotations

import os
import shutil
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from pyvz import history, paths
from pyvz.filer import ops
from pyvz.filer.filer import LEFT, RIGHT, Filer, Insert, Open, insertion
from pyvz.filer.listing import Entry, Order, size_text
from pyvz.filer.pane import Pane
from pyvz.keys import codes
from pyvz.keys.commands import Cmd
from pyvz.keys.keymap import Mode
from pyvz.ui.loop import Loop, Typed
from pyvz.ui.screen import PLAIN, Screen, Style, clip_middle, clip_start
from pyvz.ui.view import Overlay, draw_message
from pyvz.ui.widgets import HOT, TITLE, frame

MENU_BAR = [
    ("F", "File"),
    ("D", "Dir"),
    ("M", "Mask"),
    ("P", "Path"),
    ("S", "Sort"),
    ("W", "Window"),
    ("A", "All"),
    ("R", "RetCD"),
]
# The items of the bar that open a menu. Left and right go from one to the next.
MENUS = "FDMS"

FILE_MENU = [
    ("C", "コピー"),
    ("M", "移動"),
    ("D", "削除"),
    ("R", "名前の変更"),
    ("K", "ディレクトリ作成"),
    ("N", "新規ファイル作成"),
]
MASK_MENU = [("W", "すべて"), ("H", "隠しファイルの表示/非表示")]
SORT_MENU = [
    ("F", "ファイル名", Order.NAME),
    ("N", "新しい順", Order.NEWEST),
    ("O", "古い順", Order.OLDEST),
    ("L", "大きい順", Order.LARGEST),
    ("S", "小さい順", Order.SMALLEST),
]

DIRECTORY = Style(fg=6)
EXECUTABLE = Style(fg=3)
HIDDEN = Style(fg=8)
LINK = Style(fg=5)
ORIGIN_TITLE = Style(fg=6, bold=True, reverse=True)

# Below this width, one window takes the whole width instead of the right half.
NARROW = 60


def _bar_columns() -> list[int]:
    columns, column = [], 1
    for _, label in MENU_BAR:
        columns.append(column)
        column += len(label) + 2
    return columns


def _style(e: Entry) -> Style:
    if e.is_link:
        return LINK
    if e.is_dir:
        return DIRECTORY
    if e.hidden:
        return HIDDEN
    if e.executable:
        return EXECUTABLE
    return PLAIN


def _with(style: Style, *, selected: bool, cursor: bool) -> Style:
    """Selected entries are reversed (VZ), and the cursor is underlined."""
    if not (selected or cursor):
        return style
    return replace(style, underline=cursor, reverse=selected)


def date_text(mtime: float, now: datetime) -> str:
    """MM-DD HH:MM within this year, YYYY-MM-DD before, as ls -l does."""
    when = datetime.fromtimestamp(mtime)
    return when.strftime("%m-%d %H:%M" if when.year == now.year else "%Y-%m-%d")


class FilerLayer:
    """Draws the filer over the editor, with its own message line at the bottom."""

    owns_message = True

    def __init__(self, filer: Filer) -> None:
        self.filer = filer
        self.now = datetime.now()

    @staticmethod
    def list_rows(height: int) -> int:
        """Rows of files in a window, for a terminal `height` rows high."""
        return max(height - 4, 1)

    def geometry(self, width: int) -> list[tuple[Pane, int, int]]:
        """The windows shown, with their left column and width."""
        filer = self.filer
        if filer.dual:
            half = width // 2
            return [(filer.panes[LEFT], 0, half), (filer.panes[RIGHT], half, width - half)]
        if width < NARROW:
            return [(filer.panes[RIGHT], 0, width)]
        return [(filer.panes[RIGHT], width // 2, width - width // 2)]

    def draw(self, screen: Screen, overlay: Overlay) -> None:
        self.now = datetime.now()
        self._menu_bar(screen)
        height = max(screen.height - 2, 3)
        for pane, left, width in self.geometry(screen.width):
            self._pane(screen, pane, left, width, height, pane is self.filer.pane)
        row = screen.height - 1
        screen.fill(row, 0, screen.width)
        end = draw_message(screen, overlay, row)
        screen.cursor = (row, end) if overlay.question else None

    def _menu_bar(self, screen: Screen) -> None:
        screen.fill(0, 0, screen.width)
        for (key, label), column in zip(MENU_BAR, _bar_columns(), strict=True):
            screen.put(0, column, key, HOT)
            screen.put(0, column + 1, label[1:])

    def _pane(
        self, screen: Screen, pane: Pane, left: int, width: int, height: int, active: bool
    ) -> None:
        wide = screen.ambiguous_wide
        title = paths.tilde(pane.path)
        if pane.pattern != "*":
            title = title.rstrip("/") + "/" + pane.pattern
        title = f" {clip_start(title, width - 4, ambiguous_wide=wide)} "
        style = ORIGIN_TITLE if pane.path == self.filer.origin else TITLE
        footer = self._footer(pane)
        frame(screen, 1, left, height, width, title=title, title_style=style, footer=footer)
        rows = self.list_rows(screen.height)
        pane.keep_visible(rows)
        inner = width - 2
        for y in range(rows):
            i = pane.top + y
            if i >= len(pane.entries):
                break
            e = pane.entries[i]
            row = 2 + y
            selected = e.name in pane.selected
            cursor = active and i == pane.cursor
            base = _with(_style(e), selected=selected, cursor=cursor)
            if selected or cursor:
                bar = _with(PLAIN, selected=selected, cursor=cursor)
                screen.fill(row, left + 1, left + 1 + inner, bar)
            self._line(screen, row, left + 1, inner, e, base, wide)

    def _line(
        self, screen: Screen, row: int, left: int, inner: int, e: Entry, style: Style, wide: bool
    ) -> None:
        name = e.name + ("/" if e.is_dir else "")
        size = "-" if e.is_dir else size_text(e.size)
        if inner >= 34:
            info = f"{size:>5} {date_text(e.mtime, self.now):<11}"
        else:
            info = f"{size:>5}"
        room = max(inner - 1 - len(info), 1)
        screen.put(row, left, clip_middle(name, room, ambiguous_wide=wide), style)
        screen.put(row, left + inner - len(info), info, style)

    def _footer(self, pane: Pane) -> str:
        if pane.selected:
            chosen = [e for e in pane.entries if e.name in pane.selected]
            total = sum(e.size for e in chosen if not e.is_dir)
            return f" {len(chosen)} files ── {size_text(total)} "
        count = sum(1 for e in pane.entries if not e.is_parent)
        try:
            free = f"{size_text(shutil.disk_usage(pane.path).free)} free"
        except OSError:
            free = ""
        return f" {count} files ── {free} " if free else f" {count} files "


class FilerScreen:
    """Runs the filer until a file is opened, paths are inserted, or ESC."""

    def __init__(self, loop: Loop, filer: Filer, *, readonly: bool = False) -> None:
        self.loop = loop
        self.filer = filer
        self.readonly = readonly
        self.layer = FilerLayer(filer)
        self.result: Open | Insert | None = None
        self.done = False

    def message(self, text: str) -> None:
        self.loop.message(text)

    def run(self) -> Open | Insert | None:
        errors = self.filer.load()
        if errors:
            self.message(errors[0])
        self.loop.layers.append(self.layer)
        try:
            while not self.done:
                self.loop.draw()
                press = self.loop.read_press(Mode.FILER)
                self.loop.overlay.message = ""
                if press is None:
                    continue
                if isinstance(press, Typed):
                    if len(press.text) == 1:  # not a paste
                        self.typed(press.text)
                else:
                    self.command(press.number, press.key)
        finally:
            self.loop.layers.remove(self.layer)
            self.filer.save_state()
        return self.result

    def _finish(self, result: Open | Insert | None) -> None:
        self.result = result
        self.done = True

    def _rows(self) -> int:
        return FilerLayer.list_rows(self.loop.size[1])

    def _go(self, pane: Pane, path: Path, focus: str | None = None) -> None:
        try:
            pane.go(path, focus)
        except OSError as e:
            self.message(f"{paths.tilde(path)}: {e.strerror or e}")

    def _reload(self) -> None:
        for pane in self.filer.panes:
            try:
                pane.load()
            except OSError as e:
                self.message(f"{paths.tilde(pane.path)}: {e.strerror or e}")

    # Keys

    def typed(self, ch: str) -> None:
        filer, pane = self.filer, self.filer.pane
        if ch == " ":
            pane.toggle()
            pane.move(1)
        elif ch == "*":
            pane.pattern = "*"
            self._reload()
        elif ch in "/\\":
            self._go(pane, Path("/"))
        elif ch.isdigit():
            self.place(ch)
        elif ch.isupper():
            pane.jump(ch)
        elif ch.upper() in MENUS:
            self.open_menu(ch.upper())
        elif ch == "p":
            self.path_input()
        elif ch == "w":
            filer.toggle_dual()
        elif ch == "a":
            pane.invert_all()
        elif ch == "r":
            try:
                filer.ret_cd()
            except OSError as e:
                self.message(f"{e.strerror or e}")
        elif ch == "i":
            self.insert()
        elif ch == "k":
            self.make(directory=True)
        elif ch == "n":
            self.make(directory=False)

    def command(self, number: int, key: tuple[int, ...]) -> None:
        filer, pane = self.filer, self.filer.pane
        rows = self._rows()
        if number == Cmd.ESCAPE:
            self._finish(None)
        elif number in (Cmd.RETURN, Cmd.INSERT_LINE):
            self.enter()
        elif number in (Cmd.UP, Cmd.ROLL_UP, Cmd.SMOOTH_UP):
            pane.move(-1)
        elif number in (Cmd.DOWN, Cmd.ROLL_DOWN, Cmd.SMOOTH_DOWN):
            pane.move(1)
        elif number == Cmd.PAGE_UP:
            pane.move(-(rows - 1))
        elif number == Cmd.PAGE_DOWN:
            pane.move(rows - 1)
        elif number == Cmd.FILER_SELECT_UP:  # move, then select
            pane.move(-1)
            pane.toggle()
        elif number == Cmd.FILER_SELECT_DOWN:  # select, then move
            pane.toggle()
            pane.move(1)
        elif number in (Cmd.LEFT, Cmd.RIGHT):
            if filer.dual:
                filer.active = LEFT if number == Cmd.LEFT else RIGHT
        elif number == Cmd.FILER_SWITCH_WINDOW:
            filer.switch()
        elif number in (Cmd.FILER_PARENT, Cmd.BACKSPACE):
            try:
                pane.parent()
            except OSError as e:
                self.message(f"{e.strerror or e}")
        elif number == Cmd.FILER_TOP_END:
            if codes.END in key:
                pane.to_end()
            else:
                pane.to_top()
        elif number == Cmd.TEXT_TOP:
            pane.to_top()
        elif number == Cmd.TEXT_END:
            pane.to_end()
        elif number == Cmd.WINDOW_TOP:
            pane.cursor = pane.top
        elif number == Cmd.WINDOW_END:
            pane.cursor = min(pane.top + rows - 1, max(len(pane.entries) - 1, 0))
        elif number == Cmd.INSERT_MODE:  # [INS]
            pane.invert_all()
        elif number == Cmd.DELETE:  # [DEL]
            pane.clear()

    def enter(self) -> None:
        pane = self.filer.pane
        e = pane.current
        if e is None:
            return
        if e.is_dir and not pane.selected:
            try:
                pane.enter()
            except OSError as error:
                self.message(f"{e.name}: {error.strerror or error}")
            return
        files = [t for t in pane.targets() if not t.is_dir]
        if not files:
            self.message("ファイルがありません")
            return
        self._finish(Open([pane.path / t.name for t in files], self.readonly))

    def insert(self) -> None:
        pane = self.filer.pane
        targets = pane.targets()
        if not targets:
            self.message("ファイルがありません")
            return
        chosen = [pane.path / t.name for t in targets]
        self._finish(Insert(insertion(chosen, self.filer.origin)))

    def place(self, key: str) -> None:
        """A digit: that directory of the Dir menu in the other window, 0: the start."""
        filer = self.filer
        if key == "0":
            self._go(filer.pane, filer.origin)
            return
        found = dict(filer.places()).get(key)
        if found is None:
            self.message(f"Dir メニューに {key} はありません")
            return
        try:
            filer.show_other(found)
        except OSError as e:
            self.message(f"{paths.tilde(found)}: {e.strerror or e}")

    # Menus

    def open_menu(self, letter: str) -> None:
        """Open a menu of the bar. Left and right go to the next menu."""
        while True:
            chosen = self._popup(letter)
            if chosen in ("left", "right"):
                step = -1 if chosen == "left" else 1
                letter = MENUS[(MENUS.index(letter) + step) % len(MENUS)]
                continue
            if isinstance(chosen, int):
                self._act(letter, chosen)
            return

    def _popup(self, letter: str) -> int | str | None:
        column = _bar_columns()[[k for k, _ in MENU_BAR].index(letter)]
        if letter == "F":
            items = FILE_MENU
        elif letter == "D":
            items = self._dir_items()
        elif letter == "M":
            items = MASK_MENU
        else:
            items = [(k, label) for k, label, _ in SORT_MENU]
        if not items:
            return None
        return self.loop.menu(items, top=1, left=column - 1, sideways=True)

    def _dir_items(self) -> list[tuple[str, str]]:
        items = []
        for key, path in self.filer.places():
            label = paths.tilde(path)
            if path == self.filer.origin:
                label += " (起点)"
            items.append((key, label))
        return items

    def _act(self, letter: str, index: int) -> None:
        filer, pane = self.filer, self.filer.pane
        if letter == "F":
            action = FILE_MENU[index][0]
            if action in "CM":
                self.transfer(move=action == "M")
            elif action == "D":
                self.delete()
            elif action == "R":
                self.rename()
            else:
                self.make(directory=action == "K")
        elif letter == "D":
            self._go(pane, filer.places()[index][1])
        elif letter == "M":
            if MASK_MENU[index][0] == "W":
                pane.pattern = "*"
            else:
                pane.show_hidden = not pane.show_hidden
            self._reload()
        elif letter == "S":
            filer.set_order(SORT_MENU[index][2])

    def _choose_place(self) -> Path | None:
        items = self._dir_items()
        if not items:
            return None
        chosen = self.loop.menu(items, title="【Dir】", top=1, left=_bar_columns()[1] - 1)
        return self.filer.places()[chosen][1] if isinstance(chosen, int) else None

    def path_input(self) -> None:
        """P: a directory, a file, or a directory and a pattern (~/notes/*.md)."""
        pane = self.filer.pane
        here = paths.tilde(pane.path).rstrip("/") + "/"
        start = here + (pane.pattern if pane.pattern != "*" else "")
        text = self.loop.gets("【パス・マスク】", start, kind=history.FILE)
        if text is None:
            return
        if not text.strip():
            place = self._choose_place()
            if place is not None:
                self._go(pane, place)
            return
        path = pane.path / os.path.expanduser(text.strip())
        if any(ch in path.name for ch in "*?["):
            directory, pattern = path.parent, path.name
        elif path.is_dir():
            directory, pattern = path, "*"
        elif path.exists() or path.is_symlink():
            self._go(pane, path.parent, focus=path.name)
            return
        else:
            self.message(f"{text} は見つかりません")
            return
        old_pattern = pane.pattern
        pane.pattern = pattern
        self._go(pane, directory)
        if pane.path != Path(os.path.abspath(directory)):
            pane.pattern = old_pattern

    # File operations

    def _destination(self, move: bool) -> Path | None:
        filer = self.filer
        if filer.dual:
            return filer.other.path
        title = "【移動先】" if move else "【コピー先】"
        text = self.loop.gets(title, kind=history.COPY)
        if text is None:
            return None
        if not text.strip():
            return self._choose_place()
        path = filer.pane.path / os.path.expanduser(text.strip())
        if not path.is_dir():
            self.message(f"{text} はディレクトリではありません")
            return None
        return path

    def transfer(self, *, move: bool) -> None:
        pane = self.filer.pane
        targets = pane.targets()
        if not targets:
            self.message("ファイルがありません")
            return
        destination = self._destination(move)
        if destination is None:
            return
        verb = "移動" if move else "コピー"

        def ask(target: Path) -> str | None:
            question = f"{target.name} はすでに存在します. 上書きしますか？ "
            return self.loop.choose(question + "(Y/N/A:全部/S:全部しない) ", "YNAS")

        def progress(source: Path) -> None:
            self.message(f"{source.name} を{verb}中 ...")
            self.loop.draw()

        sources = [pane.path / t.name for t in targets]
        result = ops.transfer(sources, destination, move=move, ask=ask, progress=progress)
        pane.clear()
        self._reload()
        self._report(result, verb, paths.tilde(destination))

    def _report(self, result: ops.Result, verb: str, where: str = "") -> None:
        parts = []
        if result.cancelled:
            parts.append("中止しました")
        if result.done:
            parts.append(f"{len(result.done)} 個{verb}しました" + (f"（{where}）" if where else ""))
        if result.skipped:
            parts.append(f"{len(result.skipped)} 個は飛ばしました")
        if result.errors:
            parts.append(f"{len(result.errors)} 個はできませんでした: {result.errors[0]}")
        self.message("、".join(parts) or f"{verb}するものがありません")

    def delete(self) -> None:
        pane = self.filer.pane
        targets = pane.targets()
        if not targets:
            self.message("ファイルがありません")
            return
        doomed = [pane.path / t.name for t in targets]
        note = "（中身のあるディレクトリを含みます）" if any(map(ops.has_contents, doomed)) else ""
        if not self.loop.ask(f"{len(doomed)} 個のファイルを削除します{note}.よろしいです"):
            return
        result = ops.delete(doomed)
        pane.clear()
        self._reload()
        self._report(result, "削除")

    def rename(self) -> None:
        pane = self.filer.pane
        e = pane.current
        if e is None or e.is_parent:
            return
        new = self.loop.gets("【名前の変更】", e.name)
        if new is None or new == e.name:
            return
        problem = ops.check_name(new)
        if problem:
            self.message(problem)
            return
        try:
            ops.rename(pane.path, e.name, new)
        except OSError as error:
            self.message(f"{new}: {error.strerror or error}")
            return
        self._reload()
        self._go(pane, pane.path, focus=new)

    def make(self, *, directory: bool) -> None:
        pane = self.filer.pane
        name = self.loop.gets("【ディレクトリ作成】" if directory else "【新規ファイル作成】")
        if not name:
            return
        problem = ops.check_name(name)
        if problem:
            self.message(problem)
            return
        try:
            made = (ops.make_dir if directory else ops.make_file)(pane.path, name)
        except OSError as error:
            self.message(f"{name}: {error.strerror or error}")
            return
        if not made:
            self.message(f"{name} はすでに存在します")
        self._reload()
        self._go(pane, pane.path, focus=name)
