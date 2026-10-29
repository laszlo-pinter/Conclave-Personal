# src/conclave/cli/config.py

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from conclave.runtime.paths import get_runtime_paths
from conclave.runtime.env import env_secret


_RUNTIME_PATHS = get_runtime_paths()
DEFAULT_CONFIG_PATH = _RUNTIME_PATHS.config_dir / "config.toml"


def default_config_path() -> Path:
    """config.toml: CONCLAVE_CONFIG_FILE, sonst Plattform-Default (zur Aufrufzeit ermittelt)."""
    override = os.environ.get("CONCLAVE_CONFIG_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    return get_runtime_paths().config_dir / "config.toml"
DEFAULT_DB_PATH = _RUNTIME_PATHS.db_path
# flask-limiter-Syntax, pro Route und Client-IP; "off" schaltet die Begrenzung ab
DEFAULT_RATE_LIMIT = "120 per minute"
DEFAULT_KANZO_URL = "http://localhost:4242/mcp"


@dataclass
class KanzoSettings:
    """Abschnitt [kanzo] in config.toml (Consultations).

    Die Adresse steht nur hier - die API nimmt keine Ziel-URL an (SSRF).
    ``reviewers`` legt fest, welche Agenten Ticket-Inhalte zu sehen bekommen.
    """
    url: str = DEFAULT_KANZO_URL
    reviewers: tuple[str, ...] = ()
    max_per_hour: int = 3              # Consultations pro Ticket und Stunde
    comment_max_chars: int = 2000      # Kuerzung der Kommentare (ohne Schlusszeile)

    @classmethod
    def from_section(cls, section: dict) -> "KanzoSettings":
        url = os.environ.get("CONCLAVE_KANZO_URL", str(section.get("url", DEFAULT_KANZO_URL))).strip()
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("[kanzo] url muss mit http:// oder https:// beginnen")
        reviewers = section.get("reviewers", [])
        if not isinstance(reviewers, list) or not all(isinstance(r, str) and r.strip() for r in reviewers):
            raise ValueError("[kanzo] reviewers muss eine Liste von Agent-IDs sein")
        max_per_hour = section.get("max_per_hour", 3)
        comment_max_chars = section.get("comment_max_chars", 2000)
        for name, value, minimum in (("max_per_hour", max_per_hour, 1), ("comment_max_chars", comment_max_chars, 200)):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"[kanzo] {name} muss eine ganze Zahl >= {minimum} sein")
        return cls(url=url, reviewers=tuple(r.strip() for r in reviewers),
                   max_per_hour=max_per_hour, comment_max_chars=comment_max_chars)


from conclave.domain.board import DEFAULT_STATUSES  # noqa: E402

@dataclass(frozen=True)
class BoardSettings:
    """Abschnitt [board] in config.toml: die Spalten des Boards (Plan board.md).

    Neue Tickets landen in der ersten Spalte, die letzte gilt als erledigt.
    """
    statuses: tuple[str, ...] = DEFAULT_STATUSES

    @classmethod
    def from_section(cls, section: dict) -> "BoardSettings":
        from conclave.domain.board import StatusFlow
        statuses = section.get("statuses", list(DEFAULT_STATUSES))
        if not isinstance(statuses, list) or not all(isinstance(s, str) for s in statuses):
            raise ValueError("[board] statuses muss eine Liste von Spaltennamen sein")
        try:
            flow = StatusFlow(tuple(statuses))           # ohne strip(): " todo" ist ungueltig
        except ValueError as e:
            raise ValueError(f"[board] statuses: {e}") from None
        return cls(statuses=flow.statuses)


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
    rate_limit: str = DEFAULT_RATE_LIMIT
    rate_limit_source: str = "default"  # "default" | "config" | "env"
    # Gesetzt von from_sources; nur dann darf die UI Werte in config.toml speichern
    config_path: Path | None = None
    # Logging
    log_level: str = "INFO"
    # API-Keys (Fallback, wenn nicht in DB)
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    # API-Authentifizierung
    api_key: str = ""
    agent_api_key: str = ""
    allowed_hosts: str = ""
    # Betriebsmodus
    mode: str = "development"  # "development" | "production"
    # Consultations (Kanzo)
    kanzo: KanzoSettings = field(default_factory=KanzoSettings)
    board: BoardSettings = field(default_factory=BoardSettings)

    @classmethod
    def from_sources(
        cls,
        config_path: Path | None = None,
    ) -> "ConclaveConfig":
        """Lädt Config aus TOML, überlagert mit Env-Vars.

        Priorität: Env-Var > TOML > Default.
        """
        config_path = config_path or default_config_path()
        # 1. TOML laden
        data: dict = {}
        if config_path.exists():
            with open(config_path, "rb") as f:
                data = tomllib.load(f)

        db_section = data.get("database", data.get("conclave", {}))
        server_section = data.get("server", {})
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
        if os.environ.get("CONCLAVE_RATE_LIMIT") is not None:
            rate_limit, rate_limit_source = os.environ["CONCLAVE_RATE_LIMIT"].strip(), "env"
        elif "rate_limit" in server_section:
            rate_limit, rate_limit_source = str(server_section["rate_limit"]).strip(), "config"
        else:
            rate_limit, rate_limit_source = DEFAULT_RATE_LIMIT, "default"

        anthropic_api_key = env_secret("ANTHROPIC_API_KEY")
        openai_api_key = env_secret("OPENAI_API_KEY")
        gemini_api_key = env_secret("GEMINI_API_KEY")
        api_key = env_secret("CONCLAVE_API_KEY")
        agent_api_key = env_secret("CONCLAVE_AGENT_KEY")
        allowed_hosts = os.environ.get("CONCLAVE_ALLOWED_HOSTS", "")
        mode = os.environ.get("CONCLAVE_MODE", "development")
        kanzo = KanzoSettings.from_section(data.get("kanzo", {}))
        board = BoardSettings.from_section(data.get("board", {}))
        return cls(
            db_provider=provider,
            db_path=db_path,
            db_dsn=db_dsn,
            participants=participants,
            host=host,
            port=port,
            debug=debug,
            rate_limit=rate_limit,
            rate_limit_source=rate_limit_source,
            config_path=config_path,
            log_level=log_level,
            anthropic_api_key=anthropic_api_key,
            openai_api_key=openai_api_key,
            gemini_api_key=gemini_api_key,
            api_key=api_key,
            agent_api_key=agent_api_key,
            allowed_hosts=allowed_hosts,
            mode=mode,
            kanzo=kanzo,
            board=board,
        )


def load_config(config_path: Path | None = None) -> ConclaveConfig:
    """Rückwärtskompatible Funktion — delegiert an from_sources."""
    config_path = config_path or default_config_path()
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
