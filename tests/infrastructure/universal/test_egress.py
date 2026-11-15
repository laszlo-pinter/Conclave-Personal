"""R12 (conclave#47): Ausgehende Verbindungen zu Providern.

- Der Name wird bei jeder Anfrage aufgeloest, jede Adresse geprueft und mit der
  festgelegten IP verbunden (Host-Header und SNI bleiben); fail-closed.
- Gesperrt ist alles, was nicht global ist, und Multicast; eingebettete IPv4
  (mapped, 6to4, NAT64) wird ausgepackt.
- https fuer entfernte Provider; lokal (Ollama) nur auf dem konfigurierten Port.
"""

import socket

import httpx
import pytest

from conclave.domain.errors import ProviderTargetBlocked
from conclave.infrastructure.universal import egress
from conclave.infrastructure.universal.adapter import UniversalAdapter, _validate_url


def _answers(*addresses):
    return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 443))
            for a in addresses]


class Resolver:
    """Liefert je Aufruf die naechste Antwort (wie ein DNS, der umschaltet)."""

    def __init__(self, *rounds):
        self.rounds = list(rounds)
        self.calls = 0

    def __call__(self, host, port, *args, **kwargs):
        self.calls += 1
        answer = self.rounds.pop(0) if len(self.rounds) > 1 else self.rounds[0]
        if isinstance(answer, Exception):
            raise answer
        return _answers(*answer)


class Recorder:
    def __init__(self):
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return httpx.Response(200, json={"ok": True})


def _client(resolver, recorder, **kwargs):
    transport = egress.GuardedTransport("test", inner=httpx.MockTransport(recorder), resolve=resolver, **kwargs)
    return httpx.Client(transport=transport)


def test_connects_to_the_checked_address_and_keeps_host_and_sni():
    recorder = Recorder()
    with _client(Resolver(["93.184.216.34"]), recorder) as c:
        assert c.post("https://api.example.com/v1/chat", json={}).status_code == 200
    [request] = recorder.requests
    assert request.url.host == "93.184.216.34"
    assert request.headers["host"] == "api.example.com"
    assert request.extensions["sni_hostname"] == "api.example.com"


def test_rebinding_to_loopback_is_blocked():
    recorder = Recorder()
    resolver = Resolver(["93.184.216.34"], ["127.0.0.1"])
    with _client(resolver, recorder) as c:
        c.post("https://api.example.com/v1/chat", json={})
        with pytest.raises(ProviderTargetBlocked):
            c.post("https://api.example.com/v1/chat", json={})
    assert resolver.calls == 2 and len(recorder.requests) == 1            # je Anfrage neu aufgeloest


def test_unresolvable_name_is_blocked():
    recorder = Recorder()
    with _client(Resolver(socket.gaierror("kein Name")), recorder) as c, pytest.raises(ProviderTargetBlocked):
        c.post("https://api.example.com/v1/chat", json={})
    assert recorder.requests == []


@pytest.mark.parametrize("address", [
    "100.64.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "127.0.0.1", "0.0.0.0", "224.0.0.1",
    "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "2002:7f00:1::", "64:ff9b::a00:1", "ff02::1",
])
def test_non_public_addresses_are_blocked(address):
    recorder = Recorder()
    with _client(Resolver([address]), recorder) as c, pytest.raises(ProviderTargetBlocked):
        c.post("https://api.example.com/v1/chat", json={})
    assert recorder.requests == []


def test_one_private_answer_among_public_ones_blocks():
    with _client(Resolver(["93.184.216.34", "10.0.0.5"]), Recorder()) as c, pytest.raises(ProviderTargetBlocked):
        c.post("https://api.example.com/v1/chat", json={})


def test_ip_literal_is_checked_without_resolving():
    resolver = Resolver(["93.184.216.34"])
    with _client(resolver, Recorder()) as c, pytest.raises(ProviderTargetBlocked):
        c.post("https://100.64.0.1/v1/chat", json={})
    assert resolver.calls == 0


