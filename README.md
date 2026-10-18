# Rate Limiter System

A rate-limit decision API that implements a token bucket with its state in Redis. It is an HTTP service you call with `POST /check`; it is not middleware, and `/check` has no authentication.

## Features

- Token bucket rate limiting.
- Per-identifier, per-tier buckets.
- Tiers loaded from `config.yaml` and validated with Pydantic.
- `429` responses with `Retry-After` and `X-RateLimit-*` headers.
- Atomic check-and-update using a Redis `WATCH`/`MULTI`/`EXEC` transaction.
- Async Redis client with three connection attempts at startup.
- `GET /health` endpoint.

## How it works

Each tier has a bucket whose capacity is its configured `limit`. Tokens refill continuously at `limit / window` tokens per second, and an allowed request consumes one token. The state is stored as JSON containing `tokens` and `last_refill` under `rate_limit:{tier}:{identifier}`. Redis expires the key after `2 × window` seconds.

The limiter reads and calculates the new state while watching the key. It queues the update with `MULTI` and commits it with `EXEC`. If another request changes the watched key first, Redis raises `WatchError`; the limiter retries with a short random delay, up to `MAX_ATTEMPTS` (50). If those retries are exhausted, the API returns `503` with `Retry-After: 1`.

## API

### `GET /health`

When Redis is reachable, the endpoint returns `200` with the Redis status. It also performs a rate-limit check for `demo:health` so that the response exposes `X-RateLimit-*` headers. Every `/health` call consumes one token from that bucket.

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

`tier` is optional and defaults to the `default_tier` from `config.yaml`.

An allowed response is `200` and includes the `X-RateLimit-Remaining`, `X-RateLimit-Limit`, and `X-RateLimit-Reset` headers:

```text
status 200
headers {"x-ratelimit-remaining": "99", "x-ratelimit-limit": "100", "x-ratelimit-reset": "1792304263"}
body {"allowed":true,"tokens_remaining":99,"reset_at":1792304263.3635762,"limit":100,"retry_after":null}
```

When no token is available, the response is `429`. The `Retry-After` header and JSON value are integer seconds until one token is expected to be available:

```text
status 429
headers {"x-ratelimit-remaining": "0", "x-ratelimit-limit": "100", "x-ratelimit-reset": "1792304227", "retry-after": "1"}
body {"detail":{"allowed":false,"retry_after":1,"reset_at":1792304227.1306272,"limit":100}}
```

The following `400` response is returned for an unknown tier:

```text
status 400
body {"detail":"Invalid tier: unknown"}
```

If Redis is unavailable or optimistic-lock retries are exhausted, `/check` returns `503`, a JSON `detail`, and `Retry-After: 1`. A live Redis outage produced:

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

Environment variables are:

| Variable | Default | Use |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `LOG_LEVEL` | `INFO` | Application log level |

Limits are not configurable through environment variables; they come from `config.yaml`. CORS origins are hard-coded in `main.py`.

## Run locally

Redis must be running first. With a Python 3.11 environment:

```bash
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements-dev.txt
```

Start Redis with `redis-server`, or use the Redis service from Docker Compose. Then start the API:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

The API is at `http://localhost:8000`; Swagger UI is at `/docs`.

The application also starts when only `REDIS_URL` is set. `LOG_LEVEL` defaults to `INFO`.

## Run with Docker Compose

The checked-in `docker-compose.yml` starts two services: `redis` from `redis:8-alpine`, published on port `6379`, and `rate-limiter`, built from the repository and published on port `8000`. The API container uses `REDIS_URL=redis://redis:6379` and `LOG_LEVEL=INFO`.

```bash
docker compose up --build
```

To stop the services:

```bash
docker compose down
```

## Tests

Install the development dependencies and run the suite with a live Redis server:

```bash
pip install -r requirements-dev.txt
pytest
```

The tests set `REDIS_URL` to `redis://localhost:6379/15` before importing the app unless that variable is already set. Each test flushes the selected Redis database.

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

`pytest --collect-only -q` reported `17 tests collected in 0.06s` in the verification run, and the final `pytest -q` run reported `17 passed in 3.46s`.

## Concurrency verification

The concurrency pytest uses a patched free tier of 20 tokens and sends 100 simultaneous requests for one identifier. It passed as part of the full suite.

For two live instances using the same Redis, run:

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
- Many simultaneous requests for the same identifier are serialized by optimistic retries. The measured 300-request two-instance burst took 8.340 seconds in the local run above. After `MAX_ATTEMPTS`, the API returns `503`.
- `/health` consumes one token from `demo:health` on each call.
- `/check` is unauthenticated.
- CORS origins are hard-coded in `main.py`.
- There is no fail-open or fail-closed mode. If Redis is down, `/check` returns `503`.
- Rate-limit state lives only in Redis.

## Live demo

Hosted instance (Swagger UI): https://distributed-rate-limiter-system.onrender.com/docs

## License

See [LICENSE](LICENSE) for details.
