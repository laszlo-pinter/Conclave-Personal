# src/conclave/infrastructure/universal/adapter.py
"""UniversalAdapter — Ein Adapter, alle Provider.

Konfiguration statt Code. Jeder LLM-Provider der HTTP + JSON spricht
kann ueber diesen Adapter angebunden werden.

Provider-spezifische Logik (Headers, Body-Format, Response-Extraktion)
ist in ProviderProfiles gekapselt (siehe profiles.py).

Architektur:
    Agent-Config (api_url, model, message_format, ...)
          │
          ▼
    UniversalAdapter
          │
          ├── profile.build_url() → URL + Query-Params
          ├── profile.build_headers() → Auth-Headers
          ├── _format_messages() → Provider-Messages
          ├── profile.build_body() → Request-JSON
          ├── httpx.post(url, json=body, headers=headers)
          ├── profile.extract_response() → Antworttext
          └── _extract_usage() → TokenUsage
"""

from __future__ import annotations

import os
import re
import socket
from collections.abc import Iterator
from typing import Any

import httpx

from conclave.domain.conversation import Conversation
from conclave.domain.message import MessageAuthorType
from conclave.domain.model_response import TokenUsage
from conclave.domain.participant import Participant
from conclave.infrastructure.log import get_logger
from conclave.infrastructure.universal.profiles import (
    ProviderProfile,
    get_profile,
    _extract_path,
)

logger = get_logger("infrastructure.universal")


# ── Message Formatting ────────────────────────────────────────────────────

MAX_MESSAGES = int(os.environ.get("CONCLAVE_MAX_MESSAGES", "25"))


def _smart_truncate(messages: list, max_messages: int) -> list:
    """Behaelt erste User-Message (Kontext-Anker) + letzte N-1 Messages.

    Wenn die Conversation laenger ist als max_messages, wird die erste
    User-Message immer beibehalten (sie enthaelt oft die Aufgabenstellung),
    gefolgt von den letzten max_messages-1 Messages.
    """
    if len(messages) <= max_messages:
        return messages
    # Erste User-Message finden
    first_user = None
    for msg in messages:
        if getattr(msg, "author_type", None) == MessageAuthorType.USER:
            first_user = msg
            break
    tail = messages[-(max_messages - 1):] if first_user else messages[-max_messages:]
    if first_user and first_user not in tail:
        return [first_user] + list(tail)
    return list(tail)


def _format_messages(
    conversation: Conversation,
    message_format: str = "standard",
    current_participant_id: str = "",
) -> list[dict]:
    """Wandelt Conclave-Messages ins Provider-Format.

    Formate:
        "standard" — OpenAI/Mistral/Ollama: {role: "user"/"assistant", content: "..."}
        "gemini"   — Google: {role: "user"/"model", parts: [{text: "..."}]}

    In Multi-Agent-Gespraechen: Nur eigene Messages werden als assistant/model
    gesendet. Messages anderer Agents werden als user-Messages mit [Name]-Prefix
    dargestellt, damit die API korrekt alterniert.

    Nur die letzten MAX_MESSAGES werden gesendet, um Rate Limits zu schonen.
    Der Projektkontext wird ueber Workspace-Hints im System-Prompt erhalten.
    """
    messages = _smart_truncate(conversation.messages, MAX_MESSAGES)
    result = []
    for msg in messages:
        author_id = getattr(msg, "author_id", None) or ""
        is_self = (msg.author_type != MessageAuthorType.USER
                   and author_id == current_participant_id)
        is_user = msg.author_type == MessageAuthorType.USER

        if message_format == "gemini":
            if is_self:
                role = "model"
                text = msg.content
            else:
                role = "user"
                text = f"[{author_id}] {msg.content}" if not is_user else msg.content
            if result and result[-1]["role"] == role:
                result[-1]["parts"].append({"text": text})
            else:
                result.append({"role": role, "parts": [{"text": text}]})
        else:
            if is_self:
                role = "assistant"
                text = msg.content
            else:
                role = "user"
                text = f"[{author_id}] {msg.content}" if not is_user else msg.content
            if result and result[-1]["role"] == role:
                result[-1]["content"] += f"\n\n{text}"
            else:
                result.append({"role": role, "content": text})
    return result


