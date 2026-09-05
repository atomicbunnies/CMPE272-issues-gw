# GitHub Issues Gateway Service

**Author:** Byeonggwan Cho
**Course:** CMPE 272 – Enterprise Software Platforms

A FastAPI service that wraps the GitHub REST API for issue management in a single repository. The service supports issue creation, listing, retrieval, updating, closing/reopening, comments, webhook signature verification, event inspection, and conditional GET requests using ETags.

Repository: https://github.com/atomicbunnies/CMPE272-issues-gw

## 1. Features

* Create, list, retrieve, update, close, and reopen GitHub issues
* Add comments to GitHub issues
* Receive GitHub `issues`, `issue_comment`, and `ping` webhooks
* Verify webhook payloads with HMAC SHA-256
* Store received webhook events in memory
* Forward GitHub pagination `Link` headers
* Support conditional GET requests with `ETag` and `If-None-Match`
* Health check endpoint
* Automated tests with Pytest
* Docker and GitHub Actions support

GitHub does not provide a delete-issue operation. Therefore, the Delete operation is represented by closing an issue through `PATCH /issues/{number}` with `"state": "closed"`.

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
│   └── test_main.py
└── .github/
    └── workflows/
        └── ci.yml
```

## 3. Requirements

* Python 3.11 or later
* A GitHub repository that you control
* A fine-grained GitHub Personal Access Token

The token should have the minimum permissions required for the target repository:

* Issues: Read and write

Do not commit the real `.env` file or any GitHub token to the repository.

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

| Variable         | Description                                     |
| ---------------- | ----------------------------------------------- |
| `GITHUB_TOKEN`   | Fine-grained GitHub Personal Access Token       |
| `GITHUB_OWNER`   | GitHub repository owner                         |
| `GITHUB_REPO`    | GitHub repository name                          |
| `WEBHOOK_SECRET` | Shared secret used to verify webhook signatures |
| `PORT`           | Port used by the local service                  |

## 5. Local Installation

Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Start the service:

```bash
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --reload
```

The service will be available at:

```text
http://localhost:8000
```

Interactive API documentation is available at:

```text
http://localhost:8000/docs
```

The OpenAPI contract is provided in:

```text
openapi.yaml
```

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

The endpoint returns `201 Created` and includes a `Location` header pointing to the created issue.

### List Issues

```bash
curl "http://localhost:8000/issues?state=open&page=1&per_page=30"
```

Filter by labels:

```bash
curl "http://localhost:8000/issues?state=all&labels=bug,priority"
```

Supported query parameters:

* `state`: `open`, `closed`, or `all`
* `labels`: comma-separated label names
* `page`: page number
* `per_page`: number of results per page, up to 100

When GitHub provides pagination information, the service forwards the `Link` response header.

### Get an Issue

```bash
curl http://localhost:8000/issues/1
```

### Update an Issue

```bash
curl -X PATCH http://localhost:8000/issues/1 \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Updated issue title",
    "body": "Updated issue description"
  }'
```

### Close an Issue

Because GitHub does not support deleting issues, close an issue to represent the Delete operation:

```bash
curl -X PATCH http://localhost:8000/issues/1 \
  -H "Content-Type: application/json" \
  -d '{
    "state": "closed"
  }'
```

### Reopen an Issue

```bash
curl -X PATCH http://localhost:8000/issues/1 \
  -H "Content-Type: application/json" \
  -d '{
    "state": "open"
  }'
```

### Add a Comment

```bash
curl -X POST http://localhost:8000/issues/1/comments \
  -H "Content-Type: application/json" \
  -d '{
    "body": "I am looking into this issue."
  }'
```

The endpoint returns `201 Created`.

### Receive a Webhook

GitHub sends webhook requests to:

```text
POST /webhook
```

The request must include:

* `X-Hub-Signature-256`
* `X-GitHub-Event`
* `X-GitHub-Delivery`

Supported GitHub event types:

* `issues`
* `issue_comment`
* `ping`

Example local request:

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

A successfully verified webhook returns:

```text
204 No Content
```

### View Processed Events

```bash
curl http://localhost:8000/events
```

The endpoint returns the webhook events stored by the running service.

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

## 7. GitHub Webhook Setup

1. Start the local service:

   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```

2. Start a public tunnel. For example, with ngrok:

   ```bash
   ngrok http 8000
   ```

3. Copy the HTTPS forwarding URL provided by ngrok.

4. In the GitHub repository, open:

   ```text
   Settings → Webhooks → Add webhook
   ```

5. Configure:

   * Payload URL: `https://your-ngrok-url.ngrok-free.app/webhook`
   * Content type: `application/json`
   * Secret: the same value used for `WEBHOOK_SECRET`
   * Events: select `Issues` and `Issue comments`

6. Save the webhook.

7. Create or update an issue in the repository.

8. Check the GitHub Recent Deliveries page and verify that the request succeeded.

9. Check the local event store:

   ```bash
   curl http://localhost:8000/events
   ```

To resend a webhook, open the webhook's Recent Deliveries page in GitHub and select **Redeliver**.

## 8. Running Tests

Install the dependencies first:

```bash
pip install -r requirements.txt
```

Run the test suite:

```bash
pytest
```

The test suite covers:

* Health check verification
* Request validation for missing titles and invalid states
* Invalid webhook signature verification
* Valid webhook signature verification
* Unknown webhook event rejection
* Duplicate webhook delivery handling
* GitHub authentication error mapping
* Conditional GET and ETag behavior

The tests mock external GitHub API calls where appropriate so that the unit tests do not require a live GitHub token.

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

## 10. GitHub Actions

The repository includes a GitHub Actions workflow at:

```text
.github/workflows/ci.yml
```

The workflow:

1. Checks out the repository
2. Sets up Python 3.11
3. Installs the dependencies
4. Runs the Pytest test suite

The workflow is triggered by pushes and pull requests targeting the main branch.

## 11. Security Notes

* GitHub tokens are loaded from environment variables.
* The `.env` file is excluded from version control.
* Webhook signatures are verified with HMAC SHA-256.
* Signature comparisons use constant-time comparison through `hmac.compare_digest`.
* Secrets and raw authorization headers should not be logged.
* The GitHub API uses the required `application/vnd.github+json` Accept header.
