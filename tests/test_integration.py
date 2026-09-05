"""Opt-in integration tests against the configured GitHub repository.

Run with RUN_GITHUB_INTEGRATION=1 after setting the required environment
variables. These tests intentionally do not run in normal local or CI runs.
"""

import os

import pytest
from fastapi.testclient import TestClient

import main
from main import app


pytestmark = pytest.mark.integration


if os.getenv("RUN_GITHUB_INTEGRATION") != "1":
    pytest.skip(
        "Set RUN_GITHUB_INTEGRATION=1 to run tests against GitHub",
        allow_module_level=True,
    )


client = TestClient(app)


def test_issue_lifecycle_and_comment_in_github():
    response = client.post(
        "/issues",
        json={
            "title": "Automated integration test issue",
            "body": "Created by tests/test_integration.py",
        },
    )
    assert response.status_code == 201
    number = response.json()["number"]

    fetched = client.get(f"/issues/{number}")
    assert fetched.status_code == 200

    updated = client.patch(
        f"/issues/{number}",
        json={"title": "Updated integration test issue", "body": "Updated"},
    )
    assert updated.status_code == 200

    closed = client.patch(f"/issues/{number}", json={"state": "closed"})
    assert closed.status_code == 200
    reopened = client.patch(f"/issues/{number}", json={"state": "open"})
    assert reopened.status_code == 200

    comment = client.post(
        f"/issues/{number}/comments",
        json={"body": "Integration test comment"},
    )
    assert comment.status_code == 201

    comments = client.get(f"/issues/{number}/comments")
    assert comments.status_code == 200
    assert any(item["id"] == comment.json()["id"] for item in comments.json())

    # Leave the test repository clean after the lifecycle check.
    cleanup = client.patch(f"/issues/{number}", json={"state": "closed"})
    assert cleanup.status_code == 200
