"""W1 (#89): ``conclave-reviewer run`` und der Probelauf.

Der Probelauf zeigt den Aufruf von ``claude`` und die MCP-Konfiguration, wie ein echter Lauf sie
naehme, legt aber keinen Worktree an und setzt keinen Review-Status.
"""

import json

import pytest

pytest.importorskip("flask")

from conclave.reviewer.cli import main  # noqa: E402
from tests.reviewer.test_watch import (  # noqa: E402,F401 - Fixtures
    AGENT, HUMAN, PROMPT, REVIEWER, _req, _task, _ticket_in_review, cfg, repo, rv, server,
)


def _config(tmp_path, cfg, name="config.toml"):
    lines = [f'{k} = {json.dumps(v)}' for k, v in cfg.items() if not isinstance(v, dict)]
    lines += ["[projects]"] + [f'{k} = {json.dumps(v)}' for k, v in cfg["projects"].items()]
    path = tmp_path / "base" / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_dry_run_shows_the_command_and_changes_nothing(rv, cfg, server, repo, tmp_path):
    path, head = repo
    task = _ticket_in_review(server, head)
    rv.run_review(task, "api#1", str(path), dry_run=True)
    log = rv.log_file.read_text(encoding="utf-8")
    command_line = next(line for line in log.splitlines() if "dry run, command" in line)
    cmd = json.loads(command_line.split(": ", 2)[-1])
    assert cmd[1:3] == ["-p", f"Reviewe das Ticket api#1: T\nGepruefter Stand (dein Arbeitsverzeichnis, ein "
                                f"eigener Worktree): sicherheit @ {head[:7]}"]
    assert "--restricted" in cmd and cmd[cmd.index("--append-system-prompt") + 1].startswith("<Prompt")
    mcp = json.loads(next(line for line in log.splitlines() if "dry run, mcp config" in line).split(": ", 2)[-1])
    assert mcp["mcpServers"]["conclave"]["args"] == ["--reviewer"]
    assert not rv.worktrees.exists() and _task(server)["review"]["state"] == "none"
    assert not rv.mcp_config.exists()


def test_run_once_in_dry_run_mode(cfg, server, repo, tmp_path, capsys):
    path, head = repo
    config = _config(tmp_path, cfg)
    data = tmp_path / "rdata"
    _ticket_in_review(server, head)
    assert main(["run", "--config", str(config), "--data-dir", str(data), "--dry-run", "--once"]) == 0
    log = (data / "reviewer.log").read_text(encoding="utf-8")
    assert "api#1: moved to review" in log and "dry run, command" in log
    assert _task(server)["review"]["state"] == "none"


def test_dry_run_writes_no_state(rv, cfg, server, repo):
    """#89-Review B2: ein Probelauf veraendert den Zustand nicht (weder anlegen noch aendern)."""
    path, head = repo
    _ticket_in_review(server, head)
    rv.poll_once(None, dry_run=True)
    assert not rv.state_file.exists()
    saved = {"statuses": {"api#1": "doing"}, "pending": [], "reviews": []}
    rv.save_state(saved)
    before = rv.state_file.read_text(encoding="utf-8")
    rv.poll_once(rv.load_state(), dry_run=True)
    assert rv.state_file.read_text(encoding="utf-8") == before
    assert _task(server)["review"]["state"] == "none"


def test_default_data_dir_is_not_the_old_watchers_folder(tmp_path, monkeypatch):
    """#89-Review B2: ohne --data-dir nie der Ordner der alten config.toml."""
    from conclave.reviewer.watch import default_data_dir
    monkeypatch.delenv("CONCLAVE_REVIEWER_DATA_DIR", raising=False)
    config = tmp_path / "kanzo-reviewer" / "config.toml"
    assert default_data_dir(config) != config.parent and default_data_dir(config).name == "reviewer"
    monkeypatch.setenv("CONCLAVE_REVIEWER_DATA_DIR", str(tmp_path / "eigen"))
    assert default_data_dir(config) == tmp_path / "eigen"


def test_does_not_start_next_to_the_old_watcher(cfg, tmp_path, capsys):
    from tests.reviewer.test_hardening import _hold
    config = _config(tmp_path, cfg)
    holder = _hold(config.parent / "watcher.lock")
    try:
        assert main(["run", "--config", str(config), "--data-dir", str(tmp_path / "rdata"), "--once"]) == 1
        assert "alte Watcher" in capsys.readouterr().err
    finally:
        holder.kill()
        holder.wait(10)


def test_kanzo_board_is_no_longer_supported(cfg, tmp_path):
    cfg = {**cfg, "board": "kanzo"}
    with pytest.raises(SystemExit, match="nicht mehr"):
        main(["run", "--config", str(_config(tmp_path, cfg)), "--once"])
