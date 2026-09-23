"""FastAPI routes for the v0.1 demo UI (Issue #14)."""

# ANCHOR: Routes, templates, and error mapping only. Every handler reads the actor id from the
# identity cookie and passes it to DemoApplication; no handler resolves identities, checks roles,
# or applies business rules. Every POST first passes require_same_origin (decision 0006). Every
# mutating POST ends in a 303 redirect; /ask and /requests/propose render. Templates receive
# only views.py display data. The app is built by create_app_from_env when uvicorn starts
# (--factory), so importing this module never creates a database.

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from enterprise_employee_agent.app import (
    DemoApplication,
    DemoSettings,
    LeaveForm,
    build_demo_application,
)
from enterprise_employee_agent.leave.contracts import (
    ERROR_MESSAGES,
    CommandName,
    WorkflowError,
    WorkflowErrorCode,
)
from enterprise_employee_agent.web import views
from enterprise_employee_agent.web.errors import (
    CONFLICT_CODES,
    FOREIGN_ORIGIN_MESSAGE,
    FORM_CODES,
    GENERIC_ERROR_MESSAGE,
    error_title,
    http_status_for,
)
from enterprise_employee_agent.web.session import (
    IDENTITY_COOKIE,
    ForeignOriginError,
    clear_identity,
    read_identity,
    require_same_origin,
    set_identity,
)

_WEB_DIR = Path(__file__).parent
_LOG = logging.getLogger(__name__)
SAME_ORIGIN = [Depends(require_same_origin)]


def new_key() -> str:
    """A fresh idempotency key for one rendered form; not a CSRF token (decision 0006)."""

    return uuid4().hex


