# Rate Limiter System

A rate-limit decision API that implements a token bucket with its state in Redis. Clients call `POST /check` to decide whether an identified request may proceed. This project is an HTTP service, not framework middleware; `/check` is intentionally unauthenticated.

## Features

- Token-bucket rate limiting with continuous refill.
- Independent buckets for each identifier and tier.
- Tier definitions loaded from `config.yaml` and validated with Pydantic.
- `429 Too Many Requests` responses with `Retry-After` and `X-RateLimit-*` headers.
- Atomic state updates using Redis `WATCH`/`MULTI`/`EXEC` optimistic transactions.
- Async Redis client with three startup connection attempts.
- `GET /health` for Redis connectivity and service status.

## How it works

For a tier with `limit` requests per `window` seconds:

1. The bucket capacity is `limit` tokens.
2. Tokens refill continuously at `limit / window` tokens per second.
3. Each allowed request consumes one token.
4. If fewer than one token is available, the request is denied.
5. The state is stored as JSON, `{ "tokens": ..., "last_refill": ... }`, at `rate_limit:{tier}:{identifier}`.
6. Redis expires the key after `2 x window` seconds.

The check-and-decrement operation must be atomic. Otherwise, concurrent requests could read the same token count and overwrite one another's updates. The limiter watches the key, reads the current state, calculates the refill and decrement, queues the write with `MULTI`, and commits it with `EXEC`.

If another request changes the key before `EXEC`, Redis raises `WatchError`. The limiter retries with a short random delay, up to `MAX_ATTEMPTS` (50). If all attempts are exhausted, the API returns `503` with `Retry-After: 1`.

The request path is:

```text
POST /check
    -> validate the tier
    -> WATCH rate_limit:{tier}:{identifier}
    -> read, refill, and decrement the bucket
    -> MULTI / EXEC
    -> return 200, 429, or 503
```

### Code map

| File | Responsibility |
|---|---|
| `main.py` | FastAPI routes, lifespan, headers, and HTTP error handling. |
| `app/config.py` | Environment defaults and Pydantic-validated YAML configuration. |
| `app/redis_client.py` | Redis connection pool, startup retries, health ping, and shutdown. |
| `app/rate_limiter.py` | Token-bucket calculation and optimistic transaction retries. |
| `tests/` | HTTP-level tests using FastAPI, `httpx`, and a live Redis database. |
| `scripts/two_instance_check.py` | Cross-instance concurrency check against two base URLs. |

## API

| Endpoint | Purpose | Success | Failure responses |
|---|---|---:|---|
| `GET /health` | Ping Redis and expose the demo rate-limit headers. | `200` | `503` when Redis ping fails. |
| `POST /check` | Decide whether one identifier may proceed. | `200` | `400`, `429`, or `503`. |

### `GET /health`

When Redis is reachable, the endpoint returns the Redis status and performs a rate-limit check for `demo:health` so the response exposes `X-RateLimit-*` headers. Every `/health` call consumes one token from that bucket.

Request:

```bash
curl http://localhost:8000/health
```

Captured from a local uvicorn run with one Redis:

```text
status 200
headers {"x-ratelimit-remaining": "99", "x-ratelimit-limit": "100", "x-ratelimit-reset": "1792304270"}
body {"status":"ok","redis":"connected"}
```

If the Redis ping fails, `/health` returns `503`:

```text
status 503
body {"detail":"Service Unavailable"}
```

### `POST /check`

Request body:

```json
{
  "identifier": "user:123",
  "tier": "free"
}
```

`identifier` is required. `tier` is optional and defaults to `default_tier` from `config.yaml`.

Call example:

```bash
curl -X POST http://localhost:8000/check \
  -H "Content-Type: application/json" \
  -d '{"identifier":"user:123","tier":"free"}'
```

An allowed response is `200`. It includes `X-RateLimit-Remaining`, `X-RateLimit-Limit`, and `X-RateLimit-Reset` headers:

```text
status 200
headers {"x-ratelimit-remaining": "99", "x-ratelimit-limit": "100", "x-ratelimit-reset": "1792304263"}
body {"allowed":true,"tokens_remaining":99,"reset_at":1792304263.3635762,"limit":100,"retry_after":null}
```

When no token is available, the response is `429`. `Retry-After` and the JSON `retry_after` value contain the integer number of seconds until one token is expected to be available:

```text
status 429
headers {"x-ratelimit-remaining": "0", "x-ratelimit-limit": "100", "x-ratelimit-reset": "1792304227", "retry-after": "1"}
body {"detail":{"allowed":false,"retry_after":1,"reset_at":1792304227.1306272,"limit":100}}
```

An unknown tier returns `400`:

```text
status 400
body {"detail":"Invalid tier: unknown"}
```

Redis failures and exhausted optimistic-lock retries return `503`, a JSON `detail`, and `Retry-After: 1`. A live Redis outage produced:

```text
check status 503
headers {"retry-after": "1"}
body {"detail":"Redis unavailable"}
```

## Configuration

