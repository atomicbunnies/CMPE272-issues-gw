# Author: Byeonggwan Cho
# Course: CMPE 272 - Enterprise Software Platforms

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

import main
from main import app, map_github_error, parse_link_header, verify_signature

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


def test_parse_link_header_returns_relation_urls():
    header = (
        '<https://api.github.com/issues?page=2>; rel="next", '
        '<https://api.github.com/issues?page=5>; rel="last"'
    )

    assert parse_link_header(header) == {
        "next": "https://api.github.com/issues?page=2",
        "last": "https://api.github.com/issues?page=5",
    }
    assert parse_link_header(None) == {}


def test_verify_signature_rejects_missing_or_malformed_signature():
    assert verify_signature(b"payload", "secret", None) is False
    assert verify_signature(b"payload", "secret", "invalid") is False


def test_missing_github_configuration_returns_500(monkeypatch):
    monkeypatch.setattr(main, "GITHUB_TOKEN", None)

    response = client.get("/issues/1")

    assert response.status_code == 500
    assert "configuration" in response.json()["message"].lower()


def test_missing_repository_configuration_returns_500(monkeypatch):
    monkeypatch.setattr(main, "GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(main, "GITHUB_OWNER", None)

    response = client.get("/issues/1")

    assert response.status_code == 500
    assert "repository" in response.json()["message"].lower()


@pytest.mark.parametrize(
    ("status_code", "headers", "expected_status"),
    [
        (403, {}, 403),
        (404, {}, 404),
        (429, {}, 429),
        (500, {}, 503),
        (418, {}, 418),
    ],
)
def test_github_error_mapping(status_code, headers, expected_status):
    response = httpx.Response(status_code, headers=headers)

    assert map_github_error(response).status_code == expected_status


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
def test_github_connection_failure_is_mapped_to_503(mock_request, monkeypatch):
    monkeypatch.setattr(main, "GITHUB_TOKEN", "test-token")
    mock_request.side_effect = httpx.ConnectError("connection failed")

    response = client.get("/issues/1")

    assert response.status_code == 503
    assert "connect" in response.json()["message"].lower()


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
def test_issue_routes_forward_github_requests(mock_request, monkeypatch):
    monkeypatch.setattr(main, "GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(main, "GITHUB_OWNER", "test-owner")
    monkeypatch.setattr(main, "GITHUB_REPO", "test-repo")

    issue = {
        "number": 7,
        "html_url": "https://github.com/test-owner/test-repo/issues/7",
        "state": "open",
        "title": "Example",
        "body": "Body",
        "labels": [],
    }
    request = httpx.Request("GET", "https://api.github.com/test")
    responses = [
        httpx.Response(201, json=issue, request=request),
        httpx.Response(
            200,
            json=[issue],
            headers={"Link": '<next>; rel="next"'},
            request=request,
        ),
        httpx.Response(200, json=issue, request=request),
        httpx.Response(200, json=issue, request=request),
    ]
    mock_request.side_effect = responses

    created = client.post("/issues", json={"title": "Example"})
    listed = client.get("/issues?page=2&per_page=10")
    fetched = client.get("/issues/7")
    updated = client.patch("/issues/7", json={"state": "closed"})

    assert created.status_code == 201
    assert created.headers["Location"] == "/issues/7"
    assert listed.status_code == 200
    assert listed.headers["Link"] == '<next>; rel="next"'
    assert fetched.status_code == 200
    assert updated.status_code == 200
    assert mock_request.call_count == 4


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
def test_comment_routes_forward_github_requests(mock_request, monkeypatch):
    monkeypatch.setattr(main, "GITHUB_TOKEN", "test-token")
    comment = {"id": 10, "body": "A comment", "user": {"login": "jb"}}
    mock_request.side_effect = [
        httpx.Response(201, json=comment),
        httpx.Response(200, json=[comment], headers={"Link": '<last>; rel="last"'}),
    ]

    created = client.post("/issues/7/comments", json={"body": "A comment"})
    listed = client.get("/issues/7/comments?per_page=10")

    assert created.status_code == 201
    assert listed.status_code == 200
    assert listed.headers["Link"] == '<last>; rel="last"'


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
def test_github_rate_limit_and_server_errors_are_mapped(mock_request, monkeypatch):
    monkeypatch.setattr(main, "GITHUB_TOKEN", "test-token")
    mock_request.side_effect = [
        httpx.Response(
            403,
            headers={"X-RateLimit-Remaining": "0", "Retry-After": "30"},
        ),
        httpx.Response(503),
    ]

    rate_limited = client.get("/issues/1")
    unavailable = client.get("/issues/2")

    assert rate_limited.status_code == 429
    assert rate_limited.headers["Retry-After"] == "30"
    assert unavailable.status_code == 503


def test_webhook_rejects_invalid_json_and_ping_is_accepted(monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(main, "WEBHOOK_SECRET", secret)

    invalid_payload = b"not-json"
    invalid_headers = {
        "X-GitHub-Event": "issues",
        "X-GitHub-Delivery": "invalid-json-delivery",
        "X-Hub-Signature-256": make_signature(invalid_payload, secret),
    }
    invalid_response = client.post(
        "/webhook",
        content=invalid_payload,
        headers=invalid_headers,
    )

    ping_payload = b'{}'
    ping_headers = {
        "X-GitHub-Event": "ping",
        "X-GitHub-Delivery": "ping-delivery",
        "X-Hub-Signature-256": make_signature(ping_payload, secret),
    }
    ping_response = client.post(
        "/webhook",
        content=ping_payload,
        headers=ping_headers,
    )

    assert invalid_response.status_code == 400
    assert ping_response.status_code == 204


def test_webhook_requires_delivery_and_action(monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(main, "WEBHOOK_SECRET", secret)
    payload = b'{}'
    signature = make_signature(payload, secret)

    no_delivery = client.post(
        "/webhook",
        content=payload,
        headers={
            "X-GitHub-Event": "issues",
            "X-Hub-Signature-256": signature,
        },
    )
    no_action = client.post(
        "/webhook",
        content=payload,
        headers={
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": "no-action-delivery",
            "X-Hub-Signature-256": signature,
        },
    )

    assert no_delivery.status_code == 400
    assert no_action.status_code == 400
