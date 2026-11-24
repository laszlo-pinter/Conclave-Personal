"""T13 (conclave#143): Die Suite ist vom Rechner abgeschirmt.

Bei Laszlo stehen ``CONCLAVE_DB_PROVIDER=postgres`` und ``CONCLAVE_DB_DSN`` auf die echte Datenbank.
Die autouse-Fixture ``isolated_machine`` (tests/conftest.py) entfernt solche Variablen und legt die
Benutzerordner unter ``tmp_path``; Kindprozesse erben das.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from tests.conftest import foreign_variables

ROOT = Path(__file__).resolve().parents[1]
BOGUS = {
    "CONCLAVE_DB_PROVIDER": "postgres",
    "CONCLAVE_DB_DSN": "host=192.0.2.1 port=1 dbname=echt user=niemand connect_timeout=1",
    "CONCLAVE_API_KEY": "cvh_vom-rechner",
    "CONCLAVE_AGENT_KEY": "cva_vom-rechner",
    "CONCLAVE_CONFIG_FILE": str(ROOT / "gibt-es-nicht" / "config.toml"),
    "CONCLAVE_SECRET_KEY": "kein-fernet-schluessel",
    "CONCLAVE_API_URL": "http://192.0.2.1:1",
    "ANTHROPIC_API_KEY": "sk-ant-vom-rechner",
    "OPENAI_API_KEY": "sk-vom-rechner",
    "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat-vom-rechner",
}


def _only_test_paths(environ, tmp_path) -> None:
    """Uebrig sind nur die Pfade, die die Fixture selbst unter tmp_path setzt; kein Schluessel, keine DSN."""
    left = foreign_variables(environ)
    assert all(not name.endswith(("_KEY", "_TOKEN", "_DSN", "_PROVIDER", "_URL")) for name in left), left
    assert all(Path(environ[name]).is_relative_to(tmp_path) for name in left), left


def test_machine_state_is_hidden(tmp_path):
    """Der Kern-Nachweis; laeuft auch im Kindlauf unten mit den falschen Werten aus BOGUS."""
    _only_test_paths(os.environ, tmp_path)
    from conclave.cli.config import ConclaveConfig
    from conclave.runtime.paths import get_runtime_paths
    config = ConclaveConfig.from_sources()
    assert config.db_provider == "sqlite" and config.db_dsn == ""
    assert config.db_path.is_relative_to(tmp_path)
    assert (config.api_key, config.agent_api_key, config.anthropic_api_key) == ("", "", "")
    paths = get_runtime_paths()
    for path in (paths.config_dir, paths.data_dir, paths.log_dir, paths.workspace_dir, paths.db_path,
                 paths.secret_key_path):
        assert path.is_relative_to(tmp_path), path


def test_child_processes_inherit_the_clean_environment(tmp_path):
    code = ("import json, os, flask, conclave; print(json.dumps({k: v for k, v in os.environ.items() "
            "if k.startswith(('CONCLAVE_', 'APPDATA', 'LOCALAPPDATA')) or k.endswith('_API_KEY')}))")
    seen = json.loads(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                                     cwd=ROOT).stdout)
    _only_test_paths(seen, tmp_path)
    assert Path(seen["APPDATA"]).is_relative_to(tmp_path)        # und die Pakete (flask) fand er trotzdem


def test_foreign_variables_names_what_the_suite_must_not_see():
    env = {"CONCLAVE_DB_DSN": "x", "CONCLAVE_TEST_POSTGRES_DSN": "y", "OPENAI_API_KEY": "z",
           "CLAUDE_CODE_OAUTH_TOKEN": "t", "PATH": "p"}
    assert foreign_variables(env) == ["CLAUDE_CODE_OAUTH_TOKEN", "CONCLAVE_DB_DSN", "OPENAI_API_KEY"]


def test_wrong_machine_values_do_not_change_the_result():
    """Abnahme: absichtlich falsche Werte des Rechners aendern nichts; auch der Desktop-Test, der sich am
    24.11. mit der echten Postgres-DB verband, bleibt gruen."""
    env = {**os.environ, **BOGUS}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "tests/test_machine_isolation.py::test_machine_state_is_hidden",
         "tests/reviewer/test_launch.py::test_desktop_starts_and_stops_the_reviewer"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-2000:]
    assert "2 passed" in result.stdout
