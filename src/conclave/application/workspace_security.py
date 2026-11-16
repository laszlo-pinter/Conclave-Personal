"""Gemeinsame Sicherheitsregeln fuer den lokalen Workspace."""

from __future__ import annotations

import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path


DEFAULT_AGENT_READ_LIMIT_BYTES = 512 * 1024
DEFAULT_UI_READ_LIMIT_BYTES = 2 * 1024 * 1024
DEFAULT_WRITE_LIMIT_BYTES = 512 * 1024
# Hoechstens so viele Dateien setzt eine Nachricht per @workspace bzw. eine Antwort per @read ein (R6)
MAX_REFS_PER_MESSAGE = 10
# Hier duerfen Agenten auch vorhandene Dateien ueberschreiben; sonst nur neue anlegen (R8)
AGENT_WRITE_DIR = "agents"
# Fuer Agenten gesperrt (Marker fuer den Hook des Agent-Hosts); Vergleich ohne Gross/Klein,
# weil Windows und macOS Conclave_Notify.json als dieselbe Datei behandeln
AGENT_BLOCKED_FILES = frozenset({"conclave_notify.json"})

# Windows-Geraetenamen, auch mit Endung (CON, con.txt, COM1.log ...)
_DEVICE_NAMES = frozenset({"con", "prn", "aux", "nul", "conin$", "conout$", "clock$"}
                          | {f"{base}{n}" for base in ("com", "lpt") for n in (*"123456789", "¹", "²", "³")})
# 8.3-Kurznamen (CONCLA~1) koennen auf versteckte Ordner zeigen
_SHORT_NAME = re.compile(r"~\d+(\.|$)")


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def agent_read_limit_bytes() -> int:
    return _int_env("CONCLAVE_WORKSPACE_AGENT_READ_LIMIT_BYTES", DEFAULT_AGENT_READ_LIMIT_BYTES)


def ui_read_limit_bytes() -> int:
    return _int_env("CONCLAVE_WORKSPACE_UI_READ_LIMIT_BYTES", DEFAULT_UI_READ_LIMIT_BYTES)


def write_limit_bytes() -> int:
    return _int_env("CONCLAVE_WORKSPACE_WRITE_LIMIT_BYTES", DEFAULT_WRITE_LIMIT_BYTES)


