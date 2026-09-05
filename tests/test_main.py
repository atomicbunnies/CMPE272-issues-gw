# Author: Byeonggwan Cho
# Course: CMPE 272
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hmac
import hashlib
import json
import pytest
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
    response = client.post("/webhook", data=payload, headers=headers)
    assert response.status_code == 401

def test_webhook_valid_signature():
    payload = json.dumps({"action": "opened", "issue": {"number": 1}}).encode("utf-8")
    secret = WEBHOOK_SECRET.encode("utf-8")
    signature = "sha256=" + hmac.new(secret, payload, hashlib.sha256).hexdigest()
    
    headers = {
        "X-GitHub-Event": "issues",
        "X-Hub-Signature-256": signature
    }
    response = client.post("/webhook", data=payload, headers=headers)
    assert response.status_code == 204

def test_conditional_get_etag():
    res1 = client.get("/issues")
    assert res1.status_code == 200
    
    etag = res1.headers.get("ETag")
    if etag:
        res2 = client.get("/issues", headers={"If-None-Match": etag})
        assert res2.status_code in [200, 304]