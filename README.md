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
typing, saving and closing, and with Claude Code as below. The filer, blocks, the
text stack, search and the other commands are still to come.

## Usage

```sh
pyvz FILE...     # edit files
pyvz [DIR]       # start from the filer (not yet)
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
