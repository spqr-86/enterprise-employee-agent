from __future__ import annotations

from decimal import Decimal

import pytest

from enterprise_employee_agent.llm.provider import AnswerRequest, ModelConfig
from enterprise_employee_agent.llm.scripted import ScriptedProvider

MODEL = ModelConfig(model_id="offline/scripted", max_tokens=1, timeout_seconds=1.0)


def _request(question: str) -> AnswerRequest:
    return AnswerRequest(
        model=MODEL, system_prompt="s", user_prompt="u", question=question, retrieved_ids=()
    )


def test_returns_scripted_content_for_known_question() -> None:
    provider = ScriptedProvider({"q1": '{"status": "abstained"}'})
    response = provider.complete(_request("q1"))
    assert response.content == '{"status": "abstained"}'
    assert response.usage.cost_usd == Decimal("0")
    assert [request.question for request in provider.requests] == ["q1"]


def test_unknown_question_is_a_lookup_error() -> None:
    with pytest.raises(LookupError, match="no scripted response"):
        ScriptedProvider({}).complete(_request("unknown"))
