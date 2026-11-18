"""T7 (conclave#75): Netzbetrieb der Board-App.

- ``X-Forwarded-For``/``-Proto`` nur vom konfigurierten Proxy; von jeder anderen Quelle ignoriert
- Sperre nach Fehlversuchen je IP vor der Anmeldung, Limit je Konto danach
- Rate-Limit je Token statt je Rolle und IP
"""

import pytest
from flask import Blueprint, jsonify, request

from conclave_board.api.app import create_board_app
from conclave_board.api.security import WindowCounter, parse_limit, parse_networks
from conclave_board.domain.principal import Principal
from conclave_board.infrastructure.auth import StaticKeyAuthService
from conclave_board.server import open_board

HUMAN, AGENT, REVIEWER = "cvh_mensch", "cva_agent", "cvr_reviewer"
PROXY = "10.0.0.5"


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _echo():
    bp = Blueprint("echo", __name__)

    @bp.get("/echo")
    def echo():
        return jsonify({"addr": request.remote_addr, "scheme": request.scheme,
                        "forwarded": request.headers.get("X-Forwarded-For")})
    return bp


def _app(tmp_path, auth=None, **options):
    board, _conn = open_board(db_path=tmp_path / "board.db", config_dir=tmp_path / "config")
    return create_board_app(board, auth or StaticKeyAuthService(HUMAN, AGENT, REVIEWER), blueprints=[_echo()],
                            **options)


def _get(client, path="/echo", peer="192.0.2.10", token=HUMAN, headers=None):
    return client.get(path, headers={**(_h(token) if token else {}), **(headers or {})},
                      environ_base={"REMOTE_ADDR": peer})


# ── Proxy ────────────────────────────────────────────────────────────────

def test_forwarded_headers_from_a_foreign_source_are_ignored(tmp_path):
    client = _app(tmp_path, trusted_proxies=PROXY).test_client()
    data = _get(client, peer="192.0.2.10", headers={"X-Forwarded-For": "198.51.100.7",
                                                     "X-Forwarded-Proto": "https"}).get_json()
    assert data == {"addr": "192.0.2.10", "scheme": "http", "forwarded": None}   # Header entfernt


def test_forwarded_headers_from_the_proxy_are_taken(tmp_path):
    client = _app(tmp_path, trusted_proxies=f"{PROXY}, 10.1.0.0/16").test_client()
    data = _get(client, peer=PROXY, headers={"X-Forwarded-For": "198.51.100.7, 10.1.2.3",
                                             "X-Forwarded-Proto": "https"}).get_json()
    # rechtester Eintrag, der kein Proxy ist; 10.1.2.3 ist selbst ein (zweiter) Proxy
    assert data == {"addr": "198.51.100.7", "scheme": "https", "forwarded": None}


def test_a_spoofed_left_entry_does_not_win(tmp_path):
    client = _app(tmp_path, trusted_proxies=PROXY).test_client()
    data = _get(client, peer=PROXY, headers={"X-Forwarded-For": "127.0.0.1, 198.51.100.7"}).get_json()
    assert data["addr"] == "198.51.100.7"


def test_without_proxy_configuration_nothing_is_forwarded(tmp_path):
    client = _app(tmp_path).test_client()
    data = _get(client, peer=PROXY, headers={"X-Forwarded-For": "198.51.100.7"}).get_json()
    assert data["addr"] == PROXY


def test_invalid_proxy_entry_is_refused(tmp_path):
    with pytest.raises(ValueError, match="Proxy-Eintrag"):
        _app(tmp_path, trusted_proxies="proxy.intern")


# ── Fehlversuche je IP ───────────────────────────────────────────────────

def test_failed_logins_block_the_address_before_login(tmp_path):
    client = _app(tmp_path, auth_failure_limit="3 per minute").test_client()
    for _ in range(3):
        assert _get(client, token="cvh_falsch").status_code == 401
    blocked = _get(client, token=HUMAN)                       # auch ein gueltiges Token: Adresse gesperrt
    assert blocked.status_code == 429 and blocked.get_json()["type"] == "RateLimitExceeded"
    assert int(blocked.headers["Retry-After"]) >= 1
    assert _get(client, peer="192.0.2.99", token=HUMAN).status_code == 200      # andere Adresse nicht


def test_failures_behind_the_proxy_count_per_client(tmp_path):
    client = _app(tmp_path, trusted_proxies=PROXY, auth_failure_limit="2 per minute").test_client()
    for _ in range(2):
        _get(client, peer=PROXY, token="cvh_falsch", headers={"X-Forwarded-For": "198.51.100.7"})
    assert _get(client, peer=PROXY, headers={"X-Forwarded-For": "198.51.100.7"}).status_code == 429
    assert _get(client, peer=PROXY, headers={"X-Forwarded-For": "198.51.100.8"}).status_code == 200


