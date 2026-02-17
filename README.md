# Rate Limiter System

A flexible, Redis-backed rate limiting system with configurable tiers and fail-safe behavior.

## Features

- **Token Bucket Rate Limiting** — smooth, burst-friendly algorithm
- **Multi-tier rate limiting** (free, pro, enterprise) with per-user isolation
- **FastAPI REST API** with `/health` and `/check` endpoints
- **Redis-backed** for distributed, persistent rate limiting
- **Configurable** via YAML (`config.yaml`) and environment variables (`.env`)
- **Fail-safe modes** (fail-open or fail-closed on Redis unavailability)
- **Async Redis client** with automatic retry logic (3 retries, 2s delay)
- **Pydantic validation** for request/response schemas
- **Health checks** for monitoring Redis connectivity
- **Comprehensive test suite** using `pytest-asyncio` and `httpx`

## How It Works — Token Bucket Algorithm

The system uses a **Token Bucket** algorithm to control request rates:

1. Each user starts with a full bucket of tokens (e.g., 100 for `free` tier).
2. Every request consumes **1 token**.
3. Tokens refill continuously at a rate of `limit / window` tokens per second.
4. If the bucket is empty, the request is **denied** with a `429 Too Many Requests` response.
5. Bucket state (tokens + last refill timestamp) is stored in Redis with a TTL of `2× window`.

## Requirements

- Python 3.8+
- Redis
- Docker & Docker Compose (optional, for easy Redis setup)

## Quick Start

### 1. Clone and Install

```bash
git clone <your-repo-url>
cd rate-limiter-system
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env if needed (default values work for local development)
```

### 3. Start Redis

**Option A: Using Docker Compose (Recommended)**
```bash
docker-compose up -d
```

**Option B: Local Redis**
```bash
redis-server
```

### 4. Run the Application

```bash
uvicorn main:app --reload
```

The API server starts at `http://localhost:8000`. Interactive docs are available at `http://localhost:8000/docs`.

## API Endpoints

### `GET /health` — Health Check

Returns the service and Redis connection status.

```bash
curl http://localhost:8000/health
```

**Response (200):**
```json
{
  "status": "ok",
  "redis": "connected"
}
```

### `POST /check` — Check Rate Limit

Checks whether a request is allowed for the given identifier and tier.

**Request Body:**
| Field        | Type   | Required | Description                              |
|--------------|--------|----------|------------------------------------------|
| `identifier` | string | Yes      | Unique key for the user/client (e.g. `user:123`) |
| `tier`       | string | No       | Rate limit tier (`free`, `pro`, `enterprise`). Defaults to `free`. |

```bash
curl -X POST http://localhost:8000/check \
  -H "Content-Type: application/json" \
  -d '{"identifier": "user:123", "tier": "free"}'
```

**Response (200 — Allowed):**
```json
{
  "allowed": true,
  "tokens_remaining": 99,
  "reset_at": 1700000060.0,
  "limit": 100,
  "retry_after": null
}
```

**Response (429 — Rate Limited):**
```json
{
  "detail": {
    "allowed": false,
    "retry_after": 60,
    "reset_at": 1700000060.0,
    "limit": 100
  }
}
```

**Response (400 — Invalid Tier):**
```json
{
  "detail": "Invalid tier: invalid_tier"
}
```

## Configuration

### Rate Limit Tiers (`config.yaml`)

```yaml
tiers:
  free:
    limit: 100    # requests
    window: 60    # seconds

  pro:
    limit: 1000
    window: 60

  enterprise:
    limit: 10000
    window: 60

default_tier: free
```

### Environment Variables (`.env`)

| Variable    | Description                                      | Default                    |
|-------------|--------------------------------------------------|----------------------------|
| `REDIS_URL` | Redis connection URL                             | `redis://localhost:6379`   |
| `LOG_LEVEL` | Logging level                                    | `INFO`                     |
| `FAIL_MODE` | Behavior on Redis failure (`open` or `closed`)   | `closed`                   |

## Project Structure

```
rate-limiter-system/
├── app/
│   ├── config.py              # Configuration loading (env + YAML) with Pydantic validation
│   ├── rate_limiter.py        # Token Bucket algorithm implementation
│   ├── redis_client.py        # Async Redis connection with retry logic
├── tests/
│   ├── __init__.py
│   ├── conftest.py            # Pytest fixtures (async client, Redis flush)
│   └── test_api.py            # API integration tests (health, rate limit, tiers)
├── docs/
│   └── ProjectDocs.md         # Detailed design documentation
├── config.yaml                # Rate limit tier definitions
├── docker-compose.yml         # Redis container setup
├── main.py                    # FastAPI application entry point
├── pytest.ini                 # Pytest configuration (asyncio_mode = auto)
├── requirements.txt           # Production dependencies
├── requirements-dev.txt       # Development dependencies (pytest, black, ruff, mypy)
├── .env.example               # Environment variable template
└── .gitignore
```

## Development

### Install Dev Dependencies

```bash
pip install -r requirements-dev.txt
```

### Run Tests

The test suite uses `pytest-asyncio` with `httpx.AsyncClient` against the real FastAPI app and a live Redis instance.

```bash
pytest
```

**Test coverage includes:**

| Test                              | Description                                     |
|-----------------------------------|-------------------------------------------------|
| `test_health_check`              | Health endpoint returns `ok` + Redis status      |
| `test_rate_limit_allowed`        | First request is allowed with correct token count |
| `test_tokens_decrement`          | Tokens decrease with each request                |
| `test_default_tier`              | Default tier (`free`) is used when none specified |
| `test_invalid_tier`              | Returns `400` for an unknown tier                |
| `test_rate_limit_exceeded`       | Returns `429` after exhausting all tokens        |
| `test_different_identifiers_independent` | Different users have independent buckets  |
| `test_pro_tier_higher_limit`     | Pro tier returns `limit: 1000`                   |

### Concurrency Testing

> **Note:** Race conditions are a known limitation of the current JSON-based state reads. A Lua script approach would make the check-and-decrement operation atomic.

## Health Check

```bash
curl http://localhost:8000/health
```

## Shutdown

```bash
# Stop the API server
# (Ctrl+C in the terminal running uvicorn)

# Stop Redis container
docker-compose down
```

## License

See [LICENSE](LICENSE) for details.

## Documentation

For detailed design decisions and implementation details, see [docs/ProjectDocs.md](docs/ProjectDocs.md).
