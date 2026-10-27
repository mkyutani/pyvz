# pyvz

A text editor and file manager for the terminal that follows the operation of
[VZ Editor](https://github.com/vcraftjp/VZEditor) (1989–1993, MS-DOS), written in Python.

pyvz is meant to be used as `$EDITOR` for [Claude Code](https://code.claude.com/):
write a prompt in the editor, peek at files and copy file names or files with the
VZ-style filer, and put a long draft (meeting notes, for example) on hold while
you use Claude Code for something else.

It reproduces VZ's keys and the flow between the editor and the filer.
The look and file handling follow today's conventions (UTF-8, LF, long file names,
terminal width).

## Status

Under development. The editor works on the terminal with VZ's keys for moving,
typing, blocks and the text stack, search and replace, opening, saving and closing
files, and with Claude Code as below. VZ has no general undo, and neither has pyvz:
^U puts back what the delete keys deleted, and ^QL puts the cursor line back as it
was. The filer works too. Split windows, settings and macros are still to come.

Search strings follow VZ: `^QF` sets one, and `^R` and `^C` then search backward and
forward. Options go in front, as in `\WC word` (W word search, C ignore case, Z full
and half width alike, X regular expression, which is Python's, I no escapes).

## Usage

```sh
pyvz FILE...     # edit files
pyvz [DIR]       # start from the filer
pyvz -c FILE     # edit a prompt file from Claude Code's Ctrl-G (external editor)
```

To install the command from a checkout:

```sh
uv tool install --editable .
```

### With Claude Code

Claude Code opens `$VISUAL` (or else `$EDITOR`) on Ctrl-G. Set it to `pyvz -c` for
Claude Code only, for example with an alias:

```sh
alias claude='VISUAL="pyvz -c" claude'
```

In the editor:

| Keys | What happens |
|---|---|
| `[ESC]C` | Save and give the text to Claude Code's input box (no question asked) |
| `[ESC]E` | Put the text on hold and go back with the input box unchanged. The next Ctrl-G in the same session opens the draft again |
| `[ESC]Q`, `@X` | Quit; the prompt text goes to Claude Code as with `[ESC]C` |

A draft on hold belongs to one Claude Code session. If text was typed into the input
box meanwhile, it is added after the draft. A draft left by a session that has ended
opens in a later session, drafts from the same directory first, so nothing is lost.
If pyvz ends unexpectedly, the text is kept as a draft too.

### The filer

`[ESC]O` (or `[ESC]R` for read only) and Enter on the empty 【入力ファイル】 box open the
filer. One window takes the right half of the terminal, so the text stays in sight.

| Keys | What happens |
|---|---|
| Enter / ESC | Open the file or go into the directory / go back to the text |
| Space, Shift+↑↓, INS, DEL | Select, invert all, clear |
| `f` | File menu: copy, move, delete, rename, make a directory or a file |
| `d`, `1`-`5`, `0` | Dir menu / that directory in the other window / the start directory |
| `m` `p` `s` `w` `a` `r` | Mask, path, sort, one or two windows, invert the selection, back to the start |
| `i` | Type the paths of the selected files into the text, relative to the start |
| Upper case letter | The next file with that initial |

Settings go to `~/.config/pyvz/config.toml`, and state (filer position, histories,
drafts on hold) to `~/.local/state/pyvz/`, following the XDG Base Directory
Specification.

## Development

```sh
uv sync
uv run pytest
uv run ruff check
```

## Acknowledgements

pyvz is based on the design of VZ Editor by c.mos (Yoshihiko Hyodo), published at
[vcraftjp/VZEditor](https://github.com/vcraftjp/VZEditor) under the BSD 3-Clause License.
pyvz is not affiliated with or endorsed by the authors of VZ Editor.

## License

BSD 3-Clause License. See [LICENSE](LICENSE). The copyright notice of VZ Editor is kept
in it.
