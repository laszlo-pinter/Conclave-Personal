# src/conclave/infrastructure/openai/adapter.py

from collections.abc import Iterator

try:
    import openai
except ImportError:
    openai = None  # type: ignore

from conclave.domain.conversation import Conversation
from conclave.domain.message import MessageAuthorType
from conclave.domain.model_response import TokenUsage
from conclave.domain.participant import Participant
from conclave.infrastructure.log import get_logger, request_logger

logger = get_logger("infrastructure.openai")


class OpenAIAdapter:
    """Ruft die OpenAI Responses-API auf (/v1/responses)."""

    DEFAULT_MODEL = "gpt-5.6"

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 4096,
        system_prompt: str | None = None,
    ):
        if openai is None:
            raise ImportError(
                "Das 'openai'-Paket ist nicht installiert. "
                "Bitte installieren mit: pip install conclave[openai]"
            )
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._system_prompt = system_prompt
        self._last_usage: TokenUsage | None = None

    @property
    def provider(self) -> str:
        return "openai"

    @property
    def last_usage(self) -> TokenUsage | None:
        return self._last_usage

    def _build_instructions(self, conversation: Conversation) -> str | None:
        parts = []
        if self._system_prompt:
            parts.append(self._system_prompt)
        rules = getattr(conversation, "rules", "")
        if rules:
            parts.append(f"Chat-Regeln:\n{rules}")
        return "\n\n".join(parts) if parts else None

    def complete(self, conversation: Conversation, participant: Participant) -> str:
        input_msgs = self._build_input(conversation)
        instructions = self._build_instructions(conversation)
        with request_logger(logger, operation="openai.complete", model=self._model):
            response = self._client.responses.create(
                model=self._model,
                input=input_msgs,
                **({"instructions": instructions} if instructions else {}),
            )
        self._last_usage = TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return response.output_text

    def stream(
        self, conversation: Conversation, participant: Participant
    ) -> Iterator[str]:
        input_msgs = self._build_input(conversation)
        instructions = self._build_instructions(conversation)
        logger.debug("openai.stream start", extra={"model": self._model})
        stream = self._client.responses.create(
            model=self._model,
            input=input_msgs,
            **({"instructions": instructions} if instructions else {}),
            stream=True,
        )
        for event in stream:
            if event.type == "response.output_text.delta":
                yield event.delta
            elif event.type == "response.completed":
                usage = event.response.usage
                self._last_usage = TokenUsage(
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                )

    def _build_input(self, conversation: Conversation) -> list[dict]:
        """Wandelt Conclave-Messages in das OpenAI Responses-Format um."""
        result = []
        for message in conversation.messages:
            role = "user" if message.author_type == MessageAuthorType.USER else "assistant"
            result.append({"role": role, "content": message.content})
        return result
