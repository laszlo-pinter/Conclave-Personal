"""Konfiguration des Reviewers: Abschnitt ``[reviewer]`` in Conclaves ``config.toml`` (W2).

    [reviewer]
    enabled = true
    poll_seconds = 30
    max_reviews_per_hour = 6
    review_timeout_minutes = 30
    claude_exe = ""            # leer: VS-Code-Erweiterung, sonst PATH
    agent = "claude"           # oder "codex" (codex exec; nur unter einem eigenen Konto, conclave#152)
    codex_exe = ""             # leer: VS-Code-Erweiterung von OpenAI, sonst PATH
    codex_model = ""           # leer: Standardmodell von Codex
    prompt_file = ""           # leer: die mitgelieferte Fassung; relativ zum Ordner dieser config.toml
    [reviewer.projects]
    conclave = ["C:\\...\\conclave", "C:\\...\\conclave-plugins"]

Weitere Schluessel mit Standard: ``conclave_url`` (``CONCLAVE_API_URL`` bzw. http://127.0.0.1:8000),
``conclave_mcp_exe`` (``conclave-mcp`` neben dem Python dieses Reviewers bzw. im PATH),
``reviewer_token_file`` (wie Conclave), ``author``, ``review_status``, ``legacy_lock_file``.

Der Datenordner ist ``<Konfigurationsordner von Conclave>/reviewer`` (Windows
``%APPDATA%\\Conclave\\reviewer``), nur fuer den Benutzer (R13).

Ein Abschnitt ``[reviewer]`` laesst ``conclave desktop`` den Reviewer starten (W4, E-W3).

Entfernter Board-Server (TR2): eine eigene Datei, z. B. ``C:\\ProgramData\\Conclave\\reviewer.toml``, gestartet mit
``conclave-reviewer run --settings <Datei>``::

    [reviewer]
    server = "team"
    server_url = "https://board.intern"        # https, http nur fuer diesen Rechner
    ca_bundle = 'C:\\ProgramData\\Conclave\\eigene-ca.pem'
    reviewer_token_credential = "ConclaveReviewer"   # oder reviewer_token_file (nur fuer das Dienstkonto)
    data_dir = 'C:\\ProgramData\\Conclave\\reviewer'
    [reviewer.projects]
    api = ['D:\\checkouts\\api']

Mit ``server = "team"`` ist ``ca_bundle`` Pflicht (nur diese CA gilt, keine Umgebungsvariablen), und es
gelten: MCP-Server ``conclave-board-mcp --reviewer`` (mit ``CONCLAVE_BOARD_URL``,
``CONCLAVE_BOARD_CA_BUNDLE``, ``CONCLAVE_BOARD_TOKEN_FILE``), ``fetch = true`` (vor jedem Review
``git fetch`` in den Checkouts) und ``missing_commits = "red"`` (genannte Commits, die es im Git-Server
nicht gibt, ergeben ein rotes Review ohne claude). Relative Pfade gelten relativ zu dieser Datei.
Das Token steht nie in der Datei.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tomllib
from importlib import resources
from pathlib import Path

PLACEHOLDERS = ("{get}", "{comment}", "{board}")
DEFAULTS = {"enabled": True, "poll_seconds": 30, "max_reviews_per_hour": 6, "review_timeout_minutes": 30,
            "claude_exe": "", "prompt_file": "", "author": "CD · auto-review", "review_status": "review",
            "agent": "claude", "codex_exe": "", "codex_model": "", "codex_pass_env": []}
# Wer das Review schreibt (conclave#152): claude (Standard) oder codex exec. Codex hat immer eine Shell,
# deren read-only-Sandbox alles liest, was das Konto lesen darf (conclave#150/#151): nur unter einem eigenen Konto.
AGENTS = ("claude", "codex")
NUMBERS = ("poll_seconds", "max_reviews_per_hour", "review_timeout_minutes")
# Was import-config aus der alten config.toml uebernimmt (Projekte, Grenzwerte, claude)
IMPORTED = ("poll_seconds", "max_reviews_per_hour", "review_timeout_minutes", "claude_exe", "author")


SERVERS = ("personal", "team")
# Mit server = "team" (TR2); in Personal gilt das bisherige Verhalten
TEAM_DEFAULTS = {"conclave_mcp_args": ["--reviewer"], "fetch": True, "missing_commits": "red"}
PERSONAL_DEFAULTS = {"fetch": False, "missing_commits": "yellow"}


class ConfigError(SystemExit):
    """Konfiguration unbrauchbar; die Meldung nennt, was fehlt."""


def conclave_config_path() -> Path:
    override = os.environ.get("CONCLAVE_CONFIG_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    from conclave_reviewer.paths import conclave_config_dir
    return conclave_config_dir() / "config.toml"


def data_dir() -> Path:
    override = os.environ.get("CONCLAVE_REVIEWER_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    from conclave_reviewer.paths import conclave_config_dir
    return conclave_config_dir() / "reviewer"


def default_token_file() -> Path:
    override = os.environ.get("CONCLAVE_REVIEWER_TOKEN_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    from conclave_reviewer.paths import conclave_config_dir
    return conclave_config_dir() / "reviewer.token"


def codex_account_warning() -> str | None:
    """Laeuft der Reviewer mit ``agent = "codex"`` unter einem Konto, das das Mensch- oder Agent-Token lesen darf
    (also unter dem eigenen Benutzer), ein Hinweis (conclave#152, Review V3). Geprueft wird nur das Zugriffsrecht,
    gelesen wird nichts."""
    from conclave_reviewer.paths import conclave_config_dir
    names = {"CONCLAVE_API_TOKEN_FILE": "api.token", "CONCLAVE_AGENT_TOKEN_FILE": "agent.token"}
    readable = []
    for variable, name in names.items():
        override = os.environ.get(variable, "").strip()
        path = Path(override).expanduser() if override else conclave_config_dir() / name
        if path.is_file() and os.access(path, os.R_OK):
            readable.append(name)
    if not readable:
        return None
    return (f"codex laeuft unter einem Konto, das {' und '.join(readable)} lesen darf. Codex hat eine Shell; "
            "betreibe ihn unter einem eigenen Windows-Konto ohne Zugangsdaten (siehe konfiguration.md, Reviewer).")


def default_mcp_exe(program: str = "conclave-mcp") -> str:
    """``program`` (conclave-mcp, am entfernten Server conclave-board-mcp) aus derselben Installation wie dieser
    Reviewer, sonst aus dem PATH."""
    scripts = Path(sys.executable).parent
    for name in (f"{program}.exe", program):
        for folder in (scripts, scripts / "Scripts", scripts / "bin"):
            if (folder / name).is_file():
                return str(folder / name)
    return shutil.which(program) or program


def _file_beside(path: Path, value, key: str, *, must_exist: bool) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"[reviewer] {key}: Pfad erwartet.")
    target = Path(value).expanduser()
    if not target.is_absolute():
        target = path.parent / target                  # nie gegen das Arbeitsverzeichnis
    if must_exist and not target.is_file():
        raise ConfigError(f"[reviewer] {key}: {target} gibt es nicht.")
    return str(target)


def _server_settings(cfg: dict, section: dict, path: Path) -> None:
    """Personal oder entfernter Board-Server (TR2): Adresse, CA-Buendel, Token-Quelle, MCP, git fetch, fehlende Commits."""
    from conclave_reviewer.transport import TransportError, check_url
    server = cfg.get("server", "personal")
    if server not in SERVERS:
        raise ConfigError(f"[reviewer] server: einer von {SERVERS}.")
    cfg["server"] = server
    if "server_url" in section:
        if "conclave_url" in section:
            raise ConfigError("[reviewer]: server_url oder conclave_url, nicht beides.")
        cfg["conclave_url"] = section["server_url"]
    if section.get("reviewer_token_file") and section.get("reviewer_token_credential"):
        raise ConfigError("[reviewer]: reviewer_token_file oder reviewer_token_credential, nicht beides.")
    credential = section.get("reviewer_token_credential")
    if credential is not None and (not isinstance(credential, str) or not credential.strip()):
        raise ConfigError("[reviewer] reviewer_token_credential: Zielname der Anmeldeinformation erwartet.")
    if server == "team":
        if not cfg.get("conclave_url"):
            raise ConfigError("[reviewer] server_url fehlt (z. B. https://board.intern).")
        if not cfg.get("ca_bundle"):
            # Ohne eigenes Buendel laedt Python die Standardorte, und dann gelten SSL_CERT_FILE und
            # SSL_CERT_DIR (R12, TR2-Review V2); die eigene CA steht ohnehin nur im Buendel.
            raise ConfigError("[reviewer] ca_bundle fehlt: die eigene CA als PEM-Datei (z. B. eigene-ca.pem).")
        if not (section.get("reviewer_token_file") or credential):
            raise ConfigError("[reviewer]: reviewer_token_credential oder reviewer_token_file angeben; das Token "
                              "selbst steht nie in dieser Datei.")
        if "conclave_mcp_exe" not in section:
            cfg["conclave_mcp_exe"] = default_mcp_exe("conclave-board-mcp")
        for key, value in TEAM_DEFAULTS.items():
            cfg.setdefault(key, value)
        try:
            cfg["conclave_url"] = check_url(cfg["conclave_url"])
        except TransportError as e:
            raise ConfigError(f"[reviewer] server_url: {e}") from None
    else:
        for key, value in PERSONAL_DEFAULTS.items():
            cfg.setdefault(key, value)
    if not isinstance(cfg["fetch"], bool):
        raise ConfigError("[reviewer] fetch: true oder false.")
    if cfg["missing_commits"] not in ("red", "yellow"):
        raise ConfigError('[reviewer] missing_commits: "red" oder "yellow".')
    if cfg.get("ca_bundle"):
        cfg["ca_bundle"] = _file_beside(path, cfg["ca_bundle"], "ca_bundle", must_exist=True)
    if section.get("reviewer_token_file"):
        cfg["reviewer_token_file"] = _file_beside(path, section["reviewer_token_file"], "reviewer_token_file",
                                                  must_exist=False)
    if cfg.get("data_dir"):
        cfg["data_dir"] = _file_beside(path, cfg["data_dir"], "data_dir", must_exist=False)


def _projects(value) -> dict:
    if not isinstance(value, dict) or not value:
        raise ConfigError("[reviewer.projects]: mindestens ein Projekt (Kurzname = Pfad oder Liste von Pfaden).")
    for slug, paths in value.items():
        ok = isinstance(paths, str) or (isinstance(paths, list) and paths and all(isinstance(p, str) for p in paths))
        if not ok:
            raise ConfigError(f"[reviewer.projects] {slug}: Pfad oder Liste von Pfaden erwartet.")
    return dict(value)


def load(path: Path | None = None) -> dict:
    """``[reviewer]`` lesen und mit Standardwerten zu der Form ergaenzen, die ``watch.Reviewer`` nutzt."""
    path = path or conclave_config_path()
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(f"Keine Konfiguration unter {path}.") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: kein gueltiges TOML ({e}).") from None
    section = data.get("reviewer")
    if not isinstance(section, dict):
        raise ConfigError(f"{path}: kein Abschnitt [reviewer]. Uebernehmen: conclave-reviewer import-config <alte config.toml>.")
    cfg = {**DEFAULTS, **section}
    if not isinstance(cfg["enabled"], bool):
        raise ConfigError("[reviewer] enabled: true oder false.")
    for name in NUMBERS:
        value = cfg[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ConfigError(f"[reviewer] {name}: positive Zahl erwartet.")
    if cfg["agent"] not in AGENTS:
        raise ConfigError(f'[reviewer] agent: einer von {", ".join(AGENTS)}.')
    for name in ("codex_exe", "codex_model"):
        if not isinstance(cfg[name], str):
            raise ConfigError(f"[reviewer] {name}: Text erwartet.")
    if not isinstance(cfg["codex_pass_env"], list) or not all(isinstance(v, str) for v in cfg["codex_pass_env"]):
        raise ConfigError("[reviewer] codex_pass_env: Liste von Variablennamen erwartet.")
    cfg["projects"] = _projects(section.get("projects"))
    cfg["board"] = "conclave"
    _server_settings(cfg, section, path)
    cfg.setdefault("conclave_url", os.environ.get("CONCLAVE_API_URL", "").strip() or "http://127.0.0.1:8000")
    cfg.setdefault("conclave_mcp_exe", default_mcp_exe())
    if not cfg.get("reviewer_token_credential"):
        cfg.setdefault("reviewer_token_file", str(default_token_file()))
    cfg["claude_exe"] = cfg["claude_exe"] or None
    cfg["codex_exe"] = cfg["codex_exe"] or None
    cfg["_config_path"] = str(path)
    return cfg


def prompt_text(cfg: dict) -> str:
    """Die mitgelieferte Fassung oder ``prompt_file``; ohne die Platzhalter kein Start."""
    if cfg.get("prompt_file"):
        source = Path(cfg["prompt_file"]).expanduser()
        if not source.is_absolute() and cfg.get("_config_path"):
            source = Path(cfg["_config_path"]).parent / source      # nie gegen das Arbeitsverzeichnis
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as e:
            raise ConfigError(f"[reviewer] prompt_file {source}: nicht lesbar ({e.__class__.__name__}).") from None
    else:
        source = "mitgelieferte Fassung"
        text = resources.files("conclave_reviewer").joinpath("reviewer-prompt-conclave.md").read_text(encoding="utf-8")
    missing = [p for p in PLACEHOLDERS if p not in text]
    if missing:
        raise ConfigError(f"Prompt ({source}): Platzhalter fehlen: {', '.join(missing)}. Ohne sie kennt der Reviewer "
                          "die Board-Tools nicht.")
    return text


# ── import-config ────────────────────────────────────────────────────────

def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(json.dumps(v, ensure_ascii=False) for v in value) + "]"
    return json.dumps(value, ensure_ascii=False)        # JSON-Strings sind gueltige TOML-Basic-Strings


def imported_section(old: dict, old_path: Path) -> str:
    """Der neue Abschnitt aus der alten config.toml: Projekte, Grenzwerte, claude, alte Sperre."""
    projects = old.get("projects") or {}
    if not projects:
        raise ConfigError(f"{old_path}: keine [projects] zum Uebernehmen.")
    lines = ["[reviewer]", "enabled = true"]
    for name in IMPORTED:
        if old.get(name) not in (None, ""):
            lines.append(f"{name} = {_toml_value(old[name])}")
    lines.append(f"legacy_lock_file = {_toml_value(str(old_path.parent / 'watcher.lock'))}")
    lines += ["", "[reviewer.projects]"]
    lines += [f"{json.dumps(slug)} = {_toml_value(paths)}" for slug, paths in projects.items()]
    return "\n".join(lines) + "\n"


def _read_toml(path: Path, what: str) -> tuple[str, dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"{what} {path} gibt es nicht.") from None
    except OSError as e:
        raise ConfigError(f"{what} {path}: nicht lesbar ({e.__class__.__name__}).") from None
    try:
        return text, tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{what} {path}: kein gueltiges TOML ({e}).") from None


def import_config(old_path: Path, target: Path, *, confirm) -> bool:
    """Zeigt den Abschnitt und schreibt ihn erst nach ``confirm(text)``; ein vorhandenes [reviewer] bleibt.

    Geschrieben wird atomar und nur fuer den Benutzer (``replace_private``, R13): Die Konfiguration
    behaelt so keine weiteren Rechte, und ein Abbruch laesst keine halbe Datei zurueck."""
    _text, old = _read_toml(old_path, "Alte Konfiguration")
    text = imported_section(old, old_path)
    existing, current = _read_toml(target, "Ziel") if target.exists() else ("", {})
    if "reviewer" in current:
        raise ConfigError(f"{target}: [reviewer] gibt es schon; nichts geaendert.")
    if not confirm(text):
        return False
    merged = existing + ("\n" if existing and not existing.endswith("\n") else "") + ("\n" if existing else "") + text
    tomllib.loads(merged)                                   # vor dem Schreiben pruefen
    from conclave_board.runtime.file_security import replace_private
    replace_private(target, merged.encode("utf-8"))
    return True
