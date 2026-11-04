# 19. Caching

## Redis client lifecycle

`app/core/redis.py` exposes `get_redis()`, `check_redis_connection()` and `close_redis()`. The client is asynchronous and created lazily. It is associated with the event loop that created it; if called from a different loop, the old client is closed and a new one is created. The connection is established when a Redis command executes, not necessarily when the client object is constructed.

## Authorization cache

Authorization services use the Redis-compatible cache to avoid repeating expensive organization/role/department/ACL resolution and to cache organization document catalogues. Exact key names, TTLs and invalidation rules should be taken from `authorization_cache_service.py`.

## Cache invalidation

Invalidate relevant entries after:
- Membership changes.
- Role assignment or role definition changes.
- Department membership changes.
- Document ACL changes.
- Document archive or lifecycle changes that affect catalogue eligibility.

## Failure behavior

Missing `AIVEN_REDIS_URI` causes `get_redis()` to raise a runtime error. Connectivity errors occur when commands are issued. Do not silently interpret cache failure as an empty authorization scope unless the calling service explicitly implements a safe fallback.
