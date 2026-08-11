# src/conclave/infrastructure/universal/resilient.py
"""ResilientAdapter — Retry/Backoff-Wrapper fuer den UniversalAdapter.

Faengt transiente HTTP-Fehler (429, 5xx, Timeout) ab und
mappt sie auf Domain-Errors. Retry nur bei transienten Fehlern,
permanente Fehler (400, 401, 403) werden sofort durchgereicht.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator

import httpx

from conclave.domain.conversation import Conversation
from conclave.domain.errors import ProviderRateLimit, ProviderTimeout, ProviderUnavailable
from conclave.domain.model_response import TokenUsage
from conclave.domain.participant import Participant
from conclave.infrastructure.log import get_logger

logger = get_logger("infrastructure.resilient")


def _default_sleep(seconds: float) -> None:
    time.sleep(seconds)


class ResilientAdapter:
    """Wrapper der Retry/Backoff und Error-Mapping hinzufuegt.

    Args:
        adapter: Der innere Adapter (UniversalAdapter oder kompatibel)
        max_retries: Maximale Anzahl Wiederholungen bei transienten Fehlern
        backoff_base: Basis fuer exponentielles Backoff in Sekunden
        sleep_fn: Injizierbare Sleep-Funktion (fuer Tests)
    """

    def __init__(
        self,
        adapter,
        max_retries: int = 3,
        backoff_base: float = 2.0,
        sleep_fn: Callable[[float], None] = _default_sleep,
    ):
        self._adapter = adapter
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._sleep = sleep_fn

    @property
    def provider(self) -> str:
        return self._adapter.provider

    @property
    def last_usage(self) -> TokenUsage | None:
        return self._adapter.last_usage

    def complete(self, conversation: Conversation, participant: Participant) -> str:
        return self._with_retry(
            lambda: self._adapter.complete(conversation, participant)
        )

    def stream(
        self, conversation: Conversation, participant: Participant
    ) -> Iterator[str]:
        # Streaming: kein Retry — der Stream ist einmalig
        return self._adapter.stream(conversation, participant)

    def _with_retry(self, fn: Callable) -> str:
        last_exception = None
        for attempt in range(self._max_retries + 1):
            try:
                return fn()
            except httpx.TimeoutException as exc:
                last_exception = exc
                if attempt < self._max_retries:
                    wait = self._backoff_base ** attempt
                    logger.warning("Timeout bei %s, Retry %d/%d in %.1fs",
                                   self.provider, attempt + 1, self._max_retries, wait)
                    self._sleep(wait)
                    continue
                raise ProviderTimeout(self.provider) from exc
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                last_exception = exc

                # Permanent — kein Retry
                if status < 500 and status != 429:
                    raise

                # 429 Rate Limit
                if status == 429:
                    retry_after = _parse_retry_after(exc.response)
                    if attempt < self._max_retries:
                        wait = retry_after or (self._backoff_base ** attempt)
                        logger.warning("Rate Limit bei %s, Retry %d/%d in %.1fs",
                                       self.provider, attempt + 1, self._max_retries, wait)
                        self._sleep(wait)
                        continue
                    raise ProviderRateLimit(self.provider, retry_after) from exc

                # 5xx Server Error
                if attempt < self._max_retries:
                    wait = self._backoff_base ** attempt
                    logger.warning("Server-Fehler %d bei %s, Retry %d/%d in %.1fs",
                                   status, self.provider, attempt + 1, self._max_retries, wait)
                    self._sleep(wait)
                    continue
                raise ProviderUnavailable(self.provider, status) from exc

        # Sollte nicht erreichbar sein, aber sicherheitshalber
        raise ProviderUnavailable(self.provider, 0) from last_exception


def _parse_retry_after(response: httpx.Response) -> float | None:
    """Versucht Retry-After Header oder Body-Hinweis zu parsen."""
    header = response.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    # Gemini gibt retry-Info im Body: "Please retry in 7.371630858s."
    try:
        import re
        text = response.text
        match = re.search(r'retry in ([\d.]+)s', text)
        if match:
            return float(match.group(1))
    except Exception:
        pass
    return None
