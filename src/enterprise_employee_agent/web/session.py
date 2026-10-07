"""Identity cookie and same-origin POST check (decision 0006)."""

# ANCHOR: The identity cookie is a demo switcher, not authentication: unsigned by design and
# re-resolved by DemoApplication on every request. CSRF protection is SameSite=Strict on that
# cookie plus require_same_origin on every POST: Origin (or Referer when Origin is absent) must
# match this app's own scheme and host:port. A missing, "null", or foreign value raises
# ForeignOriginError before any DemoApplication call.

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request, Response

from enterprise_employee_agent.leave.contracts import WorkflowError, WorkflowErrorCode

IDENTITY_COOKIE = "demo_identity"


class ForeignOriginError(Exception):
    """A POST that did not come from this app's own pages."""


def read_identity(request: Request) -> str:
    value = request.cookies.get(IDENTITY_COOKIE)
    if not value:
        raise WorkflowError(WorkflowErrorCode.UNAUTHORIZED)
    return value


def set_identity(response: Response, identity_id: str) -> None:
    response.set_cookie(IDENTITY_COOKIE, identity_id, httponly=True, samesite="strict", path="/")


def clear_identity(response: Response) -> None:
    response.delete_cookie(IDENTITY_COOKIE, path="/", httponly=True, samesite="strict")


def require_same_origin(request: Request) -> None:
    claimed = request.headers.get("origin") or request.headers.get("referer")
    if not claimed:
        raise ForeignOriginError
    parsed = urlsplit(claimed)
    own = request.base_url
    if not parsed.scheme or (parsed.scheme, parsed.netloc) != (own.scheme, own.netloc):
        raise ForeignOriginError
