# Author: Byeonggwan Cho
# Course: CMPE 272 - Enterprise Software Platforms
# Assignment: GitHub Issues Gateway Service

import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
PORT = int(os.getenv("PORT", "8000"))

GITHUB_BASE_URL = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
logger = logging.getLogger("github-issues-gateway")

WEBHOOK_EVENTS_STORE: List[Dict[str, Any]] = []
PROCESSED_DELIVERY_IDS: set[str] = set()


class IssueCreate(BaseModel):
    title: str = Field(..., min_length=1)
    body: Optional[str] = None
    labels: Optional[List[str]] = None


class IssueUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1)
    body: Optional[str] = None
    state: Optional[Literal["open", "closed"]] = None


class CommentCreate(BaseModel):
    body: str = Field(..., min_length=1)


app = FastAPI(
    title="GitHub Issues Wrapper API",
    version="1.0.0",
)


@app.middleware("http")
async def add_request_id_and_logging(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            json.dumps(
                {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": 500,
                }
            )
        )
        raise

    response.headers["X-Request-ID"] = request_id

    logger.info(
        json.dumps(
            {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
            }
        )
    )

    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "message": "Invalid request payload",
            "errors": exc.errors(),
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(
    request: Request,
    exc: HTTPException,
):
    return JSONResponse(
        status_code=exc.status_code,
        content={"message": str(exc.detail)},
        headers=exc.headers,
    )


def get_github_headers() -> Dict[str, str]:
    if not GITHUB_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GitHub token configuration is missing",
        )

    if not GITHUB_OWNER or not GITHUB_REPO:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GitHub repository configuration is missing",
        )

    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def map_github_error(response: httpx.Response) -> HTTPException:
    github_status = response.status_code

    if github_status == 401:
        return HTTPException(
            status_code=401,
            detail="GitHub authentication failed. Check the configured token.",
        )

    if github_status == 403:
        remaining = response.headers.get("X-RateLimit-Remaining")

        if remaining == "0":
            retry_after = response.headers.get("Retry-After")
            headers = {}

            if retry_after:
                headers["Retry-After"] = retry_after

            return HTTPException(
                status_code=429,
                detail="GitHub rate limit exceeded. Retry later.",
                headers=headers,
            )

        return HTTPException(
            status_code=403,
            detail="GitHub denied access to the requested resource.",
        )

    if github_status == 404:
        return HTTPException(
            status_code=404,
            detail="The requested GitHub resource was not found.",
        )

    if github_status == 429:
        retry_after = response.headers.get("Retry-After")
        headers = {}

        if retry_after:
            headers["Retry-After"] = retry_after

        return HTTPException(
            status_code=429,
            detail="GitHub rate limit exceeded. Retry later.",
            headers=headers,
        )

    if 500 <= github_status <= 599:
        return HTTPException(
            status_code=503,
            detail="GitHub is temporarily unavailable. Retry later.",
        )

    return HTTPException(
        status_code=github_status,
        detail="GitHub rejected the request.",
    )


async def github_request(
    method: str,
    url: str,
    **kwargs,
) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.request(method, url, **kwargs)
    except httpx.RequestError as exc:
        logger.error(
            json.dumps(
                {
                    "event": "github_request_error",
                    "method": method,
                    "url": url,
                    "error": str(exc),
                }
            )
        )
        raise HTTPException(
            status_code=503,
            detail="Unable to connect to GitHub.",
        ) from exc

    return response


def verify_signature(
    payload_body: bytes,
    secret: str,
    signature_header: Optional[str],
) -> bool:
    if not signature_header:
        return False

    if not signature_header.startswith("sha256="):
        return False

    expected_signature = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature_header)


@app.get("/healthz", status_code=status.HTTP_200_OK)
async def health_check():
    return {"status": "ok"}


@app.post("/issues", status_code=status.HTTP_201_CREATED)
async def create_issue(
    payload: IssueCreate,
    response: Response,
):
    headers = get_github_headers()

    data: Dict[str, Any] = {
        "title": payload.title,
    }

    if payload.body is not None:
        data["body"] = payload.body

    if payload.labels is not None:
        data["labels"] = payload.labels

    github_response = await github_request(
        "POST",
        f"{GITHUB_BASE_URL}/issues",
        json=data,
        headers=headers,
    )

    if github_response.status_code != 201:
        raise map_github_error(github_response)

    issue_data = github_response.json()
    issue_number = issue_data.get("number")

    response.headers["Location"] = f"/issues/{issue_number}"

    return issue_data


