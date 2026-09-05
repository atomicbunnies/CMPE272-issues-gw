# System Design Note: GitHub Issues Gateway

**Author:** Byeonggwan Cho  
**Course:** CMPE 272 – Enterprise Software Platforms  

## 1. Overview

The GitHub Issues Gateway is an asynchronous FastAPI service that provides a simplified HTTP interface for managing issues and comments in one configured GitHub repository.

The service supports issue creation, listing, retrieval, updating, closing, reopening, comment creation, comment listing, webhook processing, pagination, and conditional GET requests.

GitHub does not support deleting issues. Therefore, closing an issue through `PATCH /issues/{number}` with `"state": "closed"` represents the Delete operation required by the assignment.

## 2. Error Mapping Strategy

The gateway translates common GitHub API errors into consistent responses.

- `401 Unauthorized`: GitHub authentication failed because the token is missing or invalid.
- `403 Forbidden`: GitHub denied access to the requested repository or resource.
- `404 Not Found`: The requested issue, comment, or repository resource was not found.
- `429 Too Many Requests`: The GitHub rate limit was exceeded. When available, the `Retry-After` header is forwarded to the client.
- GitHub `5xx` responses: Translated into `503 Service Unavailable`.
- GitHub connection failures: Also returned as `503 Service Unavailable`.

The gateway does not expose GitHub tokens, authorization headers, or raw signatures in error responses.

Request validation errors, such as a missing issue title or invalid issue state, are returned as `400 Bad Request`.

## 3. Pagination Strategy

The gateway accepts `page` and `per_page` query parameters. The `per_page` value is limited to a maximum of 100 items.

For issue and comment list operations, the gateway forwards GitHub's `Link` response header. Clients can use the `next` and `last` links to navigate through paginated results.

The issue list endpoint also supports `state` and `labels` filters.

## 4. Webhook Security and Processing

The `/webhook` endpoint accepts the following event types:

- `issues`
- `issue_comment`
- `ping`

Each webhook request must include:

- `X-Hub-Signature-256`
- `X-GitHub-Event`
- `X-GitHub-Delivery`

The request body is read as raw bytes before JSON parsing. The service calculates an HMAC SHA-256 digest using `WEBHOOK_SECRET` and compares it with GitHub's signature using `hmac.compare_digest`.

This constant-time comparison helps reduce timing-based signature attacks.

Requests with missing or invalid signatures return `401 Unauthorized`. Unknown event types, missing required headers, invalid JSON, and missing actions return `400 Bad Request`.

A successfully verified webhook returns `204 No Content`.

## 5. Webhook Deduplication and Storage

GitHub provides a unique delivery identifier in the `X-GitHub-Delivery` header. The gateway stores processed delivery IDs in an in-memory set.

If the same delivery is received again, the gateway recognizes the existing delivery ID and returns `204 No Content` without storing a duplicate event.

The event summary contains:

- Delivery ID
- Event type
- Action
- Issue number, when available
- Processing timestamp

The summaries are available through `GET /events`.

The current storage is in memory for simplicity. Event history and deduplication state are lost when the application restarts, and multiple service instances do not share the same state. A production deployment could use Redis or a database for durable and distributed storage.

## 6. Observability

The gateway adds an `X-Request-ID` response header to help correlate requests with log entries.

If the client sends an `X-Request-ID` header, the service reuses it. Otherwise, the service generates a UUID.

The service writes structured JSON log messages for:

- Completed requests
- GitHub connection failures
- Processed webhook deliveries
- Duplicate webhook deliveries

Sensitive values such as GitHub tokens and raw webhook signatures are not logged.

## 7. Conditional GET with ETag

The `GET /issues` endpoint supports conditional requests.

When GitHub returns an `ETag`, the gateway forwards it to the client. If the client later sends the value in an `If-None-Match` header, the gateway forwards that header to GitHub.

If the issue list has not changed, GitHub returns `304 Not Modified`, and the gateway returns the same status to the client.

This implementation forwards ETag values between the client and GitHub. It does not maintain a long-term server-side cache.

## 8. Security and Operational Trade-offs

All secrets and repository settings are loaded from environment variables. The `.env` file is excluded from version control, and the GitHub token should use only the required Issues read/write permissions.

The in-memory event store is sufficient for local development and demonstration, but it is not durable. A production implementation would use persistent storage and distributed deduplication.

Webhook processing performs only validation and lightweight event recording before returning a `204 No Content` response. Long-running work is not performed inside the webhook request.

The Docker configuration, environment-based secrets, health check endpoint, structured logging, and GitHub Actions workflow provide basic production-oriented operational support.
