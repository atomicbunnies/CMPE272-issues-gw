# GitHub Issues Gateway Service

**Team:** 4 Musketeers

**Team Members:**
- Byeonggwan Cho
- Divpreet Dhingra
- Vansh Virani
- Haozheng Yang

**Course:** CMPE 272 – Enterprise Software Platforms

A FastAPI service that wraps the GitHub REST API for issue management in a single repository. The service supports issue creation, listing, retrieval, updating, closing/reopening, comments, webhook signature verification, event inspection, and conditional GET requests using ETags.

**Repository:** https://github.com/atomicbunnies/CMPE272-issues-gw

---

## 1. Features

- Create, list, retrieve, update, close, and reopen GitHub issues
- Add comments to GitHub issues
- Retrieve comments associated with GitHub issues
- Receive GitHub `issues`, `issue_comment`, and `ping` webhooks
- Verify webhook payloads with HMAC SHA-256
- Store received webhook events in memory
- Inspect processed webhook events through `/events`
- Forward GitHub pagination `Link` headers
- Support conditional GET requests with `ETag` and `If-None-Match`
- Health check endpoint
- Automated tests with Pytest
- Docker support
- GitHub Actions CI support

GitHub does not provide a delete-issue operation. Therefore, the Delete operation is represented by closing an issue through `PATCH /issues/{number}` with:

```json
{
  "state": "closed"
}
```

---

## 2. Project Structure

```text
.
├── main.py
├── openapi.yaml
├── DESIGN.md
├── requirements.txt
├── Dockerfile
├── .env.example
├── tests/
│   ├── test_main.py
│   └── test_integration.py
└── .github/
    └── workflows/
        └── ci.yml
```

---

## 3. Requirements

- Python 3.11 or later
- A GitHub repository that you control
- A fine-grained GitHub Personal Access Token

The token should have the minimum permissions required for the target repository:

- **Issues:** Read and write

Do not commit the real `.env` file or any GitHub token to the repository.

`WEBHOOK_SECRET` should be a strong random secret shared only between the GitHub webhook configuration and the gateway service. Do not commit this value to the repository.

---

## 4. Environment Variables

Copy the example file:

```bash
cp .env.example .env
```

Configure the following values in `.env`:

```env
GITHUB_TOKEN=your_fine_grained_github_token
GITHUB_OWNER=atomicbunnies
GITHUB_REPO=CMPE272-issues-gw
WEBHOOK_SECRET=your_webhook_secret
PORT=8000
```

| Variable | Description |
|---|---|
| `GITHUB_TOKEN` | Fine-grained GitHub Personal Access Token |
| `GITHUB_OWNER` | GitHub repository owner |
| `GITHUB_REPO` | GitHub repository name |
| `WEBHOOK_SECRET` | Shared secret used to verify webhook signatures |
| `PORT` | Port used by the local service |

---

## 5. Local Installation

Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

On Windows PowerShell, activate the environment with:

```powershell
.\venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Start the service:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The service will be available at:

```text
http://localhost:8000
```

Interactive API documentation is available at:

```text
http://localhost:8000/docs
```

The OpenAPI 3.1 contract is provided in:

```text
openapi.yaml
```

---

## 6. API Endpoints

### Health Check

```bash
curl http://localhost:8000/healthz
```

Example response:

```json
{
  "status": "ok"
}
```

---

### Create an Issue

```bash
curl -X POST http://localhost:8000/issues \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Test issue from the gateway",
    "body": "Created through the FastAPI wrapper.",
    "labels": ["bug"]
  }'
```

The endpoint returns:

```text
201 Created
```

The response also includes a `Location` header pointing to the created issue.

---

### List Issues

```bash
curl "http://localhost:8000/issues?state=open&page=1&per_page=30"
```

Filter by labels:

```bash
curl "http://localhost:8000/issues?state=all&labels=bug,priority"
```

Supported query parameters:

| Parameter | Description |
|---|---|
| `state` | `open`, `closed`, or `all` |
| `labels` | Comma-separated label names |
| `page` | Page number |
| `per_page` | Number of results per page, up to 100 |

When GitHub provides pagination information, the service forwards the `Link` response header.

---

### Get an Issue

```bash
curl http://localhost:8000/issues/1
```

---

### Update an Issue

```bash
curl -X PATCH http://localhost:8000/issues/1 \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Updated issue title",
    "body": "Updated issue description"
  }'
