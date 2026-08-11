# tests/infrastructure/test_universal/test_universal_adapter.py
"""Phase 2 — Beweis: UniversalAdapter verarbeitet alle Provider-Formate.

Alle HTTP-Calls werden gemockt. Kein realer Provider-Zugriff noetig.
"""

import json
from datetime import datetime, UTC
from unittest.mock import MagicMock, patch

import pytest

from conclave.domain.conversation import Conversation
from conclave.domain.message import Message, MessageAuthorType
from conclave.domain.participant import Participant, ParticipantType

_NOW = datetime.now(UTC)


def _conversation(messages=None):
    """Hilfsfunktion: Conversation mit Messages."""
    conv = Conversation(id="conv-1", status="active", topic="test")
    if messages:
        conv.messages = messages
    else:
        conv.messages = [
            Message(id="m1", conversation_id="conv-1", author_type=MessageAuthorType.USER,
                    author_id=None, content="Hallo", sequence=1, created_at=_NOW),
        ]
    return conv


def _participant():
    return Participant(id="agent-1", conversation_id="conv-1",
                       participant_type=ParticipantType.MODEL, name="Agent")


def _mock_response(status_code=200, json_data=None, text="", iter_lines=None):
    """Erstellt ein Mock-httpx-Response-Objekt."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text or json.dumps(json_data or {})
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    if iter_lines:
        resp.iter_lines.return_value = iter_lines
    return resp


# ═════════════════════════════════════════════════════════════════════════
# RESPONSE-PATH EXTRACTION
# ═════════════════════════════════════════════════════════════════════════

class TestResponsePath:
    """JSONPath-artige Extraktion aus Provider-Antworten."""

    def test_simple_key(self):
        from conclave.infrastructure.universal.adapter import _extract_path
        data = {"output_text": "Hallo Welt"}
        assert _extract_path(data, "output_text") == "Hallo Welt"

    def test_nested_key(self):
        from conclave.infrastructure.universal.adapter import _extract_path
        data = {"message": {"content": "Antwort"}}
        assert _extract_path(data, "message.content") == "Antwort"

    def test_array_index(self):
        from conclave.infrastructure.universal.adapter import _extract_path
        data = {"choices": [{"message": {"content": "OK"}}]}
        assert _extract_path(data, "choices[0].message.content") == "OK"

    def test_deep_nested(self):
        from conclave.infrastructure.universal.adapter import _extract_path
        data = {"candidates": [{"content": {"parts": [{"text": "Gemini sagt"}]}}]}
        assert _extract_path(data, "candidates[0].content.parts[0].text") == "Gemini sagt"

    def test_invalid_path_returns_none(self):
        from conclave.infrastructure.universal.adapter import _extract_path
        data = {"a": 1}
        assert _extract_path(data, "b.c.d") is None

    def test_empty_path_returns_data(self):
        from conclave.infrastructure.universal.adapter import _extract_path
        data = {"text": "hi"}
        assert _extract_path(data, "") == data


# ═════════════════════════════════════════════════════════════════════════
# MESSAGE FORMAT
# ═════════════════════════════════════════════════════════════════════════

class TestMessageFormat:
    """Message-Mapping: Conclave → Provider-Format."""

    def test_standard_format(self):
        from conclave.infrastructure.universal.adapter import _format_messages
        conv = _conversation()
        msgs = _format_messages(conv, "standard")
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Hallo"

    def test_standard_model_role(self):
        from conclave.infrastructure.universal.adapter import _format_messages
        conv = _conversation([
            Message(id="m1", conversation_id="conv-1", author_type=MessageAuthorType.USER,
                    author_id=None, content="Frage", sequence=1, created_at=_NOW),
            Message(id="m2", conversation_id="conv-1", author_type=MessageAuthorType.MODEL,
                    author_id="agent-1", content="Antwort", sequence=2, created_at=_NOW),
        ])
        msgs = _format_messages(conv, "standard", current_participant_id="agent-1")
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    def test_gemini_format(self):
        from conclave.infrastructure.universal.adapter import _format_messages
        conv = _conversation([
            Message(id="m1", conversation_id="conv-1", author_type=MessageAuthorType.USER,
                    author_id=None, content="Frage", sequence=1, created_at=_NOW),
            Message(id="m2", conversation_id="conv-1", author_type=MessageAuthorType.MODEL,
                    author_id="agent-1", content="Antwort", sequence=2, created_at=_NOW),
        ])
        msgs = _format_messages(conv, "gemini", current_participant_id="agent-1")
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "model"
        assert msgs[0]["parts"] == [{"text": "Frage"}]


# ═════════════════════════════════════════════════════════════════════════
# COMPLETE (HTTP POST → Text)
# ═════════════════════════════════════════════════════════════════════════

class TestComplete:
    """UniversalAdapter.complete() fuer verschiedene Provider."""

    @patch("conclave.infrastructure.universal.adapter.httpx")
    def test_openai_compatible(self, mock_httpx):
        from conclave.infrastructure.universal.adapter import UniversalAdapter
        mock_httpx.post.return_value = _mock_response(json_data={
            "choices": [{"message": {"content": "OpenAI sagt Hallo"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })
        adapter = UniversalAdapter(
            api_url="https://api.openai.com/v1/chat/completions",
            api_key="sk-test",
            model="gpt-4o",
            response_path="choices[0].message.content",
            message_format="standard",
        )
        result = adapter.complete(_conversation(), _participant())
        assert result == "OpenAI sagt Hallo"
        assert adapter.last_usage is not None
        assert adapter.last_usage.input_tokens == 10
        assert adapter.last_usage.output_tokens == 5

    @patch("conclave.infrastructure.universal.adapter.httpx")
    def test_gemini_format(self, mock_httpx):
        from conclave.infrastructure.universal.adapter import UniversalAdapter
        mock_httpx.post.return_value = _mock_response(json_data={
            "candidates": [{"content": {"parts": [{"text": "Gemini sagt Hallo"}]}}],
            "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 4},
        })
        adapter = UniversalAdapter(
            api_url="https://gemini.api/v1",
            api_key="AIza-test",
            model="gemini-pro",
            response_path="candidates[0].content.parts[0].text",
            message_format="gemini",
            usage_path="usageMetadata",
            usage_input_key="promptTokenCount",
            usage_output_key="candidatesTokenCount",
        )
        result = adapter.complete(_conversation(), _participant())
        assert result == "Gemini sagt Hallo"
        assert adapter.last_usage.input_tokens == 8

    @patch("conclave.infrastructure.universal.adapter.httpx")
    def test_ollama_format(self, mock_httpx):
        from conclave.infrastructure.universal.adapter import UniversalAdapter
        mock_httpx.post.return_value = _mock_response(json_data={
            "message": {"content": "Llama sagt Hallo"},
            "eval_count": 12, "prompt_eval_count": 6,
        })
        adapter = UniversalAdapter(
            api_url="http://localhost:11434/api/chat",
            api_key="",
            model="llama3",
            response_path="message.content",
            message_format="standard",
            usage_path="",
            usage_input_key="prompt_eval_count",
            usage_output_key="eval_count",
        )
        result = adapter.complete(_conversation(), _participant())
        assert result == "Llama sagt Hallo"

    @patch("conclave.infrastructure.universal.adapter.httpx")
    def test_system_prompt_injected(self, mock_httpx):
        from conclave.infrastructure.universal.adapter import UniversalAdapter
        mock_httpx.post.return_value = _mock_response(json_data={
            "choices": [{"message": {"content": "OK"}}],
        })
        adapter = UniversalAdapter(
            api_url="https://api.example.com",
            api_key="key",
            model="model",
            response_path="choices[0].message.content",
            system_prompt="Du bist ein Analyst.",
        )
        adapter.complete(_conversation(), _participant())
        call_args = mock_httpx.post.call_args
        body = call_args.kwargs.get("json") or call_args[1].get("json")
        messages = body.get("messages", [])
        assert messages[0]["role"] == "system"
        assert "Analyst" in messages[0]["content"]

    @patch("conclave.infrastructure.universal.adapter.httpx")
    def test_chat_rules_injected(self, mock_httpx):
        from conclave.infrastructure.universal.adapter import UniversalAdapter
        mock_httpx.post.return_value = _mock_response(json_data={
            "choices": [{"message": {"content": "OK"}}],
        })
        adapter = UniversalAdapter(
            api_url="https://api.example.com",
            api_key="key",
            model="model",
            response_path="choices[0].message.content",
        )
        conv = _conversation()
        conv.rules = "Antworte knapp."
        adapter.complete(conv, _participant())
        call_args = mock_httpx.post.call_args
        body = call_args.kwargs.get("json") or call_args[1].get("json")
        messages = body.get("messages", [])
        assert any("knapp" in m.get("content", "") for m in messages)

    @patch("conclave.infrastructure.universal.adapter.httpx")
    def test_api_key_in_header(self, mock_httpx):
        from conclave.infrastructure.universal.adapter import UniversalAdapter
        mock_httpx.post.return_value = _mock_response(json_data={
            "choices": [{"message": {"content": "OK"}}],
        })
        adapter = UniversalAdapter(
            api_url="https://api.example.com",
            api_key="my-secret-key",
            model="model",
            response_path="choices[0].message.content",
        )
        adapter.complete(_conversation(), _participant())
        call_args = mock_httpx.post.call_args
        headers = call_args.kwargs.get("headers") or call_args[1].get("headers")
        assert "my-secret-key" in str(headers)

    @patch("conclave.infrastructure.universal.adapter.httpx")
    def test_no_api_key_no_auth_header(self, mock_httpx):
        """Ollama braucht keinen Key — kein Auth-Header."""
        from conclave.infrastructure.universal.adapter import UniversalAdapter
        mock_httpx.post.return_value = _mock_response(json_data={
            "message": {"content": "OK"},
        })
        adapter = UniversalAdapter(
            api_url="http://localhost:11434/api/chat",
            api_key="",
            model="llama3",
            response_path="message.content",
        )
        adapter.complete(_conversation(), _participant())
        call_args = mock_httpx.post.call_args
        headers = call_args.kwargs.get("headers") or call_args[1].get("headers")
        assert "Authorization" not in headers

    @patch("conclave.infrastructure.universal.adapter.httpx")
    def test_http_error_raises(self, mock_httpx):
        from conclave.infrastructure.universal.adapter import UniversalAdapter
        mock_httpx.post.return_value = _mock_response(status_code=500)
        adapter = UniversalAdapter(
            api_url="https://api.example.com",
            api_key="key",
            model="model",
            response_path="text",
        )
        with pytest.raises(Exception):
            adapter.complete(_conversation(), _participant())

    @patch("conclave.infrastructure.universal.adapter.httpx")
    def test_provider_property(self, mock_httpx):
        from conclave.infrastructure.universal.adapter import UniversalAdapter
        adapter = UniversalAdapter(
            api_url="https://api.example.com",
            api_key="key",
            model="model",
            response_path="text",
            provider_name="gemini",
        )
        assert adapter.provider == "gemini"

    @patch("conclave.infrastructure.universal.adapter.httpx")
    def test_provider_default_custom(self, mock_httpx):
        from conclave.infrastructure.universal.adapter import UniversalAdapter
        adapter = UniversalAdapter(
            api_url="https://api.example.com",
            api_key="key",
            model="model",
            response_path="text",
        )
        assert adapter.provider == "custom"


# ═════════════════════════════════════════════════════════════════════════
# REASONING-CONTENT EXTRAKTION (DashScope/DeepSeek-Konvention)
# ═════════════════════════════════════════════════════════════════════════

class TestReasoningContent:
    """extracts_reasoning=True liest choices[0].message.reasoning_content
    und prependet es als <think>...</think>-Block vor den content."""

    @patch("conclave.infrastructure.universal.adapter.httpx")
    def test_reasoning_prepended_when_present(self, mock_httpx):
        from conclave.infrastructure.universal.adapter import UniversalAdapter
        mock_httpx.post.return_value = _mock_response(json_data={
            "choices": [{"message": {
                "content": "Die Antwort ist 4.",
                "reasoning_content": "2 + 2 ergibt 4.",
            }}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })
        adapter = UniversalAdapter(
            api_url="https://api.example.com",
            api_key="key", model="model",
            response_path="choices[0].message.content",
            extracts_reasoning=True,
        )
        result = adapter.complete(_conversation(), _participant())
        assert result == "<think>\n2 + 2 ergibt 4.\n</think>\n\nDie Antwort ist 4."

    @patch("conclave.infrastructure.universal.adapter.httpx")
    def test_reasoning_unchanged_when_field_missing(self, mock_httpx):
        from conclave.infrastructure.universal.adapter import UniversalAdapter
        mock_httpx.post.return_value = _mock_response(json_data={
            "choices": [{"message": {"content": "Antwort ohne Reasoning."}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })
        adapter = UniversalAdapter(
            api_url="https://api.example.com",
            api_key="key", model="model",
            response_path="choices[0].message.content",
            extracts_reasoning=True,
        )
        result = adapter.complete(_conversation(), _participant())
        assert result == "Antwort ohne Reasoning."
        assert "<think>" not in result

    @patch("conclave.infrastructure.universal.adapter.httpx")
    def test_reasoning_unchanged_when_field_empty(self, mock_httpx):
        from conclave.infrastructure.universal.adapter import UniversalAdapter
        mock_httpx.post.return_value = _mock_response(json_data={
            "choices": [{"message": {
                "content": "Antwort ohne Reasoning.",
                "reasoning_content": "",
            }}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })
        adapter = UniversalAdapter(
            api_url="https://api.example.com",
            api_key="key", model="model",
            response_path="choices[0].message.content",
            extracts_reasoning=True,
        )
        result = adapter.complete(_conversation(), _participant())
        assert result == "Antwort ohne Reasoning."
        assert "<think>" not in result

    @patch("conclave.infrastructure.universal.adapter.httpx")
    def test_reasoning_ignored_when_flag_false(self, mock_httpx):
        """Auch wenn reasoning_content da ist: ohne Flag wird es ignoriert."""
        from conclave.infrastructure.universal.adapter import UniversalAdapter
        mock_httpx.post.return_value = _mock_response(json_data={
            "choices": [{"message": {
                "content": "Antwort.",
                "reasoning_content": "Reasoning das ignoriert werden soll.",
            }}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })
        adapter = UniversalAdapter(
            api_url="https://api.example.com",
            api_key="key", model="model",
            response_path="choices[0].message.content",
            extracts_reasoning=False,  # Default
        )
        result = adapter.complete(_conversation(), _participant())
        assert result == "Antwort."
        assert "<think>" not in result
        assert "Reasoning" not in result

    @patch("conclave.infrastructure.universal.adapter.httpx")
    def test_reasoning_strips_whitespace(self, mock_httpx):
        from conclave.infrastructure.universal.adapter import UniversalAdapter
        mock_httpx.post.return_value = _mock_response(json_data={
            "choices": [{"message": {
                "content": "X",
                "reasoning_content": "   reasoning mit leerzeichen   \n",
            }}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })
        adapter = UniversalAdapter(
            api_url="https://api.example.com",
            api_key="key", model="model",
            response_path="choices[0].message.content",
            extracts_reasoning=True,
        )
        result = adapter.complete(_conversation(), _participant())
        # Strip in _extract_reasoning sollte greifen
        assert result.startswith("<think>\nreasoning mit leerzeichen\n</think>")

    def test_wrap_reasoning_helper(self):
        from conclave.infrastructure.universal.adapter import UniversalAdapter
        assert UniversalAdapter._wrap_reasoning("r", "c") == "<think>\nr\n</think>\n\nc"
        assert UniversalAdapter._wrap_reasoning("", "c") == "c"

    def test_extract_reasoning_helper(self):
        from conclave.infrastructure.universal.adapter import UniversalAdapter
        data = {"choices": [{"message": {"reasoning_content": "  abc  "}}]}
        assert UniversalAdapter._extract_reasoning(data) == "abc"
        assert UniversalAdapter._extract_reasoning({}) == ""
        assert UniversalAdapter._extract_reasoning({"choices": [{"message": {"reasoning_content": None}}]}) == ""
