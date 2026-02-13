# Rate Limiter System

A flexible, Redis-backed rate limiting system with configurable tiers and fail-safe behavior.

## Features

- **Multi-tier rate limiting** (free, pro, enterprise, etc.)
- **Redis-backed** for distributed rate limiting
- **Configurable** via YAML and environment variables
- **Fail-safe modes** (fail-open or fail-closed on Redis unavailability)
- **Health checks** for monitoring

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
python main.py
```

## Configuration

### Rate Limit Tiers (`config.yaml`)

```yaml
tiers:
  free:
    limit: 100
    window: 60  # seconds
  pro:
    limit: 1000
    window: 60
  enterprise:
    limit: 10000
    window: 60

default_tier: free
```

### Environment Variables (`.env`)

| Variable | Description | Default |
|----------|-------------|---------|
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379/0` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `FAILURE_MODE` | Behavior on Redis failure (`open` or `closed`) | `open` |

## Usage Example

```python
from app.config import Settings
from app.redis_client import RedisClient

# Load configuration
settings = Settings()

# Initialize Redis
redis_client = RedisClient(settings.redis_url)
await redis_client.connect()

# Get tier configuration
tier = settings.get_tier("pro")
print(f"Limit: {tier.limit}, Window: {tier.window}s")
```

## Project Structure

```
rate-limiter-system/
├── app/
│   ├── config.py          # Configuration loading and validation
│   └── redis_client.py    # Redis connection management
├── docs/
│   └── ProjectDocs.md     # Detailed documentation
├── tests/                 # Unit and integration tests
├── config.yaml            # Rate limit tier definitions
├── docker-compose.yml     # Redis container setup
├── main.py                # Application entry point
└── requirements.txt       # Python dependencies
```

## Development

### Install Dev Dependencies

```bash
pip install -r requirements-dev.txt
```

### Run Tests

```bash
pytest
```

## Health Check

Check if Redis is available:

```python
is_healthy = await redis_client.health_check()
```

## Shutdown

```bash
# Stop Redis container
docker-compose down
```

## License

See [LICENSE](LICENSE) for details.

## Documentation

For detailed design decisions and implementation details, see [docs/ProjectDocs.md](docs/ProjectDocs.md).
