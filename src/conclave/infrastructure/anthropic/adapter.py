# src/conclave/infrastructure/anthropic/adapter.py

from collections.abc import Iterator

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore

from conclave.domain.conversation import Conversation
from conclave.domain.message import MessageAuthorType
from conclave.domain.context_report import native_context_report
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

    @property
    def provider(self) -> str:
        return "anthropic"

    def _build_system(self, conversation: Conversation) -> SystemPrompt:
        """System-Prompt wie beim UniversalAdapter: Agent-Prompt, context_files, Regeln, Workspace."""
        return assemble_system_prompt(self._system_prompt, conversation)

    def _report(self, conversation: Conversation, system: SystemPrompt):
        return native_context_report(conversation, system, adapter="anthropic-native")

    def complete(self, conversation: Conversation, participant: Participant) -> Completion:
        messages = self._build_messages(conversation)
        system = self._build_system(conversation)

        kwargs = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": messages,
        }
        if system.text:
            kwargs["system"] = system.text

        with request_logger(logger, operation="anthropic.complete", model=self._model):
            response = self._client.messages.create(**kwargs)

        usage = TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return Completion(text=response.content[0].text, usage=usage,
                          report=self._report(conversation, system))

    def stream(
        self, conversation: Conversation, participant: Participant
    ) -> Iterator[str | Completion]:
        messages = self._build_messages(conversation)
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
        yield Completion(usage=usage, report=self._report(conversation, system))

    def _build_messages(self, conversation: Conversation) -> list[dict]:
        """Wandelt Conclave-Messages in das Anthropic-Format um."""
        result = []
        for message in conversation.messages:
            role = "user" if message.author_type == MessageAuthorType.USER else "assistant"
            result.append({"role": role, "content": message.content})
        return result
