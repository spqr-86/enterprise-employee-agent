from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from enterprise_employee_agent.leave.field_proposal import (
    LEAVE_FIELD_PROPOSAL_JSON_SCHEMA,
    LEAVE_FIELD_PROPOSAL_SCHEMA_NAME,
)
from enterprise_employee_agent.llm.contract import ANSWER_JSON_SCHEMA, ANSWER_SCHEMA_NAME
from enterprise_employee_agent.llm.openrouter import (
    OpenRouterProvider,
    fetch_model_listing,
    fetch_model_pricing,
)
from enterprise_employee_agent.llm.provider import (
    AnswerRequest,
    ModelConfig,
    ProviderError,
    ProviderErrorKind,
)

FIXTURES = Path("tests/fixtures/llm")
SECRET = "sk-or-test-secret-value"
MODEL = ModelConfig(
    model_id="openai/gpt-5-mini",
    max_tokens=4000,
    timeout_seconds=12.5,
    extra_params={"reasoning": {"effort": "low"}},
)


def _request() -> AnswerRequest:
    return AnswerRequest(
        model=MODEL,
        system_prompt="system text",
        user_prompt="user text",
        question="How many weeks?",
        retrieved_ids=("people-policies/leave-of-absence/us.md",),
    )


def _provider(handler) -> OpenRouterProvider:  # type: ignore[no-untyped-def]
    ticks = iter([100.0, 101.25])
    return OpenRouterProvider(
        SECRET,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: next(ticks),
    )


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_request_shape_sent_to_openrouter() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_fixture("openrouter-answered.json"))

    _provider(handler).complete(_request())
    sent = seen[0]
    body = json.loads(sent.content)
    assert sent.url == "https://openrouter.ai/api/v1/chat/completions"
    assert sent.headers["Authorization"] == f"Bearer {SECRET}"
    assert body["model"] == "openai/gpt-5-mini"
    assert body["messages"] == [
        {"role": "system", "content": "system text"},
        {"role": "user", "content": "user text"},
    ]
    assert body["max_tokens"] == 4000
    assert body["reasoning"] == {"effort": "low"}
    assert body["provider"] == {"require_parameters": True}
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"] == ANSWER_JSON_SCHEMA


def test_build_payload_defaults_to_the_answer_schema_when_none_is_given() -> None:
    # I-1 regression guard: AnswerRequest.response_schema=None (the field's default, and what
    # every answer_question() call still passes) must keep sending answer_contract, byte-
    # identical to the pre-fix payload — no network call needed to assert this.
    payload = OpenRouterProvider(SECRET, client=httpx.Client()).build_payload(_request())
    assert payload["response_format"]["json_schema"]["name"] == ANSWER_SCHEMA_NAME
    assert payload["response_format"]["json_schema"]["schema"] == ANSWER_JSON_SCHEMA


def test_build_payload_uses_the_requests_own_response_schema_when_given() -> None:
    # I-1: propose_leave_fields sets response_schema to the leave-field-proposal schema; the
    # provider must send exactly that schema/name, not the answer contract.
    request = AnswerRequest(
        model=MODEL,
        system_prompt="system text",
        user_prompt="user text",
        question="free text",
        retrieved_ids=(),
        response_schema=(LEAVE_FIELD_PROPOSAL_SCHEMA_NAME, LEAVE_FIELD_PROPOSAL_JSON_SCHEMA),
    )
    payload = OpenRouterProvider(SECRET, client=httpx.Client()).build_payload(request)
    assert payload["response_format"]["json_schema"]["name"] == LEAVE_FIELD_PROPOSAL_SCHEMA_NAME
    assert payload["response_format"]["json_schema"]["schema"] == LEAVE_FIELD_PROPOSAL_JSON_SCHEMA
    assert payload["response_format"]["json_schema"]["schema"] != ANSWER_JSON_SCHEMA


def test_extra_params_cannot_override_fixed_fields() -> None:
    model = ModelConfig(
        model_id="m", max_tokens=1, timeout_seconds=1.0, extra_params={"model": "x"}
    )
    request = AnswerRequest(
        model=model, system_prompt="s", user_prompt="u", question="q", retrieved_ids=()
    )
    provider = _provider(lambda request: httpx.Response(200))
    with pytest.raises(ValueError, match="override"):
        provider.build_payload(request)


def test_successful_response_is_parsed_with_usage_and_cost() -> None:
    response = _provider(
        lambda request: httpx.Response(200, json=_fixture("openrouter-answered.json"))
    ).complete(_request())
    assert json.loads(response.content)["status"] == "answered"
    assert response.usage.input_tokens == 10500
    assert response.usage.output_tokens == 180
    assert response.usage.cost_usd == Decimal("0.000311")
    assert response.provider_model == "openai/gpt-5-mini"
    assert response.latency_seconds == pytest.approx(1.25)


def test_missing_cost_is_reported_as_none() -> None:
    body = _fixture("openrouter-answered.json")
    del body["usage"]["cost"]  # type: ignore[index]
    response = _provider(lambda request: httpx.Response(200, json=body)).complete(_request())
    assert response.usage.cost_usd is None


def test_timeout_surfaces_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout", request=request)

    with pytest.raises(ProviderError) as excinfo:
        _provider(handler).complete(_request())
    assert excinfo.value.kind is ProviderErrorKind.TIMEOUT


def test_http_error_surfaces_typed_error_with_status() -> None:
    with pytest.raises(ProviderError) as excinfo:
        _provider(lambda request: httpx.Response(503, json={"error": {}})).complete(_request())
    assert excinfo.value.kind is ProviderErrorKind.HTTP_ERROR
    assert excinfo.value.status_code == 503


