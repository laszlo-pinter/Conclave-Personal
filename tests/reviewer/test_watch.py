"""W1 (#89): Tests des alten Watchers (kanzo-reviewer/test_watcher.py), umgezogen nach conclave.reviewer.

Gegen einen echten Conclave-Server aus dem Quellbaum. Der Reviewer selbst (claude -p) ist durch
einen Stub ersetzt, der das Ergebnis mit dem Reviewer-Token setzt; kein Review kostet etwas.
"""

import json
import subprocess
import threading
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("flask")

from conclave.reviewer import refs  # noqa: E402
from conclave.reviewer.watch import Reviewer  # noqa: E402

HUMAN, AGENT, REVIEWER = "cvh_mensch", "cva_agent", "cvr_reviewer"


def _req(url, token, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r) if r.length != 0 else None


@pytest.fixture
def server(tmp_path, monkeypatch):
    from werkzeug.serving import make_server

    from conclave.api.server import _build_app
    from conclave.cli.config import ConclaveConfig

    for name, value in (("CONCLAVE_WORKSPACE", tmp_path / "ws"), ("CONCLAVE_SECRET_KEY_FILE", tmp_path / "secret.key"),
                        ("CONCLAVE_API_TOKEN_FILE", tmp_path / "api.token"),
                        ("CONCLAVE_AGENT_TOKEN_FILE", tmp_path / "agent.token"),
                        ("CONCLAVE_REVIEWER_TOKEN_FILE", tmp_path / "reviewer.token"),
                        ("CONCLAVE_LOG_DIR", tmp_path / "logs"), ("CONCLAVE_CONFIG_FILE", tmp_path / "config.toml"),
                        ("CONCLAVE_BACKUP_DIR", tmp_path / "backups")):
        monkeypatch.setenv(name, str(value))
    for name in ("CONCLAVE_API_KEY", "CONCLAVE_AGENT_KEY", "CONCLAVE_REVIEWER_KEY"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "ws").mkdir()
    (tmp_path / "data").mkdir()
    app, _ = _build_app(ConclaveConfig(db_path=tmp_path / "data" / "c.db", api_key=HUMAN, agent_api_key=AGENT,
                                       reviewer_api_key=REVIEWER))
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{srv.server_port}"
    _req(f"{url}/board/projects", HUMAN, "POST", {"slug": "api", "name": "API"})
    yield url
    srv.shutdown()
    thread.join(timeout=5)


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(path), *a], check=True, capture_output=True, text=True)
    run("init", "-q", "-b", "sicherheit")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "Test")
    (path / "datei.txt").write_text("alt\n", encoding="utf-8")
    run("add", ".")
    run("commit", "-q", "-m", "eins")
    (path / "datei.txt").write_text("neu\n", encoding="utf-8")
    run("commit", "-q", "-am", "zwei")
    head = run("rev-parse", "HEAD").stdout.strip()
    (path / "datei.txt").write_text("ungespeichert in cc's Arbeitsverzeichnis\n", encoding="utf-8")
    return path, head


PROMPT = "Prompt fuer {author} im {board}: {get} und {comment}."


@pytest.fixture
def cfg(server, repo, tmp_path):
    (tmp_path / "rt").write_text(REVIEWER + "\n", encoding="utf-8")
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "reviewer-prompt-conclave.md").write_text(PROMPT, encoding="utf-8")
    return {"board": "conclave", "conclave_url": server, "conclave_mcp_exe": "conclave-mcp.exe",
            "reviewer_token_file": str(tmp_path / "rt"), "review_status": "review", "author": "CD · auto-review",
            "review_timeout_minutes": 1, "max_reviews_per_hour": 6, "projects": {"api": str(repo[0])},
            "prompt_file": "reviewer-prompt-conclave.md",
            "claude_exe": "claude"}                 # wird nie aufgerufen; in der CI gibt es kein claude


@pytest.fixture
def rv(cfg, tmp_path):
    return Reviewer(cfg, tmp_path / "data", base_dir=tmp_path / "base")