```

---

### Close an Issue

Because GitHub does not support deleting issues, closing an issue represents the Delete operation:

```bash
curl -X PATCH http://localhost:8000/issues/1 \
  -H "Content-Type: application/json" \
  -d '{
    "state": "closed"
  }'
```

---

### Reopen an Issue

```bash
curl -X PATCH http://localhost:8000/issues/1 \
  -H "Content-Type: application/json" \
  -d '{
    "state": "open"
  }'
```

---

### Add a Comment

```bash
curl -X POST http://localhost:8000/issues/1/comments \
  -H "Content-Type: application/json" \
  -d '{
    "body": "I am looking into this issue."
  }'
```

The endpoint returns:

```text
201 Created
```

---

### List Comments

Retrieve the comments associated with an issue:

```bash
curl http://localhost:8000/issues/1/comments
```

The endpoint returns `200 OK` with the list of comments for the specified issue.

---

### Receive a Webhook

GitHub sends webhook requests to:

```text
POST /webhook
```

The request must include:

- `X-Hub-Signature-256`
- `X-GitHub-Event`
- `X-GitHub-Delivery`

Supported GitHub event types:

- `issues`
- `issue_comment`
- `ping`

Example request structure:

```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: ping" \
  -H "X-GitHub-Delivery: example-delivery-id" \
  -H "X-Hub-Signature-256: sha256=signature-generated-by-github" \
  -d '{
    "zen": "Keep it logically awesome.",
    "hook_id": 123456
  }'
```

> **Note:** The signature shown above is a placeholder. A real request must contain a valid HMAC SHA-256 signature calculated from the exact raw request body using `WEBHOOK_SECRET`. GitHub generates this signature automatically for configured webhook deliveries.

A webhook with a valid signature and supported event returns:

```text
204 No Content
```

---

### View Processed Events

```bash
curl http://localhost:8000/events
```

The endpoint returns the webhook events stored by the running service.

Because the current implementation uses an in-memory event store, stored events are reset when the service restarts.

---

### Conditional GET with ETag

First request:

```bash
curl -i http://localhost:8000/issues
```

Copy the returned `ETag` value and send it in a later request:

```bash
curl -i http://localhost:8000/issues \
  -H 'If-None-Match: W/"example-etag"'
```

If the issue list has not changed, the service returns:

```text
304 Not Modified
```

---

## 7. GitHub Webhook Setup

Start the local service:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Start a public tunnel. For example, with ngrok:

```bash
ngrok http 8000
```

Copy the HTTPS forwarding URL provided by ngrok.

In the GitHub repository, open:

```text
Settings → Webhooks → Add webhook
```

Configure:

- **Payload URL:** `https://your-ngrok-url.ngrok-free.app/webhook`
- **Content type:** `application/json`
- **Secret:** the same value used for `WEBHOOK_SECRET`
- **Events:** select **Issues** and **Issue comments**

Save the webhook.

Create or update an issue in the repository.

Check the GitHub **Recent Deliveries** page and verify that the request succeeded.

Check the local event store:

```bash
curl http://localhost:8000/events
```

To resend a webhook, open the webhook's **Recent Deliveries** page in GitHub and select **Redeliver**.

---

## 8. Running Tests

Install the dependencies first:

```bash
pip install -r requirements.txt
```

Run the test suite:

```bash
pytest
```

Run the coverage report:

```bash
python -m pytest --cov=main --cov-report=term-missing
```

The test suite covers:

- Health check verification
- Request validation for missing titles and invalid states
- Invalid webhook signature verification
- Valid webhook signature verification
- Unknown webhook event rejection
- Duplicate webhook delivery handling
- GitHub authentication error mapping
- Conditional GET and ETag behavior
- GitHub `Link` header parsing and pagination behavior

The tests mock external GitHub API calls where appropriate so that the unit tests do not require a live GitHub token.