def test_connection_error_surfaces_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated", request=request)

    with pytest.raises(ProviderError) as excinfo:
        _provider(handler).complete(_request())
    assert excinfo.value.kind is ProviderErrorKind.TRANSPORT_ERROR


def test_unexpected_body_surfaces_malformed_response() -> None:
    with pytest.raises(ProviderError) as excinfo:
        _provider(lambda request: httpx.Response(200, json={"choices": []})).complete(_request())
    assert excinfo.value.kind is ProviderErrorKind.MALFORMED_RESPONSE


def test_api_key_is_absent_from_recorded_request_and_response() -> None:
    # Controller ruling: the brief's original version of this test was tautological
    # (AnswerRequest never holds the key; `raw` comes from a fixture without it, so the
    # assertions would pass even if the implementation leaked the key elsewhere). This
    # version captures the actual HTTP request sent through the mock transport, proves the
    # secret DID flow through the call path in the Authorization header, and then asserts
    # it is absent from both the request record and the recorded response.
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_fixture("openrouter-answered.json"))

    response = _provider(handler).complete(_request())

    sent = seen[0]
    assert sent.headers["Authorization"] == f"Bearer {SECRET}"

    assert SECRET not in json.dumps(_request().record())
    assert SECRET not in json.dumps(dict(response.raw))


def test_recorded_response_keeps_only_allowlisted_fields() -> None:
    response = _provider(
        lambda request: httpx.Response(200, json=_fixture("openrouter-answered.json"))
    ).complete(_request())
    assert set(response.raw) == {"id", "model", "usage", "finish_reason", "content"}
    assert "reasoning" not in json.dumps(dict(response.raw))
    assert response.raw["content"] == response.content


def test_record_contains_question_documents_model_and_params() -> None:
    assert _request().record() == {
        "question": "How many weeks?",
        "retrieved_ids": ["people-policies/leave-of-absence/us.md"],
        "model_id": "openai/gpt-5-mini",
        "max_tokens": 4000,
        "timeout_seconds": 12.5,
        "params": {"reasoning": {"effort": "low"}},
    }


def test_fetch_model_pricing_reads_decimal_prices() -> None:
    body = {
        "data": [
            {
                "id": "openai/gpt-5-mini",
                "pricing": {"prompt": "0.00000025", "completion": "0.000002"},
            },
            {"id": "other/model", "pricing": {"prompt": "1", "completion": "1"}},
        ]
    }
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    pricing = fetch_model_pricing(["openai/gpt-5-mini"], client=client)
    assert pricing["openai/gpt-5-mini"].prompt_usd_per_token == Decimal("0.00000025")
    assert pricing["openai/gpt-5-mini"].completion_usd_per_token == Decimal("0.000002")


@pytest.mark.parametrize(
    "body",
    [
        {"data": []},
        {"data": [{"id": "openai/gpt-5-mini", "pricing": {"prompt": "-1", "completion": "0"}}]},
        {"data": [{"id": "openai/gpt-5-mini", "pricing": {"prompt": "abc", "completion": "0"}}]},
    ],
)
def test_fetch_model_pricing_rejects_missing_or_invalid_prices(body: dict[str, object]) -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    with pytest.raises(ProviderError) as excinfo:
        fetch_model_pricing(["openai/gpt-5-mini"], client=client)
    assert excinfo.value.kind is ProviderErrorKind.MALFORMED_RESPONSE


def test_http_error_detail_keeps_sanitized_truncated_provider_message() -> None:
    message = (
        "Invalid schema for response_format: Bearer sk-or-v1-abcdef123 leaked sk-or-v1-zzz9 "
        + "x" * 500
    )
    with pytest.raises(ProviderError) as excinfo:
        _provider(
            lambda request: httpx.Response(400, json={"error": {"message": message}})
        ).complete(_request())
    detail = excinfo.value.detail
    assert excinfo.value.status_code == 400
    assert detail.startswith("provider returned HTTP 400: Invalid schema for response_format")
    assert "sk-or-" not in detail
    assert "abcdef123" not in detail
    assert "zzz9" not in detail
    assert len(detail) <= len("provider returned HTTP 400: ") + 300


def test_http_error_with_non_json_body_keeps_status_only() -> None:
    with pytest.raises(ProviderError) as excinfo:
        _provider(lambda request: httpx.Response(502, text="<html>bad gateway</html>")).complete(
            _request()
        )
    assert excinfo.value.detail == "provider returned HTTP 502"


def test_fetch_model_listing_reads_pricing_and_supported_parameters() -> None:
    body = {
        "data": [
            {
                "id": "openai/gpt-5-mini",
                "pricing": {"prompt": "0.00000025", "completion": "0.000002"},
                "supported_parameters": ["max_tokens", "response_format", "reasoning"],
            },
            {"id": "deepseek/deepseek-v3.2", "pricing": {"prompt": "0", "completion": "0"}},
        ]
    }
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    listing = fetch_model_listing(["openai/gpt-5-mini", "deepseek/deepseek-v3.2"], client=client)
    assert len(requests) == 1
    gpt = listing["openai/gpt-5-mini"]
    assert gpt.pricing.completion_usd_per_token == Decimal("0.000002")
    assert gpt.supported_parameters == frozenset({"max_tokens", "response_format", "reasoning"})
    assert listing["deepseek/deepseek-v3.2"].supported_parameters == frozenset()