def _claude(monkeypatch, rv, fake):
    """Ersetzt den Aufruf von claude; ``fake`` bekommt wie frueher (cfg, key, cmd, cwd). Den Auftrag, der ueber
    stdin ginge (R1), legt es vorher in ``rv.seen_ask`` ab."""
    def run(key, cmd, cwd, ask=None):
        rv.seen_ask = ask
        return fake(rv.cfg, key, cmd, cwd)
    monkeypatch.setattr(rv, "run_claude", run)


def _ticket_in_review(server, head, comment=True):
    _req(f"{server}/board/tasks", HUMAN, "POST", {"project": "api", "title": "T"})
    _req(f"{server}/board/projects/api/tasks/1", HUMAN, "PATCH", {"status": "review"})
    if comment:
        _req(f"{server}/board/projects/api/tasks/1/comments", AGENT, "POST",
             {"body": f"**Branch:** `sicherheit` · **Commit:** `{head[:7]}`\nTests gruen"})
    return {"project": "api", "title": "T", "status": "review", "human": False, "review_state": "none"}


def _task(server):
    return _req(f"{server}/board/projects/api/tasks/1", HUMAN)


def test_review_runs_in_a_worktree_of_the_named_commit_and_sets_the_result(rv, cfg, server, repo, monkeypatch):
    path, head = repo
    task = _ticket_in_review(server, head)
    seen = {}

    def fake_claude(cfg_, key, cmd, cwd):
        seen["cwd"], seen["cmd"], seen["ask"] = cwd, cmd, rv.seen_ask
        seen["content"] = (Path(cwd) / "datei.txt").read_text(encoding="utf-8")
        seen["state_during"] = _task(server)["review"]["state"]
        seen["mcp"] = json.loads(rv.mcp_config.read_text())
        _req(f"{server}/board/projects/api/tasks/1/review", REVIEWER, "POST",
             {"state": "rework", "comment": "Urteil: gelb\nB1 x", "blocking": 1, "suggestions": 0,
              "checked": f"sicherheit @ {head[:7]}"})
        return "done"

    _claude(monkeypatch, rv, fake_claude)
    rv.run_review(task, "api#1", str(path), dry_run=False)

    assert seen["state_during"] == "running"
    assert seen["content"] == "neu\n"                         # Stand des Commits, nicht cc's Arbeitsverzeichnis
    assert Path(seen["cwd"]).parent == rv.worktrees
    assert not Path(seen["cwd"]).exists()                     # Worktree wieder entfernt
    assert f"sicherheit @ {head[:7]}" in seen["ask"]
    conclave = seen["mcp"]["mcpServers"]["conclave"]
    assert conclave["args"] == ["--reviewer"]
    assert conclave["env"]["CONCLAVE_MCP_ROLE"] == "reviewer"
    assert "CONCLAVE_AGENT_TOKEN_FILE" not in conclave["env"]
    assert seen["mcp"]["mcpServers"]["git"]["args"][-1] == seen["cwd"]
    assert "mcp__conclave__conclave_board_review" in seen["cmd"]
    after = _task(server)
    assert (after["status"], after["review"]["state"]) == ("todo", "rework")
    taken = _req(f"{server}/board/next", AGENT, "POST", {})
    assert taken["task"]["ref"] == "api#1" and taken["last_review"]["body"].startswith("Urteil: gelb")


@pytest.mark.parametrize("outcome, text", [("timeout", "abgebrochen"), ("done", "ohne Ergebnis"),
                                           ("failed", "Fehler")])
def test_run_without_a_result_leaves_running_and_says_so(rv, cfg, server, repo, monkeypatch, outcome, text):
    path, head = repo
    task = _ticket_in_review(server, head)
    _claude(monkeypatch, rv, lambda *a: outcome)
    rv.run_review(task, "api#1", str(path), dry_run=False)
    after = _task(server)
    assert (after["status"], after["review"]["state"], after["review"]["red_count"]) == ("review", "running", 0)
    last = after["comments"][-1]
    assert last["origin"] == "reviewer" and text in last["body"]
    assert not any(rv.worktrees.iterdir())


