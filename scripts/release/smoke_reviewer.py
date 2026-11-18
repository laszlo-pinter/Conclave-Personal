"""Prueft das installierte Reviewer-Paket in einer frischen Umgebung ohne Personal (TR1, CI).

- ``conclave`` (Personal), ``conclave_board_team``, ``anthropic``, ``openai``, ``httpx`` und ``mcp`` sind
  nicht installiert
- alle Module von ``conclave_reviewer`` lassen sich importieren, ohne dass ein Modul aus ``conclave``
  geladen wird; der mitgelieferte Prompt liegt im Paket
- ``conclave-reviewer --help`` nennt run, status und import-config
- eine Konfiguration mit ``[reviewer]`` laedt mit den Standardwerten; die Standardorte folgen der
  Regel von Personal, ohne Personal zu importieren
- ``conclave-reviewer status`` laeuft ohne Personal durch (nichts gestartet, kein Board noetig)

Aufruf mit dem Python der frischen Umgebung: python scripts/release/smoke_reviewer.py
"""

import importlib
import importlib.util
import os
import pkgutil
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ABSENT = ("conclave", "conclave_board_team", "anthropic", "openai", "httpx", "mcp")


def _cli() -> str:
    found = shutil.which("conclave-reviewer", path=str(Path(sys.executable).parent))
    if not found:
        raise SystemExit("FEHLER: conclave-reviewer liegt nicht neben diesem Python")
    return found


def main() -> int:
    problems = [f"{name} ist installiert" for name in ABSENT if importlib.util.find_spec(name) is not None]

    import conclave_reviewer
    for module in pkgutil.iter_modules(conclave_reviewer.__path__):
        if module.name != "__main__":
            importlib.import_module(f"conclave_reviewer.{module.name}")
    loaded = sorted(name for name in sys.modules if name == "conclave" or name.startswith("conclave."))
    if loaded:
        problems.append(f"Module aus Personal geladen: {loaded}")

    from importlib import resources
    if not resources.files("conclave_reviewer").joinpath("reviewer-prompt-conclave.md").is_file():
        problems.append("Prompt reviewer-prompt-conclave.md fehlt im Paket")

    cli = _cli()
    help_text = subprocess.run([cli, "--help"], capture_output=True, text=True, timeout=60)
    if help_text.returncode != 0 or not all(word in help_text.stdout for word in ("run", "status", "import-config")):
        problems.append(f"conclave-reviewer --help: {help_text.returncode} {help_text.stdout[:300]}{help_text.stderr[:300]}")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        config = root / "config.toml"
        config.write_text('[reviewer]\n[reviewer.projects]\ndemo = ["%s"]\n' % (root / "repo").as_posix(),
                          encoding="utf-8")
        env = dict(os.environ, CONCLAVE_CONFIG_FILE=str(config), CONCLAVE_REVIEWER_DATA_DIR=str(root / "data"),
                   CONCLAVE_REVIEWER_TOKEN_FILE=str(root / "reviewer.token"))
        os.environ.update(env)
        from conclave_reviewer import config as reviewer_config
        from conclave_reviewer.paths import conclave_config_dir
        cfg = reviewer_config.load(config)
        if cfg["poll_seconds"] != 30 or cfg["max_reviews_per_hour"] != 6 or list(cfg["projects"]) != ["demo"]:
            problems.append(f"Standardwerte stimmen nicht: {cfg}")
        if Path(cfg["reviewer_token_file"]) != root / "reviewer.token":
            problems.append(f"reviewer_token_file: {cfg['reviewer_token_file']}")
        expected = "Conclave" if sys.platform.startswith("win") else "conclave"
        if conclave_config_dir().name != expected:
            problems.append(f"Standardordner: {conclave_config_dir()}")
        status = subprocess.run([cli, "status"], capture_output=True, text=True, timeout=120, env=env)
        if status.returncode not in (0, 1) or "Traceback" in status.stderr:
            problems.append(f"conclave-reviewer status: {status.returncode} {status.stderr[-500:]}")

    for line in problems:
        print(f"FEHLER: {line}", file=sys.stderr)
    if problems:
        return 1
    print("Reviewer-Paket ohne Personal geprueft.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