def _build_workspace_info() -> str:
    """Erstellt eine Workspace-Uebersicht fuer den System-Prompt.

    Die @read/@save/@workspace-Faehigkeiten werden immer erklaert. Das
    automatische Auflisten ALLER Workspace-Dateien ist standardmaessig AUS:
    es blaeht jeden System-Prompt auf (rekursiver os.walk ueber den ganzen
    Baum) und verleitet Agenten dazu, bei vagen Aufgaben proaktiv fremde
    Dateien wie 'Projektziel.md' zu lesen (Kontext-Leak). Gezielten Kontext
    liefert stattdessen 'context_files:' in den Chat-Regeln. Wer das alte
    Voll-Listing will, setzt CONCLAVE_WORKSPACE_AUTOLIST=1.
    """
    workspace = os.environ.get("CONCLAVE_WORKSPACE", "/workspace")
    if not os.path.isdir(workspace):
        return ""
    info = (
        "Du hast Zugriff auf einen gemeinsamen Workspace.\n\n"
        "LESEN: Der Benutzer kann Dateien referenzieren mit @workspace/dateiname "
        "und der Inhalt wird automatisch in die Nachricht eingefuegt.\n"
        "Du selbst kannst eine konkrete, dir bekannte Datei lesen mit "
        "@read(pfad/zur/datei.py) in deiner Antwort. Lies nur Dateien, nach "
        "denen ausdruecklich gefragt wurde - erkunde nicht von dir aus den Workspace.\n\n"
        "SCHREIBEN: Du kannst Dateien im Workspace speichern. Verwende dazu:\n"
        "@save(dateiname.md)\n"
        "Hier steht der Dateiinhalt...\n"
        "@endsave\n"
        "Die Datei wird automatisch unter @workspace/output/dateiname.md gespeichert."
    )
    if not os.environ.get("CONCLAVE_WORKSPACE_AUTOLIST"):
        return info
    try:
        files = []
        for root, dirs, filenames in os.walk(workspace):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in filenames:
                if f.startswith("."):
                    continue
                rel = os.path.relpath(os.path.join(root, f), workspace)
                files.append(rel.replace("\\", "/"))
        if not files:
            return info
        listing = "\n".join(f"  - @workspace/{f}" for f in sorted(files))
        return info + f"\n\nVerfuegbare Dateien:\n{listing}"
    except Exception:
        return info


def _load_context_files(conversation: Conversation) -> str:
    """Laedt context_files aus der Conversation und gibt deren Inhalt zurueck.

    context_files ist eine kommaseparierte Liste von Workspace-Pfaden
    im rules-Feld mit dem Prefix 'context_files:'.
    Format: Erste Zeile von rules = 'context_files: datei1.md, datei2.md'
    """
    rules = getattr(conversation, "rules", "") or ""
    workspace = os.environ.get("CONCLAVE_WORKSPACE", "/workspace")
    parts = []
    for line in rules.split("\n"):
        line = line.strip()
        if not line.lower().startswith("context_files:"):
            continue
        file_list = line[len("context_files:"):].strip()
        for filepath in file_list.split(","):
            filepath = filepath.strip()
            if not filepath:
                continue
            safe = os.path.normpath(filepath)
            if safe.startswith(".."):
                continue
            full = os.path.join(workspace, safe)
            if os.path.isfile(full):
                try:
                    with open(full, "r", encoding="utf-8") as f:
                        content = f.read()
                    parts.append(f"--- Kontext: {filepath} ---\n{content}")
                except Exception:
                    pass
    return "\n\n".join(parts) if parts else ""


def _build_system_prompt(
    system_prompt: str | None, conversation: Conversation
) -> str | None:
    """Baut den kombinierten System-Prompt aus Agent-Prompt, Regeln, Kontext-Dateien und Workspace."""
    parts = []
    if system_prompt:
        parts.append(system_prompt)
    # Kontext-Dateien als statischer Kontext (spart Tokens vs. Chat-Messages)
    context = _load_context_files(conversation)
    if context:
        parts.append(context)
    # Chat-Regeln (ohne context_files-Zeilen)
    rules = getattr(conversation, "rules", "") or ""
    clean_rules = "\n".join(
        line for line in rules.split("\n")
        if not line.strip().lower().startswith("context_files:")
    ).strip()
    if clean_rules:
        parts.append(f"Chat-Regeln:\n{clean_rules}")
    workspace_info = _build_workspace_info()
    if workspace_info:
        parts.append(workspace_info)
    return "\n\n".join(parts) if parts else None


