# 19. Caching

## Redis client lifecycle

`app/core/redis.py` exposes async `get_redis()`, `check_redis_connection()` and `close_redis()`. The client is created lazily and associated with the event loop that created it; if called from another loop, the previous client is closed and a new one is created. Connectivity is established when a Redis command executes, not necessarily when the client object is constructed.

## AuthorizationCacheService

`app/services/authorization/authorization_cache_service.py` is a separate cache wrapper around `AuthorizationService`. It implements two cache families:

| Cached value | Key format | Default TTL |
|---|---|---:|
| User's authorized logical document IDs | `auth_scope:<organization_id>:<user_id>` | 300 seconds |
| Organization-wide active/superseded version catalogue | `org_catalog:<organization_id>` | 3,600 seconds |

Valid cache hits use a sliding TTL. Invalid JSON/schema values are deleted and recalculated from PostgreSQL. Redis command errors are treated as cache failures: the service falls back to PostgreSQL and returns the database result. A missing `AIVEN_REDIS_URI` raises `RuntimeError` from `get_redis()` and is not covered by the service's `RedisError` fallback.

The cache service exposes separate invalidation methods for one user's authorization scope and an organization's shared catalogue. Call them after the corresponding database transaction commits.

## Current retrieval integration boundary

The current `RetrievalOrchestrator` is constructed with `AuthorizationService` and calls `get_authorized_document_catalog()` directly. It does not currently use `AuthorizationCacheService`. The cache wrapper exists as a callable service, but its presence should not be interpreted as proof that retrieval requests are cached.

## Invalidation events

When the cache wrapper is used, invalidate relevant entries after:
- Organization membership changes.
- Role assignment changes.
- Department membership changes.
- Document ACL changes.
- Document archive or lifecycle changes that affect catalogue eligibility.

## Failure behavior

Missing `AIVEN_REDIS_URI` causes `get_redis()` to raise a runtime error. Connectivity/command errors represented by `RedisError` are handled as cache misses/fallbacks in the cache service. Do not silently interpret authorization database failures as an empty access scope.
