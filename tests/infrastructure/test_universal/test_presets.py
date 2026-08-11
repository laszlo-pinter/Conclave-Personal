# tests/infrastructure/test_universal/test_presets.py
"""Phase 3 — Beweis: Preset-Registry liefert vollstaendige Provider-Configs."""

import pytest

from conclave.infrastructure.universal.presets import (
    get_preset, list_presets, PRESETS,
)


class TestPresetRegistry:

    def test_list_presets_returns_all(self):
        """Mindestens 7 Presets vorhanden."""
        presets = list_presets()
        assert len(presets) >= 7
        names = {p["name"] for p in presets}
        assert {"openai", "openai-responses", "anthropic", "ollama",
                "gemini", "mistral", "custom"} <= names

    def test_get_preset_returns_dict(self):
        p = get_preset("openai")
        assert isinstance(p, dict)
        assert "api_url" in p
        assert "response_path" in p
        assert "message_format" in p
        assert "requires_api_key" in p

    def test_unknown_preset_returns_none(self):
        assert get_preset("nonexistent") is None


class TestPresetOpenAI:

    def test_openai_url(self):
        p = get_preset("openai")
        assert "chat/completions" in p["api_url"]

    def test_openai_response_path(self):
        p = get_preset("openai")
        assert p["response_path"] == "choices[0].message.content"

    def test_openai_format_standard(self):
        p = get_preset("openai")
        assert p["message_format"] == "standard"

    def test_openai_models(self):
        p = get_preset("openai")
        assert "gpt-5.6" in p["models"]


class TestPresetOpenAIResponses:

    def test_responses_url(self):
        p = get_preset("openai-responses")
        assert "responses" in p["api_url"]

    def test_responses_path(self):
        p = get_preset("openai-responses")
        assert p["response_path"] == "output_text"

    def test_responses_is_recommended(self):
        p = get_preset("openai-responses")
        assert p["recommended"] is True


class TestPresetAnthropic:

    def test_anthropic_url(self):
        p = get_preset("anthropic")
        assert "anthropic.com" in p["api_url"]

    def test_anthropic_format(self):
        p = get_preset("anthropic")
        assert p["message_format"] == "standard"

    def test_anthropic_auth(self):
        p = get_preset("anthropic")
        assert p["auth_format"] == "x-api-key"

    def test_anthropic_models(self):
        p = get_preset("anthropic")
        assert "claude-sonnet-5" in p["models"]


class TestPresetOllama:

    def test_ollama_url_localhost(self):
        p = get_preset("ollama")
        assert "localhost" in p["api_url"]

    def test_ollama_no_auth(self):
        p = get_preset("ollama")
        assert p["auth_format"] == "none"
        assert p["requires_api_key"] is False

    def test_ollama_response_path(self):
        p = get_preset("ollama")
        assert p["response_path"] == "message.content"

    def test_ollama_models(self):
        p = get_preset("ollama")
        assert "llama3.3" in p["models"]


class TestPresetGemini:

    def test_gemini_url(self):
        p = get_preset("gemini")
        assert "generativelanguage" in p["api_url"]

    def test_gemini_format(self):
        p = get_preset("gemini")
        assert p["message_format"] == "gemini"

    def test_gemini_response_path(self):
        p = get_preset("gemini")
        assert "candidates" in p["response_path"]

    def test_gemini_auth_query(self):
        p = get_preset("gemini")
        assert p["auth_format"] == "query"


class TestPresetMistral:

    def test_mistral_url(self):
        p = get_preset("mistral")
        assert "mistral.ai" in p["api_url"]

    def test_mistral_format_standard(self):
        p = get_preset("mistral")
        assert p["message_format"] == "standard"


class TestPresetCustom:

    def test_custom_has_empty_url(self):
        p = get_preset("custom")
        assert p["api_url"] == ""

    def test_custom_has_empty_response_path(self):
        p = get_preset("custom")
        assert p["response_path"] == ""

    def test_custom_format_standard(self):
        p = get_preset("custom")
        assert p["message_format"] == "standard"


