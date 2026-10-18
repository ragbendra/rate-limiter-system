# Configuration and Redis Setup

This document explains the configuration, Redis connection, token-bucket algorithm, HTTP API, and tests in this repository. It is intended to make the code easier to read without replacing the code as the source of behavior.

---

## 1. Overall Idea

The service has two external inputs: environment configuration and a Redis server. `app/config.py` loads environment values and `config.yaml`; `app/redis_client.py` manages the async Redis client. The FastAPI application calls these components from `main.py`.

Redis is required for normal operation because the token-bucket state is stored there. The application attempts to connect during startup and raises the connection error after three failed attempts.

---

## 2. Configuration (`config.py`)

`config.py` loads environment values, reads `config.yaml`, validates the YAML models with Pydantic, and exposes the resulting `settings` object. Rate limits are not read from environment variables.

---

## 3. Environment Configuration

The supported environment variables are:

| Variable | Default | Meaning |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `LOG_LEVEL` | `INFO` | Application log level |

`load_env()` applies these defaults when variables are unset. There is no `FAIL_MODE` setting and the application does not implement fail-open or fail-closed behavior.

---

## 4. Rate Limit Configuration (YAML)

`config.yaml` defines the `free`, `pro`, and `enterprise` tiers. Each tier has a positive integer `limit` and `window`. `default_tier` names the tier used when a request omits `tier`.

`Tier` and `RateLimitConfig` validate the values. `RateLimitConfig` also checks that `default_tier` is present in the tier dictionary.

---

## 5. Settings Object

`Settings` loads the environment and YAML configuration once when the module is imported. Its `get_tier()` method returns the named tier, or the configured default tier if called with an unknown name. The HTTP layer validates a supplied tier before calling the limiter, so an unknown HTTP tier returns `400`.

---

## 6. Redis Client (`redis_client.py`)

`RedisClient` owns the async Redis client and its lifecycle. The client is built with `redis.asyncio.BlockingConnectionPool.from_url()` using `max_connections=100` and a 10-second pool timeout, then wrapped in `redis.asyncio.Redis(connection_pool=pool)`.

The larger pool permits concurrent optimistic-lock transactions to hold connections while they watch a key.

---

## 7. RedisClient Class

The class stores the configured Redis URL, the client object, and an `is_connected` flag. `get_client()` returns the client only after a successful connection. `ping()` returns a boolean and does not retry or reconnect.

---

## 8. Connecting to Redis

`connect()` tries to ping Redis up to three times, waiting two seconds between failed attempts. A successful ping marks the client connected. If all attempts fail, the final exception is raised and application startup does not complete.

---

## 9. Accessing the Redis Client

The rate limiter obtains the client through `redis_client.get_client()`. This keeps connection setup out of the rate-limiting calculation and makes use before startup an explicit error.

---

## 10. Health Checks

`RedisClient.ping()` sends one Redis `PING` and returns `True` or `False`. `GET /health` uses that result. A successful ping produces `200`; a failed ping produces `503` with `{"detail":"Service Unavailable"}`.

After a successful ping, `/health` performs a rate-limit check for `demo:health` and adds `X-RateLimit-Remaining`, `X-RateLimit-Limit`, and `X-RateLimit-Reset` headers. That check consumes one token.

---

## 11. Shutdown Handling

The FastAPI lifespan closes the Redis client at shutdown with `aclose()` and resets the connection state.

---

## 12. Application Startup (`main.py`)

The lifespan function connects to Redis before yielding control to the application and closes Redis after the application stops. Logging is configured from `LOG_LEVEL`, whose default is `INFO`.

---

## 13. What Is Intentionally Not Included

The repository does not include authentication, middleware integration, configurable CORS origins, a fail-open/fail-closed switch, or rate limits supplied through environment variables. The HTTP API is limited to `/health` and `/check`.

---

## 14. Why This Design Was Chosen

Configuration, Redis lifecycle, rate-limit calculations, and HTTP formatting are kept in separate modules. This matches the current repository structure and makes each responsibility visible in the code.

---

## 15. Token-Bucket Algorithm

For a tier with `limit` and `window`, capacity is `limit` and the refill rate is `limit / window` tokens per second. The first request starts with a full bucket. Each allowed request subtracts one token. The calculated token count is capped at the tier capacity.

The bucket state is JSON with the fields `tokens` and `last_refill`. It is stored at `rate_limit:{tier}:{identifier}` with a Redis TTL of `2 × window`. Including the tier in the key gives the same identifier independent buckets for `free`, `pro`, and `enterprise`.

If fewer than one token is available, the request is denied without changing the bucket. `retry_after` is calculated from the time needed to refill one token and is at least one second.

---

## 16. Atomic Check-and-Update

The limiter uses a Redis optimistic transaction. It watches the bucket key, reads the state, calculates the refill and decrement, queues the `SET` with `MULTI`, and commits it with `EXEC`.

Without the transaction, concurrent requests could read the same token count and overwrite one another's decrements. If another request changes the watched key before `EXEC`, Redis raises `WatchError`. The limiter waits for a random delay and retries, up to `MAX_ATTEMPTS` (50). When retries are exhausted, it raises `RateLimiterBusy`; `/check` converts that condition to `503` with `Retry-After: 1`.

---

## 17. Summary

The service stores token-bucket state in Redis, validates tier configuration from YAML, and uses an optimistic transaction for each check-and-update. The HTTP layer reports allowed, rate-limited, invalid-tier, and Redis/contention-failure outcomes with the corresponding status codes and headers.

