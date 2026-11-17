"""W2 (#90): Konfiguration ``[reviewer]``, Datenordner mit Rechten nach R13, Prompt als Ressource, import-config.

Nur mit Testkonfigurationen (``CONCLAVE_CONFIG_FILE``); Laszlos echte Konfiguration bleibt bis W5 ohne
``[reviewer]`` (E-W3).
"""

import tomllib

import pytest

pytest.importorskip("flask")

from conclave.reviewer import config as rc  # noqa: E402
from conclave.reviewer.cli import main  # noqa: E402
from conclave.reviewer.watch import Reviewer  # noqa: E402
from conclave_board.runtime import file_security  # noqa: E402
from tests.reviewer.test_watch import _task, _ticket_in_review, cfg, repo, server  # noqa: E402,F401

OLD = r"""# alte config.toml des Watchers (Form wie bei Laszlo, Pfade erfunden)
board = "conclave"
conclave_url = "http://127.0.0.1:8000"
review_status = "review"
author = "CD · auto-review"
poll_seconds = 20
max_reviews_per_hour = 4
review_timeout_minutes = 25
claude_exe = 'C:\Tools\claude.exe'
prompt_file = "reviewer-prompt-conclave.md"

[projects]
conclave = ['C:\Code\Conclave_original', 'C:\Code\conclave-board-team']
kanzo = 'C:\Code\kanzo'
"""


@pytest.fixture
def conf(tmp_path, monkeypatch):
    path = tmp_path / "conclave" / "config.toml"
    path.parent.mkdir()
    monkeypatch.setenv("CONCLAVE_CONFIG_FILE", str(path))
    monkeypatch.setenv("CONCLAVE_REVIEWER_DATA_DIR", str(tmp_path / "rdata"))
    return path


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


# ── [reviewer] ───────────────────────────────────────────────────────────

def test_section_with_defaults(conf):
    _write(conf, '[server]\nport = 8000\n\n[reviewer]\n[reviewer.projects]\napi = "C:/x"\n')
    cfg = rc.load()
    assert cfg["enabled"] is True and cfg["projects"] == {"api": "C:/x"}
    assert (cfg["poll_seconds"], cfg["max_reviews_per_hour"], cfg["review_timeout_minutes"]) == (30, 6, 30)
    assert cfg["claude_exe"] is None and cfg["review_status"] == "review" and cfg["board"] == "conclave"
    assert cfg["reviewer_token_file"].endswith("reviewer.token")


@pytest.mark.parametrize("text, message", [
    ("[server]\nport = 1\n", "kein Abschnitt [reviewer]"),
    ("[reviewer]\n", "mindestens ein Projekt"),
    ('[reviewer]\npoll_seconds = 0\n[reviewer.projects]\na = "x"\n', "poll_seconds"),
    ('[reviewer]\nenabled = "ja"\n[reviewer.projects]\na = "x"\n', "enabled"),
    ('[reviewer]\n[reviewer.projects]\na = 1\n', "Pfad oder Liste"),
    ("[reviewer\n", "kein gueltiges TOML"),
])
def test_invalid_section_has_a_clear_message(conf, text, message):
    _write(conf, text)
    with pytest.raises(rc.ConfigError, match=message.replace("[", r"\[")):
        rc.load()


def test_disabled_reviewer_does_not_start(conf, capsys):
    _write(conf, '[reviewer]\nenabled = false\n[reviewer.projects]\na = "x"\n')
    assert main(["run", "--once"]) == 0
    assert "abgeschaltet" in capsys.readouterr().err


# ── Prompt ───────────────────────────────────────────────────────────────

def test_bundled_prompt_has_the_placeholders_and_no_paths_or_keys():
    text = rc.prompt_text({"prompt_file": ""})
    assert all(p in text for p in rc.PLACEHOLDERS)
    assert ":\\" not in text and "/Users/" not in text and "cvr_" not in text and "cva_" not in text


def test_prompt_without_placeholders_stops_the_start(conf, tmp_path):
    prompt = _write(tmp_path / "eigen.md", "Reviewe bitte gruendlich.")
    _write(conf, f'[reviewer]\nprompt_file = "{prompt.as_posix()}"\n[reviewer.projects]\na = "x"\n')
    with pytest.raises(SystemExit, match="Platzhalter fehlen"):
        main(["run", "--once"])
    assert not (tmp_path / "rdata").exists()                       # nichts angelegt


def test_own_prompt_file_replaces_the_bundled_one(tmp_path):
    prompt = _write(tmp_path / "eigen.md", "Board {board}: {get}, Ergebnis mit {comment}.")
    assert rc.prompt_text({"prompt_file": str(prompt)}).startswith("Board {board}")


