"""Fallback-Keys fuer Agents: aus Konfiguration bzw. Umgebung, nur fuer den Host ihres Presets (R3).

Ein Key aus ``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``, ``DEEPSEEK_API_KEY`` usw. gehoert
zum Anbieter dieses Presets. Er wird nur verwendet, wenn die Adresse des Agents
denselben Host und dasselbe Schema hat wie die Preset-Adresse (oder der Agent den
nativen Adapter ohne eigene Adresse nutzt). Fuer jede andere Adresse muss der Key beim
Agent eingetragen sein.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from conclave.infrastructure.log import get_logger
from conclave.runtime.env import env_secret

logger = get_logger("cli.provider_keys")


def _preset(name: str) -> dict:
    if not name:
        return {}
    try:
        from conclave.infrastructure.universal.presets import get_preset
    except ImportError:
        return {}
    return get_preset(name) or {}


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _origin(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.scheme.lower(), (parts.hostname or "").lower()


def effective_url(agent) -> str:
    """Adresse, an die der Agent sendet; leer = nativer Adapter mit der Standardadresse des SDK."""
    if agent.api_url:
        return agent.api_url
    return _preset(agent.preset).get("api_url", "") if agent.preset else ""


def destination(agent) -> tuple[str, str]:
    """(Schema, Host), die Keys dieses Agents erhalten; beim nativen Adapter die des Provider-Presets."""
    return _origin(effective_url(agent) or _preset(agent.provider).get("api_url", ""))


def key_may_be_sent(agent, source: str) -> bool:
    """Darf ein Key, der zum Preset ``source`` gehoert, an die Adresse dieses Agents gehen?"""
    url = effective_url(agent)
    if not url:
        return True
    expected = _preset(source).get("api_url", "")
    return bool(expected) and _origin(url) == _origin(expected)


def _candidates(agent, provider_keys: dict):
    """(Key, Preset, zu dem er gehoert): zuerst der Provider-Key, dann der Key des Presets."""
    if provider_keys.get(agent.provider):
        yield provider_keys[agent.provider], agent.provider
    source = agent.preset or agent.provider
    key_env = _preset(source).get("api_key_env", "")
    if key_env:
        yield env_secret(key_env), source


def fallback_key(agent, provider_keys: dict | None = None, *, log: bool = True) -> str:
    """Key aus Konfiguration bzw. Umgebung fuer diesen Agent, oder leer.

    ``log=False`` fuer reine Anzeigen (z. B. die Agent-Liste), damit nicht jede Liste
    eine Warnung erzeugt.
    """
    rejected = []
    for key, source in _candidates(agent, provider_keys or {}):
        if not key:
            continue
        if key_may_be_sent(agent, source):
            return key
        rejected.append(source)
    if rejected and log:
        logger.warning("Agent %s: Key aus der Umgebung nicht verwendet, weil die Adresse nicht zum "
                       "Preset %s gehoert; Key beim Agent eintragen.", agent.id, ", ".join(rejected))
    return ""