def workspace_root() -> Path:
    """CONCLAVE_WORKSPACE, sonst der Plattform-Default (~/Conclave/workspace).

    Frueher fiel alles ausser `conclave server/desktop` auf "/workspace" zurueck
    (Docker-Altlast): CLI-Befehle und conclave-api nutzten dann einen anderen
    Workspace als die Desktop-App.
    """
    configured = os.environ.get("CONCLAVE_WORKSPACE", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    from conclave.runtime.paths import get_runtime_paths
    return get_runtime_paths().workspace_dir.resolve()


@dataclass(frozen=True)
class WorkspacePath:
    root: Path
    path: Path

    @property
    def relative(self) -> str:
        return self.path.relative_to(self.root).as_posix()


def unsafe_path_component(part: str) -> bool:
    """Komponenten, die unter Windows etwas anderes bedeuten als eine normale Datei (R8):
    ':' (Datenstroeme, Laufwerke), Geraetenamen, Punkt oder Leerzeichen am Ende,
    Steuerzeichen und 8.3-Kurznamen."""
    if not part or part in (".", ".."):
        return False
    if ":" in part or any(ord(ch) < 32 for ch in part):
        return True
    if part[-1] in ". ":
        return True
    if part.split(".", 1)[0].rstrip(" ").lower() in _DEVICE_NAMES:
        return True
    return bool(_SHORT_NAME.search(part))


def _parts(relative_path: str) -> list[str]:
    return [p for p in re.split(r"[\\/]", relative_path) if p]


def protected_files() -> set[Path]:
    """Token-, Schluessel- und Datenbankdateien; nie ueber den Workspace erreichbar."""
    from conclave.runtime.api_token import agent_token_path, reviewer_token_path, token_path
    from conclave.runtime.paths import get_runtime_paths
    paths = get_runtime_paths()
    files = {paths.secret_key_path, paths.db_path, token_path(), agent_token_path(), reviewer_token_path()}
    resolved = set()
    for f in files:
        try:
            resolved.add(Path(f).expanduser().resolve())
        except OSError:
            continue
    return resolved


def resolve_workspace_path(relative_path: str, root: Path | None = None) -> WorkspacePath | None:
    """Loest einen Workspace-Pfad auf, falls er innerhalb des Workspace bleibt."""
    root = (root or workspace_root()).resolve()
    if not relative_path or not isinstance(relative_path, str) or Path(relative_path).is_absolute():
        return None
    if any(unsafe_path_component(part) for part in _parts(relative_path)):
        return None
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    if path in protected_files():
        return None
    return WorkspacePath(root=root, path=path)


def resolve_output_path(relative_path: str, root: Path | None = None) -> WorkspacePath | None:
    """Loest einen Agent-Output-Pfad unterhalb von workspace/output auf."""
    root = (root or workspace_root()).resolve()
    output_root = (root / "output").resolve()
    if not relative_path or not isinstance(relative_path, str) or Path(relative_path).is_absolute():
        return None
    if any(unsafe_path_component(part) for part in _parts(relative_path)):
        return None
    path = (output_root / relative_path).resolve()
    try:
        path.relative_to(output_root)
        path.relative_to(root)
    except ValueError:
        return None
    if path in protected_files():
        return None
    return WorkspacePath(root=root, path=path)


def is_hidden_workspace_path(path: Path, root: Path | None = None) -> bool:
    root = (root or workspace_root()).resolve()
    try:
        rel = path.resolve().relative_to(root)
    except ValueError:
        return True
    return any(part.startswith(".") and part not in (".", "..") for part in rel.parts)


def is_agent_visible(path: Path, root: Path | None = None) -> bool:
    """Agenten sehen keine versteckten Pfadkomponenten."""
    return not is_hidden_workspace_path(path, root=root)


def assert_size_allowed(path: Path, limit: int) -> bool:
    return path.stat().st_size <= limit


def text_size(content: str) -> int:
    return len(content.encode("utf-8"))


def agent_write_problem(resolved: WorkspacePath) -> str | None:
    """Grund, warum ein Agent hier nicht schreiben darf, sonst None (R8, E-S1 a)."""
    rel = Path(resolved.relative)
    if rel.as_posix().casefold() in AGENT_BLOCKED_FILES:
        return "Diese Datei ist fuer Agenten gesperrt."
    if rel.parts and rel.parts[0] == AGENT_WRITE_DIR:
        return None
    if resolved.path.exists():
        return (f"Vorhandene Dateien ueberschreibt nur der Mensch. Neue Datei anlegen "
                f"oder unter {AGENT_WRITE_DIR}/ schreiben.")
    return None


def _current_umask() -> int:
    mask = os.umask(0o022)
    os.umask(mask)
    return mask


# Einmal beim Laden gelesen: os.umask setzt den Wert prozessweit und ist nicht threadsicher
_UMASK = _current_umask() if os.name != "nt" else 0


def _keep_mode(tmp: Path, target: Path) -> None:
    """mkstemp legt 0600 an; die neue Datei bekommt die Rechte der alten bzw. 0666 minus umask."""
    if os.name == "nt":
        return
    try:
        mode = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        mode = 0o666 & ~_UMASK
    os.chmod(tmp, mode)


def write_text_atomic(path: Path, content: str, *, create_only: bool = False) -> None:
    """Schreibt ueber eine temporaere Datei im selben Ordner; die alte Datei bleibt bis zum
    Austausch intakt. ``create_only``: nur anlegen, vorhandene Datei -> FileExistsError."""
    if not isinstance(content, str):
        raise TypeError("content muss Text sein.")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".conclave-write-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        # Zeilenenden wie bisher mit open("w"): unter Windows CRLF
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        _keep_mode(tmp, path)
        if create_only:
            try:
                os.link(tmp, path)            # scheitert, wenn die Datei inzwischen existiert
            except FileExistsError:
                raise
            except OSError:
                # Dateisystem ohne Hardlinks (FAT/exFAT, manche Netzlaufwerke): pruefen und tauschen,
                # mit einem kleinen Fenster zwischen beidem
                if path.exists():
                    raise FileExistsError(str(path)) from None
                os.replace(tmp, path)
                return
            tmp.unlink(missing_ok=True)
        else:
            os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def workspace_location_problem(candidate: Path, *, backup_dir: Path | None = None,
                               extra_files: tuple[Path, ...] = ()) -> str | None:
    """Grund, warum ``candidate`` kein Workspace sein darf, sonst None (R8).

    Abgelehnt wird ein Ordner, der Home-, Konfigurations-, Daten-, Log- oder
    Backup-Verzeichnis ist oder enthaelt, sowie einer mit Token- oder Schluesseldateien.
    """
    from conclave.runtime.paths import get_runtime_paths
    paths = get_runtime_paths()
    target = Path(candidate).expanduser().resolve()
    if target == Path(target.anchor):
        return "Der Workspace darf kein Laufwerk und keine Wurzel sein."
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or Path.home())
    named = [("Home-Verzeichnis", home), ("Konfigurationsverzeichnis", paths.config_dir),
             ("Datenverzeichnis", paths.data_dir), ("Log-Verzeichnis", paths.log_dir)]
    if backup_dir is not None:
        named.append(("Backup-Verzeichnis", backup_dir))
    named += [("Datei", f) for f in (*protected_files(), *extra_files)]
    for label, path in named:
        try:
            resolved = Path(path).expanduser().resolve()
        except OSError:
            continue
        if resolved == target or target in resolved.parents:
            return f"Der Workspace darf das {label} nicht enthalten: {resolved}"
    return None