### GitHub Integration Test

The opt-in integration test in `tests/test_integration.py` exercises the complete issue lifecycle against the configured repository:

- Create an issue
- Retrieve the issue
- Update the issue
- Close the issue
- Reopen the issue
- Create a comment
- Retrieve the comment list

Run the integration test only against a dedicated test repository:

```bash
RUN_GITHUB_INTEGRATION=1 python -m pytest tests/test_integration.py -v
```

The integration test is skipped by default and is not run in CI. Therefore, normal test runs do not modify the configured GitHub repository or require a live GitHub token.

---

## 9. Docker

Build the image:

```bash
docker build -t github-issues-gateway .
```

Run the service:

```bash
docker run --rm \
  --env-file .env \
  -p 8000:8000 \
  github-issues-gateway
```

The service will be available at:

```text
http://localhost:8000
```

Verify the running container using:

```bash
curl http://localhost:8000/healthz
```

Expected response:

```json
{
  "status": "ok"
}
```

---

## 10. GitHub Actions

The repository includes a GitHub Actions workflow at:

```text
.github/workflows/ci.yml
```

The workflow:

- Checks out the repository
- Sets up Python 3.11
- Installs the dependencies
- Runs the Pytest test suite with coverage reporting
- Builds the Docker image

The workflow is triggered by pushes and pull requests targeting the `main` branch.

---

## 11. Security Notes

- GitHub tokens are loaded from environment variables.
- The `.env` file is excluded from version control.
- Webhook signatures are verified with HMAC SHA-256.
- Signature comparisons use constant-time comparison through `hmac.compare_digest`.
- Secrets and raw authorization headers should not be logged.
- The GitHub API uses the required `application/vnd.github+json` `Accept` header.
- The GitHub Personal Access Token should be scoped only to the repository and permissions required by the service.
- `WEBHOOK_SECRET` should not be committed or exposed in screenshots or documentation.

---

## 12. Team Contributions

The project was completed collaboratively by the **4 Musketeers** team. Byeonggwan Cho served as the primary software implementer. Other team members contributed through quality assurance, API contract and documentation review, deployment verification, and final project delivery.

### Byeonggwan Cho — Software Implementation & Integration

- Implemented the FastAPI service architecture
- Implemented GitHub REST API integration and configuration
- Implemented issue creation, listing, retrieval, updating, closing, and reopening
- Implemented issue comment operations
- Implemented pagination and HTTP error handling
- Implemented webhook processing and HMAC SHA-256 signature verification
- Implemented webhook event handling and duplicate delivery handling
- Implemented rate-limit and GitHub API error behavior
- Implemented conditional GET and ETag support
- Implemented the automated test infrastructure
- Implemented Docker and GitHub Actions CI configuration

### Vansh Virani — Testing & Quality Assurance

- Reviewed and verified the Pytest test suite
- Verified request validation and error-handling behavior
- Verified webhook signature and event-handling tests
- Verified pagination and conditional GET behavior
- Reviewed mocked GitHub API tests
- Verified test coverage results
- Performed final functional and regression testing of the service

### Haozheng Yang — API Contract & Documentation

- Reviewed and finalized the OpenAPI 3.1 API contract
- Reviewed API endpoints, request models, response models, and documented error behavior
- Edited and finalized the README documentation
- Organized API interaction examples and screenshots
- Prepared and edited the final project report
- Documented team contributions
- Reviewed setup, configuration, Docker, testing, and API usage instructions
- Prepared the final submission checklist and deliverable review

### Divpreet Dhingra — Deployment Verification & Submission

- Verified the final project structure and required deliverables
- Verified environment configuration and setup instructions
- Verified Docker build and runtime instructions
- Reviewed the repository for submission readiness
- Reviewed the final documentation and project artifacts
- Coordinated final project delivery
- Performed the final Canvas submission
- Verified that the required submission files were successfully submitted

---

## 13. Design Documentation

Additional implementation and design decisions are documented in:

```text
DESIGN.md
```

This document describes design choices related to GitHub API integration, error mapping, pagination, webhook security, duplicate delivery handling, and other implementation considerations.
