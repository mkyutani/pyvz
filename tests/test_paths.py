import stat
from pathlib import Path

import pytest

from pyvz import paths


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    return tmp_path


def test_defaults_are_under_home(home: Path):
    assert paths.config_file() == home / ".config/pyvz/config.toml"
    assert paths.filer_state_file() == home / ".local/state/pyvz/filer.json"
    assert paths.history_file() == home / ".local/state/pyvz/history.json"
    assert paths.drafts_dir() == home / ".local/state/pyvz/drafts"


def test_xdg_variables_are_used(home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "conf"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / "state"))
    assert paths.config_dir() == home / "conf/pyvz"
    assert paths.state_dir() == home / "state/pyvz"


def test_relative_xdg_variables_are_ignored(home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_STATE_HOME", "relative/state")
    assert paths.state_dir() == home / ".local/state/pyvz"


def test_private_dir_is_owner_only(home: Path):
    drafts = paths.ensure_private_dir(paths.drafts_dir())
    assert drafts.is_dir()
    assert stat.S_IMODE(drafts.stat().st_mode) == 0o700


def test_private_dir_tightens_existing_permissions(home: Path):
    target = home / "shared"
    target.mkdir(mode=0o755)
    paths.ensure_private_dir(target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
