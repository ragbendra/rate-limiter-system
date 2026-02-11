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

