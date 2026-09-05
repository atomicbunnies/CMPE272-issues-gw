# System Design Note: GitHub Issues Gateway

**Author:** Byeonggwan Cho  
**Course:** CMPE 272 – Enterprise Software Platforms  

## 1. Error Mapping Strategy
Upstream GitHub API HTTP status codes are transparently intercepted and mapped using FastAPI exception handlers.
* **401 Unauthorized / 403 Forbidden**: Mapped to standard gateway error formats without exposing raw PAT tokens or GitHub authorization headers.
* **404 Not Found**: Returned directly when requested issue or comment resources do not exist in the target repository.
* **429 Too Many Requests / Rate Limits**: GitHub rate limit headers (`X-RateLimit-Remaining`, `X-RateLimit-Reset`) are parsed to generate client-side 429 response payloads encouraging backoff.

## 2. Pagination Strategy
The service forwards GitHub REST API v3 pagination controls seamlessly:
* Accepts `page` and `per_page` query parameters (capped at a maximum of 100 items per request).
* Preserves and forwards the upstream RFC 5988 `Link` HTTP response header (`rel="next"`, `rel="last"`), allowing callers to navigate paginated results naturally.

## 3. Webhook Security & Deduplication
* **Constant-Time HMAC Verification**: Webhook payloads are authenticated via `X-Hub-Signature-256` using `hmac.compare_digest` with SHA-256. This prevents timing side-channel attacks during signature evaluation.
* **Idempotency & Retry Handling**: Incoming webhook deliveries contain a unique GUID in the `X-GitHub-Delivery` header. Evaluated events are stored in an in-memory execution cache by delivery ID to silently process duplicate redeliveries without creating redundant logs or state side effects.

## 4. Security & Operational Trade-offs
* **Secret Isolation**: Configuration and secrets are exclusively managed via 12-factor environment variables (`.env`), ensuring no credentials leak into version control.
* **Stateless Gateway Design**: By remaining stateless (except for ephemeral in-memory event deduplication), the gateway scales horizontally behind load balancers with minimal infrastructure complexity.

## 5. Extra Credit: Conditional GET (ETag)
Implemented ETag evaluation for `GET /issues`. Sending an `If-None-Match` header yields a `304 Not Modified` response when cached, optimizing bandwidth usage.
