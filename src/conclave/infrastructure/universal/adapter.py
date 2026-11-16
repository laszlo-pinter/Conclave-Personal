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
          ├── _http_post(...) ueber GuardedTransport (Ziel je Anfrage geprueft)
          ├── profile.extract_response() → Antworttext
          └── _extract_usage() → TokenUsage
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from conclave.domain.context_report import (
    ContextReport,
    attach_context_report,
    build_context_report,
    select_messages,
)
from conclave.domain.conversation import Conversation
from conclave.domain.errors import redact_secrets
from conclave.domain.message import MessageAuthorType
from conclave.domain.model_response import Completion, TokenUsage
from conclave.domain.participant import Participant
from conclave.infrastructure.log import get_logger
from conclave.infrastructure.system_prompt import (  # noqa: F401 - alte Namen fuer Tests/Aufrufer
    assemble_system_prompt as _assemble_system_prompt,
    build_system_prompt as _build_system_prompt,
    build_workspace_info as _build_workspace_info,
    collect_context_files as _collect_context_files,
    load_context_files as _load_context_files,
)
from conclave.infrastructure.universal.egress import LOCAL_HOSTS, GuardedTransport, address_blocked
from conclave.infrastructure.universal.profiles import (
    ProviderProfile,
    get_profile,
    _extract_path,
)

logger = get_logger("infrastructure.universal")


# ── Message Formatting ────────────────────────────────────────────────────

MAX_MESSAGES = int(os.environ.get("CONCLAVE_MAX_MESSAGES", "25"))


def _smart_truncate(messages: list, max_messages: int) -> list:
    """Behaelt erste User-Message (Kontext-Anker) + letzte N-1 Messages (siehe select_messages)."""
    return select_messages(messages, max_messages)


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


DEFAULT_OLLAMA_PORT = 11434


def ollama_port() -> int:
    """Port des lokalen Providers (Ollama); nur dieser ist auf localhost erlaubt."""
    return int(os.environ.get("CONCLAVE_OLLAMA_PORT", DEFAULT_OLLAMA_PORT))


def _validate_url(url: str, *, local_port: int | None = None) -> None:
    """Prueft die Provider-URL beim Anlegen des Adapters.

    Entfernte Provider nur ueber https; localhost nur fuer den lokalen Provider
    auf ``local_port``. Namen prueft der Transport bei jeder Anfrage.
    """
    if not url:
        return
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"URL-Schema '{scheme}' nicht erlaubt (nur http/https)")
    host = (parsed.hostname or "").lower()
    if host in LOCAL_HOSTS:
        port = parsed.port or (443 if scheme == "https" else 80)
        if local_port is None:
            raise ValueError("localhost ist nur fuer den lokalen Provider (Ollama) erlaubt")
        if port != local_port:
            raise ValueError(f"Lokaler Provider nur auf Port {local_port} erlaubt")
        return
    if scheme != "https":
        raise ValueError("Entfernte Provider nur ueber https")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return
    if address_blocked(host):
        raise ValueError("Private oder reservierte Adresse nicht erlaubt")


def _transport(provider: str, local_port: int | None) -> GuardedTransport:
    return GuardedTransport(provider, local_port=local_port)


def _http_post(url: str, *, transport: httpx.BaseTransport, timeout: float, **kwargs) -> httpx.Response:
    """POST ueber den geprueften Transport (Nahtstelle fuer Tests)."""
    with httpx.Client(transport=transport, timeout=timeout) as client:
        return client.post(url, **kwargs)


