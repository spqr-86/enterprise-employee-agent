"""Pydantic schema for the v0.1 micro-eval dataset (Issue #7).

Knowledge-category cases carry document-level expected evidence (decision 0001: no sub-document
chunking in v0.1). Safety/workflow-category cases carry a machine outcome code, compared exactly
— never by matching prose.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import Discriminator, Field, Tag, model_validator

from enterprise_employee_agent.leave.contracts import ContractModel


class EvalCategory(StrEnum):
    NORMAL = "normal"
    MISSING_DATA = "missing_data"
    UNSUPPORTED_ELIGIBILITY = "unsupported_eligibility"
    OUT_OF_SCOPE = "out_of_scope"
    PROMPT_INJECTION = "prompt_injection"
    FORBIDDEN_DISCLOSURE = "forbidden_disclosure"
    STALE_CONFIRMATION = "stale_confirmation"
    DUPLICATE_SUBMISSION = "duplicate_submission"
    PROVIDER_FAILURE = "provider_failure"
    ROLE_VIEW = "role_view"


KNOWLEDGE_CATEGORIES: frozenset[EvalCategory] = frozenset(
    {
        EvalCategory.NORMAL,
        EvalCategory.MISSING_DATA,
        EvalCategory.UNSUPPORTED_ELIGIBILITY,
        EvalCategory.OUT_OF_SCOPE,
    }
)

SAFETY_CATEGORIES: frozenset[EvalCategory] = frozenset(
    {
        EvalCategory.PROMPT_INJECTION,
        EvalCategory.FORBIDDEN_DISCLOSURE,
        EvalCategory.STALE_CONFIRMATION,
        EvalCategory.DUPLICATE_SUBMISSION,
        EvalCategory.PROVIDER_FAILURE,
        EvalCategory.ROLE_VIEW,
    }
)


class SafetyOutcome(StrEnum):
    REFUSED = "refused"
    REDACTED = "redacted"
    REJECTED_STALE = "rejected_stale"
    IDEMPOTENT_REPLAY = "idempotent_replay"
    ERROR_SURFACED = "error_surfaced"
    CONSISTENT_PROJECTION = "consistent_projection"


class _EvalCaseBase(ContractModel):
    id: str = Field(min_length=1)
    category: EvalCategory
    question: str | None = None
    scenario: str | None = None
    expected: str = Field(min_length=1)
    held_out: bool = False

    @model_validator(mode="after")
    def require_exactly_one_prompt_shape(self) -> Self:
        if (self.question is None) == (self.scenario is None):
            raise ValueError("case must set exactly one of question or scenario")
        return self


class KnowledgeEvalCase(_EvalCaseBase):
    expected_evidence: tuple[str, ...] = ()
    abstain_expected: bool = False
    expects_clarification: bool = False

    @model_validator(mode="after")
    def require_category_in_knowledge_group(self) -> Self:
        if self.category not in KNOWLEDGE_CATEGORIES:
            raise ValueError(f"{self.category} is not a knowledge category")
        return self

    @model_validator(mode="after")
    def require_evidence_or_abstain(self) -> Self:
        if not self.expected_evidence and not self.abstain_expected:
            raise ValueError(
                "expected_evidence must be non-empty unless abstain_expected is true"
            )
        return self


class SafetyEvalCase(_EvalCaseBase):
    expected_outcome: SafetyOutcome

    @model_validator(mode="after")
    def require_category_in_safety_group(self) -> Self:
        if self.category not in SAFETY_CATEGORIES:
            raise ValueError(f"{self.category} is not a safety category")
        return self


def _case_group(value: object) -> str:
    if isinstance(value, dict):
        category = value.get("category")
    else:
        category = getattr(value, "category", None)
    knowledge_values = {member.value for member in KNOWLEDGE_CATEGORIES}
    return "knowledge" if category in knowledge_values else "safety"


EvalCase = Annotated[
    Annotated[KnowledgeEvalCase, Tag("knowledge")]
    | Annotated[SafetyEvalCase, Tag("safety")],
    Discriminator(_case_group),
]
