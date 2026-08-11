from dataclasses import dataclass
import os
from pathlib import Path

from conclave.runtime.platform_info import get_platform_info


@dataclass(frozen=True)
class RuntimePaths:
    config_dir: Path
    data_dir: Path
    log_dir: Path
    workspace_dir: Path
    db_path: Path
    secret_key_path: Path

    def ensure(self) -> "RuntimePaths":
        for path in (self.config_dir, self.data_dir, self.log_dir, self.workspace_dir):
            path.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.secret_key_path.parent.mkdir(parents=True, exist_ok=True)
        return self


def get_runtime_paths(
    system: str | None = None,
    env: dict[str, str] | None = None,
    home: Path | None = None,
) -> RuntimePaths:
    env = env if env is not None else os.environ
    system = (system or get_platform_info().system).lower()
    if home is None:
        if system == "windows" and env.get("USERPROFILE"):
            home = Path(env["USERPROFILE"])
        else:
            home = Path.home()

    if system == "windows":
        config_root = Path(env.get("APPDATA") or home / "AppData" / "Roaming")
        data_root = Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local")
        config_dir = config_root / "Conclave"
        data_dir = data_root / "Conclave"
        log_dir = data_dir / "logs"
    else:
        config_root = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
        data_root = Path(env.get("XDG_DATA_HOME") or home / ".local" / "share")
        state_root = Path(env.get("XDG_STATE_HOME") or home / ".local" / "state")
        config_dir = config_root / "conclave"
        data_dir = data_root / "conclave"
        log_dir = state_root / "conclave" / "logs"

    workspace_dir = Path(env.get("CONCLAVE_WORKSPACE") or home / "Conclave" / "workspace")
    db_path = Path(env.get("CONCLAVE_DB_PATH") or data_dir / "conclave.db")
    secret_key_path = Path(env.get("CONCLAVE_SECRET_KEY_FILE") or config_dir / "secret.key")

    return RuntimePaths(
        config_dir=config_dir,
        data_dir=data_dir,
        log_dir=log_dir,
        workspace_dir=workspace_dir,
        db_path=db_path,
        secret_key_path=secret_key_path,
    )
