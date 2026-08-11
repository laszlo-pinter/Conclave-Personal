# src/conclave/infrastructure/universal/profiles.py
"""ProviderProfile — Provider-spezifische Request/Response-Logik.

Jedes Profil kapselt die Eigenheiten eines Providers:
- Wie wird der Request-Body gebaut?
- Welche Headers sind noetig?
- Wie wird die URL aufgebaut?
- Wie wird die Antwort extrahiert?

Der UniversalAdapter delegiert an das Profil statt if/elif-Ketten.
"""

from __future__ import annotations

import re
from typing import Any, Protocol


class ProviderProfile(Protocol):
    """Interface fuer Provider-spezifische Logik."""

    def build_url(self, base_url: str, model: str, api_key: str) -> tuple[str, dict]:
        """Gibt (url, query_params) zurueck."""
        ...

    def build_headers(self, api_key: str) -> dict:
        """Gibt HTTP-Headers inkl. Auth zurueck."""
        ...

    def build_body(
        self, messages: list[dict], model: str, system: str | None
    ) -> dict:
        """Gibt den Request-Body zurueck."""
        ...

    def extract_response(self, data: dict, response_path: str) -> str | None:
        """Extrahiert den Antworttext aus der API-Response."""
        ...


# ── Path Extraction (shared) ────────────────────────────────────────────

def _extract_path(data: Any, path: str) -> Any:
    """Extrahiert einen Wert aus verschachteltem JSON via Dot-Notation + Array-Index."""
    if not path:
        return data
    current = data
    parts = re.split(r'\.', path)
    for part in parts:
        if current is None:
            return None
        match = re.match(r'^(\w+)\[(\d+)\]$', part)
        if match:
            key, idx = match.group(1), int(match.group(2))
            if isinstance(current, dict) and key in current:
                current = current[key]
                if isinstance(current, list) and idx < len(current):
                    current = current[idx]
                else:
                    return None
            else:
                return None
        else:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
    return current


# ── Concrete Profiles ────────────────────────────────────────────────────

class StandardProfile:
    """OpenAI Chat Completions, Mistral, Ollama — Standard-Format."""

    def build_url(self, base_url: str, model: str, api_key: str) -> tuple[str, dict]:
        return base_url, {}

    def build_headers(self, api_key: str) -> dict:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def build_body(
        self, messages: list[dict], model: str, system: str | None
    ) -> dict:
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)
        return {"model": model, "messages": all_messages}

    def extract_response(self, data: dict, response_path: str) -> str | None:
        return _extract_path(data, response_path)


class AnthropicProfile:
    """Anthropic Messages API — x-api-key, anthropic-version, max_tokens, system als Top-Level."""

    def build_url(self, base_url: str, model: str, api_key: str) -> tuple[str, dict]:
        return base_url, {}

    def build_headers(self, api_key: str) -> dict:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
        return headers

    def build_body(
        self, messages: list[dict], model: str, system: str | None
    ) -> dict:
        body: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": 4096,
        }
        if system:
            body["system"] = system
        return body

    def extract_response(self, data: dict, response_path: str) -> str | None:
        return _extract_path(data, response_path)


class OpenAIResponsesProfile:
    """OpenAI Responses API — input statt messages, output-Array mit type='message'."""

    def build_url(self, base_url: str, model: str, api_key: str) -> tuple[str, dict]:
        return base_url, {}

    def build_headers(self, api_key: str) -> dict:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def build_body(
        self, messages: list[dict], model: str, system: str | None
    ) -> dict:
        input_items = []
        if system:
            input_items.append({"role": "system", "content": system})
        input_items.extend(messages)
        return {"model": model, "input": input_items}

    def extract_response(self, data: dict, response_path: str) -> str | None:
        """Navigiert das output-Array nach type='message' Items."""
        output = data.get("output", [])
        parts = []
        for item in output:
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    parts.append(content["text"])
        return "\n".join(parts) if parts else None


class GeminiProfile:
    """Google Gemini — model in URL, key als Query-Parameter, eigenes Message-Format."""

    def build_url(self, base_url: str, model: str, api_key: str) -> tuple[str, dict]:
        url = base_url.replace("{model}", model) if model else base_url
        params = {}
        if api_key:
            params["key"] = api_key
        return url, params

    def build_headers(self, api_key: str) -> dict:
        return {"Content-Type": "application/json"}

    def build_body(
        self, messages: list[dict], model: str, system: str | None
    ) -> dict:
        body: dict = {
            "contents": messages,
            "generationConfig": {},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return body

    def extract_response(self, data: dict, response_path: str) -> str | None:
        return _extract_path(data, response_path)


# ── Profile Registry ─────────────────────────────────────────────────────

PROFILES: dict[str, ProviderProfile] = {
    "standard": StandardProfile(),
    "anthropic": AnthropicProfile(),
    "openai-responses": OpenAIResponsesProfile(),
    "gemini": GeminiProfile(),
}


def get_profile(name: str) -> ProviderProfile:
    """Gibt das Profil fuer einen Provider zurueck. Fallback: StandardProfile."""
    return PROFILES.get(name, PROFILES["standard"])
