# tests/infrastructure/test_universal/test_resilient_adapter.py
"""Tests fuer ResilientAdapter — Retry/Backoff/Error-Mapping."""

import pytest
import httpx

from conclave.domain.errors import ProviderRateLimit, ProviderTimeout, ProviderUnavailable
from conclave.infrastructure.universal.resilient import ResilientAdapter


class FakeAdapter:
    """Simuliert einen Adapter der konfigurierbare Fehler wirft."""

    def __init__(self, responses):
        """responses: Liste von Ergebnissen. str = Erfolg, Exception = Fehler."""
        self._responses = list(responses)
        self._call_count = 0
        self._last_usage = None

    @property
    def provider(self) -> str:
        return "test-provider"

    @property
    def last_usage(self):
        return self._last_usage

    def complete(self, conversation, participant):
        self._call_count += 1
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    @property
    def call_count(self) -> int:
        return self._call_count


def _http_error(status_code: int, text: str = "") -> httpx.HTTPStatusError:
    """Erzeugt einen httpx.HTTPStatusError mit gegebenem Status."""
    request = httpx.Request("POST", "https://example.com")
    response = httpx.Response(status_code, request=request, text=text)
    return httpx.HTTPStatusError(
        f"Client error '{status_code}'", request=request, response=response
    )


class TestRetryOn429:
    def test_retries_on_429_then_returns_response(self):
        inner = FakeAdapter([
            _http_error(429, "rate limit"),
            _http_error(429, "rate limit"),
            "Erfolg nach Retry",
        ])
        sleeps = []
        adapter = ResilientAdapter(inner, max_retries=3, sleep_fn=sleeps.append)
        result = adapter.complete(None, None)
        assert result == "Erfolg nach Retry"
        assert inner.call_count == 3
        assert len(sleeps) == 2  # 2 Retries, dann Erfolg

    def test_raises_provider_rate_limit_after_exhausted_retries(self):
        inner = FakeAdapter([
            _http_error(429),
            _http_error(429),
            _http_error(429),
            _http_error(429),
        ])
        adapter = ResilientAdapter(inner, max_retries=3, sleep_fn=lambda _: None)
        with pytest.raises(ProviderRateLimit) as exc_info:
            adapter.complete(None, None)
        assert exc_info.value.provider == "test-provider"

    def test_parses_retry_after_from_body(self):
        inner = FakeAdapter([
            _http_error(429, "Please retry in 7.5s."),
            "OK",
        ])
        sleeps = []
        adapter = ResilientAdapter(inner, max_retries=3, sleep_fn=sleeps.append)
        adapter.complete(None, None)
        assert sleeps[0] == pytest.approx(7.5)


class TestRetryOn5xx:
    def test_retries_on_500(self):
        inner = FakeAdapter([
            _http_error(500),
            "Erfolg",
        ])
        adapter = ResilientAdapter(inner, max_retries=3, sleep_fn=lambda _: None)
        assert adapter.complete(None, None) == "Erfolg"

    def test_retries_on_502(self):
        inner = FakeAdapter([_http_error(502), "OK"])
        adapter = ResilientAdapter(inner, max_retries=3, sleep_fn=lambda _: None)
        assert adapter.complete(None, None) == "OK"

    def test_retries_on_503(self):
        inner = FakeAdapter([_http_error(503), "OK"])
        adapter = ResilientAdapter(inner, max_retries=3, sleep_fn=lambda _: None)
        assert adapter.complete(None, None) == "OK"

    def test_raises_provider_unavailable_after_exhausted(self):
        inner = FakeAdapter([_http_error(500)] * 4)
        adapter = ResilientAdapter(inner, max_retries=3, sleep_fn=lambda _: None)
        with pytest.raises(ProviderUnavailable) as exc_info:
            adapter.complete(None, None)
        assert exc_info.value.status_code == 500


class TestNoRetryOnPermanentErrors:
    def test_does_not_retry_on_400(self):
        inner = FakeAdapter([_http_error(400)])
        adapter = ResilientAdapter(inner, max_retries=3, sleep_fn=lambda _: None)
        with pytest.raises(httpx.HTTPStatusError):
            adapter.complete(None, None)
        assert inner.call_count == 1

    def test_does_not_retry_on_401(self):
        inner = FakeAdapter([_http_error(401)])
        adapter = ResilientAdapter(inner, max_retries=3, sleep_fn=lambda _: None)
        with pytest.raises(httpx.HTTPStatusError):
            adapter.complete(None, None)
        assert inner.call_count == 1

    def test_does_not_retry_on_403(self):
        inner = FakeAdapter([_http_error(403)])
        adapter = ResilientAdapter(inner, max_retries=3, sleep_fn=lambda _: None)
        with pytest.raises(httpx.HTTPStatusError):
            adapter.complete(None, None)
        assert inner.call_count == 1


class TestTimeoutHandling:
    def test_maps_timeout_to_provider_timeout(self):
        inner = FakeAdapter([httpx.ReadTimeout("timeout")] * 4)
        adapter = ResilientAdapter(inner, max_retries=3, sleep_fn=lambda _: None)
        with pytest.raises(ProviderTimeout) as exc_info:
            adapter.complete(None, None)
        assert exc_info.value.provider == "test-provider"

    def test_retries_on_timeout_then_succeeds(self):
        inner = FakeAdapter([
            httpx.ReadTimeout("timeout"),
            "Erfolg nach Timeout-Retry",
        ])
        adapter = ResilientAdapter(inner, max_retries=3, sleep_fn=lambda _: None)
        assert adapter.complete(None, None) == "Erfolg nach Timeout-Retry"
        assert inner.call_count == 2


class TestBackoff:
    def test_exponential_backoff(self):
        inner = FakeAdapter([
            _http_error(500),
            _http_error(500),
            _http_error(500),
            "OK",
        ])
        sleeps = []
        adapter = ResilientAdapter(inner, max_retries=3, backoff_base=2.0, sleep_fn=sleeps.append)
        adapter.complete(None, None)
        assert sleeps == [1.0, 2.0, 4.0]  # 2^0, 2^1, 2^2


class TestProperties:
    def test_provider_delegates(self):
        inner = FakeAdapter([])
        adapter = ResilientAdapter(inner)
        assert adapter.provider == "test-provider"

    def test_last_usage_delegates(self):
        inner = FakeAdapter([])
        inner._last_usage = "mock-usage"
        adapter = ResilientAdapter(inner)
        assert adapter.last_usage == "mock-usage"