@contextmanager
def _http_stream(method: str, url: str, *, transport: httpx.BaseTransport, timeout: float, **kwargs):
    """Stream ueber den geprueften Transport (Nahtstelle fuer Tests)."""
    with httpx.Client(transport=transport, timeout=timeout) as client:
        with client.stream(method, url, **kwargs) as response:
            yield response


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
        max_messages: int | None = None,
    ) -> None:
        # Profile bestimmen: message_format > auth_format > standard
        profile_key = message_format
        if profile_key == "standard" and auth_format == "x-api-key":
            profile_key = "anthropic"
        self._profile: ProviderProfile = get_profile(profile_key)

        self._api_url = api_url
        self._local_port = ollama_port() if provider_name == "ollama" else None
        _validate_url(api_url, local_port=self._local_port)
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
        # None = globaler Default (CONCLAVE_MAX_MESSAGES), 0 = keine Kuerzung
        self._max_messages = max_messages

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
        limit = MAX_MESSAGES if self._max_messages is None else self._max_messages
        sent = select_messages(conversation.messages, limit)
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
            truncation_limit=limit or None,
            system_parts=system.parts,
            system_text=system.text,
            context_files=system.context_files,
            skipped_context_files=system.skipped_context_files,
        )
        return PreparedRequest(url=url, params=params, headers=headers, body=body,
                               report=report, stream=stream)

    def context_report(self, conversation: Conversation, participant: Participant) -> ContextReport:
        """Vorschau: Report der Anfrage, die jetzt gesendet wuerde (kein HTTP-Aufruf)."""
        return self.prepare_request(conversation, participant).report

    def complete(self, conversation: Conversation, participant: Participant) -> Completion:
        request = self.prepare_request(conversation, participant)
        try:
            return self.send(request)
        except Exception as exc:
            attach_context_report(exc, request.report)
            raise

    def send(self, request: PreparedRequest) -> Completion:
        """Fuehrt eine mit prepare_request() gebaute Anfrage aus."""
        url, params, headers, body = request.url, request.params, request.headers, request.body
        logger.info("universal.complete request",
                    extra={"model": self._model, "provider": self._provider_name})

        with self._safe_errors():
            response = _http_post(
                url, json=body, headers=headers, params=params, timeout=self._timeout,
                transport=_transport(self._provider_name, self._local_port),
            )
            if response.status_code >= 400:
                detail = self._clean(_provider_error_text(response))
                logger.error("API-Fehler %s: %s", response.status_code, detail,
                             extra={"provider": self._provider_name, "model": self._model})
                if response.status_code < 500 and response.status_code != 429:
                    raise ValueError(
                        f"Provider '{self._provider_name}' HTTP {response.status_code}: {detail}"
                    )
            response.raise_for_status()
        data = response.json()

        text = self._profile.extract_response(data, self._response_path)
        if text is None:
            # Nur die Feldnamen: die Antwort selbst kann vertrauliche Inhalte enthalten
            fields = sorted(data)[:10] if isinstance(data, dict) else type(data).__name__
            logger.error("Antwort ohne Text unter '%s' (Felder: %s)", self._response_path, fields,
                         extra={"provider": self._provider_name})
            raise ValueError(
                f"Response-Path '{self._response_path}' lieferte None (Felder: {fields})."
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
        try:
            yield from self._send_stream(request)
        except Exception as exc:
            attach_context_report(exc, request.report)
            raise

    def _send_stream(self, request: PreparedRequest) -> Iterator[str | Completion]:
        url, params, headers, body = request.url, request.params, request.headers, request.body
        # Usage ist lokal pro Stream - nie die eines frueheren Aufrufs (A7).
        tokens: dict[str, int | None] = {"input": None, "output": None}
        with self._safe_errors(), _http_stream(
            "POST", url, json=body, headers=headers, params=params, timeout=self._timeout,
            transport=_transport(self._provider_name, self._local_port),
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

    def _clean(self, text: str) -> str:
        """Provider-Text ohne den eigenen Key und ohne URLs."""
        if self._api_key:
            text = text.replace(self._api_key, "***")
        return redact_secrets(text)

    @contextmanager
    def _safe_errors(self):
        """httpx-Fehler ohne URL und Key weitergeben (Typ bleibt fuer Retry/Mapping)."""
        name = self._provider_name
        try:
            yield
        except httpx.HTTPStatusError as exc:
            raise httpx.HTTPStatusError(f"Provider '{name}' HTTP {exc.response.status_code}",
                                        request=exc.request, response=exc.response) from None
        except httpx.TransportError as exc:
            raise type(exc)(f"Provider '{name}': {type(exc).__name__}") from None

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