Rate-limit tiers are defined in `config.yaml`:

```yaml
tiers:
  free:
    limit: 100
    window: 60
  pro:
    limit: 1000
    window: 60
  enterprise:
    limit: 10000
    window: 60
default_tier: free
```

Environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL. |
| `LOG_LEVEL` | `INFO` | Application log level. |

Limits are not configurable through environment variables; they come from `config.yaml`. CORS origins are hard-coded in `main.py`. There is no `FAIL_MODE` setting.

## Run locally

Prerequisites are Python 3.11 and a Redis server. Create a virtual environment and install the pinned development dependencies:

```bash
# Windows PowerShell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1

# macOS/Linux equivalent
# python3.11 -m venv .venv
# source .venv/bin/activate

pip install -r requirements-dev.txt
```

Start Redis with `redis-server`, or start only the Redis service from Compose:

```bash
docker compose up -d redis
```

Then start the API:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

The API is available at `http://localhost:8000`; interactive API documentation is available at `http://localhost:8000/docs`.

The application starts with only `REDIS_URL` set because `LOG_LEVEL` defaults to `INFO`.

## Run with Docker Compose

The checked-in `docker-compose.yml` defines two services:

- `redis` uses `redis:8-alpine` and publishes port `6379`.
- `rate-limiter` is built from the repository and publishes port `8000`.

The API container connects to `redis` with `REDIS_URL=redis://redis:6379` and uses `LOG_LEVEL=INFO`.

```bash
docker compose up --build
```

Stop the services with:

```bash
docker compose down
```

## Tests

The suite uses `pytest-asyncio`, `httpx.AsyncClient`, and a live Redis server:

```bash
pip install -r requirements-dev.txt
pytest
```

Before importing the application, `tests/conftest.py` defaults `REDIS_URL` to `redis://localhost:6379/15` unless that variable is already set. Each test flushes the selected Redis database. This avoids flushing the developer's default Redis database during local test runs.

The current test names and purposes are:

| Test | Description |
|---|---|
| `test_health_check` | Checks the healthy response and connected Redis status. |
| `test_health_returns_rate_limit_header` | Checks that `/health` exposes a rate-limit header. |
| `test_check_returns_rate_limit_headers` | Checks the `/check` rate-limit headers. |
| `test_rate_limit_allowed` | Checks the first allowed response and token count. |
| `test_tokens_decrement` | Checks that repeated requests decrement tokens. |
| `test_default_tier` | Checks that the configured default tier is used. |
| `test_invalid_tier` | Checks the `400` response for an unknown tier. |
| `test_rate_limit_exceeded` | Checks the `429` response after exhausting a bucket. |
| `test_different_identifiers_independent` | Checks independent buckets for different identifiers. |
| `test_pro_tier_higher_limit` | Checks the configured pro-tier limit. |
| `test_concurrent_requests_are_atomic` | Checks exact enforcement under 100 concurrent requests. |
| `test_retry_after_header_matches_body` | Checks the `Retry-After` header against the JSON value. |
| `test_refill_over_time` | Checks that a token becomes available after refill time. |
| `test_tier_buckets_are_isolated` | Checks that the same identifier has separate tier buckets. |
| `test_health_returns_503_when_redis_is_unreachable` | Checks the health response when Redis ping fails. |
| `test_env_defaults` | Checks the documented environment defaults. |
| `test_contention_exhausted_returns_503` | Checks the `503` response after retry exhaustion. |

In the verification run, `pytest --collect-only -q` reported `17 tests collected in 0.04s`, and the final `pytest -q` run reported `17 passed in 3.46s`.

## Concurrency verification

The concurrency pytest temporarily configures the free tier to 20 tokens with a 600-second window, sends 100 simultaneous requests for one identifier, and asserts that exactly 20 are allowed and 80 are rate-limited without any `5xx` responses.

For two live instances using the same Redis, run each uvicorn command in a separate terminal:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
uvicorn main:app --host 0.0.0.0 --port 8001
python scripts/two_instance_check.py http://localhost:8000 http://localhost:8001
```

The script alternates 300 requests between the two URLs. A local run using two available ports (`8001` and `8002`) and one Redis produced:

```text
200 responses: 102
429 responses: 198
elapsed seconds: 8.340
```

## Known limitations

- Timestamps come from each application server's clock. Instances with skewed clocks can refill slightly differently.
- Requests for the same identifier contend on one Redis key and are serialized by optimistic retries. The measured 300-request two-instance burst took 8.340 seconds in the local run above. After `MAX_ATTEMPTS`, the API returns `503`.
- `/health` consumes one token from `demo:health` on every call.
- `/check` is unauthenticated.
- CORS origins are hard-coded in `main.py`.
- There is no fail-open or fail-closed mode. If Redis is down, `/check` returns `503`.
- Rate-limit state lives only in Redis.

## Live demo

Hosted instance (Swagger UI): https://distributed-rate-limiter-system.onrender.com/docs

## License

See [LICENSE](LICENSE) for details.