def test_ticket_without_a_named_commit_is_not_reviewed(rv, cfg, server, repo, monkeypatch):
    path, _ = repo
    task = _ticket_in_review(server, "", comment=False)
    _claude(monkeypatch, rv, lambda *a: pytest.fail("darf nicht laufen"))
    rv.run_review(task, "api#1", str(path), dry_run=False)
    after = _task(server)
    assert after["review"]["state"] == "none"
    assert "kein Commit" in after["comments"][-1]["body"]


def test_unknown_commit_falls_back_to_the_named_branch(rv, cfg, server, repo, monkeypatch):
    path, head = repo
    _req(f"{server}/board/tasks", HUMAN, "POST", {"project": "api", "title": "T"})
    _req(f"{server}/board/projects/api/tasks/1", HUMAN, "PATCH", {"status": "review"})
    _req(f"{server}/board/projects/api/tasks/1/comments", AGENT, "POST",
         {"body": "**Branch:** `sicherheit` · **Commit:** `deadbee`"})
    seen = {}
    _claude(monkeypatch, rv, lambda c, k, cmd, cwd: seen.setdefault("ask", rv.seen_ask) and "done")
    rv.run_review({"title": "T"}, "api#1", str(path), dry_run=False)
    assert f"sicherheit @ {head[:7]}" in seen["ask"]


@pytest.mark.parametrize("title", ['Login & Logout | 50% "schneller" > alt', "%PATH% ^ ! --help", "Umlaute äöü ✓"])
def test_any_title_is_reviewed_and_never_reaches_the_command_line(rv, cfg, server, repo, monkeypatch, title):
    """R1 (conclave#142): Der Titel startet oder verhindert nichts; er steht weder im Aufruf noch im Auftrag."""
    path, head = repo
    _req(f"{server}/board/tasks", HUMAN, "POST", {"project": "api", "title": title})
    _req(f"{server}/board/projects/api/tasks/1", HUMAN, "PATCH", {"status": "review"})
    _req(f"{server}/board/projects/api/tasks/1/comments", AGENT, "POST",
         {"body": f"**Branch:** `sicherheit` · **Commit:** `{head[:7]}`"})
    seen = {}

    def fake_claude(cfg_, key, cmd, cwd):
        seen["cmd"], seen["ask"], seen["state"] = cmd, rv.seen_ask, _task(server)["review"]["state"]
        seen["prompt"] = rv.prompt_file.read_text(encoding="utf-8")
        return "done"

    _claude(monkeypatch, rv, fake_claude)
    rv.run_review({"project": "api", "title": title, "status": "review"}, "api#1", str(path), dry_run=False)
    assert seen["state"] == "running"                                    # das Review lief
    assert title not in seen["ask"] and all(title not in arg for arg in seen["cmd"])
    assert not any(ch in arg for arg in seen["cmd"] for ch in "\r\n")
    assert seen["ask"].startswith("Reviewe das Ticket api#1.") and f"sicherheit @ {head[:7]}" in seen["ask"]
    assert seen["prompt"] == PROMPT.format(author="CD · auto-review", board="Conclave-Board",
                                           get="conclave_board_get", comment="conclave_board_review")


def test_reviews_of_the_reviewer_are_not_taken_as_named_commits():
    detail = {"comments": [
        {"origin": "agent", "author_name": "cc", "body": "Commit `1111111`"},
        {"origin": "agent", "author_name": "CD · auto-review", "body": "geprueft `2222222`"},
        {"origin": "reviewer", "author_name": "", "body": "Urteil: gelb `3333333`"},
    ]}
    assert refs.named_commits(detail, "CD · auto-review") == (["1111111"], None)


