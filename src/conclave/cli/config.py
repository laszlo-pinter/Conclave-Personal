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
DEFAULT_DB_PATH = _RUNTIME_PATHS.db_path          # Stand beim Import; fuer Vorgaben default_db_path()


def default_db_path() -> Path:
    """SQLite-Datei: CONCLAVE_DB_PATH, sonst Plattform-Default (zur Aufrufzeit ermittelt, wie die config.toml).
    Ohne bestimmbares Benutzerverzeichnis (leere Umgebung) bleibt es beim Stand vom Import."""
    try:
        return get_runtime_paths().db_path
    except RuntimeError:
        return DEFAULT_DB_PATH
# flask-limiter-Syntax, pro Route und Client-IP; "off" schaltet die Begrenzung ab
DEFAULT_RATE_LIMIT = "120 per minute"
DEFAULT_KANZO_URL = "http://localhost:4242/mcp"


CONSULTATION_KEYS = ("reviewers", "max_per_hour", "comment_max_chars")


@dataclass
class KanzoSettings:
    """Consultations: ``[consultations]`` in config.toml, dazu ``[kanzo] url`` fuer ein externes Kanzo.

    Die Adresse steht nur hier - die API nimmt keine Ziel-URL an (SSRF).
    ``reviewers`` legt fest, welche Agenten Ticket-Inhalte zu sehen bekommen.
    Bis v0.6.0 standen ``reviewers``, ``max_per_hour`` und ``comment_max_chars``
    unter ``[kanzo]``; dort werden sie weiter gelesen, wenn ``[consultations]``
    sie nicht setzt (siehe ``legacy_keys``).
    """
    url: str = DEFAULT_KANZO_URL
    reviewers: tuple[str, ...] = ()
    max_per_hour: int = 3              # Consultations pro Ticket und Stunde
    comment_max_chars: int = 2000      # Kuerzung der Kommentare (ohne Schlusszeile)
    legacy_keys: tuple[str, ...] = ()  # aus [kanzo] statt [consultations] gelesen
    ignored_keys: tuple[str, ...] = ()  # in [kanzo] und [consultations]; [kanzo] wird ignoriert

    @classmethod
    def from_section(cls, section: dict, consultations: dict | None = None) -> "KanzoSettings":
        consultations = consultations or {}
        url = os.environ.get("CONCLAVE_KANZO_URL", str(section.get("url", DEFAULT_KANZO_URL))).strip()
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("[kanzo] url muss mit http:// oder https:// beginnen")
        legacy = tuple(k for k in CONSULTATION_KEYS if k in section and k not in consultations)
        ignored = tuple(k for k in CONSULTATION_KEYS if k in section and k in consultations)
        values = {**{k: section[k] for k in legacy}, **{k: consultations[k] for k in CONSULTATION_KEYS
                                                         if k in consultations}}

        def label(key: str) -> str:
            return f"[{'kanzo' if key in legacy else 'consultations'}] {key}"

        reviewers = values.get("reviewers", [])
        if not isinstance(reviewers, list) or not all(isinstance(r, str) and r.strip() for r in reviewers):
            raise ValueError(f"{label('reviewers')} muss eine Liste von Agent-IDs sein")
        max_per_hour = values.get("max_per_hour", 3)
        comment_max_chars = values.get("comment_max_chars", 2000)
        for name, value, minimum in (("max_per_hour", max_per_hour, 1), ("comment_max_chars", comment_max_chars, 200)):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{label(name)} muss eine ganze Zahl >= {minimum} sein")
        return cls(url=url, reviewers=tuple(r.strip() for r in reviewers),
                   max_per_hour=max_per_hour, comment_max_chars=comment_max_chars, legacy_keys=legacy,
                   ignored_keys=ignored)


from conclave.domain.board import DEFAULT_STATUSES  # noqa: E402

BOARD_SOURCES = ("internal", "kanzo")

@dataclass(frozen=True)
class BoardSettings:
    """Abschnitt [board] in config.toml: die Spalten des Boards (Plan board.md).

    Neue Tickets landen in der ersten Spalte, die letzte gilt als erledigt.
    ``source`` bestimmt, woher Consultations Tickets lesen (E6): ``internal`` (eigenes
    Board) oder ``kanzo`` (externes Kanzo unter ``[kanzo] url``). Ohne Angabe gilt
    ``kanzo`` nur, wenn eine Kanzo-Adresse ausdruecklich gesetzt ist.
    """
    statuses: tuple[str, ...] = DEFAULT_STATUSES
    source: str = "internal"

    @classmethod
    def from_section(cls, section: dict, kanzo_url_set: bool = False) -> "BoardSettings":
        from conclave.domain.board import StatusFlow
        source = section.get("source", "kanzo" if kanzo_url_set else "internal")
        if source not in BOARD_SOURCES:
            raise ValueError(f"[board] source muss einer von {list(BOARD_SOURCES)} sein")
        statuses = section.get("statuses", list(DEFAULT_STATUSES))
        if not isinstance(statuses, list) or not all(isinstance(s, str) for s in statuses):
            raise ValueError("[board] statuses muss eine Liste von Spaltennamen sein")
        try:
            flow = StatusFlow(tuple(statuses))           # ohne strip(): " todo" ist ungueltig
        except ValueError as e:
            raise ValueError(f"[board] statuses: {e}") from None
        return cls(statuses=flow.statuses, source=source)


