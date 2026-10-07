"""Full v0.1 scenario through the demo UI with the real application (Issue #14)."""

from __future__ import annotations

import itertools
import re
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from enterprise_employee_agent.app import DemoSettings, build_demo_application
from enterprise_employee_agent.web.server import create_app

NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
ORIGIN = {"origin": "http://testserver"}
QUESTION = "How long is parental leave in the US?"
DESCRIPTION = "I need continuous leave from 2026-10-01 to 2026-10-05 for a family matter."


def _client(tmp_path) -> TestClient:
    counter = itertools.count(1)
    demo = build_demo_application(
        DemoSettings(database_path=tmp_path / "demo.sqlite", openrouter_api_key=None),
        clock=lambda: NOW,
        id_factory=lambda prefix: f"{prefix}-{next(counter):04d}",
    )
    return TestClient(create_app(demo))


def _act_as(client: TestClient, identity_id: str) -> None:
    assert (
        client.post(
            "/identity", data={"identity_id": identity_id}, headers=ORIGIN, follow_redirects=False
        ).status_code
        == 303
    )


def _form(html: str, action: str) -> dict[str, str]:
    match = re.search(rf'<form method="post" action="{re.escape(action)}">.*?</form>', html, re.S)
    assert match is not None, f"no form posting to {action}"
    return dict(re.findall(r'<input type="hidden" name="([a-z_]+)" value="([^"]*)">', match[0]))


def _post(client: TestClient, path: str, data: dict[str, str]) -> int:
    return client.post(path, data=data, headers=ORIGIN, follow_redirects=False).status_code


def _fields_from(html: str) -> dict[str, str]:
    values = dict(re.findall(r'name="(start_date|end_date)" type="date" value="([^"]*)"', html))
    values["request_type"] = re.search(r'<option value="(\w+)" selected>', html)[1]
    values["employee_comment"] = re.search(r'name="employee_comment"[^>]*>([^<]*)<', html)[1]
    return values


def test_full_demo_journey_through_the_ui(tmp_path) -> None:
    client = _client(tmp_path)

    _act_as(client, "employee-alice")
    answer = client.post("/ask", data={"question": QUESTION}, headers=ORIGIN)
    assert "16 weeks" in answer.text
    assert "United States Leave of Absence Policies" in answer.text

    proposed = client.post("/requests/propose", data={"description": DESCRIPTION}, headers=ORIGIN)
    fields = _fields_from(proposed.text)
    assert fields == {
        "start_date": "2026-10-01",
        "end_date": "2026-10-05",
        "request_type": "continuous",
        "employee_comment": "Family matter.",
    }
    created = client.post(
        "/requests",
        data={**_form(proposed.text, "/requests"), **fields},
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert created.status_code == 303
    url = created.headers["location"]
    request_id = url.rsplit("/", 1)[-1]

    preview = client.get(url)
    assert "Confirm and submit version 1" in preview.text
    assert _post(client, f"{url}/confirm", _form(preview.text, f"{url}/confirm")) == 303

    _act_as(client, "hr-harper")
    assert request_id in client.get("/requests").text
    hr_page = client.get(url)
    assert "Audit history" in hr_page.text
    ask = _form(hr_page.text, f"{url}/clarification-request")
    assert (
        _post(client, f"{url}/clarification-request", {**ask, "question": "Confirm the end date."})
        == 303
    )

    _act_as(client, "employee-alice")
    page = client.get(url)
    assert "Confirm the end date." in page.text
    reply = _form(page.text, f"{url}/clarification-response")
    assert (
        _post(
            client, f"{url}/clarification-response", {**reply, **fields, "end_date": "2026-10-06"}
        )
        == 303
    )
    page = client.get(url)
    assert "2026-10-06" in page.text
    assert _post(client, f"{url}/confirm", _form(page.text, f"{url}/confirm")) == 303

    _act_as(client, "hr-harper")
    page = client.get(url)
    assert (
        _post(client, f"{url}/start-processing", _form(page.text, f"{url}/start-processing")) == 303
    )

    _act_as(client, "manager-morgan")
    manager_page = client.get(url)
    assert manager_page.status_code == 200
    assert "processing" in manager_page.text
    assert "Family matter." not in manager_page.text

    _act_as(client, "manager-riley")
    assert client.get(url).status_code == 404


def test_stale_confirmation_is_visibly_rejected(tmp_path) -> None:
    client = _client(tmp_path)
    _act_as(client, "employee-alice")
    proposed = client.post("/requests/propose", data={"description": DESCRIPTION}, headers=ORIGIN)
    created = client.post(
        "/requests",
        data={**_form(proposed.text, "/requests"), **_fields_from(proposed.text)},
        headers=ORIGIN,
        follow_redirects=False,
    )
    url = created.headers["location"]
    stale = _form(client.get(url).text, f"{url}/confirm")
    edit_page = client.get(f"{url}/edit")
    edited = {
        **_form(edit_page.text, f"{url}/edit"),
        **_fields_from(edit_page.text),
        "end_date": "2026-10-07",
    }
    assert _post(client, f"{url}/edit", edited) == 303

    rejected = client.post(f"{url}/confirm", data=stale, headers=ORIGIN)
    assert rejected.status_code == 409
    assert "The preview changed; review and confirm it again." in rejected.text
    assert "Confirm and submit version 2" in rejected.text