def test_local_provider_only_on_its_port():
    recorder = Recorder()
    resolver = Resolver(["127.0.0.1"])
    with _client(resolver, recorder, local_port=11434) as c:
        assert c.post("http://localhost:11434/api/chat", json={}).status_code == 200
        with pytest.raises(ProviderTargetBlocked):
            c.post("http://localhost:6379/", json={})
    assert len(recorder.requests) == 1


def test_blocked_message_names_no_address():
    with _client(Resolver(["10.0.0.5"]), Recorder()) as c, pytest.raises(ProviderTargetBlocked) as e:
        c.post("https://api.example.com/v1/chat?key=geheim", json={})
    assert "10.0.0.5" not in str(e.value) and "geheim" not in str(e.value) and "://" not in str(e.value)


# ── Pruefung beim Anlegen des Adapters ─────────────────────────────────────

@pytest.mark.parametrize("url", [
    "http://api.openai.com/v1/chat/completions",      # entfernt nur mit https
    "https://localhost:11434/api/chat",               # localhost nur fuer den lokalen Provider
    "https://10.0.0.5/v1",
    "https://100.64.0.1/v1",
    "ftp://api.example.com/v1",
])
def test_rejected_urls(url):
    with pytest.raises(ValueError):
        _validate_url(url)


def test_local_provider_url_needs_the_configured_port():
    _validate_url("http://localhost:11434/api/chat", local_port=11434)
    _validate_url("http://127.0.0.1:11434/api/chat", local_port=11434)
    with pytest.raises(ValueError):
        _validate_url("http://localhost:6379/", local_port=11434)


def test_ollama_port_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("CONCLAVE_OLLAMA_PORT", "12000")
    UniversalAdapter(api_url="http://localhost:12000/api/chat", provider_name="ollama")
    with pytest.raises(ValueError):
        UniversalAdapter(api_url="http://localhost:11434/api/chat", provider_name="ollama")


# ── Der Adapter nutzt den Transport ─────────────────────────────────────────

def _conversation():
    from datetime import UTC, datetime

    from conclave.domain.conversation import Conversation
    from conclave.domain.message import Message, MessageAuthorType
    conv = Conversation(id="c1", status="active", topic="t")
    conv.messages = [Message(id="m1", conversation_id="c1", author_type=MessageAuthorType.USER, author_id=None,
                             content="Hallo", sequence=1, created_at=datetime.now(UTC))]
    return conv


def _participant():
    from conclave.domain.participant import Participant, ParticipantType
    return Participant(id="p1", conversation_id="c1", participant_type=ParticipantType.MODEL, name="P")


@pytest.mark.parametrize("streaming", [False, True])
def test_adapter_requests_go_through_the_guard(monkeypatch, streaming):
    monkeypatch.setattr(egress.socket, "getaddrinfo", lambda *a, **k: _answers("127.0.0.1"))
    adapter = UniversalAdapter(api_url="https://api.example.com/v1/chat", api_key="sk-test", model="m")
    with pytest.raises(ProviderTargetBlocked):
        if streaming:
            list(adapter.stream(_conversation(), _participant()))
        else:
            adapter.complete(_conversation(), _participant())


# ── Vorhandene Agenten mit nicht mehr erlaubter URL ────────────────────────

def test_server_starts_with_an_agent_whose_url_is_no_longer_allowed(tmp_path):
    """Ein alter Agent mit http-URL bricht den Start nicht ab; der Aufruf meldet den Grund."""
    from conclave.cli.bootstrap import build_agent_service, build_registry, build_service
    from conclave.cli.config import ConclaveConfig
    from conclave.domain.agent import Agent

    config = ConclaveConfig(db_path=tmp_path / "t.db")
    service = build_service(config=config)
    agents = build_agent_service(config=config)
    agents.create_agent(Agent(id="alt", name="Alt", provider="custom", model="m",
                              api_url="http://llm.example.com/v1/chat/completions", api_key="sk-x"))
    agents.create_agent(Agent(id="neu", name="Neu", provider="custom", model="m",
                              api_url="https://llm.example.com/v1/chat/completions", api_key="sk-x"))
    registry = build_registry(service, agent_service=agents, config=config)
    assert "neu" in registry._adapters and "alt" not in registry._adapters
    with pytest.raises(ValueError, match="https"):
        registry.get_for("alt")
