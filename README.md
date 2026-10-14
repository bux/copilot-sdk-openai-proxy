# <p align="center"><img src="assets/hero.png" alt="hero" /></p>

# Copilot SDK OpenAI Proxy (Python)

OpenAI-compatible API server powered by the GitHub Copilot SDK.

It exposes the classic OpenAI endpoints so you can use standard OpenAI clients (including the official Python OpenAI SDK) against a local Copilot-backed proxy.

## Features

- Authentication UI via GitHub OAuth device flow (`GET /auth`)
- Token dashboard (`GET /auth/dashboard`) with quota and session management
- OpenAI-compatible endpoints:
  - `GET /v1/models`
  - `POST /v1/chat/completions`
- Streaming and non-streaming chat completions
- Multi-turn conversation support
- Tool calling support (including multi-step tool loops)
- Multimodal image input (`image_url` content parts)
- FastAPI server with CORS enabled

## Requirements

- Python 3.11+
- A valid GitHub token with Copilot access

## Project Layout

- `server/main.py`: FastAPI app, root UI, and endpoints
- `server/auth.py`: Auth UI, dashboard UI, and auth/dashboard APIs
- `server/state.py`: Per-token `CopilotClient` cache and session retention pruning
- `server/handlers.py`: Copilot session orchestration
- `server/converters.py`: OpenAI <-> Copilot conversion logic
- `server/models.py`: OpenAI-compatible request/response models
- `test_proxy.py`: end-to-end tests using the official OpenAI Python SDK
- `Dockerfile`: container image for running the proxy

## UI Endpoints

- `GET /`: centralized home UI (navigation)
- `GET /auth`: authentication page
- `GET /auth/dashboard`: token dashboard

## Authentication

The proxy supports two authentication methods.

### 1. GitHub Token (Bearer Token)

Pass your GitHub token in the `Authorization` header with the `Bearer` scheme:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8081/v1",
    api_key="ghp_your_github_token"
)
```

### 2. OAuth Device Flow (Web UI)

Open `http://localhost:8081/auth` and complete GitHub device flow. A token is shown after authentication.

### Auth API endpoints

- `POST /auth/device/start`: start GitHub device flow
- `POST /auth/device/poll`: poll for device flow completion
- `GET /auth/status`: check token auth status

## Token Dashboard

Open `http://localhost:8081/auth/dashboard` to:

- paste/select the GitHub token to inspect
- view Copilot quota snapshots (`account.getQuota`) including used and remaining requests
- list persisted sessions for that token
- delete a single session
- prune old sessions keeping only the latest 10

## Session Retention

The proxy prunes persisted Copilot sessions automatically to avoid unbounded growth.

- Keeps the 10 most recently modified sessions per token by default
- Deletes older sessions through the SDK (`client.delete_session`)
- Pruning is throttled (default once every 120 seconds per token)

Environment variables:

- `COPILOT_SESSION_KEEP_COUNT` (default: `10`)
- `COPILOT_SESSION_PRUNE_INTERVAL_SECONDS` (default: `120`)

## Local Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .

python -m server.main --host 0.0.0.0 --port 8081
```

## Quick API Checks

```bash
curl http://localhost:8081/health

curl http://localhost:8081/auth/status \
  -H "Authorization: Bearer ghp_your_github_token"

curl http://localhost:8081/v1/models \
  -H "Authorization: Bearer ghp_your_github_token"

curl http://localhost:8081/v1/chat/completions \
  -H "Authorization: Bearer ghp_your_github_token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5-mini",
    "messages": [{"role": "user", "content": "Say hello in one word."}]
  }'
```

## Model Discovery And Selection

`GET /v1/models` returns the model IDs currently advertised for the supplied
GitHub token. Select one of those exact IDs in Mealie or another OpenAI client;
do not configure a guessed model name such as `gpt-6-luna` unless it appears in
that response for the token being used.

The proxy forwards the requested `model` value unchanged to the Copilot SDK.
It does not use model discovery before creating a chat session, so chat
completions continue to work if a model-list request fails. The Copilot backend
decides whether the requested ID is available to that token and reports a
session error for unsupported IDs.

The proxy pins `github-copilot-sdk==1.0.21`. It passes each bearer token directly
to `CopilotClient(github_token=...)` and uses the SDK's public typed session
events. The SDK represents model billing with an optional multiplier; billing is
not exposed by this proxy.

## Offline Regression Tests

After installing the project dependencies, run the offline tests without a
GitHub token:

```bash
python -m unittest discover -s tests -v
```

The existing `test_proxy.py` is a credentialed end-to-end smoke script, not an
offline test suite. To run it locally with an existing authenticated account,
start the proxy and set `GITHUB_TOKEN` in your shell; do not commit or print the
token.

## OpenAI SDK End-to-End Test

Run server:

```bash
source .venv/bin/activate
python -m server.main --port 8081
```

In another terminal:

```bash
source .venv/bin/activate
export GITHUB_TOKEN=ghp_your_github_token
python test_proxy.py
```

## Docker

Docker Compose (recommended):

```bash
docker-compose up -d
```

or standalone Docker

The image pre-downloads the SDK-managed Copilot runtime during the build, so it
does not install Node.js or the standalone Copilot CLI.

Build:

```bash
docker build -t copilot-sdk-openai-proxy .
```

Run:

```bash
docker run --rm -p 8081:8081 \
  -e PORT=8081 \
  copilot-sdk-openai-proxy
```

Then open:

- Home UI: `http://localhost:8081/`
- Auth UI: `http://localhost:8081/auth`
- Dashboard UI: `http://localhost:8081/auth/dashboard`

### Later Deployment (Do Not Run On The Proxy Host Until Ready)

From the checked-out deployment directory, build and replace only this service:

```bash
docker compose build copilot-sdk-openai-proxy
docker compose up -d --force-recreate copilot-sdk-openai-proxy
docker compose ps copilot-sdk-openai-proxy
docker compose logs --tail=100 copilot-sdk-openai-proxy
```

Verify the deployed service through its normal network path with a valid token:

```bash
curl -fsS http://localhost:8081/health
curl -fsS http://localhost:8081/v1/models \
  -H "Authorization: Bearer $GITHUB_TOKEN"
```

## Notes

- The proxy keeps compatibility with OpenAI request/response shapes for chat completions.
- Tool execution follows the OpenAI flow: model requests tool calls, client executes tools, then client sends tool results back in follow-up messages.
- Each GitHub token gets its own cached `CopilotClient`, so multiple tokens can be used concurrently.
