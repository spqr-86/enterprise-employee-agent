"""Versioned deterministic contracts for the v0.1 leave workflow."""

# ANCHOR: Defines the validated leave payload, commands, state transitions, role projections,
# confirmation digest, and synthetic access-fixture boundary used by later workflow code.

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import InitVar, dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)


class ContractModel(BaseModel):
    """Strict immutable base for values that cross workflow boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True)


type Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")]
type IdempotencyKey = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,199}$")
]


class ActorRole(StrEnum):
    EMPLOYEE = "employee"
    MANAGER = "manager"
    HR = "hr"


class DemoIdentity(ContractModel):
    identity_id: Identifier
    display_name: str = Field(min_length=1, max_length=100)
    role: ActorRole
    reports_to: Identifier | None = None


class RequestType(StrEnum):
    CONTINUOUS = "continuous"
    INTERMITTENT = "intermittent"


class RequestScope(StrEnum):
    OWN = "own"
    DIRECT_REPORTS = "direct_reports"
    ALL = "all"


class AccessAction(StrEnum):
    VIEW_REQUEST = "view_request"
    START_PROCESSING = "start_processing"


class NegativeAccessReason(StrEnum):
    CROSS_EMPLOYEE_ACCESS = "cross_employee_access"
    NON_REPORT_MANAGER_ACCESS = "non_report_manager_access"
    EMPLOYEE_HR_ACTION = "employee_hr_action"


class LeaveStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    PROCESSING = "processing"
    NEEDS_CLARIFICATION = "needs_clarification"
    CANCELLED = "cancelled"


class CommandName(StrEnum):
    CREATE_DRAFT = "create_draft"
    UPDATE_DRAFT = "update_draft"
    CANCEL_DRAFT = "cancel_draft"
    CONFIRM_SUBMIT = "confirm_submit"
    START_PROCESSING = "start_processing"
    REQUEST_CLARIFICATION = "request_clarification"
    PROVIDE_CLARIFICATION = "provide_clarification"


class WorkflowErrorCode(StrEnum):
    VALIDATION_FAILED = "validation_failed"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    VERSION_CONFLICT = "version_conflict"
    STALE_CONFIRMATION = "stale_confirmation"
    INVALID_TRANSITION = "invalid_transition"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    SENSITIVE_CONTENT_REJECTED = "sensitive_content_rejected"


ERROR_MESSAGES: dict[WorkflowErrorCode, str] = {
    WorkflowErrorCode.VALIDATION_FAILED: "The request data is invalid.",
    WorkflowErrorCode.UNAUTHORIZED: "A valid demo identity is required.",
    WorkflowErrorCode.FORBIDDEN: "This action is not available to the selected identity.",
    WorkflowErrorCode.NOT_FOUND: "The requested leave item was not found.",
    WorkflowErrorCode.VERSION_CONFLICT: "The request changed; reload it before continuing.",
    WorkflowErrorCode.STALE_CONFIRMATION: "The preview changed; review and confirm it again.",
    WorkflowErrorCode.INVALID_TRANSITION: "This action is not valid for the current status.",
    WorkflowErrorCode.IDEMPOTENCY_CONFLICT: "This operation key was used for different data.",
    WorkflowErrorCode.SENSITIVE_CONTENT_REJECTED: (
        "Remove medical details or documents and provide operational information only."
    ),
}


class WorkflowError(Exception):
    """A stable workflow error code with its safe, non-leaking message."""

    def __init__(self, code: WorkflowErrorCode) -> None:
        self.code = code
        super().__init__(ERROR_MESSAGES[code])


class LeaveRequestPayload(ContractModel):
    start_date: date
    end_date: date
    request_type: RequestType
    employee_comment: str | None = Field(default=None, max_length=500)

    @field_validator("employee_comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


def payload_digest(payload: LeaveRequestPayload) -> str:
    """Return the stable SHA-256 digest used by a version-bound preview."""

    canonical = json.dumps(
        payload.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class ConfirmationEnvelope(ContractModel):
    request_id: Identifier
    request_version: int = Field(ge=1)
    payload_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    def matches(
        self, *, request_id: str, payload: LeaveRequestPayload, request_version: int
    ) -> bool:
        return (
            hmac.compare_digest(self.request_id, request_id)
            and self.request_version == request_version
            and hmac.compare_digest(self.payload_digest, payload_digest(payload))
        )


class CommandSpec(ContractModel):
    allowed_roles: frozenset[ActorRole]
    requires_expected_version: bool = True
    requires_idempotency_key: bool = True
    requires_confirmation: bool = False


class ClientCommandBase(ContractModel):
    idempotency_key: IdempotencyKey


class ExistingRequestInput(ClientCommandBase):
    request_id: Identifier
    expected_version: int = Field(ge=1)


class CreateDraftInput(ClientCommandBase):
    command: Literal[CommandName.CREATE_DRAFT] = CommandName.CREATE_DRAFT
    expected_version: Literal[0] = 0
    payload: LeaveRequestPayload


class UpdateDraftInput(ExistingRequestInput):
    command: Literal[CommandName.UPDATE_DRAFT] = CommandName.UPDATE_DRAFT
    payload: LeaveRequestPayload


class CancelDraftInput(ExistingRequestInput):
    command: Literal[CommandName.CANCEL_DRAFT] = CommandName.CANCEL_DRAFT


class ConfirmSubmitInput(ExistingRequestInput):
    command: Literal[CommandName.CONFIRM_SUBMIT] = CommandName.CONFIRM_SUBMIT
    confirmation: ConfirmationEnvelope

    @model_validator(mode="after")
    def validate_confirmation_target(self) -> Self:
        if self.request_id != self.confirmation.request_id:
            raise ValueError("confirmation request_id does not match command target")
        if self.expected_version != self.confirmation.request_version:
            raise ValueError("confirmation version does not match expected_version")
        return self


class StartProcessingInput(ExistingRequestInput):
    command: Literal[CommandName.START_PROCESSING] = CommandName.START_PROCESSING


class RequestClarificationInput(ExistingRequestInput):
    command: Literal[CommandName.REQUEST_CLARIFICATION] = CommandName.REQUEST_CLARIFICATION
    question: str = Field(min_length=1, max_length=500)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("question must not be blank")
        return normalized


class ProvideClarificationInput(ExistingRequestInput):
    command: Literal[CommandName.PROVIDE_CLARIFICATION] = CommandName.PROVIDE_CLARIFICATION
    payload: LeaveRequestPayload


type ClientCommandInput = Annotated[
    CreateDraftInput
    | UpdateDraftInput
    | CancelDraftInput
    | ConfirmSubmitInput
    | StartProcessingInput
    | RequestClarificationInput
    | ProvideClarificationInput,
    Field(discriminator="command"),
]


COMMAND_SPECS: dict[CommandName, CommandSpec] = {
    CommandName.CREATE_DRAFT: CommandSpec(allowed_roles=frozenset({ActorRole.EMPLOYEE})),
    CommandName.UPDATE_DRAFT: CommandSpec(allowed_roles=frozenset({ActorRole.EMPLOYEE})),
    CommandName.CANCEL_DRAFT: CommandSpec(allowed_roles=frozenset({ActorRole.EMPLOYEE})),
    CommandName.CONFIRM_SUBMIT: CommandSpec(
        allowed_roles=frozenset({ActorRole.EMPLOYEE}), requires_confirmation=True
    ),
    CommandName.START_PROCESSING: CommandSpec(allowed_roles=frozenset({ActorRole.HR})),
    CommandName.REQUEST_CLARIFICATION: CommandSpec(allowed_roles=frozenset({ActorRole.HR})),
    CommandName.PROVIDE_CLARIFICATION: CommandSpec(allowed_roles=frozenset({ActorRole.EMPLOYEE})),
}


_BINDING_TOKEN = object()
IDENTIFIER_ADAPTER = TypeAdapter(Identifier)


@dataclass(frozen=True, slots=True)
class _CommandContext:
    """Opaque server-bound command returned only by ``bind_server_command``."""

    actor: DemoIdentity
    request_id: Identifier
    input: ClientCommandInput
    _token: InitVar[object]

    def __post_init__(self, _token: object) -> None:
        if _token is not _BINDING_TOKEN:
            raise TypeError("command contexts must be created by bind_server_command")
        if self.actor.role not in COMMAND_SPECS[self.input.command].allowed_roles:
            raise WorkflowError(WorkflowErrorCode.FORBIDDEN)
        input_request_id = getattr(self.input, "request_id", None)
        if input_request_id is not None and input_request_id != self.request_id:
            raise ValueError("server request_id does not match command target")


def _require_bound_command(command: object) -> _CommandContext:
    if not isinstance(command, _CommandContext):
        raise TypeError("command must come from bind_server_command")
    return command


def command_fingerprint(command: _CommandContext) -> str:
    """Compute a server-owned digest over the complete semantic command intent."""

    command = _require_bound_command(command)
    intent = command.input.model_dump(mode="json", exclude={"idempotency_key"})
    semantic_request_id = (
        None if isinstance(command.input, CreateDraftInput) else command.request_id
    )
    canonical = json.dumps(
        {
            "actor_id": command.actor.identity_id,
            "actor_role": command.actor.role,
            "request_id": semantic_request_id,
            "intent": intent,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class Transition(ContractModel):
    source: LeaveStatus
    command: CommandName
    target: LeaveStatus


TRANSITIONS: tuple[Transition, ...] = (
    Transition(
        source=LeaveStatus.DRAFT,
        command=CommandName.CONFIRM_SUBMIT,
        target=LeaveStatus.SUBMITTED,
    ),
    Transition(
        source=LeaveStatus.DRAFT,
        command=CommandName.CANCEL_DRAFT,
        target=LeaveStatus.CANCELLED,
    ),
    Transition(
        source=LeaveStatus.SUBMITTED,
        command=CommandName.START_PROCESSING,
        target=LeaveStatus.PROCESSING,
    ),
    Transition(
        source=LeaveStatus.SUBMITTED,
        command=CommandName.REQUEST_CLARIFICATION,
        target=LeaveStatus.NEEDS_CLARIFICATION,
    ),
    Transition(
        source=LeaveStatus.NEEDS_CLARIFICATION,
        command=CommandName.CONFIRM_SUBMIT,
        target=LeaveStatus.SUBMITTED,
    ),
)


class AuditEvent(ContractModel):
    event_id: Identifier
    request_id: Identifier
    actor_id: Identifier
    command: CommandName
    previous_status: LeaveStatus | None
    new_status: LeaveStatus
    previous_version: int = Field(ge=0)
    request_version: int = Field(ge=1)
    idempotency_key: IdempotencyKey
    command_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_event_invariants(self) -> Self:
        if self.request_version != self.previous_version + 1:
            raise ValueError("audit request version must increment by one")

        allowed_states = {
            CommandName.CREATE_DRAFT: {(None, LeaveStatus.DRAFT)},
            CommandName.UPDATE_DRAFT: {(LeaveStatus.DRAFT, LeaveStatus.DRAFT)},
            CommandName.CANCEL_DRAFT: {(LeaveStatus.DRAFT, LeaveStatus.CANCELLED)},
            CommandName.CONFIRM_SUBMIT: {
                (LeaveStatus.DRAFT, LeaveStatus.SUBMITTED),
                (LeaveStatus.NEEDS_CLARIFICATION, LeaveStatus.SUBMITTED),
            },
            CommandName.START_PROCESSING: {(LeaveStatus.SUBMITTED, LeaveStatus.PROCESSING)},
            CommandName.REQUEST_CLARIFICATION: {
                (LeaveStatus.SUBMITTED, LeaveStatus.NEEDS_CLARIFICATION)
            },
            CommandName.PROVIDE_CLARIFICATION: {
                (LeaveStatus.NEEDS_CLARIFICATION, LeaveStatus.NEEDS_CLARIFICATION)
            },
        }
        if (self.previous_status, self.new_status) not in allowed_states[self.command]:
            raise ValueError("audit state pair is invalid for command")
        if self.command is CommandName.CREATE_DRAFT and (
            self.previous_version != 0 or self.request_version != 1
        ):
            raise ValueError("create_draft audit must record version 0 to 1")
        if self.command is not CommandName.CREATE_DRAFT and self.previous_version < 1:
            raise ValueError("non-create audit must start from a positive version")
        return self


class LeaveRequest(ContractModel):
    """The internal, immutable in-memory record a policy and projection are built from.

    D2 (Issue #9): this entity's fields are owned here; later persistence (#10) stores it
    without changing its shape.
    """

    request_id: Identifier
    employee_id: Identifier
    status: LeaveStatus
    version: int = Field(ge=1)
    payload: LeaveRequestPayload
    clarification_question: str | None = Field(default=None, max_length=500)
    updated_at: AwareDatetime
    audit_history: tuple[AuditEvent, ...]

    @field_validator("clarification_question", mode="before")
    @classmethod
    def normalize_clarification_question(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = " ".join(value.split())
        return normalized or None

    @model_validator(mode="after")
    def validate_audit_history(self) -> Self:
        if any(event.request_id != self.request_id for event in self.audit_history):
            raise ValueError("audit_history may contain only this request's events")
        return self


class LeaveRequestPreview(ContractModel):
    """Normalized request data and the exact envelope an employee may confirm."""

    request_id: Identifier
    request_version: int = Field(ge=1)
    payload: LeaveRequestPayload
    confirmation: ConfirmationEnvelope

    @model_validator(mode="after")
    def validate_confirmation(self) -> Self:
        if not self.confirmation.matches(
            request_id=self.request_id,
            payload=self.payload,
            request_version=self.request_version,
        ):
            raise ValueError("preview confirmation does not match its normalized payload")
        return self


def build_leave_preview(request: LeaveRequest) -> LeaveRequestPreview:
    """Build a confirmable preview only for a draft or clarification response."""

    if request.status not in {LeaveStatus.DRAFT, LeaveStatus.NEEDS_CLARIFICATION}:
        raise WorkflowError(WorkflowErrorCode.INVALID_TRANSITION)
    confirmation = ConfirmationEnvelope(
        request_id=request.request_id,
        request_version=request.version,
        payload_digest=payload_digest(request.payload),
    )
    return LeaveRequestPreview(
        request_id=request.request_id,
        request_version=request.version,
        payload=request.payload,
        confirmation=confirmation,
    )


class ManagerLeaveProjection(ContractModel):
    request_id: Identifier
    employee_id: Identifier
    status: LeaveStatus
    start_date: date
    end_date: date
    request_type: RequestType

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class EmployeeLeaveProjection(ContractModel):
    request_id: Identifier
    employee_id: Identifier
    status: LeaveStatus
    version: int = Field(ge=1)
    start_date: date
    end_date: date
    request_type: RequestType
    employee_comment: str | None = Field(default=None, max_length=500)
    clarification_question: str | None = Field(default=None, max_length=500)
    updated_at: AwareDatetime
    action_history: tuple[AuditEvent, ...]

    @field_validator("employee_comment", "clarification_question", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = " ".join(value.split())
        return normalized or None

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if any(
            event.actor_id != self.employee_id or event.request_id != self.request_id
            for event in self.action_history
        ):
            raise ValueError(
                "employee action_history may contain only this employee's current request"
            )
        return self


class HrLeaveProjection(ContractModel):
    request_id: Identifier
    employee_id: Identifier
    status: LeaveStatus
    version: int = Field(ge=1)
    start_date: date
    end_date: date
    request_type: RequestType
    employee_comment: str | None = Field(default=None, max_length=500)
    clarification_question: str | None = Field(default=None, max_length=500)
    updated_at: AwareDatetime
    audit_history: tuple[AuditEvent, ...]

    @field_validator("employee_comment", "clarification_question", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = " ".join(value.split())
        return normalized or None

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


ROLE_PROJECTION_FIELDS: dict[ActorRole, frozenset[str]] = {
    ActorRole.EMPLOYEE: frozenset(EmployeeLeaveProjection.model_fields),
    ActorRole.MANAGER: frozenset(ManagerLeaveProjection.model_fields),
    ActorRole.HR: frozenset(HrLeaveProjection.model_fields),
}


class NegativeAccessCase(ContractModel):
    actor_id: Identifier
    target_employee_id: Identifier
    action: AccessAction
    reason: NegativeAccessReason


class PermissionRule(ContractModel):
    role: ActorRole
    request_scope: RequestScope
    projection: ActorRole
    allowed_commands: frozenset[CommandName]


class DemoAccessManifest(ContractModel):
    schema_version: int = Field(ge=1, le=1)
    identities: tuple[DemoIdentity, ...]
    permission_rules: tuple[PermissionRule, ...]
    negative_cases: tuple[NegativeAccessCase, ...]

    @model_validator(mode="after")
    def validate_relationships_and_cases(self) -> Self:
        by_id = {identity.identity_id: identity for identity in self.identities}
        if len(by_id) != len(self.identities):
            raise ValueError("identity_id values must be unique")
        roles = [identity.role for identity in self.identities]
        if roles.count(ActorRole.EMPLOYEE) < 2:
            raise ValueError("demo manifest requires at least two employees")
        if ActorRole.MANAGER not in roles:
            raise ValueError("demo manifest requires at least one manager")
        if ActorRole.HR not in roles:
            raise ValueError("demo manifest requires at least one HR identity")

        rules_by_role = {rule.role: rule for rule in self.permission_rules}
        if len(rules_by_role) != len(self.permission_rules) or set(rules_by_role) != set(ActorRole):
            raise ValueError("permission_rules must declare every role exactly once")
        for role, rule in rules_by_role.items():
            expected_commands = frozenset(
                command for command, spec in COMMAND_SPECS.items() if role in spec.allowed_roles
            )
            if rule.allowed_commands != expected_commands:
                raise ValueError(f"permission commands do not match command contract for {role}")
            if rule.projection is not role:
                raise ValueError(f"permission projection must match role {role}")
            expected_scope = {
                ActorRole.EMPLOYEE: RequestScope.OWN,
                ActorRole.MANAGER: RequestScope.DIRECT_REPORTS,
                ActorRole.HR: RequestScope.ALL,
            }[role]
            if rule.request_scope is not expected_scope:
                raise ValueError(f"permission scope does not match role {role}")

        for identity in self.identities:
            if identity.role is ActorRole.EMPLOYEE:
                manager = by_id.get(identity.reports_to or "")
                if manager is None or manager.role is not ActorRole.MANAGER:
                    raise ValueError("every employee must report to a declared manager")
            elif identity.reports_to is not None:
                raise ValueError("only employees may declare reports_to")

        for case in self.negative_cases:
            if case.actor_id not in by_id or case.target_employee_id not in by_id:
                raise ValueError("negative access cases must reference declared identities")
            if by_id[case.target_employee_id].role is not ActorRole.EMPLOYEE:
                raise ValueError("negative access targets must be employees")
            actor = by_id[case.actor_id]
            target = by_id[case.target_employee_id]
            expected_shape = {
                NegativeAccessReason.CROSS_EMPLOYEE_ACCESS: (
                    actor.role is ActorRole.EMPLOYEE
                    and actor.identity_id != target.identity_id
                    and case.action is AccessAction.VIEW_REQUEST
                ),
                NegativeAccessReason.NON_REPORT_MANAGER_ACCESS: (
                    actor.role is ActorRole.MANAGER
                    and target.reports_to != actor.identity_id
                    and case.action is AccessAction.VIEW_REQUEST
                ),
                NegativeAccessReason.EMPLOYEE_HR_ACTION: (
                    actor.role is ActorRole.EMPLOYEE
                    and actor.identity_id == target.identity_id
                    and case.action is AccessAction.START_PROCESSING
                ),
            }[case.reason]
            if not expected_shape:
                raise ValueError(f"negative access case has invalid shape for {case.reason}")
        if {case.reason for case in self.negative_cases} != set(NegativeAccessReason):
            raise ValueError("negative access cases must cover every declared reason")
        return self


def load_demo_access_manifest(path: Path) -> DemoAccessManifest:
    """Load and validate the synthetic server-selected identity manifest."""

    return DemoAccessManifest.model_validate_json(path.read_text(encoding="utf-8"))


def bind_server_command(
    manifest: DemoAccessManifest,
    actor_id: Identifier,
    input: ClientCommandInput,
    *,
    generated_request_id: Identifier | None = None,
) -> _CommandContext:
    """Bind validated client intent to an identity selected by the server."""

    validated_actor_id = IDENTIFIER_ADAPTER.validate_python(actor_id)
    identity = next(
        (
            candidate
            for candidate in manifest.identities
            if candidate.identity_id == validated_actor_id
        ),
        None,
    )
    if identity is None:
        raise WorkflowError(WorkflowErrorCode.UNAUTHORIZED)
    if isinstance(input, CreateDraftInput):
        if generated_request_id is None:
            raise ValueError("create_draft requires a server-generated request_id")
        request_id = IDENTIFIER_ADAPTER.validate_python(generated_request_id)
    else:
        if generated_request_id is not None:
            raise ValueError("only create_draft accepts a generated request_id")
        request_id = input.request_id
    return _CommandContext(
        actor=identity,
        request_id=request_id,
        input=input,
        _token=_BINDING_TOKEN,
    )


def build_audit_event(
    command: _CommandContext,
    *,
    event_id: Identifier,
    previous_status: LeaveStatus | None,
    new_status: LeaveStatus,
    previous_version: int,
    request_version: int,
    occurred_at: datetime,
) -> AuditEvent:
    """Build an audit event only from a server-bound command context."""

    command = _require_bound_command(command)
    if previous_version != command.input.expected_version:
        raise ValueError("audit previous_version must match command expected_version")
    return AuditEvent(
        event_id=event_id,
        request_id=command.request_id,
        actor_id=command.actor.identity_id,
        command=command.input.command,
        previous_status=previous_status,
        new_status=new_status,
        previous_version=previous_version,
        request_version=request_version,
        idempotency_key=command.input.idempotency_key,
        command_fingerprint=command_fingerprint(command),
        occurred_at=occurred_at,
    )
