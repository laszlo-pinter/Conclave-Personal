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
from dataclasses import dataclass
from typing import Any

import httpx

from conclave.application.workspace_security import (
    agent_read_limit_bytes,
    assert_size_allowed,
    is_agent_visible,
    resolve_workspace_path,
    workspace_root,
)
from conclave.domain.context_report import (
    ContextReport,
    build_context_report,
    requested_context_files,
)
from conclave.domain.conversation import Conversation
from conclave.domain.message import MessageAuthorType
from conclave.domain.model_response import Completion, TokenUsage
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


_STREAM_DONE = object()


def _parse_stream_line(line: str):
    """Eine Zeile eines Streams: SSE ("data: {...}", "[DONE]") oder NDJSON (Ollama)."""
    line = line.strip()
    if not line or line.startswith(("event:", ":", "id:", "retry:")):
        return None
    if line.startswith("data:"):
        line = line[5:].strip()
        if line == "[DONE]":
            return _STREAM_DONE
    if not line.startswith("{"):
        return None
    try:
        return __import__("json").loads(line)
    except ValueError:
        return None


def _format_messages(
    conversation: Conversation,
    message_format: str = "standard",
    current_participant_id: str = "",
    messages: list | None = None,
) -> list[dict]:
    """Wandelt Conclave-Messages ins Provider-Format.

    Formate:
        "standard" — OpenAI/Mistral/Ollama: {role: "user"/"assistant", content: "..."}
        "gemini"   — Google: {role: "user"/"model", parts: [{text: "..."}]}

    In Multi-Agent-Gespraechen: Nur eigene Messages werden als assistant/model
    gesendet. Messages anderer Agents werden als user-Messages mit [Name]-Prefix
    dargestellt, damit die API korrekt alterniert.

    Nur die letzten MAX_MESSAGES werden gesendet, um Rate Limits zu schonen
    (oder die bereits ausgewaehlten ``messages``).
    Der Projektkontext wird ueber Workspace-Hints im System-Prompt erhalten.
    """
    if messages is None:
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
    workspace = str(workspace_root())
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
        "Behaupte nicht selbst, dass die Datei gespeichert wurde. Das Backend "
        "fuehrt den Schreibvorgang aus und protokolliert das Ergebnis als Tool-Event."
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


def _collect_context_files(conversation: Conversation) -> tuple[str, list[dict], list[dict]]:
    """Laedt context_files aus der Conversation.

    context_files ist eine kommaseparierte Liste von Workspace-Pfaden
    im rules-Feld mit dem Prefix 'context_files:'.
    Format: Erste Zeile von rules = 'context_files: datei1.md, datei2.md'

    Returns: (Text fuer den System-Prompt, eingebundene [{path, bytes}],
    abgewiesene [{path, reason}])
    """
    root = workspace_root()
    parts = []
    loaded: list[dict] = []
    skipped: list[dict] = []
    for filepath in requested_context_files(getattr(conversation, "rules", "") or ""):
        # Dieselben Grenzen wie @workspace/ und @read(): kein absoluter Pfad,
        # kein Ausbruch aus dem Workspace, keine versteckten Pfade, Leselimit.
        resolved = resolve_workspace_path(filepath, root)
        if resolved is None or not resolved.path.is_file() or not is_agent_visible(resolved.path, root):
            logger.warning("context_files: '%s' ignoriert (ausserhalb des Workspace, versteckt oder fehlt)", filepath)
            skipped.append({"path": filepath, "reason": "not_found_or_not_allowed"})
            continue
        if not assert_size_allowed(resolved.path, agent_read_limit_bytes()):
            logger.warning("context_files: '%s' ignoriert (groesser als das Agent-Leselimit)", filepath)
            skipped.append({"path": filepath, "reason": "too_large"})
            continue
        try:
            content = resolved.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            skipped.append({"path": filepath, "reason": "unreadable"})
            continue
        parts.append(f"--- Kontext: {resolved.relative} ---\n{content}")
        loaded.append({"path": resolved.relative, "bytes": len(content.encode("utf-8"))})
    return ("\n\n".join(parts) if parts else ""), loaded, skipped


