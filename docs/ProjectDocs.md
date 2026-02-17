# Configuration and Redis Setup

This document explains how configuration loading and Redis connection management are implemented in this project. It is written to help anyone reading the code (including my future self) quickly understand **what exists, why it exists, and how the pieces fit together**, without needing to read every line of code first.

The focus is on **clarity and intent**, not just implementation details.

---

## 1. Overall Idea

This project depends on two kinds of external inputs:

1. **Configuration** (environment variables and YAML files)
2. **Redis** (an external service required at runtime)

Both are handled explicitly and early, so that:
- Invalid configuration is caught at startup
- Redis availability is verified before the app does any work
- The rest of the code can assume things are already valid

To achieve this, the project uses:
- `config.py` → for loading and validating configuration
- `redis_client.py` → for managing the Redis connection lifecycle

---

## 2. Configuration (`config.py`)

### Purpose

`config.py` is responsible for:
- Loading environment variables
- Loading `config.yaml`
- Validating all configuration using strict schemas
- Providing a single `settings` object that the rest of the app uses

The goal is to **centralize configuration and validation** instead of spreading it across the codebase.

---

## 3. Environment Configuration

### What it represents

Environment variables are used for values that:
- Change between environments (local, staging, production)
- Contain secrets or connection details

Examples:
- Redis connection URL
- Log level
- Failure mode

### How it is modeled

An `EnvConfig` model is defined using Pydantic. This model:
- Describes what environment variables are expected
- Provides default values where appropriate
- Automatically validates types

Loading is done through a small helper function that reads from `os.getenv()` and constructs an `EnvConfig` object.

If required values are missing or invalid, the application fails immediately.

---

## 4. Rate Limit Configuration (YAML)

### What it represents

`config.yaml` defines rate-limiting tiers, for example:
- free
- pro
- enterprise

Each tier has:
- a request limit
- a time window

There is also a `default_tier` used as a fallback.

---

### How it is modeled

Two Pydantic models are used:

1. `Tier`
   - Represents a single tier
   - Ensures `limit` and `window` are positive integers

2. `RateLimitConfig`
   - Holds all tiers in a dictionary
   - Stores the `default_tier`
   - Validates that `default_tier` actually exists

This ensures the YAML file is both **structurally correct** and **logically consistent**.

---

## 5. Settings Object

A `Settings` class is used to group all configuration together.

When a `Settings` object is created:
- Environment variables are loaded and validated
- YAML configuration is loaded and validated

The rest of the application interacts only with this object, instead of reloading config multiple times.

Example responsibility of `Settings`:
- Provide access to Redis configuration
- Resolve a tier name with a safe fallback to the default tier

This makes configuration usage predictable and centralized.

---

## 6. Redis Client (`redis_client.py`)

### Purpose

`redis_client.py` manages the **entire lifecycle of the Redis connection**. It is responsible for:
- Connecting to Redis at startup
- Verifying Redis availability
- Providing safe access to the Redis client
- Closing the connection at shutdown

It does **not** contain business logic or rate-limiting logic.

---

## 7. RedisClient Class

The Redis connection is wrapped inside a `RedisClient` class. This allows:
- Keeping connection state in one place
- Avoiding global variables scattered across the project
- Enforcing correct usage through explicit methods

The class internally tracks:
- The Redis connection URL
- The Redis client instance
- Whether a successful connection has been established

---

## 8. Connecting to Redis

### Startup behavior

At application startup, the Redis client:
- Creates a Redis connection from the configured URL
- Sends a `PING` command to verify connectivity
- Retries the connection a limited number of times if it fails

If Redis is still unavailable after retries, the application stops.

This ensures the app never runs in a partially broken state.

---

## 9. Accessing the Redis Client

A dedicated method is used to return the Redis client.

Before returning the client, it verifies:
- A connection was established
- The internal state is valid

If Redis is accessed incorrectly (for example, before connecting), an error is raised immediately.

This prevents silent failures and hard-to-debug runtime issues.

---

## 10. Health Checks

The Redis client provides a lightweight health check method that:
- Sends a `PING` command
- Returns a boolean indicating current availability

This method:
- Does not retry
- Does not reconnect
- Does not modify state

It is meant only for observing system health.

---

## 11. Shutdown Handling

When the application shuts down:
- The Redis connection is closed cleanly
- Internal state is reset

This prevents resource leaks and ensures clean termination, especially in async environments.

---

## 12. Application Startup (`main.py`)

`main.py` acts as the orchestrator of the system lifecycle.

Its responsibilities are:
1. Start the application
2. Initialize Redis
3. Execute application logic
4. Shut down Redis cleanly

It does not contain configuration parsing or Redis logic itself. It simply controls **when** things happen.

---

## 13. What Is Intentionally Not Included

The following are deliberately kept out of config and Redis modules:
- Rate limiting logic
- Request handling
- Business rules
- API framework code

This separation keeps the system modular, testable, and easy to extend.

---

## 14. Why This Design Was Chosen

This approach provides:
- Early failure for invalid configuration
- Clear ownership of responsibilities
- Predictable startup and shutdown behavior
- A structure that scales to real production systems

The same pattern can be reused for other external services such as databases, message queues, or third-party APIs.

---

## 15. Summary

In this project:
- Configuration is loaded and validated once, at startup
- Redis is treated as a required external dependency
- Connection lifecycle is explicit and controlled
- The rest of the codebase can assume a valid, ready system

This results in simpler application logic and fewer runtime surprises.

---
---

# FastAPI Application Layer

This section explains how the rate limiter is exposed as an HTTP service. The API acts as a thin execution layer: it validates requests, delegates logic to the rate limiter core, and formats responses.

