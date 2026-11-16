import re


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


class EmptyConversation(ConclaveError):
    """Conversation hat noch keinen Prompt, der an ein Modell gesendet werden kann."""
    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        super().__init__(
            f"Conversation '{conversation_id}' enthält noch keine Nachricht. "
            "Bitte zuerst eine Nachricht schreiben."
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


class ProviderTargetBlocked(ProviderError):
    """Ziel der Provider-Anfrage ist nicht erlaubt (nicht oeffentlich oder nicht aufloesbar)."""
    def __init__(self, provider: str, reason: str):
        super().__init__(provider, f"Ziel nicht erlaubt ({reason}).")


# ── Fehlertexte fuer Clients und Logs ───────────────────────────────────

_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s'\"<>]+", re.IGNORECASE)
_SECRETS = (
    (re.compile(r"(?i)\b(key|api_key|apikey|token|access_token|secret)=[^&\s'\"]+"), r"\1=***"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer ***"),
    (re.compile(r"\b(?:sk|cva|cvh|cvr)[-_][A-Za-z0-9_-]{6,}"), "***"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"), "***"),
)


def redact_secrets(text: str, *, urls: bool = True) -> str:
    """Schwaerzt Keys (und URLs) in einem Fehlertext."""
    text = str(text)
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    return _URL.sub("<url>", text) if urls else text


def public_message(exc: BaseException) -> str:
    """Text eines Fehlers fuer Clients: eigene Meldungen geschwaerzt, fremde nur mit Typ."""
    if isinstance(exc, (ConclaveError, ValueError)) or type(exc).__module__.startswith("httpx"):
        return redact_secrets(str(exc))
    return f"Interner Fehler ({type(exc).__name__}), Details im Server-Log."


class TaskSourceError(ConclaveError):
    """Ticket-Quelle (z. B. Kanzo) nicht erreichbar oder lieferte einen Fehler."""


class TaskNotFound(TaskSourceError):
    def __init__(self, task_ref: str, detail: str = ""):
        self.task_ref = task_ref
        super().__init__(f"Task '{task_ref}' was not found{': ' + detail if detail else '.'}")


class TaskFormatError(TaskSourceError):
    """Antwort der Ticket-Quelle hat ein unbekanntes Format - im Zweifel ablehnen."""