@app.get("/issues", status_code=status.HTTP_200_OK)
async def list_issues(
    request: Request,
    response: Response,
    state: Literal["open", "closed", "all"] = "open",
    labels: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
):
    headers = get_github_headers()

    if_none_match = request.headers.get("If-None-Match")

    if if_none_match:
        headers["If-None-Match"] = if_none_match

    params: Dict[str, Any] = {
        "state": state,
        "page": page,
        "per_page": per_page,
    }

    if labels:
        params["labels"] = labels

    github_response = await github_request(
        "GET",
        f"{GITHUB_BASE_URL}/issues",
        params=params,
        headers=headers,
    )

    if github_response.status_code == 304:
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers={
                "ETag": github_response.headers.get("ETag", ""),
            },
        )

    if github_response.status_code != 200:
        raise map_github_error(github_response)

    if "ETag" in github_response.headers:
        response.headers["ETag"] = github_response.headers["ETag"]

    if "Link" in github_response.headers:
        response.headers["Link"] = github_response.headers["Link"]

    return github_response.json()


@app.get("/issues/{number}", status_code=status.HTTP_200_OK)
async def get_issue(number: int):
    headers = get_github_headers()

    github_response = await github_request(
        "GET",
        f"{GITHUB_BASE_URL}/issues/{number}",
        headers=headers,
    )

    if github_response.status_code != 200:
        if github_response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Issue #{number} not found",
            )

        raise map_github_error(github_response)

    return github_response.json()


@app.patch("/issues/{number}", status_code=status.HTTP_200_OK)
async def update_issue(
    number: int,
    payload: IssueUpdate,
):
    headers = get_github_headers()
    data = payload.model_dump(exclude_unset=True)

    if not data:
        raise HTTPException(
            status_code=400,
            detail="At least one field must be provided for update",
        )

    github_response = await github_request(
        "PATCH",
        f"{GITHUB_BASE_URL}/issues/{number}",
        json=data,
        headers=headers,
    )

    if github_response.status_code != 200:
        if github_response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Issue #{number} not found",
            )

        raise map_github_error(github_response)

    return github_response.json()


@app.post(
    "/issues/{number}/comments",
    status_code=status.HTTP_201_CREATED,
)
async def create_comment(
    number: int,
    payload: CommentCreate,
):
    headers = get_github_headers()

    github_response = await github_request(
        "POST",
        f"{GITHUB_BASE_URL}/issues/{number}/comments",
        json={"body": payload.body},
        headers=headers,
    )

    if github_response.status_code != 201:
        if github_response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Issue #{number} not found",
            )

        raise map_github_error(github_response)

    return github_response.json()


@app.get("/issues/{number}/comments")
async def list_comments(
    number: int,
    response: Response,
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
):
    headers = get_github_headers()

    github_response = await github_request(
        "GET",
        f"{GITHUB_BASE_URL}/issues/{number}/comments",
        params={
            "page": page,
            "per_page": per_page,
        },
        headers=headers,
    )

    if github_response.status_code != 200:
        if github_response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Issue #{number} was not found",
            )

        raise map_github_error(github_response)

    if "Link" in github_response.headers:
        response.headers["Link"] = github_response.headers["Link"]

    return github_response.json()


@app.post(
    "/webhook",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def handle_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None),
    x_github_event: Optional[str] = Header(None),
    x_github_delivery: Optional[str] = Header(None),
):
    if not WEBHOOK_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Webhook secret configuration is missing",
        )

    if not x_github_event:
        raise HTTPException(
            status_code=400,
            detail="X-GitHub-Event header is required",
        )

    if not x_github_delivery:
        raise HTTPException(
            status_code=400,
            detail="X-GitHub-Delivery header is required",
        )

    allowed_events = {"issues", "issue_comment", "ping"}

    if x_github_event not in allowed_events:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported GitHub event: {x_github_event}",
        )

    body_bytes = await request.body()

    if not verify_signature(
        body_bytes,
        WEBHOOK_SECRET,
        x_hub_signature_256,
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid webhook signature",
        )

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON payload",
        ) from exc

    action = payload.get("action")

    if x_github_event != "ping" and not action:
        raise HTTPException(
            status_code=400,
            detail="Webhook action is required",
        )

    if x_github_delivery in PROCESSED_DELIVERY_IDS:
        logger.info(
            json.dumps(
                {
                    "event": "webhook_duplicate",
                    "delivery_id": x_github_delivery,
                    "github_event": x_github_event,
                }
            )
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    issue_number = payload.get("issue", {}).get("number")
    timestamp = datetime.now(timezone.utc).isoformat()

    event_data = {
        "id": x_github_delivery,
        "event": x_github_event,
        "action": action,
        "issue_number": issue_number,
        "timestamp": timestamp,
    }

    PROCESSED_DELIVERY_IDS.add(x_github_delivery)
    WEBHOOK_EVENTS_STORE.append(event_data)

    logger.info(
        json.dumps(
            {
                "event": "webhook_processed",
                "delivery_id": x_github_delivery,
                "github_event": x_github_event,
                "action": action,
                "issue_number": issue_number,
            }
        )
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/events", status_code=status.HTTP_200_OK)
async def list_events(
    limit: int = Query(50, ge=1, le=100),
):
    return WEBHOOK_EVENTS_STORE[-limit:]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        reload=True,
    )