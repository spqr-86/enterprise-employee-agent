"""Offline AnswerProvider serving hand-written contract JSON keyed by question text.

Used by the offline eval run and tests. It is never a recording of a real provider.
"""

# ANCHOR: Deterministic stand-in for AnswerProvider (Issue #8, Task 7's offline eval and unit
# tests elsewhere). Content is looked up by exact question text and returned verbatim; there is
# no model call and no cost. ``requests`` records every AnswerRequest passed to complete(), in
# order, so callers can assert on what the pipeline sent without a mock transport.

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal

from enterprise_employee_agent.llm.provider import AnswerRequest, ProviderResponse, Usage


class ScriptedProvider:
    def __init__(
        self,
        responses: Mapping[str, str],
        *,
        key: Callable[[AnswerRequest], str] = lambda r: r.question,
    ) -> None:
        self._responses = dict(responses)
        self._key = key
        self.requests: list[AnswerRequest] = []

    def complete(self, request: AnswerRequest) -> ProviderResponse:
        self.requests.append(request)
        lookup_key = self._key(request)
        try:
            content = self._responses[lookup_key]
        except KeyError as error:
            raise LookupError(f"no scripted response for key: {lookup_key!r}") from error
        return ProviderResponse(
            content=content,
            usage=Usage(input_tokens=0, output_tokens=0, cost_usd=Decimal("0")),
            raw={"scripted": True},
            provider_model=request.model.model_id,
            latency_seconds=0.0,
        )
