"""TR2 (conclave#124): Reviewer am Team-Server.

Eigene Konfigurationsdatei (``--settings``), https mit eigenem CA-Buendel ohne Proxy und Umleitungen,
Token aus der Anmeldeinformationsverwaltung oder einer Datei, MCP-Server ``conclave-board-mcp --reviewer``,
``git fetch`` vor dem Review und rot bei Commits, die es im Git-Server nicht gibt.

Der Server hier ist der Board-Kern aus dem Quellbaum (dieselbe API v1 wie der Team-Server) hinter TLS
mit einer eigenen Test-CA. Die Probe gegen den echten Team-Server mit ``conclave-board-mcp`` liegt im
Team-Repo (tests/test_reviewer_e2e.py).
"""

import datetime
import http.server
import ipaddress
import json
import os
import ssl
import subprocess
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

pytest.importorskip("flask")
x509 = pytest.importorskip("cryptography.x509")

from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402

from conclave_reviewer import command, credentials, transport  # noqa: E402
from conclave_reviewer import config as rc  # noqa: E402
from conclave_reviewer.cli import main as cli_main  # noqa: E402
from conclave_reviewer.watch import Reviewer  # noqa: E402

HUMAN, AGENT, REVIEWER = "cvh_mensch", "cva_agent", "cvr_reviewer"


# ── Test-CA und Server ueber https ────────────────────────────────────────

def _cert(subject, issuer_key, issuer_name, key, *, ca=False, san=None):
    now = datetime.datetime.now(datetime.timezone.utc)
    builder = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer_name).public_key(key.public_key())
               .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
               .not_valid_after(now + datetime.timedelta(days=1))
               .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    if san:
        builder = builder.add_extension(x509.SubjectAlternativeName(san), critical=False)
    return builder.sign(issuer_key, hashes.SHA256())


