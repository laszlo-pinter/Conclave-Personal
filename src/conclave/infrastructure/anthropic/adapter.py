# src/conclave/infrastructure/anthropic/adapter.py

from collections.abc import Iterator

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore

from conclave.domain.conversation import Conversation
from conclave.domain.message import MessageAuthorType
from conclave.domain.context_report import (
    ContextReport,
    attach_context_report,
    native_context_report,
    select_messages,
)
from conclave.domain.model_response import Completion, TokenUsage
from conclave.domain.participant import Participant
from conclave.infrastructure.log import get_logger, request_logger
from conclave.infrastructure.system_prompt import SystemPrompt, assemble_system_prompt

logger = get_logger("infrastructure.anthropic")


class AnthropicAdapter:
    """Ruft die Anthropic API auf – unterstützt complete() und stream()."""

    DEFAULT_MODEL = "claude-sonnet-5"
    DEFAULT_MAX_TOKENS = 4096

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        system_prompt: str | None = None,
        max_messages: int | None = None,
    ):
        if anthropic is None:
            raise ImportError(
                "Das 'anthropic'-Paket ist nicht installiert. "
                "Bitte installieren mit: pip install conclave[anthropic]"
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._system_prompt = system_prompt
        # Ohne Limit (None/0) voller Verlauf wie bisher; sonst Kuerzung wie beim UniversalAdapter
        self._max_messages = max_messages

    @property
    def provider(self) -> str:
        return "anthropic"

    def _build_system(self, conversation: Conversation) -> SystemPrompt:
        """System-Prompt wie beim UniversalAdapter: Agent-Prompt, context_files, Regeln, Workspace."""
        return assemble_system_prompt(self._system_prompt, conversation)

    def _sent(self, conversation: Conversation) -> list:
        return select_messages(conversation.messages, self._max_messages)

    def _report(self, conversation: Conversation, system: SystemPrompt, sent: list | None = None):
        return native_context_report(conversation, system, adapter="anthropic-native",
                                     sent=sent if sent is not None else self._sent(conversation),
                                     limit=self._max_messages)

    def context_report(self, conversation: Conversation, participant: Participant) -> ContextReport:
        """Vorschau ohne Provider-Aufruf."""
        return self._report(conversation, self._build_system(conversation))

    def complete(self, conversation: Conversation, participant: Participant) -> Completion:
        sent = self._sent(conversation)
        messages = self._build_messages(conversation, sent)
        system = self._build_system(conversation)

        kwargs = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": messages,
        }
        if system.text:
            kwargs["system"] = system.text

        try:
            with request_logger(logger, operation="anthropic.complete", model=self._model):
                response = self._client.messages.create(**kwargs)
        except Exception as exc:
            attach_context_report(exc, self._report(conversation, system, sent))
            raise

        usage = TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return Completion(text=response.content[0].text, usage=usage,
                          report=self._report(conversation, system, sent))

    def stream(
        self, conversation: Conversation, participant: Participant
    ) -> Iterator[str | Completion]:
        sent = self._sent(conversation)
        messages = self._build_messages(conversation, sent)
        system = self._build_system(conversation)

        kwargs = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": messages,
        }
        if system.text:
            kwargs["system"] = system.text

        logger.debug("anthropic.stream start", extra={"model": self._model})
        with self._client.messages.stream(**kwargs) as stream:
            for event in stream:
                if (
                    event.type == "content_block_delta"
                    and event.delta.type == "text_delta"
                ):
                    yield event.delta.text
            # Usage nach Stream-Ende
            final = stream.get_final_message()
            usage = TokenUsage(
                input_tokens=final.usage.input_tokens,
                output_tokens=final.usage.output_tokens,
            )
        yield Completion(usage=usage, report=self._report(conversation, system, sent))

    def _build_messages(self, conversation: Conversation, messages: list | None = None) -> list[dict]:
        """Wandelt Conclave-Messages in das Anthropic-Format um."""
        result = []
        for message in (conversation.messages if messages is None else messages):
            role = "user" if message.author_type == MessageAuthorType.USER else "assistant"
            result.append({"role": role, "content": message.content})
        return result
