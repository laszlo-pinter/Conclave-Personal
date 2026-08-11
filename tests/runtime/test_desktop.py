from pathlib import Path
from unittest.mock import patch

from conclave.cli.config import ConclaveConfig
from conclave.runtime.desktop import prepare_launch_config


def test_prepare_launch_config_creates_runtime_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "win-cfg"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "win-data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("CONCLAVE_DB_PATH", raising=False)
    monkeypatch.delenv("CONCLAVE_WORKSPACE", raising=False)
    config = ConclaveConfig()

    launch = prepare_launch_config(config, host="127.0.0.1", port=8123)

    assert launch.paths.config_dir.exists()
    assert launch.paths.data_dir.exists()
    assert launch.paths.log_dir.exists()
    assert launch.paths.workspace_dir.exists()
    assert launch.config.db_path == launch.paths.db_path
    assert launch.url == "http://127.0.0.1:8123"


def test_prepare_launch_config_finds_free_port_for_desktop(monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "win-cfg"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "win-data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    config = ConclaveConfig()

    with patch("conclave.runtime.desktop.find_free_port", return_value=9010):
        launch = prepare_launch_config(config, port=8000, open_browser=True)

    assert launch.config.port == 9010
    assert launch.url == "http://127.0.0.1:9010"