# ── Datenordner (R13) ────────────────────────────────────────────────────

def test_data_dir_and_files_only_for_the_user(tmp_path):
    rv = Reviewer({"conclave_url": "x", "author": "a"}, tmp_path / "rdata", prompt="p")
    rv.prepare()
    rv.log("start")
    rv.save_state({"statuses": {}, "pending": [], "reviews": []})
    for path in (rv.data_dir, rv.log_file, rv.state_file):
        assert file_security.foreign_access(path) == [], path
    assert rv.state_file.name == "state.json"


def test_default_data_dir_is_below_conclaves_config(monkeypatch, tmp_path):
    monkeypatch.delenv("CONCLAVE_REVIEWER_DATA_DIR", raising=False)
    from conclave.runtime.paths import get_runtime_paths
    assert rc.data_dir() == get_runtime_paths().config_dir / "reviewer"


# ── Lauf mit [reviewer] ───────────────────────────────────────────────────

def test_run_with_the_new_section(conf, cfg, server, repo, tmp_path, monkeypatch):
    path, head = repo
    monkeypatch.setenv("CONCLAVE_CONFIG_FILE", str(conf))           # die Server-Fixture setzt eine eigene
    _write(conf, "[reviewer]\n" + "".join(
        f"{k} = {rc._toml_value(cfg[k])}\n" for k in ("conclave_url", "conclave_mcp_exe", "reviewer_token_file",
                                                     "author", "claude_exe", "review_timeout_minutes"))
        + f"[reviewer.projects]\napi = {rc._toml_value(str(path))}\n")
    _ticket_in_review(server, head)
    assert main(["run", "--once", "--dry-run"]) == 0
    log = (tmp_path / "rdata" / "reviewer.log").read_text(encoding="utf-8")
    assert "dry run, command" in log and f"sicherheit @ {head[:7]}" in log
    assert _task(server)["review"]["state"] == "none"


# ── import-config ────────────────────────────────────────────────────────

def test_import_takes_projects_and_limits(tmp_path):
    old = _write(tmp_path / "old" / "config.toml", OLD) if (tmp_path / "old").mkdir() is None else None
    target = _write(tmp_path / "conclave.toml", '[server]\nport = 8000\n')
    shown = []
    assert rc.import_config(old, target, confirm=lambda text: shown.append(text) or True)
    new = tomllib.loads(target.read_text(encoding="utf-8"))
    old_data = tomllib.loads(OLD)
    assert new["server"] == {"port": 8000}                           # Rest bleibt
    section = new["reviewer"]
    assert section["projects"] == old_data["projects"]
    for key in ("poll_seconds", "max_reviews_per_hour", "review_timeout_minutes", "claude_exe", "author"):
        assert section[key] == old_data[key], key
    assert section["legacy_lock_file"].endswith("watcher.lock") and section["enabled"] is True
    assert shown and "[reviewer.projects]" in shown[0]                # vor dem Schreiben gezeigt


def test_import_writes_nothing_without_confirmation(tmp_path):
    (tmp_path / "old").mkdir()
    old = _write(tmp_path / "old" / "config.toml", OLD)
    target = _write(tmp_path / "conclave.toml", "[server]\nport = 8000\n")
    assert rc.import_config(old, target, confirm=lambda text: False) is False
    assert target.read_text(encoding="utf-8") == "[server]\nport = 8000\n"


def test_import_does_not_overwrite_an_existing_section(tmp_path):
    (tmp_path / "old").mkdir()
    old = _write(tmp_path / "old" / "config.toml", OLD)
    target = _write(tmp_path / "conclave.toml", '[reviewer]\n[reviewer.projects]\na = "x"\n')
    with pytest.raises(rc.ConfigError, match="gibt es schon"):
        rc.import_config(old, target, confirm=lambda text: True)


def test_import_config_command(tmp_path, capsys, monkeypatch):
    (tmp_path / "old").mkdir()
    old = _write(tmp_path / "old" / "config.toml", OLD)
    target = tmp_path / "neu.toml"
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert main(["import-config", str(old), "--target", str(target)]) == 0
    assert not target.exists() and "Nichts geschrieben" in capsys.readouterr().out
    assert main(["import-config", str(old), "--target", str(target), "--yes"]) == 0
    assert tomllib.loads(target.read_text(encoding="utf-8"))["reviewer"]["projects"]["kanzo"] == "C:\\Code\\kanzo"