def _ca(base: Path, name: str):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    cert = _cert(subject, key, subject, key, ca=True)
    (base / f"{name}.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return key, subject, base / f"{name}.pem"


def _server_context(base: Path, ca_key, ca_name) -> ssl.SSLContext:
    key = ec.generate_private_key(ec.SECP256R1())
    cert = _cert(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "board.intern")]), ca_key, ca_name, key,
                 san=[x509.IPAddress(ipaddress.ip_address("127.0.0.1")), x509.DNSName("localhost")])
    (base / "server.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (base / "server.key").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                        serialization.NoEncryption()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(base / "server.pem", base / "server.key")
    return context


@pytest.fixture
def tls(tmp_path, monkeypatch):
    """Board-Kern (aus Personal) ueber https mit eigener CA; dazu eine zweite, fremde CA."""
    from werkzeug.serving import make_server

    from conclave.api.server import _build_app
    from conclave.cli.config import ConclaveConfig

    for name, value in (("CONCLAVE_WORKSPACE", tmp_path / "ws"), ("CONCLAVE_SECRET_KEY_FILE", tmp_path / "secret.key"),
                        ("CONCLAVE_API_TOKEN_FILE", tmp_path / "api.token"),
                        ("CONCLAVE_AGENT_TOKEN_FILE", tmp_path / "agent.token"),
                        ("CONCLAVE_REVIEWER_TOKEN_FILE", tmp_path / "srv-reviewer.token"),
                        ("CONCLAVE_LOG_DIR", tmp_path / "logs"), ("CONCLAVE_CONFIG_FILE", tmp_path / "srv.toml"),
                        ("CONCLAVE_BACKUP_DIR", tmp_path / "backups")):
        monkeypatch.setenv(name, str(value))
    for name in ("CONCLAVE_API_KEY", "CONCLAVE_AGENT_KEY", "CONCLAVE_REVIEWER_KEY"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "ws").mkdir()
    certs = tmp_path / "certs"
    certs.mkdir()
    ca_key, ca_name, ca_file = _ca(certs, "firmen-ca")
    _other_key, _other_name, other_file = _ca(certs, "fremde-ca")
    app, _ = _build_app(ConclaveConfig(db_path=tmp_path / "c.db", api_key=HUMAN, agent_api_key=AGENT,
                                       reviewer_api_key=REVIEWER))
    srv = make_server("127.0.0.1", 0, app, threaded=True, ssl_context=_server_context(certs, ca_key, ca_name))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    url = f"https://127.0.0.1:{srv.server_port}"
    human = transport.opener(str(ca_file))

    def call(method, path, token=HUMAN, body=None):
        req = urllib.request.Request(url + path, data=json.dumps(body).encode() if body is not None else None,
                                     method=method, headers={"Authorization": f"Bearer {token}",
                                                             "Content-Type": "application/json"})
        with human.open(req, timeout=10) as r:
            raw = r.read()
            return json.loads(raw) if raw else None

    call("POST", "/board/v1/projects", body={"slug": "api", "name": "API"})
    yield type("TLS", (), {"url": url, "ca": str(ca_file), "other_ca": str(other_file), "call": staticmethod(call)})
    srv.shutdown()
    thread.join(timeout=5)


def _git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repos(tmp_path):
    """Git-Server (bare) und der Checkout des Reviewers davon; ``push`` legt einen Commit nur im Git-Server an."""
    work = tmp_path / "entwickler"
    work.mkdir()
    _git(work, "init", "-q", "-b", "feature")
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "a.txt").write_text("eins\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "eins")
    bare = tmp_path / "git-server.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(bare)], check=True, capture_output=True)
    _git(work, "remote", "add", "origin", str(bare))
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", "-q", str(bare), str(checkout)], check=True, capture_output=True)

    def push(text):
        (work / "a.txt").write_text(text, encoding="utf-8")
        _git(work, "commit", "-q", "-am", text.strip())
        _git(work, "push", "-q", "origin", "feature")
        return _git(work, "rev-parse", "HEAD")

    return type("Repos", (), {"checkout": checkout, "push": staticmethod(push)})


def _settings(tmp_path, tls, checkout, **extra) -> Path:
    token = tmp_path / "secrets" / "reviewer.token"
    token.parent.mkdir(exist_ok=True)
    token.write_text(REVIEWER + "\n", encoding="utf-8")
    lines = ['[reviewer]', 'server = "team"', f'server_url = "{tls.url}"',
             f'ca_bundle = {json.dumps(tls.ca)}', 'reviewer_token_file = "secrets/reviewer.token"',
             'data_dir = "reviewer-daten"', 'conclave_mcp_exe = "conclave-board-mcp"', 'claude_exe = "claude"']
    lines += [f"{k} = {json.dumps(v)}" for k, v in extra.items()]
    lines += ["[reviewer.projects]", f"api = [{json.dumps(str(checkout))}]"]
    path = tmp_path / "reviewer.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ── Konfiguration ────────────────────────────────────────────────────────

def test_team_settings_with_defaults(tmp_path, tls, repos):
    cfg = rc.load(_settings(tmp_path, tls, repos.checkout))
    assert cfg["server"] == "team" and cfg["conclave_url"] == tls.url
    assert cfg["ca_bundle"] == tls.ca
    assert cfg["reviewer_token_file"] == str(tmp_path / "secrets" / "reviewer.token")   # relativ zur Datei
    assert cfg["data_dir"] == str(tmp_path / "reviewer-daten")
    assert (cfg["conclave_mcp_args"], cfg["fetch"], cfg["missing_commits"]) == (["--reviewer"], True, "red")
    assert REVIEWER not in json.dumps(cfg)                                              # das Token nie


def test_team_default_mcp_server_is_conclave_board_mcp(tmp_path, tls, repos):
    path = _settings(tmp_path, tls, repos.checkout)
    path.write_text(path.read_text(encoding="utf-8").replace('conclave_mcp_exe = "conclave-board-mcp"\n', ""),
                    encoding="utf-8")
    assert Path(rc.load(path)["conclave_mcp_exe"]).name.startswith("conclave-board-mcp")


def test_personal_keeps_its_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[reviewer]\nconclave_url = "http://rechner.lan:8000"\n[reviewer.projects]\napi = "C:/x"\n',
                    encoding="utf-8")
    cfg = rc.load(path)
    assert (cfg["server"], cfg["fetch"], cfg["missing_commits"]) == ("personal", False, "yellow")
    assert cfg["conclave_url"] == "http://rechner.lan:8000"            # in Personal wie bisher nicht geprueft