---

# FastAPI Application Layer

This section describes the HTTP layer. It validates the request, delegates to the rate limiter, and formats the result; it does not calculate tokens itself.

## 18. Application Lifecycle

FastAPI lifespan events connect to Redis before serving requests and close the client during shutdown. A startup connection failure prevents normal application startup.

## 19. Data Contracts

The request model is:

```json
{
  "identifier": "user:123",
  "tier": "free"
}
```

`identifier` is required. `tier` is optional and defaults to the configured default tier.

An allowed `/check` response is `200`:

```json
{
  "allowed": true,
  "tokens_remaining": 99,
  "reset_at": 1792304263.3635762,
  "limit": 100,
  "retry_after": null
}
```

A rate-limited response is `429` with this body shape and a matching `Retry-After` header:

```json
{
  "detail": {
    "allowed": false,
    "retry_after": 1,
    "reset_at": 1792304227.1306272,
    "limit": 100
  }
}
```

## 20. Endpoints

### `GET /health`

The endpoint pings Redis. A successful ping returns `200` and `{"status":"ok","redis":"connected"}`. A failed ping returns `503` and `{"detail":"Service Unavailable"}`. On success, the endpoint also checks `demo:health` and returns the rate-limit headers.

### `POST /check`

The endpoint validates the tier, calls the limiter, and returns the result. Invalid tiers return `400`. Allowed requests return `200`. Denied requests return `429` with `Retry-After`. Redis errors and `RateLimiterBusy` return `503` with `Retry-After: 1`.

| Scenario | Status |
|---|---:|
| Invalid tier | `400` |
| Allowed | `200` |
| Rate limited | `429` |
| Redis or contention failure | `503` |

## 21. Error Handling Strategy

The API preserves the distinction between client input errors, rate limiting, and temporary service conditions:

| Code | Meaning |
|---:|---|
| `400` | The requested tier is not configured. |
| `429` | The bucket has fewer than one token. |
| `503` | Redis is unavailable or optimistic retries were exhausted. |

## 22. Architectural Responsibility

**API layer:** request validation, HTTP status codes, response bodies, headers, and Redis-dependent error handling.

**Rate limiter core:** token calculations, tier-key construction, Redis state reads and writes, and optimistic transaction retries.

**Configuration and Redis modules:** settings validation and connection lifecycle.

## 23. API Behavior That Callers Must Account For

`/check` has no authentication. CORS origins are hard-coded in `main.py`. `/health` consumes one token from `demo:health`. Rate-limit state is held only in Redis, so Redis is required for checks.

---

# API Testing Documentation

The tests use `httpx.AsyncClient` with the FastAPI application and a live Redis server. They exercise the observable HTTP behavior and the configuration and refill behavior needed by the limiter.

## 24. Testing Strategy

The suite checks health responses, headers, token decrementing, default and configured tiers, invalid input, rate-limit enforcement, identifier and tier isolation, concurrent atomicity, refill timing, environment defaults, Redis failure, and contention exhaustion.

## 25. Shared Test Setup (`conftest.py`)

Before importing `main`, the test setup defaults `REDIS_URL` to `redis://localhost:6379/15` when the variable is unset. The async fixtures connect to Redis, flush the selected database before each test, provide an `httpx.AsyncClient`, and close Redis afterward. An existing `REDIS_URL` value overrides the test default.

## 26. Test Groups

The current test functions are:

| Test | Purpose |
|---|---|
| `test_health_check` | Healthy Redis response. |
| `test_health_returns_rate_limit_header` | Health rate-limit header. |
| `test_check_returns_rate_limit_headers` | Check rate-limit headers. |
| `test_rate_limit_allowed` | First request allowed. |
| `test_tokens_decrement` | Repeated requests decrement tokens. |
| `test_default_tier` | Default tier selection. |
| `test_invalid_tier` | Invalid tier returns `400`. |
| `test_rate_limit_exceeded` | Exhausted bucket returns `429`. |
| `test_different_identifiers_independent` | Identifier isolation. |
| `test_pro_tier_higher_limit` | Pro-tier configuration. |
| `test_concurrent_requests_are_atomic` | Atomic concurrent enforcement. |
| `test_retry_after_header_matches_body` | Matching retry header and body. |
| `test_refill_over_time` | Refill after elapsed time. |
| `test_tier_buckets_are_isolated` | Tier isolation. |
| `test_health_returns_503_when_redis_is_unreachable` | Health failure status. |
| `test_env_defaults` | Environment defaults. |
| `test_contention_exhausted_returns_503` | Contention failure status. |

The final verification command `pytest -q` reported `17 passed in 3.46s` in the checked environment.

---

## 27. Testing Notes

The concurrency test uses a patched free tier of 20 tokens and sends 100 simultaneous requests for one identifier. The refill test replaces the limiter's clock with a controlled fake clock. The contention test sets `MAX_ATTEMPTS` to zero so the API's `503` path is directly observable.

The separate `scripts/two_instance_check.py` sends 300 alternating requests to two base URLs. In a local run with two uvicorn instances and one Redis, it printed 102 `200` responses, 198 `429` responses, and an elapsed time of 8.340 seconds.

---

## 28. Scope of These Tests

The tests verify the behaviors listed in the test table against the current implementation. They do not verify authentication, configurable CORS, fail-open/fail-closed behavior, clock synchronization between servers, or persistence outside Redis.