The API does **not** implement rate limiting logic itself. All business rules exist in `rate_limiter.py`.

---

## 16. Application Lifecycle

The application uses FastAPI **lifespan events** to manage Redis connections.

**Startup:**
- Establish connection to Redis
- Service becomes ready only after Redis is reachable

**Shutdown:**
- Gracefully close Redis connection
- Prevents hanging sockets and resource leaks

This guarantees:
- Every request runs with a valid Redis client
- No lazy connection creation during traffic

---

## 17. Data Contracts

### Request Model

The client sends:

```json
{
  "identifier": "user:123",
  "tier": "free"
}
```

Rules:
- `identifier` uniquely identifies the caller
- `tier` is optional — missing tier defaults to `"free"`

### Response Model

**Successful request:**

```json
{
  "allowed": true,
  "tokens_remaining": 99,
  "reset_at": 1700000000.0,
  "limit": 100
}
```

**Rate limited:**

```json
{
  "allowed": false,
  "tokens_remaining": 0,
  "reset_at": 1700000000.0,
  "limit": 100,
  "retry_after": 60
}
```

---

## 18. Endpoints

### GET /health

**Purpose:** Operational readiness check.

Behavior:
- Pings Redis
- Confirms dependency availability

Response:

```json
{
  "status": "ok",
  "redis": "connected"
}
```

If Redis is unavailable: **HTTP 503** is returned.

This endpoint is designed for load balancers and container orchestration systems.

### POST /check

**Purpose:** Evaluate whether a request should be allowed.

Flow:
1. Validate that the tier exists in configuration
2. Call rate limiter core
3. Convert result into API response

| Scenario         | HTTP Status |
|------------------|-------------|
| Invalid tier     | 400         |
| Internal failure | 500         |

---

## 19. Error Handling Strategy

| Code | Meaning                                |
|------|----------------------------------------|
| 400  | Client error (bad tier)                |
| 429  | Rate limit exceeded (from limiter)     |
| 503  | Dependency failure (Redis down)        |
| 500  | Unexpected internal error              |

The API layer never hides system state.

---

## 20. Architectural Responsibility

**API Layer:**
- Input validation
- Output formatting
- Dependency lifecycle
- HTTP semantics

**Rate Limiter Core:**
- Token calculations
- Redis state management
- Algorithm correctness

This separation allows:
- Algorithm testing without HTTP
- API changes without touching logic
- Independent scalability

---

## 21. API Guarantees

The API guarantees:

- Deterministic validation
- No business logic duplication
- Stateless request handling
- Externalized state in Redis

---
---

# API Testing Documentation

This section explains how the rate limiter service is tested from a client's perspective. The goal is not verifying Python functions, but verifying **service guarantees** through observable behavior.

The tests simulate how a real consumer interacts with the system:
- Sends HTTP requests
- Receives responses
- Relies on response semantics

This represents **behavioral contract testing**.

---

## 22. Testing Strategy

The system depends on:
- FastAPI application
- Redis state storage
- Token bucket algorithm

Because of this, unit testing individual functions is insufficient. We instead test **observable behavior** using an async HTTP client.

We validate:

| Category      | Meaning                              |
|---------------|--------------------------------------|
| Availability  | Service is reachable                 |
| Correctness   | Tokens decrement properly            |
| Persistence   | Redis state survives across requests |
| Safety        | Invalid input handled safely         |
| Protection    | Limit enforced                       |
| Isolation     | Users do not affect each other       |
| Configuration | Tier limits applied correctly        |

---

## 23. Shared Test Setup (`conftest.py`)

### Why this file exists

Tests require:
1. Redis connected
2. Redis clean before each test
3. Async HTTP client

Instead of repeating this setup in every test, fixtures provide a reusable environment.

### Client Fixture

Creates an `AsyncClient` connected to the FastAPI app.

Steps:
1. Connect Redis
2. Create in‑memory HTTP client
3. Run test
4. Close Redis

This ensures each test interacts with a real running application instance.

### flush_redis Fixture

Automatically clears the database before every test.

Why required: Rate limiting depends on stored state. If state persists between tests, results become non‑deterministic.

Therefore every test starts from identical conditions.

---

## 24. Test Groups

### 1. Health Check

**Purpose:** Verify service readiness for traffic.

Guarantees:
- API reachable
- Redis reachable
- System safe to send requests

This protects load balancers from routing traffic to broken instances.

### 2. Valid Request Behavior

Ensures normal users are not incorrectly blocked.

Verified:
- First request allowed
- Token count decreases
- Default tier works

This confirms basic service functionality.

### 3. Invalid Input Handling

Ensures bad client input does not crash the server.

- Invalid tier → **400** response

This distinguishes client error from server failure — important for monitoring systems.

### 4. Rate Limit Enforcement

Core guarantee of the project.

Behavior:
- N requests → allowed
- N+1 request → rejected

Also provides retry information.

**If this test fails, the system is not a rate limiter.**

### 5. Identifier Isolation

Ensures independent quotas per user.

Without this: one abusive user would block all others.

This validates key‑based state separation.

### 6. Tier Differences

Ensures configuration correctness.

Paid tiers must have higher limits. This prevents billing inconsistencies.

---

## 25. Why Async HTTP Testing

The system is:
- Asynchronous
- Network‑facing
- Stateful (external storage)

Therefore the correct testing method is **integration testing via HTTP**, not direct function calls.

---

## 26. What These Tests Prove

Together the suite guarantees:

> The service enforces rate limits correctly, consistently, safely, and independently for all clients.

This verifies **production‑level behavior** rather than implementation details.
