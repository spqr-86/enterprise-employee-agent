"""OpenRouter chat-completions transport over httpx: one implementation of AnswerProvider.

The API key is sent only in the Authorization header and never stored. Timeouts, HTTP errors,
connection errors and unexpected bodies become ``ProviderError``. v0.1 does not retry.
"""

# ANCHOR: The only module in this codebase allowed to know OpenRouter's request/response shape.
# build_payload() is split out from complete() so the request-shape test can assert on it
# without a network round trip. RECORDED_RESPONSE_FIELDS is the allowlist enforced when turning
# a provider response into ProviderResponse.raw: message.reasoning (and anything else the
# provider returns) never reaches it, per the framework's ban on recording hidden reasoning.

from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from enterprise_employee_agent.llm.contract import ANSWER_JSON_SCHEMA, ANSWER_SCHEMA_NAME
from enterprise_employee_agent.llm.provider import (
    AnswerRequest,
    ModelPricing,
    ProviderError,
    ProviderErrorKind,
    ProviderResponse,
    Usage,
)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Top-level body fields kept in the run artifact. Everything else, including message.reasoning,
# is dropped: the framework forbids recording hidden model reasoning.
RECORDED_RESPONSE_FIELDS = ("id", "model", "provider", "created", "usage")
ERROR_MESSAGE_MAX_CHARS = 300
# The error body never carries the key; this is defence in depth before the text is recorded.
_SECRET_PATTERNS = (re.compile(r"Bearer\s+\S+", re.IGNORECASE), re.compile(r"sk-or-[\w-]*"))


def _error_message(response: httpx.Response) -> str | None:
    """``error.message`` from a JSON error body, secrets redacted, truncated; else None."""
    try:
        message = response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(message, str) or not message.strip():
        return None
    for pattern in _SECRET_PATTERNS:
        message = pattern.sub("[redacted]", message)
    return message[:ERROR_MESSAGE_MAX_CHARS]


class OpenRouterProvider:
    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client,
        base_url: str = OPENROUTER_BASE_URL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not api_key:
            raise ValueError("api_key must be non-empty")
        self._api_key = api_key
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._clock = clock

    def build_payload(self, request: AnswerRequest) -> dict[str, Any]:
        schema_name, schema_body = request.response_schema or (
            ANSWER_SCHEMA_NAME,
            ANSWER_JSON_SCHEMA,
        )
        payload: dict[str, Any] = {
            "model": request.model.model_id,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "max_tokens": request.model.max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema_body,
                },
            },
            "provider": {"require_parameters": True},
        }
        for key, value in request.model.extra_params.items():
            if key in payload:
                raise ValueError(f"extra param {key!r} would override a fixed request field")
            payload[key] = value
        return payload

    def complete(self, request: AnswerRequest) -> ProviderResponse:
        payload = self.build_payload(request)
        started = self._clock()
        try:
            http_response = self._client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=request.model.timeout_seconds,
            )
        except httpx.TimeoutException as error:
            raise ProviderError(
                ProviderErrorKind.TIMEOUT,
                f"no response within {request.model.timeout_seconds}s",
            ) from error
        except httpx.HTTPError as error:
            raise ProviderError(ProviderErrorKind.TRANSPORT_ERROR, type(error).__name__) from error
        latency = self._clock() - started

        if http_response.status_code >= 400:
            detail = f"provider returned HTTP {http_response.status_code}"
            message = _error_message(http_response)
            if message is not None:
                detail = f"{detail}: {message}"
            raise ProviderError(
                ProviderErrorKind.HTTP_ERROR, detail, status_code=http_response.status_code
            )
        try:
            body = http_response.json()
            choice = body["choices"][0]
            content = choice["message"]["content"]
            finish_reason = choice.get("finish_reason")
            usage = body["usage"]
            input_tokens = int(usage["prompt_tokens"])
            output_tokens = int(usage["completion_tokens"])
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
            raise ProviderError(
                ProviderErrorKind.MALFORMED_RESPONSE,
                f"unexpected response body: {type(error).__name__}",
            ) from error
        if not isinstance(content, str):
            raise ProviderError(ProviderErrorKind.MALFORMED_RESPONSE, "content is not a string")

        raw_cost = usage.get("cost")
        cost = (
            Decimal(str(raw_cost))
            if isinstance(raw_cost, int | float) and not isinstance(raw_cost, bool)
            else None
        )
        model = body.get("model")
        recorded: dict[str, object] = {
            key: body[key] for key in RECORDED_RESPONSE_FIELDS if key in body
        }
        recorded["finish_reason"] = finish_reason
        recorded["content"] = content
        return ProviderResponse(
            content=content,
            usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost),
            raw=recorded,
            provider_model=model if isinstance(model, str) else None,
            latency_seconds=latency,
        )


