# src/conclave/infrastructure/openai/adapter.py

from collections.abc import Iterator

try:
    import openai
except ImportError:
    openai = None  # type: ignore

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
        max_messages: int | None = None,
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
        # Ohne Limit (None/0) voller Verlauf wie bisher; sonst Kuerzung wie beim UniversalAdapter
        self._max_messages = max_messages

    @property
    def provider(self) -> str:
        return "openai"

    def _build_instructions(self, conversation: Conversation) -> SystemPrompt:
        """System-Prompt wie beim UniversalAdapter: Agent-Prompt, context_files, Regeln, Workspace."""
        return assemble_system_prompt(self._system_prompt, conversation)

    def _sent(self, conversation: Conversation) -> list:
        return select_messages(conversation.messages, self._max_messages)

    def _report(self, conversation: Conversation, instructions: SystemPrompt, sent: list | None = None):
        return native_context_report(conversation, instructions, adapter="openai-native",
                                     sent=sent if sent is not None else self._sent(conversation),
                                     limit=self._max_messages)

    def context_report(self, conversation: Conversation, participant: Participant) -> ContextReport:
        """Vorschau ohne Provider-Aufruf."""
        return self._report(conversation, self._build_instructions(conversation))

    def complete(self, conversation: Conversation, participant: Participant) -> Completion:
        sent = self._sent(conversation)
        input_msgs = self._build_input(conversation, sent)
        instructions = self._build_instructions(conversation)
        try:
            with request_logger(logger, operation="openai.complete", model=self._model):
                response = self._client.responses.create(
                    model=self._model,
                    input=input_msgs,
                    **({"instructions": instructions.text} if instructions.text else {}),
                )
        except Exception as exc:
            attach_context_report(exc, self._report(conversation, instructions, sent))
            raise
        usage = TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return Completion(text=response.output_text, usage=usage,
                          report=self._report(conversation, instructions, sent))

    def stream(
        self, conversation: Conversation, participant: Participant
    ) -> Iterator[str | Completion]:
        sent = self._sent(conversation)
        input_msgs = self._build_input(conversation, sent)
        instructions = self._build_instructions(conversation)
        logger.debug("openai.stream start", extra={"model": self._model})
        stream = self._client.responses.create(
            model=self._model,
            input=input_msgs,
            **({"instructions": instructions.text} if instructions.text else {}),
            stream=True,
        )
        usage = None
        for event in stream:
            if event.type == "response.output_text.delta":
                yield event.delta
            elif event.type == "response.completed":
                usage = TokenUsage(
                    input_tokens=event.response.usage.input_tokens,
                    output_tokens=event.response.usage.output_tokens,
                )
        yield Completion(usage=usage, report=self._report(conversation, instructions, sent))

    def _build_input(self, conversation: Conversation, messages: list | None = None) -> list[dict]:
        """Wandelt Conclave-Messages in das OpenAI Responses-Format um."""
        result = []
        for message in (conversation.messages if messages is None else messages):
            role = "user" if message.author_type == MessageAuthorType.USER else "assistant"
            result.append({"role": role, "content": message.content})
        return result