class TestPresetQwenDashScope:

    def test_qwen_dashscope_url_intl(self):
        p = get_preset("qwen-dashscope")
        assert "dashscope-intl.aliyuncs.com" in p["api_url"]
        assert "chat/completions" in p["api_url"]

    def test_qwen_dashscope_thinking_off(self):
        p = get_preset("qwen-dashscope")
        assert p["extra_body"] == {"enable_thinking": False}

    def test_qwen_dashscope_response_path(self):
        p = get_preset("qwen-dashscope")
        assert p["response_path"] == "choices[0].message.content"

    def test_qwen_dashscope_auth_bearer(self):
        p = get_preset("qwen-dashscope")
        assert p["auth_format"] == "bearer"

    def test_qwen_dashscope_api_key_env(self):
        p = get_preset("qwen-dashscope")
        assert p["api_key_env"] == "DASHSCOPE_API_KEY"

    def test_qwen_dashscope_models(self):
        p = get_preset("qwen-dashscope")
        assert "qwen-plus" in p["models"]

    def test_qwen_dashscope_thinking_url_same_as_non_thinking(self):
        p1 = get_preset("qwen-dashscope")
        p2 = get_preset("qwen-dashscope-thinking")
        assert p1["api_url"] == p2["api_url"]

    def test_qwen_dashscope_thinking_on(self):
        p = get_preset("qwen-dashscope-thinking")
        assert p["extra_body"] == {"enable_thinking": True}

    def test_qwen_dashscope_thinking_api_key_env(self):
        p = get_preset("qwen-dashscope-thinking")
        assert p["api_key_env"] == "DASHSCOPE_API_KEY"

    def test_qwen_dashscope_thinking_models_qwen_plus_only(self):
        """qwen-plus mit enable_thinking=true ist Hybrid-Thinking auf DashScope.
        qwq-plus wurde entfernt (Streaming-only auf DashScope, hier nicht nutzbar)."""
        p = get_preset("qwen-dashscope-thinking")
        assert p["models"] == ["qwen-plus"]
        assert "qwq-plus" not in p["models"]

    def test_qwen_dashscope_thinking_extracts_reasoning(self):
        """DashScope liefert reasoning_content als separates JSON-Feld,
        nicht inline als <think>-Tag. Adapter muss es explizit extrahieren."""
        p = get_preset("qwen-dashscope-thinking")
        assert p.get("extracts_reasoning") is True

    def test_qwen_dashscope_non_thinking_does_not_extract_reasoning(self):
        """Non-thinking Preset braucht kein Reasoning-Extract (waere immer leer)."""
        p = get_preset("qwen-dashscope")
        assert not p.get("extracts_reasoning", False)


class TestPresetDeepSeek:

    def test_deepseek_url(self):
        p = get_preset("deepseek")
        assert "api.deepseek.com" in p["api_url"]
        assert "chat/completions" in p["api_url"]

    def test_deepseek_response_path(self):
        p = get_preset("deepseek")
        assert p["response_path"] == "choices[0].message.content"

    def test_deepseek_format_standard(self):
        p = get_preset("deepseek")
        assert p["message_format"] == "standard"

    def test_deepseek_auth_bearer(self):
        p = get_preset("deepseek")
        assert p["auth_format"] == "bearer"

    def test_deepseek_api_key_env(self):
        p = get_preset("deepseek")
        assert p["api_key_env"] == "DEEPSEEK_API_KEY"

    def test_deepseek_models(self):
        p = get_preset("deepseek")
        assert "deepseek-chat" in p["models"]
        assert "deepseek-reasoner" in p["models"]

    def test_deepseek_no_extra_body(self):
        """DeepSeek braucht kein extra_body — Reasoner-Verhalten via Modell-Auswahl."""
        p = get_preset("deepseek")
        assert "extra_body" not in p

    def test_deepseek_extracts_reasoning(self):
        """DeepSeek-Reasoner liefert reasoning_content; Adapter muss extrahieren.
        Bei deepseek-chat ist das Feld leer/fehlt - bleibt harmlos."""
        p = get_preset("deepseek")
        assert p.get("extracts_reasoning") is True


class TestPresetThinkingConventions:
    """DashScope nutzt 'enable_thinking', Nemotron nutzt 'disable_thinking' —
    nicht austauschbar. Stelle sicher, dass beide Welten korrekt nebeneinander
    leben."""

    def test_dashscope_uses_enable_thinking(self):
        p = get_preset("qwen-dashscope-thinking")
        assert "enable_thinking" in p["extra_body"]
        assert "disable_thinking" not in p["extra_body"]

    def test_nemotron_uses_disable_thinking(self):
        p = get_preset("openai-no-thinking")
        assert "disable_thinking" in p["extra_body"]
        assert "enable_thinking" not in p["extra_body"]


class TestPresetApiKeyEnv:
    """Phase 8: Presets deklarieren ihre bevorzugte Key-Env explizit."""

    def test_openai_preset_has_api_key_env(self):
        p = get_preset("openai")
        assert p["api_key_env"] == "OPENAI_API_KEY"

    def test_anthropic_preset_has_api_key_env(self):
        p = get_preset("anthropic")
        assert p["api_key_env"] == "ANTHROPIC_API_KEY"

    def test_gemini_preset_has_api_key_env(self):
        p = get_preset("gemini")
        assert p["api_key_env"] == "GEMINI_API_KEY"
