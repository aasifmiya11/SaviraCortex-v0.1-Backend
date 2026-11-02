from redis.asyncio import Redis

from .config import settings


_redis_client: Redis | None = None


async def get_redis() -> Redis:
    """
    Return the shared asynchronous Valkey client.

    The connection is created lazily and reused across requests.
    Actual connectivity is established when a Redis command executes.
    """
    global _redis_client

    if not settings.AIVEN_REDIS_URI:
        raise RuntimeError(
            "AIVEN_REDIS_URI is missing from environment variables."
        )

    if _redis_client is None:
        _redis_client = Redis.from_url(
            settings.AIVEN_REDIS_URI,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30,
        )

    return _redis_client


async def check_redis_connection() -> bool:
    """Check whether the Valkey service is reachable."""
    client = await get_redis()
    return bool(await client.ping())


async def close_redis() -> None:
    """Close the shared Valkey connection pool."""
    global _redis_client

    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None