@pytest.mark.parametrize("change,message", [
    ({"server_url": "http://board.intern"}, "nur https"),
    ({"server_url": "https://user:pw@board.intern"}, "ohne Anmeldedaten"),
    ({"server": "firma"}, "server: einer von"),
    ({"ca_bundle": "fehlt.pem"}, "gibt es nicht"),
    ({"ca_bundle": ""}, "ca_bundle fehlt"),                             # Review V2: Pflicht im Team
    ({"reviewer_token_credential": "X"}, "nicht beides"),
    ({"conclave_url": "https://a"}, "server_url oder conclave_url"),
    ({"missing_commits": "orange"}, "missing_commits"),
    ({"fetch": "ja"}, "fetch: true oder false"),
])
def test_team_settings_errors_are_clear(tmp_path, tls, repos, change, message):
    path = _settings(tmp_path, tls, repos.checkout)
    text = path.read_text(encoding="utf-8")
    for key, value in change.items():
        line = next((ln for ln in text.splitlines() if ln.startswith(f"{key} =")), None)
        new = f"{key} = {json.dumps(value)}"
        text = text.replace(line, new) if line else text.replace("[reviewer]\n", f"[reviewer]\n{new}\n", 1)
    path.write_text(text, encoding="utf-8")
    with pytest.raises(rc.ConfigError, match=message):
        rc.load(path)


def test_team_needs_a_token_source(tmp_path, tls, repos):
    path = _settings(tmp_path, tls, repos.checkout)
    path.write_text(path.read_text(encoding="utf-8").replace('reviewer_token_file = "secrets/reviewer.token"\n', ""),
                    encoding="utf-8")
    with pytest.raises(rc.ConfigError, match="reviewer_token_credential oder reviewer_token_file"):
        rc.load(path)


@pytest.mark.parametrize("url,ok", [("https://board.intern", True), ("https://board.intern:8443/", True),
                                    ("http://127.0.0.1:8000", True), ("http://localhost:1", True),
                                    ("http://board.intern", False), ("ftp://board.intern", False),
                                    ("https://board.intern/?x=1", False), ("board.intern", False)])
def test_server_address(url, ok):
    if ok:
        assert transport.check_url(url) == url.rstrip("/")
    else:
        with pytest.raises(transport.TransportError):
            transport.check_url(url)


# ── MCP-Server des Teams: Umgebung und Tool-Namen ────────────────────────

def test_team_mcp_server_gets_url_ca_and_token_file_but_never_the_token(tmp_path, tls, repos):
    cfg = rc.load(_settings(tmp_path, tls, repos.checkout))
    token_file = Path(cfg["reviewer_token_file"])
    board = command.mcp_servers(cfg, [str(repos.checkout)], token_file)["mcpServers"]["conclave"]
    assert board["command"] == "conclave-board-mcp" and board["args"] == ["--reviewer"]
    assert board["env"] == {"CONCLAVE_BOARD_URL": tls.url, "CONCLAVE_BOARD_MCP_ROLE": "reviewer",
                            "CONCLAVE_BOARD_TOKEN_FILE": str(token_file), "CONCLAVE_BOARD_CA_BUNDLE": tls.ca}
    assert REVIEWER not in json.dumps(board)


def test_allowed_tool_names_match_the_board_tools_of_the_core():
    """A4: conclave-mcp --reviewer und conclave-board-mcp --reviewer bieten dieselben drei Tools (aus
    conclave_board.tools); der Servername in der MCP-Konfiguration ist in beiden Faellen "conclave"."""
    from conclave_board.tools import BoardTools
    allowed = command.BOARDS["conclave"]["allowed"]
    assert allowed == ["mcp__conclave__conclave_board_get", "mcp__conclave__conclave_board_list",
                       "mcp__conclave__conclave_board_review"]
    methods = {"conclave_board_get": "get", "conclave_board_list": "list", "conclave_board_review": "review"}
    assert all(callable(getattr(BoardTools, methods[name.split("__")[-1]])) for name in allowed)
    assert not set(allowed) & set(command.BOARDS["conclave"]["denied"])


# ── https mit eigener CA, ohne Proxy, ohne Umleitung ─────────────────────

def _reviewer(tmp_path, cfg) -> Reviewer:
    return Reviewer(cfg, Path(cfg.get("data_dir") or tmp_path / "data"), prompt="P {get} {comment} {board}")


