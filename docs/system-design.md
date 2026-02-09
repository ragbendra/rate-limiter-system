# Distributed Rate Limiter System

## 1. SYSTEM OVERVIEW
A standalone HTTP microservice that enforces rate limits using the token bucket algorithm with Redis as the distributed state store. The service accepts HTTP requests from any application (Java, Python, Node.js, etc.) and returns immediate allow/deny decisions with detailed rate limit metadata. Built on FastAPI for high-performance async handling, Redis for distributed state management, and configured via YAML for deployment-time tier definitions.

## 2. CONFIGURATION DESIGN
Tier-Based Configuration Approach
I'm implementing a three-tier configuration system (free, pro, enterprise) defined in a YAML configuration file. This approach provides clear, predictable rate limits that align with typical SaaS pricing models while maintaining simplicity for initial implementation.

### Configuration Structure
tiers:
  free:
    limit: 100      # requests
    window: 60      # seconds (100 req/min)
    
  pro:
    limit: 1000     # requests (1000 req/min)
    window: 60      # seconds
    
  enterprise:
    limit: 10000    # requests (10000 req/min)
    window: 60      # seconds

default_tier: free  # Fallback when tier not specified


### Configuration Resolution
When a client application calls the service:

If tier is specified in the request → Use that tier's limits

If tier is omitted → Use the default_tier (free)

All limits are loaded at service startup from the YAML file

### Tradeoff Analysis
Advantage: Simple, predictable, no database required. Configuration is version-controlled and deployment is atomic.
Disadvantage: Cannot add new tiers or modify limits without redeploying the service. Cannot provide custom limits per identifier without code changes.

