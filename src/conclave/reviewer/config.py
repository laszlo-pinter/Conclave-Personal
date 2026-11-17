"""Konfiguration des Reviewers: Abschnitt ``[reviewer]`` in Conclaves ``config.toml`` (W2).

    [reviewer]
    enabled = true
    poll_seconds = 30
    max_reviews_per_hour = 6
    review_timeout_minutes = 30
    claude_exe = ""            # leer: VS-Code-Erweiterung, sonst PATH
    prompt_file = ""           # leer: die mitgelieferte Fassung
    [reviewer.projects]
    conclave = ["C:\\...\\Conclave_original", "C:\\...\\conclave-board-team"]

Weitere Schluessel mit Standard: ``conclave_url`` (``CONCLAVE_API_URL`` bzw. http://127.0.0.1:8000),
``conclave_mcp_exe`` (``conclave-mcp`` neben dem Python dieses Reviewers bzw. im PATH),
``reviewer_token_file`` (wie Conclave), ``author``, ``review_status``, ``legacy_lock_file``.

Der Datenordner ist ``<Konfigurationsordner von Conclave>/reviewer`` (Windows
``%APPDATA%\\Conclave\\reviewer``), nur fuer den Benutzer (R13).

Wichtig bis W5 (E-W3): Ein Abschnitt ``[reviewer]`` laesst ``conclave desktop`` den Reviewer starten.
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
            "claude_exe": "", "prompt_file": "", "author": "CD · auto-review", "review_status": "review"}
NUMBERS = ("poll_seconds", "max_reviews_per_hour", "review_timeout_minutes")
# Was import-config aus der alten config.toml uebernimmt (Projekte, Grenzwerte, claude)
IMPORTED = ("poll_seconds", "max_reviews_per_hour", "review_timeout_minutes", "claude_exe", "author")


class ConfigError(SystemExit):
    """Konfiguration unbrauchbar; die Meldung nennt, was fehlt."""


def conclave_config_path() -> Path:
    override = os.environ.get("CONCLAVE_CONFIG_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    from conclave.runtime.paths import get_runtime_paths
    return get_runtime_paths().config_dir / "config.toml"


def data_dir() -> Path:
    override = os.environ.get("CONCLAVE_REVIEWER_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    from conclave.runtime.paths import get_runtime_paths
    return get_runtime_paths().config_dir / "reviewer"


def default_token_file() -> Path:
    override = os.environ.get("CONCLAVE_REVIEWER_TOKEN_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    from conclave.runtime.paths import get_runtime_paths
    return get_runtime_paths().config_dir / "reviewer.token"


def default_mcp_exe() -> str:
    """conclave-mcp aus derselben Installation wie dieser Reviewer, sonst aus dem PATH."""
    scripts = Path(sys.executable).parent
    for name in ("conclave-mcp.exe", "conclave-mcp"):
        for folder in (scripts, scripts / "Scripts", scripts / "bin"):
            if (folder / name).is_file():
                return str(folder / name)
    return shutil.which("conclave-mcp") or "conclave-mcp"


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
    cfg["projects"] = _projects(section.get("projects"))
    cfg["board"] = "conclave"
    cfg.setdefault("conclave_url", os.environ.get("CONCLAVE_API_URL", "").strip() or "http://127.0.0.1:8000")
    cfg.setdefault("conclave_mcp_exe", default_mcp_exe())
    cfg.setdefault("reviewer_token_file", str(default_token_file()))
    cfg["claude_exe"] = cfg["claude_exe"] or None
    cfg["_config_path"] = str(path)
    return cfg


def prompt_text(cfg: dict) -> str:
    """Die mitgelieferte Fassung oder ``prompt_file``; ohne die Platzhalter kein Start."""
    if cfg.get("prompt_file"):
        source = Path(cfg["prompt_file"]).expanduser()
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as e:
            raise ConfigError(f"[reviewer] prompt_file {source}: nicht lesbar ({e.__class__.__name__}).") from None
    else:
        source = "mitgelieferte Fassung"
        text = resources.files("conclave.reviewer").joinpath("reviewer-prompt-conclave.md").read_text(encoding="utf-8")
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


def import_config(old_path: Path, target: Path, *, confirm) -> bool:
    """Zeigt den Abschnitt und schreibt ihn erst nach ``confirm(text)``; ein vorhandenes [reviewer] bleibt."""
    with old_path.open("rb") as f:
        old = tomllib.load(f)
    text = imported_section(old, old_path)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    if existing and "reviewer" in tomllib.loads(existing):
        raise ConfigError(f"{target}: [reviewer] gibt es schon; nichts geaendert.")
    if not confirm(text):
        return False
    merged = existing + ("\n" if existing and not existing.endswith("\n") else "") + ("\n" if existing else "") + text
    tomllib.loads(merged)                                   # vor dem Schreiben pruefen
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(merged, encoding="utf-8")
    tmp.replace(target)
    return True