def test_reviewer_talks_to_the_team_server_over_tls_with_its_ca_and_sends_a_heartbeat(tmp_path, tls, repos,
                                                                                     monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")            # gilt nicht (R12)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    rv = _reviewer(tmp_path, rc.load(_settings(tmp_path, tls, repos.checkout)))
    assert isinstance(rv.changes(), int)
    assert rv.fetch_tasks() == {}
    rv.send_heartbeat()
    status = tls.call("GET", "/board/v1/reviewer")
    assert status["state"] == "active" and status["version"]


def test_team_without_ca_bundle_is_refused_even_with_ssl_cert_file(tmp_path, tls, repos, monkeypatch):
    """Review V2: Ohne ca_bundle gaelten SSL_CERT_FILE/SSL_CERT_DIR; im Team-Modus startet er so nicht."""
    monkeypatch.setenv("SSL_CERT_FILE", tls.ca)
    path = _settings(tmp_path, tls, repos.checkout)
    path.write_text("\n".join(ln for ln in path.read_text(encoding="utf-8").splitlines()
                              if not ln.startswith("ca_bundle")) + "\n", encoding="utf-8")
    with pytest.raises(rc.ConfigError, match="ca_bundle fehlt"):
        rc.load(path)


def test_other_ca_or_system_store_is_refused_even_with_ssl_cert_file(tmp_path, tls, repos, monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", tls.ca)                        # gilt nicht neben ca_bundle
    cfg = rc.load(_settings(tmp_path, tls, repos.checkout))
    cfg["ca_bundle"] = tls.other_ca
    with pytest.raises(urllib.error.URLError, match="CERTIFICATE_VERIFY_FAILED"):
        _reviewer(tmp_path, cfg).changes()
    monkeypatch.delenv("SSL_CERT_FILE")
    cfg["ca_bundle"] = None                                            # Systemspeicher kennt die Test-CA nicht
    with pytest.raises(urllib.error.URLError, match="CERTIFICATE_VERIFY_FAILED"):
        _reviewer(tmp_path, cfg).changes()


def test_redirect_is_not_followed_so_the_token_stays_with_the_server(tmp_path):
    seen = []

    class Target(http.server.BaseHTTPRequestHandler):
        def do_GET(self):                                               # noqa: N802
            seen.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"changes": 1}')

        def log_message(self, *args):
            pass

    target = http.server.HTTPServer(("127.0.0.1", 0), Target)

    class Redirect(Target):
        def do_GET(self):                                               # noqa: N802
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{target.server_port}/board/v1/changes")
            self.end_headers()

    source = http.server.HTTPServer(("127.0.0.1", 0), Redirect)
    for srv in (target, source):
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        token = tmp_path / "t"
        token.write_text(REVIEWER, encoding="utf-8")
        rv = Reviewer({"conclave_url": f"http://127.0.0.1:{source.server_port}", "reviewer_token_file": str(token)},
                      tmp_path / "data")
        with pytest.raises(urllib.error.HTTPError) as e:
            rv.changes()
        assert e.value.code == 302 and seen == []
    finally:
        target.shutdown()
        source.shutdown()


# ── git fetch und fehlende Commits ───────────────────────────────────────

def _ticket(tls, comment):
    tls.call("POST", "/board/v1/tasks", body={"project": "api", "title": "T"})
    tls.call("PATCH", "/board/v1/projects/api/tasks/1", body={"status": "review"})
    tls.call("POST", "/board/v1/projects/api/tasks/1/comments", AGENT, {"body": comment})
    return {"project": "api", "title": "T", "status": "review", "human": False, "review_state": "none"}


def test_commit_pushed_after_the_checkout_is_fetched_and_reviewed(tmp_path, tls, repos, monkeypatch):
    rv = _reviewer(tmp_path, rc.load(_settings(tmp_path, tls, repos.checkout)))
    head = repos.push("zwei\n")                                         # nur im Git-Server, noch nicht im Checkout
    task = _ticket(tls, f"**Branch:** `feature` · **Commit:** `{head[:7]}`")
    seen = {}

    def fake_claude(key, cmd, cwd):
        seen["content"] = (Path(cwd) / "a.txt").read_text(encoding="utf-8")
        seen["mcp"] = json.loads(rv.mcp_config.read_text(encoding="utf-8"))
        tls.call("POST", "/board/v1/projects/api/tasks/1/review", REVIEWER,
                 {"state": "passed", "comment": "Urteil: gruen", "blocking": 0, "suggestions": 0})
        return "done"

    monkeypatch.setattr(rv, "run_claude", fake_claude)
    rv.prepare()
    rv.run_review(task, "api#1", str(repos.checkout), dry_run=False)
    assert seen["content"] == "zwei\n"
    assert seen["mcp"]["mcpServers"]["conclave"]["env"]["CONCLAVE_BOARD_URL"] == tls.url
    assert tls.call("GET", "/board/v1/projects/api/tasks/1")["review"]["state"] == "passed"


def test_commit_missing_on_the_git_server_is_red_without_claude(tmp_path, tls, repos, monkeypatch):
    rv = _reviewer(tmp_path, rc.load(_settings(tmp_path, tls, repos.checkout)))
    task = _ticket(tls, "**Branch:** `feature` · **Commit:** `abcdef1` (nur lokal, nicht gepusht)")
    monkeypatch.setattr(rv, "run_claude", lambda *a: pytest.fail("claude darf nicht starten"))
    rv.prepare()
    rv.run_review(task, "api#1", str(repos.checkout), dry_run=False)
    detail = tls.call("GET", "/board/v1/projects/api/tasks/1")
    assert detail["review"]["state"] == "failed" and detail["review"]["blocking"] == 1
    assert detail["status"] == "todo"                                    # rot: zurueck zur Nacharbeit
    last = detail["comments"][-1]
    assert last["origin"] == "reviewer" and "Commits nicht im Git-Server: `abcdef1`" in last["body"]
    for line in ("Urteil: rot", "Geprüft:", "Blockierend:", "Vorschläge:", "Erledigt aus dem letzten Review:",
                 "Nicht geprüft:", "nicht von Laszlo freigegeben"):                 # Review V4: festes Format
        assert line in last["body"], line


def test_only_mentioned_old_commit_is_a_note_for_claude_not_red(tmp_path, tls, repos, monkeypatch):
    """Review V1: Ein nur erwaehnter Commit (etwa vor einem Rebase) fehlt; der zu pruefende ist da."""
    rv = _reviewer(tmp_path, rc.load(_settings(tmp_path, tls, repos.checkout)))
    head = repos.push("zwei\n")
    task = _ticket(tls, f"**Repo:** `feature` @ `{head[:7]}` · vorher `1234567` (vor dem Rebase)")
    seen = {}

    def fake_claude(key, cmd, cwd):
        seen["ask"] = cmd[2]
        tls.call("POST", "/board/v1/projects/api/tasks/1/review", REVIEWER,
                 {"state": "passed", "comment": "Urteil: gruen", "blocking": 0, "suggestions": 0})
        return "done"

    monkeypatch.setattr(rv, "run_claude", fake_claude)
    rv.prepare()
    rv.run_review(task, "api#1", str(repos.checkout), dry_run=False)
    assert "`1234567`" in seen["ask"]                                    # als Hinweis an claude
    assert tls.call("GET", "/board/v1/projects/api/tasks/1")["review"]["state"] == "passed"


def test_missing_commit_to_check_is_red_even_if_another_named_one_exists(tmp_path, tls, repos, monkeypatch):
    """Review V1: Der zu pruefende Commit (`branch` @ `hash`) fehlt, ein anderer genannter ist da: rot."""
    rv = _reviewer(tmp_path, rc.load(_settings(tmp_path, tls, repos.checkout)))
    old = _git(repos.checkout, "rev-parse", "HEAD")
    task = _ticket(tls, f"**Repo:** `feature` @ `abcdef1` · Basis `{old[:7]}`")
    monkeypatch.setattr(rv, "run_claude", lambda *a: pytest.fail("claude darf nicht starten"))
    rv.prepare()
    rv.run_review(task, "api#1", str(repos.checkout), dry_run=False)
    detail = tls.call("GET", "/board/v1/projects/api/tasks/1")
    assert detail["review"]["state"] == "failed"
    assert "Commits nicht im Git-Server: `abcdef1`" in detail["comments"][-1]["body"]
    assert old[:7] not in detail["comments"][-1]["body"]


def test_token_file_left_by_a_killed_run_is_removed_on_start(tmp_path, tls, repos):
    """Review V3: nach einem harten Ende liegt mcp-reviewer.token noch im Datenordner."""
    rv = _reviewer(tmp_path, rc.load(_settings(tmp_path, tls, repos.checkout)))
    rv.data_dir.mkdir(parents=True)
    rv.mcp_token.write_text(REVIEWER, encoding="utf-8")
    rv.prepare()
    assert not rv.mcp_token.exists()


def test_personal_keeps_missing_commits_yellow_and_does_not_fetch(tmp_path, tls, repos, monkeypatch):
    cfg = rc.load(_settings(tmp_path, tls, repos.checkout, fetch=False, missing_commits="yellow"))
    rv = _reviewer(tmp_path, cfg)
    head = repos.push("zwei\n")
    task = _ticket(tls, f"**Branch:** `feature` · **Commit:** `{head[:7]}`")
    seen = {}

    def fake_claude(key, cmd, cwd):
        """Wie bisher in Personal: der Kopf des genannten Branches, der fehlende Commit nur als Hinweis (gelb)."""
        seen["ask"], seen["content"] = cmd[2], (Path(cwd) / "a.txt").read_text(encoding="utf-8")
        tls.call("POST", "/board/v1/projects/api/tasks/1/review", REVIEWER,
                 {"state": "rework", "comment": "Urteil: gelb", "blocking": 0, "suggestions": 1})
        return "done"

    monkeypatch.setattr(rv, "run_claude", fake_claude)
    rv.prepare()
    rv.run_review(task, "api#1", str(repos.checkout), dry_run=False)
    assert seen["content"] == "eins\n"                                 # kein fetch: der alte Stand
    assert f"In keinem lokalen Repo gefunden (dazu nicht pruefbar, Urteil hoechstens gelb): `{head[:7]}`" in seen["ask"]


# ── Token aus der Anmeldeinformationsverwaltung ──────────────────────────

def test_token_from_the_credential_store_reaches_the_mcp_server_only_during_a_review(tmp_path, tls, repos,
                                                                                    monkeypatch):
    path = _settings(tmp_path, tls, repos.checkout)
    path.write_text(path.read_text(encoding="utf-8").replace(
        'reviewer_token_file = "secrets/reviewer.token"', 'reviewer_token_credential = "ConclaveReviewerTest"'),
        encoding="utf-8")
    (tmp_path / "secrets" / "reviewer.token").unlink()
    asked = []
    monkeypatch.setattr(credentials, "read_generic", lambda target: (asked.append(target), REVIEWER)[1])
    cfg = rc.load(path)
    assert "reviewer_token_file" not in cfg
    rv = _reviewer(tmp_path, cfg)
    head = repos.push("zwei\n")
    task = _ticket(tls, f"**Branch:** `feature` · **Commit:** `{head[:7]}`")
    seen = {}

    def fake_claude(key, cmd, cwd):
        env = json.loads(rv.mcp_config.read_text(encoding="utf-8"))["mcpServers"]["conclave"]["env"]
        seen["file"] = Path(env["CONCLAVE_BOARD_TOKEN_FILE"])
        seen["token"] = seen["file"].read_text(encoding="utf-8")
        tls.call("POST", "/board/v1/projects/api/tasks/1/review", REVIEWER,
                 {"state": "passed", "comment": "Urteil: gruen", "blocking": 0, "suggestions": 0})
        return "done"

    monkeypatch.setattr(rv, "run_claude", fake_claude)
    rv.prepare()
    rv.run_review(task, "api#1", str(repos.checkout), dry_run=False)
    assert asked and set(asked) == {"ConclaveReviewerTest"}
    assert seen["token"] == REVIEWER and seen["file"].parent == rv.data_dir
    assert not seen["file"].exists()                                    # nach dem Review wieder weg
    assert REVIEWER not in rv.mcp_config.read_text(encoding="utf-8")


@pytest.mark.skipif(os.name != "nt" or not os.environ.get("CI"), reason="schreibt in die Anmeldeinformationsverwaltung")
def test_windows_credential_store_roundtrip():
    target = f"conclave-reviewer-test-{uuid.uuid4().hex[:8]}"
    subprocess.run(["cmdkey", f"/generic:{target}", "/user:reviewer", f"/pass:{REVIEWER}"], check=True,
                   capture_output=True)
    try:
        assert credentials.read_generic(target) == REVIEWER
    finally:
        subprocess.run(["cmdkey", f"/delete:{target}"], capture_output=True)
    with pytest.raises(credentials.CredentialError, match="nicht gefunden"):
        credentials.read_generic(target)


# ── --settings ───────────────────────────────────────────────────────────

def test_status_with_settings_uses_its_data_dir(tmp_path, tls, repos, capsys):
    path = _settings(tmp_path, tls, repos.checkout)
    assert cli_main(["status", "--settings", str(path), "--json"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert Path(info["data_dir"]) == tmp_path / "reviewer-daten"
