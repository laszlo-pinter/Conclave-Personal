from pathlib import Path

from conclave.runtime.paths import get_runtime_paths


def test_windows_runtime_paths_use_appdata_and_localappdata():
    home = Path("C:/Users/Ada")
    env = {
        "APPDATA": "C:/Users/Ada/AppData/Roaming",
        "LOCALAPPDATA": "C:/Users/Ada/AppData/Local",
    }

    paths = get_runtime_paths(system="windows", env=env, home=home)

    assert paths.config_dir == Path("C:/Users/Ada/AppData/Roaming") / "Conclave"
    assert paths.data_dir == Path("C:/Users/Ada/AppData/Local") / "Conclave"
    assert paths.log_dir == paths.data_dir / "logs"
    assert paths.workspace_dir == home / "Conclave" / "workspace"
    assert paths.db_path == paths.data_dir / "conclave.db"


def test_linux_runtime_paths_use_xdg_defaults():
    home = Path("/home/ada")

    paths = get_runtime_paths(system="linux", env={}, home=home)

    assert paths.config_dir == home / ".config" / "conclave"
    assert paths.data_dir == home / ".local" / "share" / "conclave"
    assert paths.log_dir == home / ".local" / "state" / "conclave" / "logs"
    assert paths.workspace_dir == home / "Conclave" / "workspace"


def test_runtime_paths_respect_env_overrides():
    home = Path("/home/ada")
    env = {
        "XDG_CONFIG_HOME": "/cfg",
        "XDG_DATA_HOME": "/data",
        "XDG_STATE_HOME": "/state",
        "CONCLAVE_WORKSPACE": "/work",
        "CONCLAVE_DB_PATH": "/db/conclave.db",
        "CONCLAVE_SECRET_KEY_FILE": "/secrets/key",
    }

    paths = get_runtime_paths(system="linux", env=env, home=home)

    assert paths.config_dir == Path("/cfg/conclave")
    assert paths.data_dir == Path("/data/conclave")
    assert paths.log_dir == Path("/state/conclave/logs")
    assert paths.workspace_dir == Path("/work")
    assert paths.db_path == Path("/db/conclave.db")
    assert paths.secret_key_path == Path("/secrets/key")
