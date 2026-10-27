import pytest


@pytest.fixture(autouse=True)
def private_xdg(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    """Keep every test away from the user's own settings, histories and drafts."""
    base = tmp_path_factory.mktemp("xdg")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(base / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(base / "state"))
    return base


@pytest.fixture(autouse=True)
def default_colors():
    """Colors set by a test do not stay for the next one."""
    from pyvz.ui import theme

    yield
    theme.reset()