def _load_context_files(conversation: Conversation) -> str:
    """Inhalt der context_files als Text (siehe _collect_context_files)."""
    return _collect_context_files(conversation)[0]


@dataclass(frozen=True)
class _SystemPrompt:
    text: str | None
    parts: tuple[str, ...] = ()
    context_files: tuple[dict, ...] = ()
    skipped_context_files: tuple[dict, ...] = ()


def _assemble_system_prompt(
    system_prompt: str | None, conversation: Conversation
) -> _SystemPrompt:
    """Baut den System-Prompt und merkt sich, welche Bausteine enthalten sind."""
    parts = []
    names = []
    if system_prompt:
        parts.append(system_prompt)
        names.append("agent_prompt")
    # Kontext-Dateien als statischer Kontext (spart Tokens vs. Chat-Messages)
    context, loaded, skipped = _collect_context_files(conversation)
    if context:
        parts.append(context)
        names.append("context_files")
    # Chat-Regeln (ohne context_files-Zeilen)
    rules = getattr(conversation, "rules", "") or ""
    clean_rules = "\n".join(
        line for line in rules.split("\n")
        if not line.strip().lower().startswith("context_files:")
    ).strip()
    if clean_rules:
        parts.append(f"Chat-Regeln:\n{clean_rules}")
        names.append("rules")
    workspace_info = _build_workspace_info()
    if workspace_info:
        parts.append(workspace_info)
        names.append("workspace_info")
    return _SystemPrompt(
        text="\n\n".join(parts) if parts else None,
        parts=tuple(names),
        context_files=tuple(loaded),
        skipped_context_files=tuple(skipped),
    )


def _build_system_prompt(
    system_prompt: str | None, conversation: Conversation
) -> str | None:
    """Baut den kombinierten System-Prompt aus Agent-Prompt, Regeln, Kontext-Dateien und Workspace."""
    return _assemble_system_prompt(system_prompt, conversation).text


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


def _provider_error_text(response) -> str:
    """Extrahiert eine kurze Provider-Fehlermeldung ohne Secrets."""
    try:
        data = response.json()
    except Exception:
        return str(getattr(response, "text", ""))[:500]

    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        parts = [
            str(error.get("message", "")).strip(),
            str(error.get("type", "")).strip(),
            str(error.get("code", "")).strip(),
        ]
        return " ".join(part for part in parts if part)[:500]
    if isinstance(error, str):
        return error[:500]
    return str(data)[:500]


