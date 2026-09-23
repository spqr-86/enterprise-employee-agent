"""Composition, mode selection, identities, and the offline script (Issue #14)."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from pathlib import Path

import pytest

from enterprise_employee_agent.app import (
    OFFLINE_MODEL,
    DemoApplication,
    DemoSettings,
    OfflineDemoProvider,
    build_demo_application,
    load_scripted_fixture,
)
from enterprise_employee_agent.evals.live import DECISION_MODEL
from enterprise_employee_agent.knowledge.access import load_document_access_map
from enterprise_employee_agent.leave.access_policy import resolve_identity
from enterprise_employee_agent.leave.assistant import AssistantOutcomeKind, answer_for_actor
from enterprise_employee_agent.leave.contracts import (
    ActorRole,
    WorkflowError,
    WorkflowErrorCode,
    load_demo_access_manifest,
)
from enterprise_employee_agent.llm.provider import (
    AnswerRequest,
    ModelConfig,
    ProviderError,
    ProviderErrorKind,
)

NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
MANIFEST_PATH = Path("data/synthetic_protected/demo-access-v1.json")


def _demo(tmp_path: Path, *, api_key: str | None = None) -> DemoApplication:
    counter = itertools.count(1)
    return build_demo_application(
        DemoSettings(database_path=tmp_path / "demo.sqlite", openrouter_api_key=api_key),
        clock=lambda: NOW,
        id_factory=lambda prefix: f"{prefix}-{next(counter):04d}",
    )


def test_settings_from_env_defaults_to_offline_and_var_database() -> None:
    settings = DemoSettings.from_env({})
    assert settings.database_path == Path("var/demo.sqlite")
    assert settings.openrouter_api_key is None


def test_settings_from_env_reads_key_and_database_path() -> None:
    settings = DemoSettings.from_env(
        {"OPENROUTER_API_KEY": "sk-test", "DEMO_DATABASE_PATH": "/tmp/x.sqlite"}
    )
    assert settings.openrouter_api_key == "sk-test"
    assert settings.database_path == Path("/tmp/x.sqlite")


def test_empty_key_counts_as_unset() -> None:
    assert DemoSettings.from_env({"OPENROUTER_API_KEY": ""}).openrouter_api_key is None


def test_offline_mode_without_key(tmp_path) -> None:
    mode = _demo(tmp_path).mode()
    assert mode.live is False
    assert mode.label == "offline · scripted"


def test_live_mode_with_key_uses_the_decision_model(tmp_path) -> None:
    mode = _demo(tmp_path, api_key="sk-test-not-used").mode()
    assert mode.live is True
    assert mode.model_id == DECISION_MODEL.model_id
    assert mode.label == f"live · {DECISION_MODEL.model_id}"


def test_identities_list_all_six_manifest_identities(tmp_path) -> None:
    options = _demo(tmp_path).identities()
    assert [option.identity_id for option in options] == [
        "employee-alice",
        "employee-bob",
        "employee-carol",
        "manager-morgan",
        "manager-riley",
        "hr-harper",
    ]
    assert options[5].role is ActorRole.HR


def test_can_create_request_matches_create_draft_allowed_roles(tmp_path) -> None:
    # T5, final review: base.html used to check role.value == "employee" itself; web/ must not
    # check roles, so the nav link is driven by this flag, computed from the same allowed_roles
    # CREATE_DRAFT uses everywhere else.
    demo = _demo(tmp_path)
    by_id = {option.identity_id: option for option in demo.identities()}
    assert by_id["employee-alice"].can_create_request is True
    assert by_id["manager-morgan"].can_create_request is False
    assert by_id["hr-harper"].can_create_request is False


def test_identity_resolves_known_and_rejects_unknown(tmp_path) -> None:
    demo = _demo(tmp_path)
    assert demo.identity("hr-harper").display_name == "Harper HR"
    for bad in ("employee-zed", "", "../etc"):
        with pytest.raises(WorkflowError) as error:
            demo.identity(bad)
        assert error.value.code is WorkflowErrorCode.UNAUTHORIZED


def test_offline_suggestions_come_from_the_script(tmp_path) -> None:
    demo = _demo(tmp_path)
    assert "How long is parental leave in the US?" in demo.suggested_questions()
    assert len(demo.suggested_leave_descriptions()) == 1


def test_live_mode_has_no_scripted_suggestions(tmp_path) -> None:
    demo = _demo(tmp_path, api_key="sk-test-not-used")
    assert demo.suggested_questions() == ()
    assert demo.suggested_leave_descriptions() == ()


def test_offline_provider_turns_a_missing_script_into_a_provider_error() -> None:
    provider = OfflineDemoProvider({})
    request = AnswerRequest(
        model=ModelConfig(model_id="m", max_tokens=1, timeout_seconds=1.0),
        system_prompt="s",
        user_prompt="u",
        question="unscripted",
        retrieved_ids=(),
    )
    with pytest.raises(ProviderError) as error:
        provider.complete(request)
    assert error.value.kind is ProviderErrorKind.MALFORMED_RESPONSE
    assert error.value.detail == "no scripted response"


@pytest.mark.parametrize("actor_id", ["employee-alice", "manager-morgan", "hr-harper"])
def test_every_scripted_question_is_grounded_for_every_role(actor_id) -> None:
    # Guards the fixture against retrieval drift: a citation outside the retrieved set would
    # turn the scripted answer into a contract violation (UNAVAILABLE).
    fixture = load_scripted_fixture()
    manifest = load_demo_access_manifest(MANIFEST_PATH)
    resolve_identity(manifest, actor_id)
    for question in fixture.questions:
        outcome = answer_for_actor(
            question,
            manifest=manifest,
            actor_id=actor_id,
            access_map=load_document_access_map(),
            provider=OfflineDemoProvider(fixture.responses),
            model=OFFLINE_MODEL,
        )
        assert outcome.kind in {AssistantOutcomeKind.ANSWERED, AssistantOutcomeKind.ESCALATED}
