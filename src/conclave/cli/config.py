# src/conclave/cli/config.py

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from conclave.runtime.paths import get_runtime_paths


_RUNTIME_PATHS = get_runtime_paths()
DEFAULT_CONFIG_PATH = _RUNTIME_PATHS.config_dir / "config.toml"
DEFAULT_DB_PATH = _RUNTIME_PATHS.db_path


@dataclass
class ConclaveConfig:
    db_provider: str = "sqlite"                                  # "sqlite" | "postgres"
    db_path: Path = field(default_factory=lambda: DEFAULT_DB_PATH)  # für sqlite
    db_dsn: str = ""                                             # für postgres
    participants: dict = field(default_factory=dict)
    # Server
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False
    # Logging
    log_level: str = "INFO"
    # API-Keys (Fallback, wenn nicht in DB)
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    # API-Authentifizierung
    api_key: str = ""
    # Betriebsmodus
    mode: str = "development"  # "development" | "production"

    @classmethod
    def from_sources(
        cls,
        config_path: Path = DEFAULT_CONFIG_PATH,
    ) -> "ConclaveConfig":
        """Lädt Config aus TOML, überlagert mit Env-Vars.

        Priorität: Env-Var > TOML > Default.
        """
        # 1. TOML laden
        data: dict = {}
        if config_path.exists():
            with open(config_path, "rb") as f:
                data = tomllib.load(f)

        db_section = data.get("database", data.get("conclave", {}))
        participants = data.get("participants", {})

        # TOML-Werte mit Defaults
        provider = db_section.get("provider", "sqlite")
        db_path_str = db_section.get("path", db_section.get("db_path", ""))
        db_path = Path(db_path_str) if db_path_str else DEFAULT_DB_PATH
        db_dsn = db_section.get("dsn", "")

        # 2. Env-Vars überlagern
        provider = os.environ.get("CONCLAVE_DB_PROVIDER", provider)
        db_dsn = os.environ.get("CONCLAVE_DB_DSN", db_dsn)

        env_db_path = os.environ.get("CONCLAVE_DB_PATH", "")
        if env_db_path:
            db_path = Path(env_db_path)

        host = os.environ.get("CONCLAVE_HOST", "127.0.0.1")
        port = int(os.environ.get("CONCLAVE_PORT", "8000"))
        debug = os.environ.get("CONCLAVE_DEBUG", "").lower() in ("1", "true")
        log_level = os.environ.get("CONCLAVE_LOG_LEVEL", "INFO")

        anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        openai_api_key = os.environ.get("OPENAI_API_KEY", "")
        gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
        api_key = os.environ.get("CONCLAVE_API_KEY", "")
        mode = os.environ.get("CONCLAVE_MODE", "development")
        return cls(
            db_provider=provider,
            db_path=db_path,
            db_dsn=db_dsn,
            participants=participants,
            host=host,
            port=port,
            debug=debug,
            log_level=log_level,
            anthropic_api_key=anthropic_api_key,
            openai_api_key=openai_api_key,
            gemini_api_key=gemini_api_key,
            api_key=api_key,
            mode=mode,
        )


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> ConclaveConfig:
    """Rückwärtskompatible Funktion — delegiert an from_sources."""
    if not config_path.exists():
        return ConclaveConfig()

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    db_section = data.get("database", data.get("conclave", {}))

    provider = db_section.get("provider", "sqlite")
    db_path = Path(db_section["path"]) if "path" in db_section else (
        Path(db_section["db_path"]) if "db_path" in db_section else DEFAULT_DB_PATH
    )
    db_dsn = db_section.get("dsn", "")
    participants = data.get("participants", {})

    return ConclaveConfig(
        db_provider=provider,
        db_path=db_path,
        db_dsn=db_dsn,
        participants=participants,
    )
