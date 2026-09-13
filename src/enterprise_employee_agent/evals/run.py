"""Score the v0.1 micro-eval dataset (Issue #7) and print a report.

Knowledge-category cases are scored against a self-consistent stub answer in v0.1 — there is no
retrieval/model integration yet (Issue #8); this only exercises the schema/validator/scorer/
report pipeline end-to-end. Safety/workflow-category cases run against the real Issue #6
workflow contracts and the demo access manifest, except provider_failure, which has no LLM
adapter to call yet and is scored against a fixed placeholder outcome until that adapter exists.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path

from enterprise_employee_agent.evals.reporting import format_report
from enterprise_employee_agent.evals.schema import (
    EvalCategory,
    KnowledgeEvalCase,
    SafetyEvalCase,
    SafetyOutcome,
)
from enterprise_employee_agent.evals.scorer import (
    build_report,
    score_knowledge_case,
    score_safety_case,
)
from enterprise_employee_agent.evals.validator import (
    DatasetValidationError,
    load_cases,
    validate_dataset,
)
from enterprise_employee_agent.knowledge.corpus import load_manifest
from enterprise_employee_agent.leave.contracts import (
    ROLE_PROJECTION_FIELDS,
    ActorRole,
    ConfirmationEnvelope,
    ConfirmSubmitInput,
    DemoAccessManifest,
    EmployeeLeaveProjection,
    HrLeaveProjection,
    LeaveRequestPayload,
    ManagerLeaveProjection,
    NegativeAccessReason,
    RequestType,
    bind_server_command,
    command_fingerprint,
    load_demo_access_manifest,
    payload_digest,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
CASES_PATH = _REPO_ROOT / "evals" / "cases" / "v0.1.yaml"
DEMO_MANIFEST_PATH = _REPO_ROOT / "data" / "synthetic_protected" / "demo-access-v1.json"


def _stub_knowledge_answer(case: KnowledgeEvalCase) -> tuple[list[str], bool]:
    """A self-consistent fixture answer: correct by construction until real retrieval lands."""
    return list(case.expected_evidence), case.abstain_expected


def _score_prompt_injection(manifest: DemoAccessManifest) -> SafetyOutcome:
    has_denial = any(
        case.reason is NegativeAccessReason.CROSS_EMPLOYEE_ACCESS
        for case in manifest.negative_cases
    )
    return SafetyOutcome.REFUSED if has_denial else SafetyOutcome.ERROR_SURFACED


def _score_forbidden_disclosure() -> SafetyOutcome:
    manager_fields = ROLE_PROJECTION_FIELDS[ActorRole.MANAGER]
    return (
        SafetyOutcome.REDACTED
        if "employee_comment" not in manager_fields
        else SafetyOutcome.ERROR_SURFACED
    )


def _leave_payload() -> LeaveRequestPayload:
    return LeaveRequestPayload(
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 10),
        request_type=RequestType.CONTINUOUS,
    )


def _score_stale_confirmation() -> SafetyOutcome:
    payload = _leave_payload()
    envelope = ConfirmationEnvelope(
        request_id="req-1", request_version=1, payload_digest=payload_digest(payload)
    )
    is_stale = not envelope.matches(request_id="req-1", payload=payload, request_version=2)
    return SafetyOutcome.REJECTED_STALE if is_stale else SafetyOutcome.ERROR_SURFACED


def _score_duplicate_submission(manifest: DemoAccessManifest) -> SafetyOutcome:
    payload = _leave_payload()
    envelope = ConfirmationEnvelope(
        request_id="req-1", request_version=1, payload_digest=payload_digest(payload)
    )
    command_input = ConfirmSubmitInput(
        idempotency_key="confirm-req-1-attempt-1",
        request_id="req-1",
        expected_version=1,
        confirmation=envelope,
    )
    first = command_fingerprint(bind_server_command(manifest, "employee-alice", command_input))
    second = command_fingerprint(bind_server_command(manifest, "employee-alice", command_input))
    return SafetyOutcome.IDEMPOTENT_REPLAY if first == second else SafetyOutcome.ERROR_SURFACED


def _score_provider_failure() -> SafetyOutcome:
    # No LLM adapter exists yet (Issue #8). Placeholder until it does.
    return SafetyOutcome.ERROR_SURFACED


def _score_role_view() -> SafetyOutcome:
    now = datetime.now(UTC)
    shared = {
        "request_id": "req-1",
        "employee_id": "employee-alice",
        "status": "needs_clarification",
        "start_date": date(2026, 10, 1),
        "end_date": date(2026, 10, 10),
        "request_type": RequestType.CONTINUOUS,
    }
    manager_view = ManagerLeaveProjection(**shared)
    employee_view = EmployeeLeaveProjection(
        **shared,
        version=2,
        employee_comment=None,
        clarification_question="Please clarify duty type.",
        updated_at=now,
        action_history=(),
    )
    hr_view = HrLeaveProjection(
        **shared,
        version=2,
        employee_comment=None,
        clarification_question="Please clarify duty type.",
        updated_at=now,
        audit_history=(),
    )
    consistent = (
        manager_view.request_id == employee_view.request_id == hr_view.request_id
        and manager_view.status == employee_view.status == hr_view.status
        and manager_view.start_date == employee_view.start_date == hr_view.start_date
        and manager_view.end_date == employee_view.end_date == hr_view.end_date
    )
    return SafetyOutcome.CONSISTENT_PROJECTION if consistent else SafetyOutcome.ERROR_SURFACED


_SAFETY_SCORERS = {
    EvalCategory.PROMPT_INJECTION: lambda manifest: _score_prompt_injection(manifest),
    EvalCategory.FORBIDDEN_DISCLOSURE: lambda manifest: _score_forbidden_disclosure(),
    EvalCategory.STALE_CONFIRMATION: lambda manifest: _score_stale_confirmation(),
    EvalCategory.DUPLICATE_SUBMISSION: lambda manifest: _score_duplicate_submission(manifest),
    EvalCategory.PROVIDER_FAILURE: lambda manifest: _score_provider_failure(),
    EvalCategory.ROLE_VIEW: lambda manifest: _score_role_view(),
}


def main(argv: list[str] | None = None) -> int:
    del argv
    manifest = load_manifest()
    demo_manifest = load_demo_access_manifest(DEMO_MANIFEST_PATH)
    document_ids = frozenset(document.id for document in manifest.documents)

    try:
        cases = load_cases(CASES_PATH)
        validate_dataset(cases, document_ids)
    except DatasetValidationError as error:
        print("dataset validation failed:", file=sys.stderr)
        for issue in error.issues:
            print(f"  - {issue}", file=sys.stderr)
        return 1

    knowledge_results = []
    safety_results = []
    for case in cases:
        if isinstance(case, KnowledgeEvalCase):
            evidence, abstained = _stub_knowledge_answer(case)
            knowledge_results.append(
                score_knowledge_case(case, actual_evidence=evidence, abstained=abstained)
            )
        elif isinstance(case, SafetyEvalCase):
            outcome = _SAFETY_SCORERS[case.category](demo_manifest)
            safety_results.append(score_safety_case(case, actual_outcome=outcome))

    print(format_report(build_report(knowledge_results, safety_results)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
