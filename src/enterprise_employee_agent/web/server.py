"""FastAPI routes for the v0.1 demo UI (Issue #14)."""

# ANCHOR: Routes, templates, and error mapping only. Every handler reads the actor id from the
# identity cookie and passes it to DemoApplication; no handler resolves identities, checks roles,
# or applies business rules. Every POST first passes require_same_origin (decision 0006). Every
# mutating POST ends in a 303 redirect; /ask and /requests/propose render. Templates receive
# only views.py display data. The app is built by create_app_from_env when uvicorn starts
# (--factory), so importing this module never creates a database.

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from enterprise_employee_agent.app import DemoApplication, DemoSettings, build_demo_application
from enterprise_employee_agent.leave.contracts import (
    ERROR_MESSAGES,
    WorkflowError,
    WorkflowErrorCode,
)
from enterprise_employee_agent.web import views
from enterprise_employee_agent.web.errors import (
    FOREIGN_ORIGIN_MESSAGE,
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

    return app


def create_app_from_env() -> FastAPI:
    """uvicorn factory (``--factory``): compose the demo only when the server starts."""

    return create_app(build_demo_application(DemoSettings.from_env()))
