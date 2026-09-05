# Author: Byeonggwan Cho
# Course: CMPE 272 - Enterprise Software Platforms

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

import main
from main import app

client = TestClient(app)


def make_signature(payload: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()


def test_healthz_endpoint():
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_issue_missing_title_returns_400():
    response = client.post(
        "/issues",
        json={"body": "Missing title"},
    )

    assert response.status_code == 400
    assert response.json()["message"] == "Invalid request payload"


def test_update_issue_invalid_state_returns_400():
    response = client.patch(
        "/issues/1",
        json={"state": "invalid"},
    )

    assert response.status_code == 400
    assert response.json()["message"] == "Invalid request payload"


def test_webhook_invalid_signature(monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(main, "WEBHOOK_SECRET", secret)

    payload = json.dumps(
        {
            "action": "opened",
            "issue": {"number": 1},
        }
    ).encode("utf-8")

    headers = {
        "X-GitHub-Event": "issues",
        "X-GitHub-Delivery": "invalid-delivery",
        "X-Hub-Signature-256": "sha256=invalid_signature",
    }

    response = client.post(
        "/webhook",
        content=payload,
        headers=headers,
    )

    assert response.status_code == 401


def test_webhook_valid_signature(monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(main, "WEBHOOK_SECRET", secret)

    payload = json.dumps(
        {
            "action": "opened",
            "issue": {"number": 1001},
        }
    ).encode("utf-8")

    signature = make_signature(payload, secret)

    headers = {
        "X-GitHub-Event": "issues",
        "X-GitHub-Delivery": "valid-delivery-1001",
        "X-Hub-Signature-256": signature,
    }

    response = client.post(
        "/webhook",
        content=payload,
        headers=headers,
    )

    assert response.status_code == 204

    events_response = client.get("/events")

    assert events_response.status_code == 200
    assert any(
        event["id"] == "valid-delivery-1001"
        for event in events_response.json()
    )


def test_webhook_unknown_event_returns_400(monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(main, "WEBHOOK_SECRET", secret)

    payload = b'{"action":"opened"}'
    signature = make_signature(payload, secret)

    headers = {
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": "unknown-event-delivery",
        "X-Hub-Signature-256": signature,
    }

    response = client.post(
        "/webhook",
        content=payload,
        headers=headers,
    )

    assert response.status_code == 400


def test_webhook_duplicate_delivery_is_not_stored_twice(monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(main, "WEBHOOK_SECRET", secret)

    payload = json.dumps(
        {
            "action": "created",
            "issue": {"number": 1002},
        }
    ).encode("utf-8")

    delivery_id = "duplicate-delivery-1002"
    signature = make_signature(payload, secret)

    headers = {
        "X-GitHub-Event": "issue_comment",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": signature,
    }

    first_response = client.post(
        "/webhook",
        content=payload,
        headers=headers,
    )

    second_response = client.post(
        "/webhook",
        content=payload,
        headers=headers,
    )

    assert first_response.status_code == 204
    assert second_response.status_code == 204

    matching_events = [
        event
        for event in main.WEBHOOK_EVENTS_STORE
        if event["id"] == delivery_id
    ]

    assert len(matching_events) == 1


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
def test_conditional_get_etag(mock_request):
    first_response = httpx.Response(
        200,
        json=[{"number": 1, "title": "Test Issue"}],
        headers={"ETag": 'W/"12345"'},
        request=httpx.Request(
            "GET",
            "https://api.github.com/repos/test/test/issues",
        ),
    )

    second_response = httpx.Response(
        304,
        headers={"ETag": 'W/"12345"'},
        request=httpx.Request(
            "GET",
            "https://api.github.com/repos/test/test/issues",
        ),
    )

    mock_request.side_effect = [
        first_response,
        second_response,
    ]

    first_result = client.get("/issues")

    assert first_result.status_code == 200
    assert first_result.headers.get("ETag") == 'W/"12345"'

    second_result = client.get(
        "/issues",
        headers={"If-None-Match": 'W/"12345"'},
    )

    assert second_result.status_code == 304


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
def test_github_401_is_mapped_to_gateway_error(mock_request):
    github_response = httpx.Response(
        401,
        request=httpx.Request(
            "GET",
            "https://api.github.com/repos/test/test/issues/1",
        ),
    )

    mock_request.return_value = github_response

    response = client.get("/issues/1")

    assert response.status_code == 401
    assert "authentication failed" in response.json()["message"].lower()