"""LLM client with retry, QPS control, and JSON parsing."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from research_agent.core.exceptions import LLMCallError, LLMResponseParseError
from research_agent.core.output import append_jsonl


@dataclass
class LLMResponse:
    content: str
    parsed: dict | list | None
    tokens_used: int
    model: str
    latency_seconds: float


class LLMClient:
    """LLM client for OpenAI-compatible APIs."""

    def __init__(self, config: dict[str, Any], log_path: Path | None = None):
        self._provider = config.get("provider", "openai_compatible")
        self._model = config.get("model", "mimo-v2.5-pro")
        self._base_url = config.get("base_url", "")
        self._api_key_env = config.get("api_key_env", "MIMO_API_KEY")
        self._api_key = os.environ.get(self._api_key_env, "")
        self._timeout = config.get("timeout_seconds", 120)
        self._max_retries = config.get("max_retries", 3)
        self._retry_delay = config.get("retry_delay_seconds", 5)
        self._max_tokens = config.get("max_tokens", 4096)
        self._qps = config.get("qps", 2.0)
        self._log_path = log_path
        self._last_call_time: float = 0.0

    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: str = "json",
        seed: int | None = None,
    ) -> LLMResponse:
        """Call the LLM API with retry and QPS control.

        Args:
            system_prompt: System message.
            user_prompt: User message.
            temperature: Sampling temperature.
            max_tokens: Max tokens to generate (overrides config default).
            response_format: "json" or "text".
            seed: Seed parameter for deterministic output.

        Returns:
            LLMResponse with content, parsed JSON, and metadata.

        Raises:
            LLMCallError: After max_retries failures.
            LLMResponseParseError: After max_retries JSON parse failures.
        """
        if not self._api_key:
            raise LLMCallError(
                f"API key not found in environment variable '{self._api_key_env}'",
                retries=0,
                last_error="Missing API key",
            )

        self._enforce_qps()

        effective_max_tokens = max_tokens or self._max_tokens
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        last_error = ""
        raw_response = ""

        for attempt in range(self._max_retries + 1):
            start_time = time.monotonic()
            try:
                resp_dict = self._raw_call(messages, temperature, effective_max_tokens, seed)
                latency = time.monotonic() - start_time

                content = resp_dict.get("content", "")
                reasoning = resp_dict.get("reasoning_content", "")

                # If content is empty but reasoning has output, the model exhausted
                # max_tokens on thinking. Fall back to reasoning content, or retry
                # with higher max_tokens.
                if not content and reasoning:
                    content = reasoning
                    self._log_call(system_prompt, user_prompt, 0, latency, False,
                                   note="content empty, using reasoning_content")
                elif not content and not reasoning:
                    last_error = "Both content and reasoning_content are empty"
                    self._log_call(system_prompt, user_prompt, 0, latency, False)
                    if attempt < self._max_retries:
                        # Double max_tokens on retry
                        effective_max_tokens = min(effective_max_tokens * 2, 16384)
                        time.sleep(self._retry_delay)
                        continue

                raw_response = content

                if response_format == "json":
                    parsed = self._try_parse_json(content)
                    if parsed is None:
                        # Append instruction and retry
                        messages[-1] = {
                            "role": "user",
                            "content": user_prompt + "\n\nReturn valid JSON only.",
                        }
                        last_error = "JSON parse failed"
                        if attempt < self._max_retries:
                            time.sleep(self._retry_delay)
                            continue
                        self._log_call(system_prompt, user_prompt, 0, latency, False)
                        raise LLMResponseParseError(
                            f"Failed to parse JSON after {self._max_retries} retries",
                            raw_response,
                        )
                else:
                    parsed = None

                self._log_call(system_prompt, user_prompt, 0, latency, True)
                return LLMResponse(
                    content=content,
                    parsed=parsed,
                    tokens_used=0,  # TODO: extract from API response
                    model=self._model,
                    latency_seconds=latency,
                )

            except (httpx.TimeoutException, httpx.HTTPStatusError, OSError) as e:
                latency = time.monotonic() - start_time
                last_error = str(e)
                self._log_call(system_prompt, user_prompt, 0, latency, False)
                if attempt < self._max_retries:
                    time.sleep(self._retry_delay)
                    continue

        raise LLMCallError(
            f"LLM API failed after {self._max_retries} retries: {last_error}",
            retries=self._max_retries,
            last_error=last_error,
        )

    def _raw_call(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        seed: int | None,
    ) -> dict[str, str]:
        """Make a raw HTTP call to the LLM API.

        Returns dict with 'content' and 'reasoning_content'.
        Some reasoning models (e.g. mimo) put chain-of-thought in 'reasoning_content'
        and the final answer in 'content'. When max_tokens is too low for the reasoning
        budget, 'content' may be empty while 'reasoning_content' has the thinking.
        """
        url = f"{self._base_url.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if seed is not None:
            body["seed"] = seed

        # MiMo compatibility: disable thinking mode to get responses in content field
        if "mimo" in self._model.lower() or "xiaomimimo" in self._base_url.lower():
            body["thinking"] = {"type": "disabled"}

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            message = data["choices"][0]["message"]
            return {
                "content": message.get("content", ""),
                "reasoning_content": message.get("reasoning_content", ""),
            }

    def _try_parse_json(self, text: str) -> dict | list | None:
        """Try to parse JSON from text, handling markdown code blocks."""
        # Strip markdown code block wrappers
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove first and last lines (```json and ```)
            if lines[-1].strip() == "```":
                lines = lines[1:-1]
            elif lines[0].strip().startswith("```"):
                lines = lines[1:]
            cleaned = "\n".join(lines)

        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            return None

    def _enforce_qps(self) -> None:
        """Sleep if needed to respect QPS limit."""
        if self._qps <= 0:
            return
        min_interval = 1.0 / self._qps
        elapsed = time.monotonic() - self._last_call_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_call_time = time.monotonic()

    def _log_call(
        self,
        system_prompt: str,
        user_prompt: str,
        tokens_used: int,
        latency: float,
        success: bool,
        note: str = "",
    ) -> None:
        """Append call record to llm_calls.jsonl."""
        if self._log_path is None:
            return
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": self._model,
            "input_tokens": tokens_used,
            "latency_seconds": round(latency, 3),
            "success": success,
            "system_prompt_preview": system_prompt[:200],
            "user_prompt_preview": user_prompt[:200],
        }
        if note:
            record["note"] = note
        append_jsonl(self._log_path, record)
