"""Provider-neutral answer boundary. Business code depends only on these types."""

# ANCHOR: The seam between business code and any concrete LLM provider (Issue #8). Business
# code (the answer pipeline, Task 5; the offline eval, Task 7) depends only on AnswerProvider
# and the plain-data types here, never on a provider SDK. AnswerRequest.record() is what a run
# artifact stores about the request: it holds no transport fields (no API key, no headers) by
# construction, since AnswerRequest never carries them. ProviderResponse.raw is the allowlisted
# subset of the provider's response body a concrete provider chooses to keep; hidden reasoning
# must never appear in it (enforced by the concrete provider, e.g. openrouter.py).

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ModelConfig:
    model_id: str
    max_tokens: int
    timeout_seconds: float
    extra_params: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AnswerRequest:
    model: ModelConfig
    system_prompt: str
    user_prompt: str
    question: str
    retrieved_ids: tuple[str, ...]
    # (schema_name, json_schema) sent as the provider's structured-output contract; None means
    # "use the provider's own default" (OpenRouterProvider defaults to the answer contract, so
    # every existing answer_question() call stays byte-identical). Set explicitly by callers that
    # want a different structured-output contract, e.g. propose_leave_fields's leave-field
    # proposal schema (final review I-1).
    response_schema: tuple[str, dict[str, Any]] | None = None

    def record(self) -> dict[str, object]:
        """What a run artifact stores about the request: never keys, headers or transport."""
        return {
            "question": self.question,
            "retrieved_ids": list(self.retrieved_ids),
            "model_id": self.model.model_id,
            "max_tokens": self.model.max_tokens,
            "timeout_seconds": self.model.timeout_seconds,
            "params": dict(self.model.extra_params),
        }


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal | None


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    content: str
    usage: Usage
    raw: Mapping[str, object]
    provider_model: str | None
    latency_seconds: float


class ProviderErrorKind(StrEnum):
    TIMEOUT = "timeout"
    HTTP_ERROR = "http_error"
    TRANSPORT_ERROR = "transport_error"
    MALFORMED_RESPONSE = "malformed_response"


class ProviderError(Exception):
    def __init__(
        self, kind: ProviderErrorKind, detail: str, *, status_code: int | None = None
    ) -> None:
        super().__init__(f"{kind.value}: {detail}")
        self.kind = kind
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ModelPricing:
    prompt_usd_per_token: Decimal
    completion_usd_per_token: Decimal


class AnswerProvider(Protocol):
    def complete(self, request: AnswerRequest) -> ProviderResponse: ...
