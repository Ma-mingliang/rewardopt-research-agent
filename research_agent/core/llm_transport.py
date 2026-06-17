"""LLM transport layer with resilience and retry logic.

Provides unified LLM call wrapper with:
- Transient error detection and retry
- Exponential backoff with jitter
- Request deduplication via hash
- Response caching for resume
- Secret redaction in error messages
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

import httpx


class ErrorCategory(str, Enum):
    """Classification of LLM errors."""
    TRANSIENT = "transient"  # Retry immediately
    RATE_LIMITED = "rate_limited"  # Retry with backoff
    PERMANENT = "permanent"  # Do not retry
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LLMTransportResult:
    """Result from LLM transport call."""
    ok: bool
    content: str = ""
    raw_response_type: str = ""
    provider: str = ""
    model: str = ""
    attempt_count: int = 0
    error_type: str | None = None
    error_message_redacted: str | None = None
    transient: bool = False
    retryable: bool = False
    request_hash: str = ""
    response_hash: str | None = None
    duration_seconds: float = 0.0
    cache_hit: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "ok": self.ok,
            "content": self.content[:500] if self.content else "",
            "raw_response_type": self.raw_response_type,
            "provider": self.provider,
            "model": self.model,
            "attempt_count": self.attempt_count,
            "error_type": self.error_type,
            "error_message_redacted": self.error_message_redacted,
            "transient": self.transient,
            "retryable": self.retryable,
            "request_hash": self.request_hash,
            "response_hash": self.response_hash,
            "duration_seconds": round(self.duration_seconds, 3),
            "cache_hit": self.cache_hit,
        }


# Transient error patterns that should be retried
TRANSIENT_PATTERNS = [
    # SSL errors
    r"ssl\.SSLError",
    r"\[SSL.*\]",
    r"UNEXPECTED_EOF_WHILE_READING",
    r"SSL.*violation",
    r"ssl.*error",
    # Connection errors
    r"ConnectionError",
    r"ConnectError",
    r"Connection reset",
    r"Connection refused",
    r"Connection aborted",
    # Timeout errors
    r"TimeoutError",
    r"Timeout",
    r"timed out",
    # HTTP transient errors
    r"502 Bad Gateway",
    r"503 Service Unavailable",
    r"504 Gateway Timeout",
    r"429 Too Many Requests",
    # Network errors
    r"Network is unreachable",
    r"Host is unreachable",
    r"Name or service not known",
    r"Temporary failure in name resolution",
]

# Permanent error patterns that should NOT be retried
PERMANENT_PATTERNS = [
    r"401 Unauthorized",
    r"403 Forbidden",
    r"Invalid API key",
    r"Authentication failed",
    r"400 Bad Request",
    r"Invalid request",
    r"Prompt too long",
    r"context_length_exceeded",
    r"model_not_found",
    r"unsupported_response_format",
]

# Rate limit patterns
RATE_LIMIT_PATTERNS = [
    r"429",
    r"rate.limit",
    r"too.many.requests",
    r"quota.exceeded",
]


def compute_request_hash(messages: list[dict], model: str, temperature: float) -> str:
    """Compute stable hash for request deduplication."""
    content = json.dumps({
        "messages": messages,
        "model": model,
        "temperature": temperature,
    }, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def compute_response_hash(content: str) -> str:
    """Compute hash for response content."""
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def redact_error_message(message: str) -> str:
    """Redact sensitive information from error messages."""
    # Redact API keys (common patterns)
    redacted = re.sub(r'(api[_-]?key|token|secret|password|authorization)[\s:=]+\S+', r'\1=REDACTED', message, flags=re.IGNORECASE)
    # Redact bearer tokens
    redacted = re.sub(r'Bearer\s+\S+', 'Bearer REDACTED', redacted)
    # Redact long hex strings (potential tokens)
    redacted = re.sub(r'[0-9a-f]{32,}', 'REDACTED', redacted)
    return redacted


def classify_error(error: Exception) -> ErrorCategory:
    """Classify an error into a category."""
    error_str = str(error)
    error_type = type(error).__name__

    # Check permanent patterns first
    for pattern in PERMANENT_PATTERNS:
        if re.search(pattern, error_str, re.IGNORECASE):
            return ErrorCategory.PERMANENT

    # Check rate limit patterns
    for pattern in RATE_LIMIT_PATTERNS:
        if re.search(pattern, error_str, re.IGNORECASE):
            return ErrorCategory.RATE_LIMITED

    # Check transient patterns
    for pattern in TRANSIENT_PATTERNS:
        if re.search(pattern, error_str, re.IGNORECASE):
            return ErrorCategory.TRANSIENT
        if re.search(pattern, error_type, re.IGNORECASE):
            return ErrorCategory.TRANSIENT

    # Check for specific exception types
    if isinstance(error, (ssl.SSLError, httpx.ConnectError, httpx.TimeoutException)):
        return ErrorCategory.TRANSIENT

    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if status in (502, 503, 504):
            return ErrorCategory.TRANSIENT
        if status == 429:
            return ErrorCategory.RATE_LIMITED
        if status in (401, 403):
            return ErrorCategory.PERMANENT
        if status == 400:
            return ErrorCategory.PERMANENT

    return ErrorCategory.UNKNOWN


def is_retryable(error: Exception) -> bool:
    """Check if an error is retryable."""
    category = classify_error(error)
    return category in (ErrorCategory.TRANSIENT, ErrorCategory.RATE_LIMITED)


def calculate_backoff(
    attempt: int,
    initial_backoff: float = 2.0,
    max_backoff: float = 30.0,
    backoff_factor: float = 2.0,
    jitter: float = 0.5,
) -> float:
    """Calculate backoff time with jitter."""
    backoff = min(initial_backoff * (backoff_factor ** attempt), max_backoff)
    jitter_amount = backoff * jitter
    return backoff + random.uniform(-jitter_amount, jitter_amount)


def call_llm_with_transport_resilience(
    llm_client: Any,
    messages: list[dict],
    *,
    node_name: str = "unknown",
    request_id: str = "",
    timeout_s: float = 120.0,
    max_attempts: int = 3,
    initial_backoff_s: float = 2.0,
    max_backoff_s: float = 30.0,
    jitter: float = 0.5,
    retry_on: list[str] | None = None,
    observer: Any | None = None,
    cache: dict[str, str] | None = None,
) -> LLMTransportResult:
    """Call LLM with transport resilience.

    Args:
        llm_client: The LLM client instance.
        messages: Messages to send.
        node_name: Name of the calling node.
        request_id: Unique request identifier.
        timeout_s: Timeout in seconds.
        max_attempts: Maximum retry attempts.
        initial_backoff_s: Initial backoff time.
        max_backoff_s: Maximum backoff time.
        jitter: Jitter factor (0-1).
        retry_on: Additional error patterns to retry on.
        observer: Optional observer for events.
        cache: Optional cache for responses.

    Returns:
        LLMTransportResult with the outcome.
    """
    start_time = time.monotonic()
    model = getattr(llm_client, '_model', 'unknown')
    provider = getattr(llm_client, '_provider', 'unknown')

    # Compute request hash
    temperature = 0.0
    request_hash = compute_request_hash(messages, model, temperature)

    # Check cache
    if cache and request_hash in cache:
        cached_content = cache[request_hash]
        return LLMTransportResult(
            ok=True,
            content=cached_content,
            raw_response_type="cached",
            provider=provider,
            model=model,
            attempt_count=0,
            request_hash=request_hash,
            response_hash=compute_response_hash(cached_content),
            duration_seconds=time.monotonic() - start_time,
            cache_hit=True,
        )

    last_error = None
    last_error_category = ErrorCategory.UNKNOWN
    attempt = 0

    for attempt in range(max_attempts):
        try:
            # Call LLM
            response = llm_client.call(
                system_prompt=messages[0]["content"] if messages else "",
                user_prompt=messages[1]["content"] if len(messages) > 1 else "",
                temperature=temperature,
                max_tokens=None,
                response_format="json",
            )

            content = response.content
            if content:
                # Cache response
                if cache is not None:
                    cache[request_hash] = content

                return LLMTransportResult(
                    ok=True,
                    content=content,
                    raw_response_type="json",
                    provider=provider,
                    model=model,
                    attempt_count=attempt + 1,
                    request_hash=request_hash,
                    response_hash=compute_response_hash(content),
                    duration_seconds=time.monotonic() - start_time,
                )

            # Empty response - not a transport error
            return LLMTransportResult(
                ok=False,
                error_type="empty_response",
                error_message_redacted="LLM returned empty response",
                transient=False,
                retryable=False,
                attempt_count=attempt + 1,
                request_hash=request_hash,
                duration_seconds=time.monotonic() - start_time,
            )

        except Exception as e:
            last_error = e
            last_error_category = classify_error(e)
            error_type = type(e).__name__

            # Emit event
            if observer:
                observer.emit("llm_transport_error",
                             node_name=node_name,
                             attempt=attempt + 1,
                             error_type=error_type,
                             error_category=last_error_category.value,
                             transient=last_error_category in (ErrorCategory.TRANSIENT, ErrorCategory.RATE_LIMITED))

            # Check if should retry
            if last_error_category == ErrorCategory.PERMANENT:
                break

            if attempt < max_attempts - 1:
                backoff = calculate_backoff(
                    attempt,
                    initial_backoff=initial_backoff_s,
                    max_backoff=max_backoff_s,
                    jitter=jitter,
                )
                if last_error_category == ErrorCategory.RATE_LIMITED:
                    backoff = max(backoff, 5.0)  # Minimum 5s for rate limits
                time.sleep(backoff)

    # All attempts failed
    return LLMTransportResult(
        ok=False,
        error_type=type(last_error).__name__ if last_error else "unknown",
        error_message_redacted=redact_error_message(str(last_error)) if last_error else "Unknown error",
        transient=last_error_category in (ErrorCategory.TRANSIENT, ErrorCategory.RATE_LIMITED),
        retryable=last_error_category in (ErrorCategory.TRANSIENT, ErrorCategory.RATE_LIMITED),
        attempt_count=attempt + 1,
        request_hash=request_hash,
        duration_seconds=time.monotonic() - start_time,
    )
