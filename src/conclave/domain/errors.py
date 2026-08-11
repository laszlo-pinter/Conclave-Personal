class ConclaveError(Exception):
    """Basis-Exception fuer alle Conclave-Domain-Fehler.

    Alle spezifischen Fehler erben von dieser Klasse.
    API-Layer mappt sie auf HTTP-Statuscodes.
    """


class AuthenticationError(ConclaveError):
    """Authentifizierung fehlgeschlagen."""
    def __init__(self, message: str = "Invalid or missing authentication token."):
        super().__init__(message)


class ConversationNotFound(ConclaveError):
    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        super().__init__(f"Conversation '{conversation_id}' was not found.")


class ParticipantAlreadyRegistered(ConclaveError):
    def __init__(self, participant_id: str, conversation_id: str):
        self.participant_id = participant_id
        self.conversation_id = conversation_id
        super().__init__(
            f"Participant '{participant_id}' is already registered "
            f"for conversation '{conversation_id}'."
        )


class ParticipantConversationMismatch(ConclaveError):
    def __init__(self, participant_conversation_id: str, conversation_id: str):
        self.participant_conversation_id = participant_conversation_id
        self.conversation_id = conversation_id
        super().__init__(
            f"Participant belongs to conversation "
            f"'{participant_conversation_id}', not '{conversation_id}'."
        )

class ParticipantNotRegistered(ConclaveError):
    def __init__(self, participant_id: str, conversation_id: str):
        self.participant_id = participant_id
        self.conversation_id = conversation_id
        super().__init__(
            f"Participant '{participant_id}' is not registered "
            f"for conversation '{conversation_id}'."
        )


class AdapterNotFound(ConclaveError):
    def __init__(self, participant_id: str):
        self.participant_id = participant_id
        super().__init__(
            f"No adapter registered for participant '{participant_id}'."
        )


class AgentNotFound(ConclaveError):
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        super().__init__(f"Agent '{agent_id}' was not found.")


class AgentAlreadyExists(ConclaveError):
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        super().__init__(f"Agent '{agent_id}' already exists.")


class FloorNotGranted(ConclaveError):
    """Participant hat kein Rederecht."""
    def __init__(self, participant_id: str, floor_holder: str | None):
        self.participant_id = participant_id
        self.floor_holder = floor_holder
        holder = f"'{floor_holder}'" if floor_holder else "niemand"
        super().__init__(
            f"Participant '{participant_id}' hat kein Rederecht. "
            f"Das Wort hat aktuell: {holder}."
        )


class NoFloorGranted(ConclaveError):
    """Kein Participant hat aktuell das Rederecht."""
    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        super().__init__(
            f"Kein Participant hat in Conversation '{conversation_id}' das Rederecht."
        )


# ── Provider-Fehler (Resilience) ─────────────────────────────────────────

class ProviderError(ConclaveError):
    """Basis fuer alle Provider-bezogenen Laufzeitfehler."""
    def __init__(self, provider: str, message: str):
        self.provider = provider
        super().__init__(f"Provider '{provider}': {message}")


class ProviderTimeout(ProviderError):
    """Provider hat nicht innerhalb des Timeouts geantwortet."""
    def __init__(self, provider: str):
        super().__init__(provider, "Timeout — keine Antwort innerhalb des Zeitlimits.")


class ProviderRateLimit(ProviderError):
    """Provider hat Rate Limit erreicht (429)."""
    def __init__(self, provider: str, retry_after: float | None = None):
        self.retry_after = retry_after
        msg = "Rate Limit erreicht (429)."
        if retry_after:
            msg += f" Retry nach {retry_after:.1f}s."
        super().__init__(provider, msg)


class ProviderUnavailable(ProviderError):
    """Provider ist temporaer nicht erreichbar (5xx)."""
    def __init__(self, provider: str, status_code: int):
        self.status_code = status_code
        super().__init__(provider, f"Temporaer nicht erreichbar (HTTP {status_code}).")