@dataclass(frozen=True, slots=True)
class ModelListing:
    pricing: ModelPricing
    supported_parameters: frozenset[str]


def fetch_model_listing(
    model_ids: Sequence[str],
    *,
    client: httpx.Client,
    base_url: str = OPENROUTER_BASE_URL,
    timeout_seconds: float = 30.0,
) -> dict[str, ModelListing]:
    """Read per-token USD prices and supported request parameters in one models-listing GET."""
    try:
        response = client.get(f"{base_url.rstrip('/')}/models", timeout=timeout_seconds)
    except httpx.TimeoutException as error:
        raise ProviderError(ProviderErrorKind.TIMEOUT, "models listing timed out") from error
    except httpx.HTTPError as error:
        raise ProviderError(ProviderErrorKind.TRANSPORT_ERROR, type(error).__name__) from error
    if response.status_code >= 400:
        raise ProviderError(
            ProviderErrorKind.HTTP_ERROR,
            f"models listing returned HTTP {response.status_code}",
            status_code=response.status_code,
        )
    try:
        listing = {item["id"]: item for item in response.json()["data"]}
    except (ValueError, KeyError, TypeError) as error:
        raise ProviderError(
            ProviderErrorKind.MALFORMED_RESPONSE, "unexpected models body"
        ) from error

    result: dict[str, ModelListing] = {}
    for model_id in model_ids:
        item = listing.get(model_id)
        if item is None:
            raise ProviderError(
                ProviderErrorKind.MALFORMED_RESPONSE, f"model not listed: {model_id}"
            )
        try:
            prompt = Decimal(str(item["pricing"]["prompt"]))
            completion = Decimal(str(item["pricing"]["completion"]))
        except (KeyError, TypeError, InvalidOperation) as error:
            raise ProviderError(
                ProviderErrorKind.MALFORMED_RESPONSE, f"invalid pricing for {model_id}"
            ) from error
        if prompt < 0 or completion < 0:
            raise ProviderError(
                ProviderErrorKind.MALFORMED_RESPONSE, f"negative pricing for {model_id}"
            )
        raw_parameters = item.get("supported_parameters")
        parameters = (
            frozenset(name for name in raw_parameters if isinstance(name, str))
            if isinstance(raw_parameters, list)
            else frozenset()
        )
        result[model_id] = ModelListing(
            pricing=ModelPricing(prompt_usd_per_token=prompt, completion_usd_per_token=completion),
            supported_parameters=parameters,
        )
    return result


def fetch_model_pricing(
    model_ids: Sequence[str],
    *,
    client: httpx.Client,
    base_url: str = OPENROUTER_BASE_URL,
    timeout_seconds: float = 30.0,
) -> dict[str, ModelPricing]:
    """Read per-token USD prices for the given models from the public models listing."""
    listing = fetch_model_listing(
        model_ids, client=client, base_url=base_url, timeout_seconds=timeout_seconds
    )
    return {model_id: item.pricing for model_id, item in listing.items()}
