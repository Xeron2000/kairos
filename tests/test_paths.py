"""Tests for centralized path management (XDG-compliant)."""

from pathlib import Path
from unittest.mock import patch

from kairos.paths import (
    get_config_dir,
    get_config_path,
    get_log_path,
    get_markets_path,
    get_pid_path,
    get_symbols_path,
)


class TestGetConfigDir:
    """Tests for get_config_dir()."""

    def test_xdg_config_home_set(self, monkeypatch, tmp_path: Path):
        """When XDG_CONFIG_HOME is set, use it as base."""
        xdg = tmp_path / "xdg_config"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

        result = get_config_dir()

        assert result == xdg / "kairos"
        assert result.exists()
        assert result.is_dir()

    def test_xdg_config_home_not_set(self, monkeypatch, tmp_path: Path):
        """When XDG_CONFIG_HOME is not set, default to ~/.config/kairos."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()

        with patch("kairos.paths.Path.home", return_value=fake_home):
            result = get_config_dir()

        expected = fake_home / ".config" / "kairos"
        assert result == expected
        assert expected.exists()
        assert expected.is_dir()

    def test_creates_dir_if_missing(self, monkeypatch, tmp_path: Path):
        """Directory should be created if it doesn't exist."""
        xdg = tmp_path / "xdg_nonexistent"
        # Don't create this dir yet
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

        result = get_config_dir()

        assert result.exists()
        assert result.is_dir()

    def test_existing_dir_no_error(self, monkeypatch, tmp_path: Path):
        """No error when the directory already exists."""
        xdg = tmp_path / "xdg_already"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
        (xdg / "kairos").mkdir(parents=True)

        result = get_config_dir()

        assert result.exists()
        assert result.is_dir()


class TestGetConfigPath:
    """Tests for get_config_path()."""

    def test_returns_config_yaml(self, monkeypatch, tmp_path: Path):
        """Returns config_dir/config.yaml."""
        xdg = tmp_path / "xdg_cfg"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

        result = get_config_path()

        assert result == xdg / "kairos" / "config.yaml"

    def test_from_default_home(self, monkeypatch, tmp_path: Path):
        """Returns ~/.config/kairos/config.yaml when XDG not set."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()

        with patch("kairos.paths.Path.home", return_value=fake_home):
            result = get_config_path()

        assert result == fake_home / ".config" / "kairos" / "config.yaml"


class TestGetMarketsPath:
    """Tests for get_markets_path()."""

    def test_returns_supported_markets_json(self, monkeypatch, tmp_path: Path):
        xdg = tmp_path / "xdg_markets"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

        result = get_markets_path()

        assert result == xdg / "kairos" / "supported_markets.json"


class TestGetSymbolsPath:
    """Tests for get_symbols_path()."""

    def test_returns_symbols_txt(self, monkeypatch, tmp_path: Path):
        xdg = tmp_path / "xdg_symbols"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

        result = get_symbols_path()

        assert result == xdg / "kairos" / "symbols.txt"


class TestGetPidPath:
    """Tests for get_pid_path()."""

    def test_returns_kairos_pid(self, monkeypatch, tmp_path: Path):
        xdg = tmp_path / "xdg_pid"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

        result = get_pid_path()

        assert result == xdg / "kairos" / "kairos.pid"


class TestGetLogPath:
    """Tests for get_log_path()."""

    def test_returns_kairos_log(self, monkeypatch, tmp_path: Path):
        xdg = tmp_path / "xdg_log"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

        result = get_log_path()

        assert result == xdg / "kairos" / "kairos.log"


class TestReturnTypes:
    """All functions should return Path objects."""

    def test_all_return_path_objects(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg_types"))

        assert isinstance(get_config_dir(), Path)
        assert isinstance(get_config_path(), Path)
        assert isinstance(get_markets_path(), Path)
        assert isinstance(get_symbols_path(), Path)
        assert isinstance(get_pid_path(), Path)
        assert isinstance(get_log_path(), Path)
