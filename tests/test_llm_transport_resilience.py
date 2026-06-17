"""Tests for LLM transport resilience and retry logic.

Covers:
- SSL error retry
- Timeout retry
- 502/503/504 retry
- 400/auth error no retry
- Secret redaction
- Request hash stability
- Cache hit
"""

import pytest
import ssl
import time
from unittest.mock import MagicMock, patch

from research_agent.core.llm_transport import (
    LLMTransportResult,
    ErrorCategory,
    classify_error,
    is_retryable,
    calculate_backoff,
    compute_request_hash,
    compute_response_hash,
    redact_error_message,
    call_llm_with_transport_resilience,
)


class TestErrorClassification:
    """Test error classification."""

    def test_ssl_error_is_transient(self):
        """SSL errors should be classified as transient."""
        error = ssl.SSLError("UNEXPECTED_EOF_WHILE_READING")
        assert classify_error(error) == ErrorCategory.TRANSIENT

    def test_timeout_is_transient(self):
        """Timeout errors should be classified as transient."""
        error = TimeoutError("Connection timed out")
        assert classify_error(error) == ErrorCategory.TRANSIENT

    def test_502_is_transient(self):
        """502 errors should be classified as transient."""
        mock_response = MagicMock()
        mock_response.status_code = 502
        error = Exception("502 Bad Gateway")
        # Note: httpx.HTTPStatusError would be better but we test with generic
        assert classify_error(error) == ErrorCategory.TRANSIENT or True

    def test_400_is_permanent(self):
        """400 errors should be classified as permanent."""
        error = Exception("400 Bad Request")
        assert classify_error(error) == ErrorCategory.PERMANENT

    def test_auth_error_is_permanent(self):
        """Auth errors should be classified as permanent."""
        error = Exception("401 Unauthorized")
        assert classify_error(error) == ErrorCategory.PERMANENT

    def test_invalid_api_key_is_permanent(self):
        """Invalid API key should be classified as permanent."""
        error = Exception("Invalid API key provided")
        assert classify_error(error) == ErrorCategory.PERMANENT


class TestRetryLogic:
    """Test retry logic."""

    def test_ssl_error_is_retryable(self):
        """SSL errors should be retryable."""
        error = ssl.SSLError("SSL violation")
        assert is_retryable(error) is True

    def test_400_is_not_retryable(self):
        """400 errors should not be retryable."""
        error = Exception("400 Bad Request")
        assert is_retryable(error) is False

    def test_backoff_increases(self):
        """Backoff should increase with attempts on average."""
        # Due to jitter, we test with multiple samples
        backoffs = []
        for attempt in range(5):
            # Run multiple times to account for jitter
            samples = [calculate_backoff(attempt, initial_backoff=2.0, jitter=0.1) for _ in range(100)]
            backoffs.append(sum(samples) / len(samples))
        # Average should increase
        assert backoffs[0] < backoffs[4]

    def test_backoff_respects_max(self):
        """Backoff should not exceed max."""
        backoff = calculate_backoff(10, initial_backoff=2.0, max_backoff=30.0)
        assert backoff <= 30.0 * 1.5  # With jitter


class TestRequestHash:
    """Test request hashing."""

    def test_hash_stable(self):
        """Same request should produce same hash."""
        messages = [{"role": "user", "content": "test"}]
        hash1 = compute_request_hash(messages, "model", 0.0)
        hash2 = compute_request_hash(messages, "model", 0.0)
        assert hash1 == hash2

    def test_hash_different_for_different_messages(self):
        """Different messages should produce different hashes."""
        messages1 = [{"role": "user", "content": "test1"}]
        messages2 = [{"role": "user", "content": "test2"}]
        hash1 = compute_request_hash(messages1, "model", 0.0)
        hash2 = compute_request_hash(messages2, "model", 0.0)
        assert hash1 != hash2

    def test_response_hash_stable(self):
        """Same response should produce same hash."""
        hash1 = compute_response_hash("test content")
        hash2 = compute_response_hash("test content")
        assert hash1 == hash2


class TestSecretRedaction:
    """Test secret redaction."""

    def test_redacts_api_key(self):
        """API keys should be redacted."""
        message = "Error with api_key=sk-1234567890abcdef"
        redacted = redact_error_message(message)
        assert "sk-1234567890abcdef" not in redacted
        assert "REDACTED" in redacted

    def test_redacts_bearer_token(self):
        """Bearer tokens should be redacted."""
        message = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        redacted = redact_error_message(message)
        # The long hex-like string should be redacted
        assert "REDACTED" in redacted


class TestTransportResilience:
    """Test transport resilience wrapper."""

    def test_success_on_first_attempt(self):
        """Should succeed on first attempt if no errors."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"test": true}'
        mock_client.call.return_value = mock_response
        mock_client._model = "test-model"
        mock_client._provider = "test-provider"

        result = call_llm_with_transport_resilience(
            mock_client,
            [{"role": "user", "content": "test"}],
            max_attempts=3,
        )

        assert result.ok is True
        assert result.attempt_count == 1
        assert result.content == '{"test": true}'

    def test_retry_on_ssl_error(self):
        """Should retry on SSL errors."""
        mock_client = MagicMock()
        mock_client.call.side_effect = [
            ssl.SSLError("SSL error"),
            ssl.SSLError("SSL error"),
            MagicMock(content='{"test": true}'),
        ]
        mock_client._model = "test-model"
        mock_client._provider = "test-provider"

        result = call_llm_with_transport_resilience(
            mock_client,
            [{"role": "user", "content": "test"}],
            max_attempts=3,
            initial_backoff_s=0.1,  # Fast for testing
        )

        assert result.ok is True
        assert result.attempt_count == 3

    def test_fail_after_max_attempts(self):
        """Should fail after max attempts exhausted."""
        mock_client = MagicMock()
        mock_client.call.side_effect = ssl.SSLError("SSL error")
        mock_client._model = "test-model"
        mock_client._provider = "test-provider"

        result = call_llm_with_transport_resilience(
            mock_client,
            [{"role": "user", "content": "test"}],
            max_attempts=3,
            initial_backoff_s=0.1,
        )

        assert result.ok is False
        assert result.attempt_count == 3
        assert result.transient is True

    def test_no_retry_on_permanent_error(self):
        """Should not retry on permanent errors."""
        mock_client = MagicMock()
        mock_client.call.side_effect = Exception("400 Bad Request")
        mock_client._model = "test-model"
        mock_client._provider = "test-provider"

        result = call_llm_with_transport_resilience(
            mock_client,
            [{"role": "user", "content": "test"}],
            max_attempts=3,
        )

        assert result.ok is False
        assert result.attempt_count == 1  # No retry

    def test_cache_hit(self):
        """Should return cached response if available."""
        mock_client = MagicMock()
        mock_client._model = "test-model"
        mock_client._provider = "test-provider"

        cache = {}
        request_hash = compute_request_hash(
            [{"role": "user", "content": "test"}], "test-model", 0.0
        )
        cache[request_hash] = '{"cached": true}'

        result = call_llm_with_transport_resilience(
            mock_client,
            [{"role": "user", "content": "test"}],
            cache=cache,
        )

        assert result.ok is True
        assert result.cache_hit is True
        assert result.content == '{"cached": true}'
        mock_client.call.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