def test_check_skips_tickets_that_already_have_a_result(rv, cfg, monkeypatch):
    called = []
    monkeypatch.setattr(rv, "run_review", lambda *a: called.append(a))
    monkeypatch.setattr(rv, "save_state", lambda *a: None)
    tasks = {"api#1": {"project": "api", "title": "T", "status": "review", "human": False,
                       "review_state": "passed"}}
    rv.check({"statuses": {"api#1": "doing"}, "pending": [], "reviews": []}, tasks, dry_run=False)
    assert called == []


def test_reviewer_never_uses_the_agent_token():
    import conclave.reviewer as package
    for path in Path(package.__file__).parent.glob("*.py"):
        code = path.read_text(encoding="utf-8").split('"""', 2)[-1]  # ohne den Modul-Docstring
        assert "agent.token" not in code and "agent_token" not in code and "CONCLAVE_AGENT" not in code, path


# ── Mehrere Repos je Projekt (P7) ───────────────────────────────────────────

def _second_repo(tmp_path, name="team"):
    path = tmp_path / name
    path.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(path), *a], check=True, capture_output=True, text=True)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "Test")
    (path / "team.txt").write_text("team\n", encoding="utf-8")
    run("add", ".")
    run("commit", "-q", "-m", "team")
    return path, run("rev-parse", "HEAD").stdout.strip()


def _comment(server, body):
    _req(f"{server}/board/tasks", HUMAN, "POST", {"project": "api", "title": "T"})
    _req(f"{server}/board/projects/api/tasks/1", HUMAN, "PATCH", {"status": "review"})
    _req(f"{server}/board/projects/api/tasks/1/comments", AGENT, "POST", {"body": body})
    return {"project": "api", "title": "T", "status": "review", "human": False, "review_state": "none"}


def _capture(monkeypatch, seen, rv):
    def fake_claude(cfg_, key, cmd, cwd):
        seen["cwd"], seen["cmd"], seen["ask"] = cwd, cmd, rv.seen_ask
        seen["mcp"] = json.loads(rv.mcp_config.read_text())
        seen["files"] = sorted(str(p.relative_to(cwd)).replace("\\", "/") for p in Path(cwd).rglob("*.txt"))
        return "done"
    _claude(monkeypatch, rv, fake_claude)


def test_commit_only_in_the_second_repo_is_reviewed_there(rv, cfg, server, repo, tmp_path, monkeypatch):
    core, _ = repo
    team, team_head = _second_repo(tmp_path)
    task = _comment(server, f"**Branch:** `main` · **Commit:** `{team_head[:7]}`")
    seen = {}
    _capture(monkeypatch, seen, rv)
    rv.run_review(task, "api#1", [str(core), str(team)], dry_run=False)
    assert seen["files"] == ["team.txt"]                       # Arbeitsverzeichnis = Team-Worktree
    assert f"team: main @ {team_head[:7]}" in seen["ask"]
    assert "repo:" not in seen["ask"]                       # Kern-Repo hat den Commit nicht
    assert list(seen["mcp"]["mcpServers"]) == ["git", "conclave"]
    assert not Path(seen["cwd"]).exists()


def test_commits_in_both_repos_get_two_worktrees_and_two_git_servers(rv, cfg, server, repo, tmp_path, monkeypatch):
    core, core_head = repo
    team, team_head = _second_repo(tmp_path)
    task = _comment(server, f"**Branch:** `sicherheit` · **Commit:** `{core_head[:7]}`\n"
                            f"**Branch:** `main` · **Commit:** `{team_head[:7]}`")
    seen = {}
    _capture(monkeypatch, seen, rv)
    rv.run_review(task, "api#1", [str(core), str(team)], dry_run=False)
    assert seen["files"] == ["_repos/team/team.txt", "datei.txt"]
    ask = seen["ask"]
    assert f"repo: sicherheit @ {core_head[:7]}" in ask and f"team: main @ {team_head[:7]}" in ask
    assert "_repos/team" in ask and "git_team" in ask
    servers = seen["mcp"]["mcpServers"]
    assert servers["git"]["args"][-1] == seen["cwd"]
    assert Path(servers["git_team"]["args"][-1]) == Path(seen["cwd"]) / "_repos" / "team"
    assert "mcp__git_team__show" in seen["cmd"] and "mcp__git__show" in seen["cmd"]
    assert not any(rv.worktrees.iterdir())                # beide Worktrees wieder entfernt
    for path in (core, team):                                  # und in git abgemeldet
        listed = subprocess.run(["git", "-C", str(path), "worktree", "list"], capture_output=True, text=True)
        assert len(listed.stdout.strip().splitlines()) == 1