class ConfigError(ValueError):
    """Ungueltiger Wert in config.toml; ``conclave`` und ``conclave-api`` melden ihn beim Start
    ohne Traceback (``config_error_message``)."""


def config_error_message(exc: Exception) -> str:
    """Startmeldung fuer einen ungueltigen Wert in config.toml, mit der Datei."""
    return f"FEHLER in {default_config_path()}: {exc}"


UI_MODES = ("studio", "board")
# Pfad der Board-Seite aus dem Board-Kern (U1); /board bleibt bis zum Sunset der API-Alias
BOARD_PAGE_PATH = "/ui/board"


@dataclass(frozen=True)
class UiSettings:
    """Abschnitt [ui] in config.toml (U2, Plan board-ui.md 3.3).

    ``mode = "studio"`` (Standard) zeigt das Studio unter ``/``. ``mode = "board"`` zeigt nur die
    Board-Seite: ``/`` leitet auf ``/ui/board`` weiter, das Studio wird nicht ausgeliefert. Die API
    bleibt in beiden Modi gleich (Agenten, Consultations, Reviewer).
    """
    mode: str = "studio"

    @classmethod
    def from_section(cls, section: dict) -> "UiSettings":
        mode = section.get("mode", "studio")
        if mode not in UI_MODES:
            raise ConfigError(f"[ui] mode muss einer von {list(UI_MODES)} sein, nicht {mode!r}")
        return cls(mode=mode)

    @property
    def board_only(self) -> bool:
        return self.mode == "board"


DEFAULT_AGENT_RATE_LIMIT = "60 per minute"


def _rate_limit_problem(value: str) -> str | None:
    if value.strip().lower() in ("off", "none", "0", ""):
        return None
    try:
        from limits import parse_many
    except ImportError:  # flask-limiter nicht installiert: Begrenzung ist ohnehin aus
        return None
    try:
        parse_many(value)
    except ValueError:
        return f"ungueltiges Rate-Limit {value!r} (Beispiel: '60 per minute')"
    return None


@dataclass(frozen=True)
class LimitSettings:
    """Abschnitt [limits] in config.toml: Grenzen fuer Agenten (R11). 0 schaltet ein Budget ab.

    Budgets gelten fuer die letzten 24 Stunden und zaehlen Tokens (Eingabe plus Ausgabe) der
    Modelllaeufe, die ein Agent ausgeloest hat - je Agent-Zugang und je Conversation.
    """
    agent_tokens_per_day: int = 2_000_000
    conversation_tokens_per_day: int = 500_000
    agent_concurrent_runs: int = 2
    agent_rate_limit: str = DEFAULT_AGENT_RATE_LIMIT

    @classmethod
    def from_section(cls, section: dict) -> "LimitSettings":
        values = {}
        for name in ("agent_tokens_per_day", "conversation_tokens_per_day", "agent_concurrent_runs"):
            if name in section:
                value = section[name]
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError(f"[limits] {name} muss eine ganze Zahl ab 0 sein")
                values[name] = value
        if "agent_rate_limit" in section:
            value = section["agent_rate_limit"]
            if not isinstance(value, str) or _rate_limit_problem(value):
                raise ValueError(f"[limits] agent_rate_limit: {_rate_limit_problem(str(value)) or 'Text erwartet'}")
            values["agent_rate_limit"] = value.strip()
        return cls(**values)


@dataclass
class ConclaveConfig:
    db_provider: str = "sqlite"                                  # "sqlite" | "postgres"
    db_path: Path = field(default_factory=default_db_path)  # für sqlite
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
    reviewer_api_key: str = ""
    allowed_hosts: str = ""
    # Betriebsmodus
    mode: str = "development"  # "development" | "production"
    # Consultations (Kanzo)
    kanzo: KanzoSettings = field(default_factory=KanzoSettings)
    board: BoardSettings = field(default_factory=BoardSettings)
    limits: LimitSettings = field(default_factory=LimitSettings)
    ui: UiSettings = field(default_factory=UiSettings)

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
        db_path = Path(db_path_str) if db_path_str else default_db_path()
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
        reviewer_api_key = env_secret("CONCLAVE_REVIEWER_KEY")
        allowed_hosts = os.environ.get("CONCLAVE_ALLOWED_HOSTS", "")
        mode = os.environ.get("CONCLAVE_MODE", "development")
        kanzo = KanzoSettings.from_section(data.get("kanzo", {}), data.get("consultations", {}))
        kanzo_url_set = "url" in data.get("kanzo", {}) or bool(os.environ.get("CONCLAVE_KANZO_URL", "").strip())
        board = BoardSettings.from_section(data.get("board", {}), kanzo_url_set=kanzo_url_set)
        limits = LimitSettings.from_section(data.get("limits", {}))
        ui = UiSettings.from_section(data.get("ui", {}))
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
            reviewer_api_key=reviewer_api_key,
            allowed_hosts=allowed_hosts,
            mode=mode,
            kanzo=kanzo,
            board=board,
            limits=limits,
            ui=ui,
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
        Path(db_section["db_path"]) if "db_path" in db_section else default_db_path()
    )
    db_dsn = db_section.get("dsn", "")
    participants = data.get("participants", {})

    return ConclaveConfig(
        db_provider=provider,
        db_path=db_path,
        db_dsn=db_dsn,
        participants=participants,
    )
