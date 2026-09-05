# Author: Byeonggwan Cho
# Course: CMPE 272
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hmac
import hashlib
import json
import pytest
import httpx
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from main import app, WEBHOOK_SECRET

client = TestClient(app)

def test_healthz_endpoint():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_webhook_invalid_signature():
    payload = json.dumps({"action": "opened"}).encode("utf-8")
    headers = {
        "X-GitHub-Event": "issues",
        "X-Hub-Signature-256": "sha256=invalid_signature"
    }
    response = client.post("/webhook", content=payload, headers=headers)
    assert response.status_code == 401

def test_webhook_valid_signature():
    payload = json.dumps({"action": "opened", "issue": {"number": 1}}).encode("utf-8")
    secret = WEBHOOK_SECRET.encode("utf-8")
    signature = "sha256=" + hmac.new(secret, payload, hashlib.sha256).hexdigest()
    
    headers = {
        "X-GitHub-Event": "issues",
        "X-Hub-Signature-256": signature
    }
    response = client.post("/webhook", content=payload, headers=headers)
    assert response.status_code == 204

@patch("httpx.AsyncClient.get", new_callable=AsyncMock)
def test_conditional_get_etag(mock_get):
    # 실제 httpx.Response 객체를 반환하도록 구성
    resp1 = httpx.Response(
        200,
        json=[{"number": 1, "title": "Test Issue"}],
        headers={"ETag": 'W/"12345"'}
    )
    resp2 = httpx.Response(
        304,
        headers={}
    )
    mock_get.side_effect = [resp1, resp2]

    # 1. 일반 GET 요청 검증 (200 OK + ETag Header)
    res1 = client.get("/issues")
    assert res1.status_code == 200
    assert res1.headers.get("ETag") == 'W/"12345"'

    # 2. Conditional GET 요청 검증 (304 Not Modified)
    res2 = client.get("/issues", headers={"If-None-Match": 'W/"12345"'})
    assert res2.status_code == 304