def _is_private_target(host: str) -> bool:
    """Prueft Host/IP auf SSRF-gefaehrdete interne Zielbereiche."""
    import ipaddress

    def _blocked(value: str) -> bool:
        ip = ipaddress.ip_address(value.split("%", 1)[0])
        return ip.is_private or ip.is_reserved or ip.is_loopback or ip.is_link_local

    try:
        return _blocked(host)
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return False
    for info in infos:
        address = info[4][0]
        try:
            if _blocked(address):
                return True
        except ValueError:
            continue
    return False


def _validate_url(url: str, *, allow_localhost: bool = False) -> None:
    """Blockt SSRF-gefaehrdete URLs.

    Lokale Ziele sind nur fuer explizite lokale Provider wie Ollama erlaubt.
    """
    if not url:
        return
    from urllib.parse import urlparse
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"URL-Schema '{scheme}' nicht erlaubt (nur http/https)")
    host = parsed.hostname or ""
    # Bekannte Provider immer erlauben
    allowed_hosts = {
        "api.openai.com", "api.anthropic.com",
        "generativelanguage.googleapis.com", "api.mistral.ai",
        "api.deepseek.com", "dashscope-intl.aliyuncs.com",
    }
    if host in allowed_hosts:
        return
    if allow_localhost and host in ("localhost", "127.0.0.1", "::1"):
        return
    if _is_private_target(host):
        raise ValueError(f"Private/reservierte IP oder Host '{host}' nicht erlaubt")


# ── Adapter ───────────────────────────────────────────────────────────────

