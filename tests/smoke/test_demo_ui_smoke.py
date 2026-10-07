"""The demo app starts offline from the environment and serves its first page (Issue #14)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from enterprise_employee_agent.web.server import create_app_from_env


@pytest.mark.smoke
def test_demo_app_starts_offline_from_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DEMO_DATABASE_PATH", str(tmp_path / "demo.sqlite"))
    client = TestClient(create_app_from_env())
    client.post(
        "/identity", data={"identity_id": "employee-alice"}, headers={"origin": "http://testserver"}
    )
    page = client.get("/")
    assert page.status_code == 200
    assert "offline · scripted" in page.text
    assert (tmp_path / "demo.sqlite").exists()
