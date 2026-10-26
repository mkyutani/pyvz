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

Under development. Nothing is usable yet.

## Planned usage

```sh
pyvz FILE...     # edit files
pyvz [DIR]       # start from the filer
pyvz -c FILE     # edit a prompt file from Claude Code's Ctrl-G (external editor)
```

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