class UniversalAdapter:
    """Provider-agnostischer Adapter. Delegiert an ProviderProfile.

    Args:
        api_url: Provider-URL (z.B. https://api.openai.com/v1/chat/completions)
        api_key: API-Key (leer fuer Ollama/lokale Modelle)
        model: Modell-Name
        response_path: JSONPath zur Antwort (z.B. "choices[0].message.content")
        message_format: "standard" | "gemini" | "openai-responses"
        system_prompt: System-Prompt fuer den Agenten
        provider_name: Provider-Name fuer Audit-Log (Default: "custom")
        auth_format: Deprecated — wird aus dem Profile abgeleitet
        usage_path: JSONPath zum Usage-Objekt (Default: "usage")
        usage_input_key: Key fuer Input-Tokens (Default: "prompt_tokens")
        usage_output_key: Key fuer Output-Tokens (Default: "completion_tokens")
        timeout: Request-Timeout in Sekunden (Default: 120)
        extra_body: Zusaetzliche Felder die in den Request-Body gemerged werden
            (z.B. {"disable_thinking": true} fuer Modelle mit Reasoning-Tokens)
        extracts_reasoning: Wenn True, wird nach Response-Extract zusaetzlich
            choices[0].message.reasoning_content gelesen (DashScope/DeepSeek-
            Konvention) und als <think>...</think>-Block dem content vorangestellt.
            Bei leer/fehlend: keine Aenderung am content.
    """

    def __init__(
        self,
        api_url: str,
        api_key: str = "",
        model: str = "",
        response_path: str = "choices[0].message.content",
        message_format: str = "standard",
        system_prompt: str | None = None,
        provider_name: str = "custom",
        auth_format: str = "bearer",
        usage_path: str = "usage",
        usage_input_key: str = "prompt_tokens",
        usage_output_key: str = "completion_tokens",
        timeout: int = 120,
        extra_body: dict | None = None,
        extracts_reasoning: bool = False,
    ) -> None:
        # Profile bestimmen: message_format > auth_format > standard
        profile_key = message_format
        if profile_key == "standard" and auth_format == "x-api-key":
            profile_key = "anthropic"
        self._profile: ProviderProfile = get_profile(profile_key)

        self._api_url = api_url
        _validate_url(api_url, allow_localhost=(provider_name == "ollama"))
        self._api_key = api_key
        self._model = model
        self._response_path = response_path
        self._message_format = message_format
        self._system_prompt = system_prompt
        self._provider_name = provider_name
        self._usage_path = usage_path
        self._usage_input_key = usage_input_key
        self._usage_output_key = usage_output_key
        self._timeout = timeout
        self._extra_body = extra_body or {}
        self._extracts_reasoning = extracts_reasoning
        self._last_usage: TokenUsage | None = None

    @staticmethod
    def _extract_reasoning(data: dict) -> str:
        """Liest choices[0].message.reasoning_content (DashScope/DeepSeek).
        Liefert leeren String wenn Feld nicht da oder None."""
        rc = _extract_path(data, "choices[0].message.reasoning_content")
        return str(rc).strip() if rc else ""

    @staticmethod
    def _wrap_reasoning(reasoning: str, content: str) -> str:
        """Praependet reasoning als <think>...</think>-Block vor content.
        Bei leerem reasoning: content unveraendert."""
        if not reasoning:
            return content
        return f"<think>\n{reasoning}\n</think>\n\n{content}"

    @property
    def provider(self) -> str:
        return self._provider_name

    @property
    def last_usage(self) -> TokenUsage | None:
        return self._last_usage

    def complete(self, conversation: Conversation, participant: Participant) -> str:
        messages = _format_messages(conversation, self._message_format, participant.id)
        system = _build_system_prompt(self._system_prompt, conversation)
        body = self._profile.build_body(messages, self._model, system)
        if self._extra_body:
            body.update(self._extra_body)
        headers = self._profile.build_headers(self._api_key)
        url, params = self._profile.build_url(self._api_url, self._model, self._api_key)

        logger.info("universal.complete request",
                    extra={"model": self._model, "provider": self._provider_name})

        response = httpx.post(
            url, json=body, headers=headers, params=params, timeout=self._timeout,
        )
        if response.status_code >= 400:
            logger.error("API-Fehler %s %s: %s",
                         response.status_code, url,
                         response.text[:500],
                         extra={"provider": self._provider_name, "model": self._model})
        response.raise_for_status()
        data = response.json()

        text = self._profile.extract_response(data, self._response_path)
        if text is None:
            logger.error("Response extraction failed. Full response: %s", str(data)[:1000],
                         extra={"provider": self._provider_name})
            raise ValueError(
                f"Response-Path '{self._response_path}' lieferte None. "
                f"Response: {str(data)[:500]}"
            )

        self._extract_usage(data)
        text = str(text)
        if self._extracts_reasoning:
            text = self._wrap_reasoning(self._extract_reasoning(data), text)
        return text

    def stream(
        self, conversation: Conversation, participant: Participant
    ) -> Iterator[str]:
        messages = _format_messages(conversation, self._message_format, participant.id)
        system = _build_system_prompt(self._system_prompt, conversation)
        body = self._profile.build_body(messages, self._model, system)
        if self._extra_body:
            body.update(self._extra_body)
        body["stream"] = True
        headers = self._profile.build_headers(self._api_key)
        url, params = self._profile.build_url(self._api_url, self._model, self._api_key)

        with httpx.stream(
            "POST", url, json=body, headers=headers, params=params, timeout=self._timeout
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    break
                try:
                    chunk = __import__("json").loads(payload)
                    delta = _extract_path(chunk, "choices[0].delta.content")
                    if delta:
                        yield delta
                except Exception:
                    continue

    def _extract_usage(self, data: dict) -> None:
        """Extrahiert Token-Usage aus der Response (optional)."""
        try:
            if self._usage_path:
                usage_obj = _extract_path(data, self._usage_path)
            else:
                usage_obj = data

            if usage_obj and isinstance(usage_obj, dict):
                input_t = usage_obj.get(self._usage_input_key, 0)
                output_t = usage_obj.get(self._usage_output_key, 0)
                if input_t or output_t:
                    self._last_usage = TokenUsage(
                        input_tokens=int(input_t),
                        output_tokens=int(output_t),
                    )
                    return
        except Exception:
            pass
        self._last_usage = None
