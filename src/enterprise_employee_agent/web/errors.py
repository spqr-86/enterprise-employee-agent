"""WorkflowError code -> HTTP status and page titles for the demo UI (Issue #14)."""

from __future__ import annotations

from enterprise_employee_agent.leave.contracts import WorkflowErrorCode

FORM_CODES = frozenset(
    {WorkflowErrorCode.VALIDATION_FAILED, WorkflowErrorCode.SENSITIVE_CONTENT_REJECTED}
)
CONFLICT_CODES = frozenset(
    {
        WorkflowErrorCode.VERSION_CONFLICT,
        WorkflowErrorCode.STALE_CONFIRMATION,
        WorkflowErrorCode.INVALID_TRANSITION,
        WorkflowErrorCode.IDEMPOTENCY_CONFLICT,
    }
)
_STATUS: dict[WorkflowErrorCode, int] = {
    WorkflowErrorCode.VALIDATION_FAILED: 422,
    WorkflowErrorCode.SENSITIVE_CONTENT_REJECTED: 422,
    WorkflowErrorCode.NOT_FOUND: 404,
    WorkflowErrorCode.FORBIDDEN: 403,
    WorkflowErrorCode.UNAUTHORIZED: 303,
    WorkflowErrorCode.VERSION_CONFLICT: 409,
    WorkflowErrorCode.STALE_CONFIRMATION: 409,
    WorkflowErrorCode.INVALID_TRANSITION: 409,
    WorkflowErrorCode.IDEMPOTENCY_CONFLICT: 409,
    WorkflowErrorCode.STORAGE_UNAVAILABLE: 503,
}
_TITLES = {
    403: "Not available",
    404: "Not found",
    409: "The request changed",
    422: "Check the entered data",
    503: "Storage unavailable",
}
GENERIC_ERROR_MESSAGE = "Something went wrong in the demo. Try again."
FOREIGN_ORIGIN_MESSAGE = "This form did not come from the demo page, so it was rejected."


def http_status_for(code: WorkflowErrorCode) -> int:
    return _STATUS[code]


def error_title(status: int) -> str:
    return _TITLES.get(status, "Something went wrong")
