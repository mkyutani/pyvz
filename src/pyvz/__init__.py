"""pyvz: a VZ Editor-style text editor and file manager for the terminal."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pyvz")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "0.0.0"
