# tests/infrastructure/test_universal/test_profiles.py
"""Tests fuer ProviderProfiles — Provider-spezifische Request/Response-Logik."""

import pytest

from conclave.infrastructure.universal.profiles import (
    AnthropicProfile,
    GeminiProfile,
    OpenAIResponsesProfile,
    StandardProfile,
    get_profile,
)


class TestStandardProfile:
    def test_build_headers_with_bearer(self):
        profile = StandardProfile()
        headers = profile.build_headers("sk-test-key")
        assert headers["Authorization"] == "Bearer sk-test-key"
        assert headers["Content-Type"] == "application/json"

    def test_build_headers_without_key(self):
        profile = StandardProfile()
        headers = profile.build_headers("")
        assert "Authorization" not in headers

    def test_build_body_with_system(self):
        profile = StandardProfile()
        messages = [{"role": "user", "content": "Hallo"}]
        body = profile.build_body(messages, "gpt-4o", "Du bist ein Assistent.")
        assert body["model"] == "gpt-4o"
        assert body["messages"][0] == {"role": "system", "content": "Du bist ein Assistent."}
        assert body["messages"][1] == {"role": "user", "content": "Hallo"}

    def test_build_body_without_system(self):
        profile = StandardProfile()
        messages = [{"role": "user", "content": "Hi"}]
        body = profile.build_body(messages, "gpt-4o", None)
        assert len(body["messages"]) == 1

    def test_build_url_passthrough(self):
        profile = StandardProfile()
        url, params = profile.build_url("https://api.openai.com/v1/chat/completions", "gpt-4o", "key")
        assert url == "https://api.openai.com/v1/chat/completions"
        assert params == {}

    def test_extract_response(self):
        profile = StandardProfile()
        data = {"choices": [{"message": {"content": "Antwort"}}]}
        assert profile.extract_response(data, "choices[0].message.content") == "Antwort"


class TestAnthropicProfile:
    def test_build_headers_includes_version(self):
        profile = AnthropicProfile()
        headers = profile.build_headers("sk-ant-test")
        assert headers["X-API-Key"] == "sk-ant-test"
        assert headers["anthropic-version"] == "2023-06-01"
        assert "Authorization" not in headers

    def test_build_body_has_max_tokens(self):
        profile = AnthropicProfile()
        messages = [{"role": "user", "content": "Hallo"}]
        body = profile.build_body(messages, "claude-sonnet-4-20250514", "System")
        assert body["max_tokens"] == 4096
        assert body["system"] == "System"
        assert body["messages"] == messages

    def test_build_body_without_system(self):
        profile = AnthropicProfile()
        messages = [{"role": "user", "content": "Hi"}]
        body = profile.build_body(messages, "claude-sonnet-4-20250514", None)
        assert "system" not in body
        assert body["max_tokens"] == 4096

    def test_extract_response_skips_non_text_blocks(self):
        profile = AnthropicProfile()
        data = {
            "content": [
                {"type": "thinking", "thinking": "", "signature": "sig"},
                {"type": "text", "text": "Hallo"},
                {"type": "text", "text": "Welt"},
            ]
        }

        assert profile.extract_response(data, "content[0].text") == "Hallo\nWelt"


class TestOpenAIResponsesProfile:
    def test_build_body_uses_input_not_messages(self):
        profile = OpenAIResponsesProfile()
        messages = [{"role": "user", "content": "Hallo"}]
        body = profile.build_body(messages, "gpt-5.4", "System")
        assert "input" in body
        assert "messages" not in body
        assert body["input"][0] == {"role": "system", "content": "System"}
        assert body["input"][1] == {"role": "user", "content": "Hallo"}

    def test_extract_response_from_output_array(self):
        profile = OpenAIResponsesProfile()
        data = {
            "output": [
                {"type": "reasoning", "summary": []},
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "Berlin"}
                    ],
                },
            ]
        }
        assert profile.extract_response(data, "output_text") == "Berlin"

    def test_extract_response_empty_output(self):
        profile = OpenAIResponsesProfile()
        data = {"output": []}
        assert profile.extract_response(data, "output_text") is None

    def test_build_headers_bearer(self):
        profile = OpenAIResponsesProfile()
        headers = profile.build_headers("sk-proj-test")
        assert headers["Authorization"] == "Bearer sk-proj-test"


class TestGeminiProfile:
    def test_build_url_replaces_model(self):
        profile = GeminiProfile()
        url, params = profile.build_url(
            "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            "gemini-flash-latest",
            "AIza-test",
        )
        assert "gemini-flash-latest" in url
        assert "{model}" not in url
        assert params == {"key": "AIza-test"}

    def test_build_headers_no_auth(self):
        profile = GeminiProfile()
        headers = profile.build_headers("AIza-test")
        assert "Authorization" not in headers
        assert "X-API-Key" not in headers

    def test_build_body_gemini_format(self):
        profile = GeminiProfile()
        messages = [{"role": "user", "parts": [{"text": "Hallo"}]}]
        body = profile.build_body(messages, "gemini-flash-latest", "System-Prompt")
        assert "contents" in body
        assert body["systemInstruction"] == {"parts": [{"text": "System-Prompt"}]}
        assert "model" not in body

    def test_build_body_without_system(self):
        profile = GeminiProfile()
        messages = [{"role": "user", "parts": [{"text": "Hi"}]}]
        body = profile.build_body(messages, "gemini-flash-latest", None)
        assert "systemInstruction" not in body


class TestGetProfile:
    def test_known_profiles(self):
        assert isinstance(get_profile("standard"), StandardProfile)
        assert isinstance(get_profile("anthropic"), AnthropicProfile)
        assert isinstance(get_profile("openai-responses"), OpenAIResponsesProfile)
        assert isinstance(get_profile("gemini"), GeminiProfile)

    def test_unknown_falls_back_to_standard(self):
        assert isinstance(get_profile("unknown-provider"), StandardProfile)

    def test_profiles_cover_all_presets(self):
        """Jedes Preset in presets.py muss ein passendes Profil haben."""
        from conclave.infrastructure.universal.presets import PRESETS
        for name, preset in PRESETS.items():
            if name == "custom":
                continue
            msg_format = preset.get("message_format", "standard")
            auth_format = preset.get("auth_format", "bearer")
            # Profil-Aufloesung wie im Adapter
            profile_key = msg_format
            if profile_key == "standard" and auth_format == "x-api-key":
                profile_key = "anthropic"
            profile = get_profile(profile_key)
            assert profile is not None, f"Kein Profil fuer Preset '{name}' (key='{profile_key}')"
