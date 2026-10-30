"""Fallback-Keys fuer Agents: aus Konfiguration bzw. Umgebung, nur fuer den Host ihres Presets (R3).

Ein Key aus ``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``, ``DEEPSEEK_API_KEY`` usw. gehoert
zum Anbieter dieses Presets. Er wird nur verwendet, wenn die Adresse des Agents
denselben Host hat wie die Preset-Adresse (oder der Agent den nativen Adapter ohne
eigene Adresse nutzt). Fuer jede andere Adresse muss der Key beim Agent eingetragen sein.
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


def effective_url(agent) -> str:
    """Adresse, an die der Agent sendet; leer = nativer Adapter mit der Standardadresse des SDK."""
    if agent.api_url:
        return agent.api_url
    return _preset(agent.preset).get("api_url", "") if agent.preset else ""


def destination_host(agent) -> str:
    """Host, der Keys dieses Agents erhaelt; beim nativen Adapter der Host des Provider-Presets."""
    return _host(effective_url(agent) or _preset(agent.provider).get("api_url", ""))


def _key_and_source(agent, provider_keys: dict) -> tuple[str, str]:
    """(Key, Preset, zu dem der Key gehoert)."""
    key = provider_keys.get(agent.provider) or ""
    if key:
        return key, agent.provider
    source = agent.preset or agent.provider
    key_env = _preset(source).get("api_key_env", "")
    return (env_secret(key_env) if key_env else ""), source


def key_may_be_sent(agent, source: str) -> bool:
    url = effective_url(agent)
    if not url:
        return True
    expected = _preset(source).get("api_url", "")
    return bool(expected) and _host(url) == _host(expected)


def fallback_key(agent, provider_keys: dict | None = None) -> str:
    """Key aus Konfiguration bzw. Umgebung fuer diesen Agent, oder leer."""
    key, source = _key_and_source(agent, provider_keys or {})
    if not key:
        return ""
    if not key_may_be_sent(agent, source):
        logger.warning("Agent %s: Key aus der Umgebung nicht verwendet, weil die Adresse nicht zum "
                       "Preset %s gehoert; Key beim Agent eintragen.", agent.id, source)
        return ""
    return key