def create_app(demo: DemoApplication) -> FastAPI:
    app = FastAPI(
        title="Enterprise Employee Agent demo", docs_url=None, redoc_url=None, openapi_url=None
    )
    templates = Jinja2Templates(directory=_WEB_DIR / "templates")
    app.mount("/static", StaticFiles(directory=_WEB_DIR / "static"), name="static")

    def header(request: Request) -> views.HeaderView:
        identity = None
        actor_id = request.cookies.get(IDENTITY_COOKIE)
        if actor_id:
            try:
                identity = demo.identity(actor_id)
            except WorkflowError:
                identity = None
        return views.HeaderView(
            identity=identity, mode_label=demo.mode().label, identities=demo.identities()
        )

    def render(request: Request, name: str, *, status_code: int = 200, **context) -> Response:
        return templates.TemplateResponse(
            request, name, {"header": header(request), **context}, status_code=status_code
        )

    def render_error(request: Request, status_code: int, message: str) -> Response:
        return render(
            request,
            "error.html",
            status_code=status_code,
            title=error_title(status_code),
            message=message,
        )

    @app.exception_handler(WorkflowError)
    async def handle_workflow_error(request: Request, error: WorkflowError) -> Response:
        if error.code is WorkflowErrorCode.UNAUTHORIZED:
            response = RedirectResponse("/identity", status_code=303)
            clear_identity(response)
            return response
        return render_error(request, http_status_for(error.code), ERROR_MESSAGES[error.code])

    @app.exception_handler(ForeignOriginError)
    async def handle_foreign_origin(request: Request, error: ForeignOriginError) -> Response:
        return render_error(request, 403, FOREIGN_ORIGIN_MESSAGE)

    @app.exception_handler(RequestValidationError)
    async def handle_invalid_form(request: Request, error: RequestValidationError) -> Response:
        return render_error(request, 422, ERROR_MESSAGES[WorkflowErrorCode.VALIDATION_FAILED])

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, error: StarletteHTTPException) -> Response:
        if error.status_code == 404:
            return render_error(request, 404, ERROR_MESSAGES[WorkflowErrorCode.NOT_FOUND])
        return render_error(request, error.status_code, GENERIC_ERROR_MESSAGE)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, error: Exception) -> Response:
        _LOG.exception("unhandled error in demo UI", exc_info=error)
        return render_error(request, 500, GENERIC_ERROR_MESSAGE)

    @app.get("/identity")
    def identity_page(request: Request) -> Response:
        return render(request, "identity.html")

    @app.post("/identity", dependencies=SAME_ORIGIN)
    def choose_identity(identity_id: Annotated[str, Form()] = "") -> Response:
        chosen = demo.identity(identity_id)
        response = RedirectResponse("/", status_code=303)
        set_identity(response, chosen.identity_id)
        return response

    @app.get("/")
    def ask_page(request: Request) -> Response:
        demo.identity(read_identity(request))
        return render(
            request, "ask.html", question="", answer=None, suggestions=demo.suggested_questions()
        )

    @app.post("/ask", dependencies=SAME_ORIGIN)
    def ask(request: Request, question: Annotated[str, Form()] = "") -> Response:
        result = demo.ask(read_identity(request), question)
        return render(
            request,
            "ask.html",
            question=question,
            answer=views.answer_view(result),
            suggestions=demo.suggested_questions(),
        )

    def leave_form(
        start_date: str, end_date: str, request_type: str, employee_comment: str
    ) -> LeaveForm:
        return LeaveForm(
            start_date=start_date,
            end_date=end_date,
            request_type=request_type,
            employee_comment=employee_comment,
        )

    def render_form(
        request: Request,
        *,
        heading: str,
        action_url: str,
        form: LeaveForm,
        submit_label: str,
        expected_version: int | None = None,
        note: str | None = None,
        error: str | None = None,
        status_code: int = 200,
    ) -> Response:
        return render(
            request,
            "request_form.html",
            status_code=status_code,
            heading=heading,
            action_url=action_url,
            form=form,
            idempotency_key=new_key(),
            expected_version=expected_version,
            note=note,
            error=error,
            submit_label=submit_label,
        )

    def render_detail(
        request: Request,
        actor_id: str,
        request_id: str,
        *,
        status_code: int = 200,
        notice: str | None = None,
        error: str | None = None,
        form: LeaveForm | None = None,
    ) -> Response:
        detail = views.detail_view(demo.request_for(actor_id, request_id))
        return render(
            request,
            "request.html",
            status_code=status_code,
            detail=detail,
            keys={action: new_key() for action in detail.actions},
            notice=notice,
            error=error,
            form=form or detail.form,
        )

    def mutate(
        request: Request,
        actor_id: str,
        request_id: str,
        action: Callable[[], object],
        *,
        on_form_error: Callable[[str], Response] | None = None,
    ) -> Response:
        try:
            action()
        except WorkflowError as error:
            if error.code in CONFLICT_CODES:
                return render_detail(
                    request,
                    actor_id,
                    request_id,
                    status_code=409,
                    notice=ERROR_MESSAGES[error.code],
                )
            if error.code in FORM_CODES and on_form_error is not None:
                return on_form_error(ERROR_MESSAGES[error.code])
            raise
        return RedirectResponse(f"/requests/{request_id}", status_code=303)

    @app.get("/requests")
    def request_list(request: Request) -> Response:
        actor_id = read_identity(request)
        role = demo.identity(actor_id).role
        rows = tuple(views.row_view(p) for p in demo.requests_for(actor_id))
        return render(request, "requests.html", heading=views.list_heading(role), rows=rows)

    @app.get("/requests/new")
    def new_request(request: Request) -> Response:
        demo.identity(read_identity(request))
        return render(request, "request_new.html", suggestions=demo.suggested_leave_descriptions())

    @app.post("/requests/propose", dependencies=SAME_ORIGIN)
    def propose(request: Request, description: Annotated[str, Form()] = "") -> Response:
        outcome = demo.propose_fields(read_identity(request), description)
        form, note = views.form_from_proposal(outcome)
        return render_form(
            request,
            heading="Check the pre-filled request",
            action_url="/requests",
            form=form,
            note=note,
            submit_label="Save draft",
        )

    @app.post("/requests", dependencies=SAME_ORIGIN)
    def create(
        request: Request,
        start_date: Annotated[str, Form()] = "",
        end_date: Annotated[str, Form()] = "",
        request_type: Annotated[str, Form()] = "",
        employee_comment: Annotated[str, Form()] = "",
        idempotency_key: Annotated[str, Form()] = "",
    ) -> Response:
        actor_id = read_identity(request)
        form = leave_form(start_date, end_date, request_type, employee_comment)
        try:
            preview = demo.create_draft(actor_id, form, idempotency_key)
        except WorkflowError as error:
            if error.code not in FORM_CODES:
                raise
            return render_form(
                request,
                heading="Check the pre-filled request",
                action_url="/requests",
                form=form,
                error=ERROR_MESSAGES[error.code],
                submit_label="Save draft",
                status_code=422,
            )
        return RedirectResponse(f"/requests/{preview.request_id}", status_code=303)

    @app.get("/requests/{request_id}")
    def request_detail(request: Request, request_id: str) -> Response:
        return render_detail(request, read_identity(request), request_id)

    @app.get("/requests/{request_id}/edit")
    def edit_page(request: Request, request_id: str) -> Response:
        view = demo.request_for(read_identity(request), request_id)
        if CommandName.UPDATE_DRAFT not in view.actions:
            raise WorkflowError(WorkflowErrorCode.INVALID_TRANSITION)
        return render_form(
            request,
            heading="Edit draft",
            action_url=f"/requests/{request_id}/edit",
            form=views.form_from_projection(view.projection),
            expected_version=view.projection.version,
            submit_label="Save changes",
        )

    @app.post("/requests/{request_id}/edit", dependencies=SAME_ORIGIN)
    def edit(
        request: Request,
        request_id: str,
        expected_version: Annotated[int, Form()],
        start_date: Annotated[str, Form()] = "",
        end_date: Annotated[str, Form()] = "",
        request_type: Annotated[str, Form()] = "",
        employee_comment: Annotated[str, Form()] = "",
        idempotency_key: Annotated[str, Form()] = "",
    ) -> Response:
        actor_id = read_identity(request)
        form = leave_form(start_date, end_date, request_type, employee_comment)
        return mutate(
            request,
            actor_id,
            request_id,
            lambda: demo.update_draft(
                actor_id, request_id, expected_version, form, idempotency_key
            ),
            on_form_error=lambda message: render_form(
                request,
                heading="Edit draft",
                action_url=f"/requests/{request_id}/edit",
                form=form,
                expected_version=expected_version,
                error=message,
                submit_label="Save changes",
                status_code=422,
            ),
        )

    @app.post("/requests/{request_id}/cancel", dependencies=SAME_ORIGIN)
    def cancel(
        request: Request,
        request_id: str,
        expected_version: Annotated[int, Form()],
        idempotency_key: Annotated[str, Form()] = "",
    ) -> Response:
        actor_id = read_identity(request)
        return mutate(
            request,
            actor_id,
            request_id,
            lambda: demo.cancel_draft(actor_id, request_id, expected_version, idempotency_key),
        )

    @app.post("/requests/{request_id}/confirm", dependencies=SAME_ORIGIN)
    def confirm(
        request: Request,
        request_id: str,
        expected_version: Annotated[int, Form()],
        payload_digest: Annotated[str, Form()] = "",
        idempotency_key: Annotated[str, Form()] = "",
    ) -> Response:
        actor_id = read_identity(request)
        return mutate(
            request,
            actor_id,
            request_id,
            lambda: demo.confirm(
                actor_id, request_id, expected_version, payload_digest, idempotency_key
            ),
        )

    @app.post("/requests/{request_id}/start-processing", dependencies=SAME_ORIGIN)
    def start_processing(
        request: Request,
        request_id: str,
        expected_version: Annotated[int, Form()],
        idempotency_key: Annotated[str, Form()] = "",
    ) -> Response:
        actor_id = read_identity(request)
        return mutate(
            request,
            actor_id,
            request_id,
            lambda: demo.hr_start(actor_id, request_id, expected_version, idempotency_key),
        )

    @app.post("/requests/{request_id}/clarification-request", dependencies=SAME_ORIGIN)
    def request_clarification(
        request: Request,
        request_id: str,
        expected_version: Annotated[int, Form()],
        question: Annotated[str, Form()] = "",
        idempotency_key: Annotated[str, Form()] = "",
    ) -> Response:
        actor_id = read_identity(request)
        return mutate(
            request,
            actor_id,
            request_id,
            lambda: demo.hr_clarify(
                actor_id, request_id, expected_version, question, idempotency_key
            ),
            on_form_error=lambda message: render_detail(
                request, actor_id, request_id, status_code=422, error=message
            ),
        )

    @app.post("/requests/{request_id}/clarification-response", dependencies=SAME_ORIGIN)
    def provide_clarification(
        request: Request,
        request_id: str,
        expected_version: Annotated[int, Form()],
        start_date: Annotated[str, Form()] = "",
        end_date: Annotated[str, Form()] = "",
        request_type: Annotated[str, Form()] = "",
        employee_comment: Annotated[str, Form()] = "",
        idempotency_key: Annotated[str, Form()] = "",
    ) -> Response:
        actor_id = read_identity(request)
        form = leave_form(start_date, end_date, request_type, employee_comment)
        return mutate(
            request,
            actor_id,
            request_id,
            lambda: demo.employee_clarify(
                actor_id, request_id, expected_version, form, idempotency_key
            ),
            on_form_error=lambda message: render_detail(
                request, actor_id, request_id, status_code=422, error=message, form=form
            ),
        )

    return app


def create_app_from_env() -> FastAPI:
    """uvicorn factory (``--factory``): compose the demo only when the server starts."""

    return create_app(build_demo_application(DemoSettings.from_env()))