def test_commit_in_no_repo_is_named_as_not_checkable(rv, cfg, server, repo, tmp_path, monkeypatch):
    core, core_head = repo
    team, _ = _second_repo(tmp_path)
    task = _comment(server, f"Kern: `{core_head[:7]}` · Team: `abcdef1`")
    seen = {}
    _capture(monkeypatch, seen, rv)
    rv.run_review(task, "api#1", [str(core), str(team)], dry_run=False)
    assert "nicht pruefbar" in seen["ask"] and "`abcdef1`" in seen["ask"]
    assert f"repo: detached @ {core_head[:7]}" in seen["ask"]


def test_repos_for_accepts_one_path_or_a_list():
    assert refs.repos_for({"projects": {"a": "C:/x"}}, "a") == ["C:/x"]
    assert refs.repos_for({"projects": {"a": ["C:/x", "C:/y"]}}, "a") == ["C:/x", "C:/y"]
    assert refs.repos_for({"projects": {}}, "a") == []


def test_check_passes_all_existing_repos_and_drops_missing_ones(rv, cfg, repo, tmp_path, monkeypatch):
    team, _ = _second_repo(tmp_path)
    called = []
    monkeypatch.setattr(rv, "run_review", lambda t, k, r, d: called.append(r))
    monkeypatch.setattr(rv, "save_state", lambda *a: None)
    tasks = {"api#1": {"project": "api", "title": "T", "status": "review", "human": False, "review_state": "none"}}
    for projects, expected in (([str(repo[0]), str(team)], [str(repo[0]), str(team)]),
                               ([str(repo[0]), str(tmp_path / "fehlt")], str(repo[0])),
                               (str(repo[0]), str(repo[0]))):
        cfg["projects"] = {"api": projects}
        called.clear()
        rv.check({"statuses": {"api#1": "doing"}, "pending": [], "reviews": []}, tasks, dry_run=False)
        assert called == [expected]


def test_multi_repo_comment_form_names_branches():
    detail = {"comments": [{"origin": "agent", "author_name": "cc",
                            "body": "**Kern:** `feature-x` @ `a07cda0` · **App:** `feature-y` @ `d50667c`"}]}
    assert refs.named_refs(detail, "CD · auto-review") == (["a07cda0", "d50667c"], ["feature-x", "feature-y"])


def test_commit_on_the_named_branch_wins_over_a_newer_one_in_the_text(rv, cfg, server, repo, tmp_path, monkeypatch):
    """Ein nur erwaehnter, neuerer Commit auf einem anderen Branch ersetzt nicht den zu pruefenden."""
    core, core_head = repo
    run = lambda *a: subprocess.run(["git", "-C", str(core), *a], check=True, capture_output=True, text=True)
    run("switch", "-q", "-c", "anderer", core_head)
    (core / "anders.txt").write_text("x\n", encoding="utf-8")
    run("add", "anders.txt")
    run("commit", "-q", "--date=2099-01-01T00:00:00", "-m", "neuer, anderer Branch")
    other = run("rev-parse", "HEAD").stdout.strip()
    task = _comment(server, f"**Kern:** `sicherheit` @ `{core_head[:7]}`\nOffen: `{other[:7]}` liegt nur auf anderer.")
    seen = {}
    _capture(monkeypatch, seen, rv)
    rv.run_review(task, "api#1", [str(core)], dry_run=False)
    assert f"sicherheit @ {core_head[:7]}" in seen["ask"]
    assert "nicht pruefbar" not in seen["ask"]                  # beide existieren; keiner fehlt
