"""Exception classes for research-agent."""

from __future__ import annotations


class ResearchAgentError(Exception):
    """Base exception for all research-agent errors."""

    error_code: str = "UNKNOWN_ERROR"
    next_action: str = ""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            "ok": False,
            "error_code": self.error_code,
            "message": self.message,
            "next_action": self.next_action,
        }


class LLMCallError(ResearchAgentError):
    """LLM API call failed after retries exhausted."""

    error_code = "LLM_SERVICE_UNAVAILABLE"
    next_action = "Wait for LLM service to recover, then retry."

    def __init__(self, message: str, retries: int, last_error: str):
        self.retries = retries
        self.last_error = last_error
        super().__init__(message)


class LLMResponseParseError(ResearchAgentError):
    """LLM returned unparseable JSON after retries exhausted."""

    error_code = "LLM_INVALID_RESPONSE"
    next_action = "Wait for LLM service to recover, then retry."

    def __init__(self, message: str, raw_response: str):
        self.raw_response = raw_response
        super().__init__(message)


class GuardViolationError(ResearchAgentError):
    """Candidate patch violates permission boundaries."""

    error_code = "GUARD_VIOLATION"
    next_action = "Optimizer should regenerate candidate without violating constraints."

    def __init__(self, violations: list[str]):
        self.violations = violations
        super().__init__(f"Guard violations: {violations}")


class BudgetExhaustedError(ResearchAgentError):
    """Budget exhausted."""

    error_code = "BUDGET_EXHAUSTED"
    next_action = "Call 'report --json' to get results."

    def __init__(self, budget_type: str):
        super().__init__(f"Budget exhausted: {budget_type}")


class PatchApplyError(ResearchAgentError):
    """git apply failed."""

    error_code = "PATCH_APPLY_FAILED"
    next_action = "Check patch file and project state."

    def __init__(self, patch_path: str, git_error: str):
        super().__init__(f"Failed to apply patch {patch_path}: {git_error}")


class PatchRollbackError(ResearchAgentError):
    """git rollback failed."""

    error_code = "PATCH_ROLLBACK_FAILED"
    next_action = "Manual intervention required to restore workdir."

    def __init__(self, git_error: str):
        super().__init__(f"Failed to rollback: {git_error}")


class BaselineDriftError(ResearchAgentError):
    """Baseline hash mismatch detected by baseline guard."""

    error_code = "BASELINE_DRIFT"
    next_action = (
        "Run with --accept-baseline-migration to override, "
        "or update the baseline manifest to match current env.py."
    )

    def __init__(
        self,
        message: str,
        drift_type: str = "",
        env_hash: str = "",
        manifest_hash: str = "",
    ):
        self.drift_type = drift_type
        self.env_hash = env_hash
        self.manifest_hash = manifest_hash
        super().__init__(message)


class StateFileCorruptError(ResearchAgentError):
    """state.json cannot be parsed."""

    error_code = "STATE_FILE_CORRUPT"
    next_action = "Check state.json, or delete and re-init."

    def __init__(self, parse_error: str):
        super().__init__(f"state.json corrupt: {parse_error}")


class LiteratureError(ResearchAgentError):
    """Literature pipeline error (search/classify/select stage)."""

    def __init__(self, error_code: str, message: str, next_action: str):
        self.error_code = error_code
        self.next_action = next_action
        super().__init__(message)


class DependencyMissingError(ResearchAgentError):
    """Prerequisite dependency missing (objective, task_classification, etc.)."""

    def __init__(self, error_code: str, message: str, next_action: str):
        self.error_code = error_code
        self.next_action = next_action
        super().__init__(message)