# ── Adapter ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PreparedRequest:
    """Eine fertig gebaute Provider-Anfrage samt Kontext-Report.

    Wird genau einmal gebaut; Wiederholungen (ResilientAdapter) und die
    Vorschau verwenden dieselbe Anfrage.
    """
    url: str
    params: dict | None
    headers: dict
    body: dict
    report: ContextReport
    stream: bool = False


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
        stream_usage: bool = False,
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
        # Usage im Stream per stream_options anfordern (nur OpenAI-kompatible
        # Provider, die das Feld kennen; andere koennten es ablehnen).
        self._stream_usage = stream_usage

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

    def prepare_request(
        self, conversation: Conversation, participant: Participant, *, stream: bool = False
    ) -> PreparedRequest:
        """Baut die Provider-Anfrage und den Kontext-Report daraus (ohne HTTP-Aufruf)."""
        limit = MAX_MESSAGES
        sent = _smart_truncate(conversation.messages, limit)
        messages = _format_messages(conversation, self._message_format, participant.id, messages=sent)
        system = _assemble_system_prompt(self._system_prompt, conversation)
        body = self._profile.build_body(messages, self._model, system.text)
        if self._extra_body:
            body.update(self._extra_body)
        url, params = self._profile.build_url(self._api_url, self._model, self._api_key)
        if stream:
            # Provider-spezifisch: "stream"-Flag bzw. eigener Endpunkt (Gemini)
            url, params, body = self._profile.prepare_stream(url, params, body)
            if self._stream_usage:
                body["stream_options"] = {"include_usage": True}
        headers = self._profile.build_headers(self._api_key)
        report = build_context_report(
            all_messages=list(conversation.messages),
            sent_messages=list(sent),
            adapter="universal",
            truncation_limit=limit,
            system_parts=system.parts,
            system_text=system.text,
            context_files=system.context_files,
            skipped_context_files=system.skipped_context_files,
        )
        return PreparedRequest(url=url, params=params, headers=headers, body=body,
                               report=report, stream=stream)

    def complete(self, conversation: Conversation, participant: Participant) -> Completion:
        return self.send(self.prepare_request(conversation, participant))

    def send(self, request: PreparedRequest) -> Completion:
        """Fuehrt eine mit prepare_request() gebaute Anfrage aus."""
        url, params, headers, body = request.url, request.params, request.headers, request.body
        logger.info("universal.complete request",
                    extra={"model": self._model, "provider": self._provider_name})

        response = httpx.post(
            url, json=body, headers=headers, params=params, timeout=self._timeout,
        )
        if response.status_code >= 400:
            detail = _provider_error_text(response)
            logger.error("API-Fehler %s %s: %s",
                         response.status_code, url,
                         detail,
                         extra={"provider": self._provider_name, "model": self._model})
            if response.status_code < 500 and response.status_code != 429:
                raise ValueError(
                    f"Provider '{self._provider_name}' HTTP {response.status_code}: {detail}"
                )
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

        usage = self._extract_usage(data)
        text = str(text)
        if self._extracts_reasoning:
            text = self._wrap_reasoning(self._extract_reasoning(data), text)
        return Completion(text=text, usage=usage, report=request.report)

    def stream(
        self, conversation: Conversation, participant: Participant
    ) -> Iterator[str | Completion]:
        """Liefert Text-Chunks und zum Abschluss ein Completion ohne Text (Usage, Report)."""
        return self.send_stream(self.prepare_request(conversation, participant, stream=True))

    def send_stream(self, request: PreparedRequest) -> Iterator[str | Completion]:
        url, params, headers, body = request.url, request.params, request.headers, request.body
        # Usage ist lokal pro Stream - nie die eines frueheren Aufrufs (A7).
        tokens: dict[str, int | None] = {"input": None, "output": None}
        with httpx.stream(
            "POST", url, json=body, headers=headers, params=params, timeout=self._timeout
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                event = _parse_stream_line(line)
                if event is _STREAM_DONE:
                    break
                if not isinstance(event, dict):
                    continue
                text, usage_source = self._profile.parse_stream_event(event)
                self._merge_stream_usage(tokens, usage_source)
                if text:
                    yield text
        usage = None
        if tokens["input"] is not None or tokens["output"] is not None:
            usage = TokenUsage(input_tokens=tokens["input"] or 0,
                               output_tokens=tokens["output"] or 0)
        yield Completion(usage=usage, report=request.report)

    def _merge_stream_usage(self, tokens: dict, source: dict | None) -> None:
        """Uebernimmt Usage-Angaben eines Stream-Ereignisses (spaetere Werte gewinnen)."""
        if not isinstance(source, dict):
            return
        usage = _extract_path(source, self._usage_path) if self._usage_path else source
        if not isinstance(usage, dict):
            return
        for slot, key in (("input", self._usage_input_key), ("output", self._usage_output_key)):
            value = usage.get(key)
            if isinstance(value, (int, float)):
                tokens[slot] = int(value)

    def _extract_usage(self, data: dict) -> TokenUsage | None:
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
                    return TokenUsage(
                        input_tokens=int(input_t),
                        output_tokens=int(output_t),
                    )
        except Exception:
            pass
        return None
