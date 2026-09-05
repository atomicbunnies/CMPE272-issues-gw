# Author: Byeonggwan Cho
# Course: CMPE 272 - Enterprise Software Platforms
# Assignment: GitHub Issues Gateway Service
# Description: FastAPI gateway for GitHub REST API & Webhook HMAC Verification

import os
import hmac
import hashlib
import json
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, HTTPException, Header, status, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import httpx
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
PORT = int(os.getenv("PORT", 8000))

GITHUB_BASE_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"

# 웹훅 이벤트 인메모리 저장소
WEBHOOK_EVENTS_STORE: List[Dict[str, Any]] = []

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(
    title="GitHub Issues Wrapper API",
    version="1.0.0",
    lifespan=lifespan
)

def get_github_headers() -> Dict[str, str]:
    if not GITHUB_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GITHUB_TOKEN configuration missing"
        )
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

# --- Pydantic Schemas ---
class IssueCreate(BaseModel):
    title: str
    body: Optional[str] = None
    labels: Optional[List[str]] = None

class IssueUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    state: Optional[str] = None

class CommentCreate(BaseModel):
    body: str

# --- Endpoints ---

@app.get("/healthz", status_code=status.HTTP_200_OK)
async def health_check():
    return {"status": "ok"}

@app.post("/issues", status_code=status.HTTP_201_CREATED)
async def create_issue(payload: IssueCreate, response: Response):
    headers = get_github_headers()
    data = {"title": payload.title}
    if payload.body is not None:
        data["body"] = payload.body
    if payload.labels is not None:
        data["labels"] = payload.labels

    async with httpx.AsyncClient() as client:
        res = await client.post(f"{GITHUB_BASE_URL}/issues", json=data, headers=headers)

    if res.status_code == 401:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid GitHub Token")
    if res.status_code != 201:
        raise HTTPException(status_code=res.status_code, detail=res.text)

    issue_data = res.json()
    issue_number = issue_data.get("number")
    response.headers["Location"] = f"/issues/{issue_number}"
    return issue_data

@app.get("/issues", status_code=status.HTTP_200_OK)
async def list_issues(
    request: Request,
    response: Response,
    state: str = Query("open", enum=["open", "closed", "all"]),
    labels: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(30, le=100)
):
    headers = get_github_headers()
    
    # 클라이언트가 전송한 If-None-Match 헤더 전달 (Conditional GET)
    if_none_match = request.headers.get("if-none-match")
    if if_none_match:
        headers["If-None-Match"] = if_none_match

    params = {"state": state, "page": page, "per_page": per_page}
    if labels:
        params["labels"] = labels

    async with httpx.AsyncClient() as client:
        res = await client.get(f"{GITHUB_BASE_URL}/issues", params=params, headers=headers)

    # 변경 사항이 없으면 304 Not Modified 응답
    if res.status_code == 304:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED)

    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=res.text)

    # ETag 및 Link 헤더 전달
    if "ETag" in res.headers:
        response.headers["ETag"] = res.headers["ETag"]
    if "Link" in res.headers:
        response.headers["Link"] = res.headers["Link"]

    return res.json()

@app.get("/issues/{number}", status_code=status.HTTP_200_OK)
async def get_issue(number: int):
    headers = get_github_headers()
    async with httpx.AsyncClient() as client:
        res = await client.get(f"{GITHUB_BASE_URL}/issues/{number}", headers=headers)

    if res.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Issue #{number} not found")
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=res.text)

    return res.json()

@app.patch("/issues/{number}", status_code=status.HTTP_200_OK)
async def update_issue(number: int, payload: IssueUpdate):
    headers = get_github_headers()
    data = payload.model_dump(exclude_unset=True)

    if "state" in data and data["state"] not in ["open", "closed"]:
        raise HTTPException(status_code=400, detail="State must be 'open' or 'closed'")

    async with httpx.AsyncClient() as client:
        res = await client.patch(f"{GITHUB_BASE_URL}/issues/{number}", json=data, headers=headers)

    if res.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Issue #{number} not found")
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=res.text)

    return res.json()

@app.post("/issues/{number}/comments", status_code=status.HTTP_201_CREATED)
async def create_comment(number: int, payload: CommentCreate):
    headers = get_github_headers()
    data = {"body": payload.body}

    async with httpx.AsyncClient() as client:
        res = await client.post(f"{GITHUB_BASE_URL}/issues/{number}/comments", json=data, headers=headers)

    if res.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Issue #{number} not found")
    if res.status_code != 201:
        raise HTTPException(status_code=res.status_code, detail=res.text)

    return res.json()

# --- Webhook & Event Endpoints ---

def verify_signature(payload_body: bytes, secret: str, signature_header: str) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected_signature = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        payload_body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_signature, signature_header)

@app.post("/webhook", status_code=status.HTTP_204_NO_CONTENT)
async def handle_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None),
    x_github_event: Optional[str] = Header(None),
    x_github_delivery: Optional[str] = Header(None)
):
    body_bytes = await request.body()
    
    # HMAC 서명 검증
    if WEBHOOK_SECRET:
        if not x_hub_signature_256 or not verify_signature(body_bytes, WEBHOOK_SECRET, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # 웹훅 이벤트 정보 메모리 저장
    event_data = {
        "id": x_github_delivery,
        "event": x_github_event,
        "action": payload.get("action"),
        "issue_number": payload.get("issue", {}).get("number"),
        "payload": payload
    }
    WEBHOOK_EVENTS_STORE.append(event_data)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@app.get("/events", status_code=status.HTTP_200_OK)
async def list_events():
    return WEBHOOK_EVENTS_STORE

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)