def test_spoofed_forwarded_for_does_not_dodge_the_block(tmp_path):
    client = _app(tmp_path, trusted_proxies=PROXY, auth_failure_limit="2 per minute").test_client()
    for n in range(2):
        _get(client, peer="192.0.2.10", token="cvh_falsch", headers={"X-Forwarded-For": f"198.51.100.{n}"})
    assert _get(client, peer="192.0.2.10", headers={"X-Forwarded-For": "198.51.100.9"}).status_code == 429


# ── Je Konto und je Token ────────────────────────────────────────────────

class _Accounts:
    """Zwei Tokens desselben Kontos, eines eines anderen."""

    PEOPLE = {"cvh_anna1": "anna", "cvh_anna2": "anna", "cvh_ben": "ben"}

    def authenticate(self, token):
        actor = self.PEOPLE.get(token or "")
        return Principal("human", actor_id=actor) if actor else None


def test_account_limit_counts_all_tokens_of_the_account(tmp_path):
    client = _app(tmp_path, auth=_Accounts(), account_rate_limit="3 per minute").test_client()
    codes = [_get(client, token=t).status_code for t in ("cvh_anna1", "cvh_anna2", "cvh_anna1", "cvh_anna2")]
    assert codes == [200, 200, 200, 429]
    assert _get(client, token="cvh_ben").status_code == 200


def test_rate_limit_is_per_token(tmp_path):
    client = _app(tmp_path, auth=_Accounts(), rate_limit="2 per minute").test_client()
    assert [_get(client, token="cvh_anna1").status_code for _ in range(3)] == [200, 200, 429]
    assert _get(client, token="cvh_anna2").status_code == 200       # gleiche IP, anderes Token


# ── Bausteine ────────────────────────────────────────────────────────────

def test_parse_limit_and_networks():
    assert parse_limit("10 per minute") == (10, 60) and parse_limit("5/second") == (5, 1)
    assert parse_limit("off") is None and parse_limit("") is None
    with pytest.raises(ValueError):
        parse_limit("viele")
    assert [str(n) for n in parse_networks("10.0.0.5, 10.1.0.0/16, ::1")] == ["10.0.0.5/32", "10.1.0.0/16", "::1/128"]


def test_window_counter_resets_with_the_next_window():
    now = [0.0]
    counter = WindowCounter((2, 60), clock=lambda: now[0])
    assert [counter.hit("a") for _ in range(3)] == [False, False, True] and counter.over("a")
    now[0] = 61
    assert not counter.over("a") and counter.hit("a") is False


# ── Review T7 ────────────────────────────────────────────────────────────

class _CountingAuth:
    def __init__(self):
        self.calls = 0

    def authenticate(self, token):
        self.calls += 1
        return Principal("human", actor_id="anna") if token == HUMAN else None


def test_a_blocked_address_does_not_trigger_token_checks(tmp_path):
    """V1: nach der Sperre keine Token-Pruefung mehr (kein DB-Zugriff, kein Audit)."""
    auth = _CountingAuth()
    client = _app(tmp_path, auth=auth, auth_failure_limit="2 per minute").test_client()
    for _ in range(2):
        _get(client, token="cvh_falsch")
    calls = auth.calls
    for token in ("cvh_falsch", HUMAN):
        assert _get(client, token=token).status_code == 429
    assert auth.calls == calls


def test_proxy_only_refuses_direct_connections(tmp_path):
    """V3: im Netzbetrieb nur ueber den Proxy (oder von Loopback), nie direkt per HTTP."""
    client = _app(tmp_path, trusted_proxies=PROXY, proxy_only=True).test_client()
    direct = _get(client, peer="10.0.0.99")
    assert direct.status_code == 403 and direct.get_json()["type"] == "ProxyRequired"
    assert _get(client, peer=PROXY, headers={"X-Forwarded-For": "198.51.100.7"}).status_code == 200
    assert _get(client, peer="127.0.0.1").status_code == 200
    with pytest.raises(ValueError, match="trusted_proxies"):
        _app(tmp_path, proxy_only=True)


def test_window_counter_memory_stays_bounded(monkeypatch):
    """V5: auch wenn alle Schluessel im aktuellen Fenster liegen."""
    monkeypatch.setattr(WindowCounter, "MAX_KEYS", 50)
    counter = WindowCounter((5, 60), clock=lambda: 0.0)
    for n in range(500):
        counter.hit(f"k{n}")
    assert len(counter._windows) <= 50 and counter.over("k499") is False and "k499" in counter._windows
