
from uuid import UUID

import pytest

from app.core.database import get_db_session
from app.core.redis import get_redis
from app.repositories.authorization_repository import AuthorizationRepository
from app.services.authorization import (
    AuthorizationCacheService,
    AuthorizationService,
)


ORGANIZATION_ID = UUID("3c0428f9-c49a-4afc-a1d9-4c3e266e47a1")
USER_ID = UUID("8ea71a7e-f963-4e76-968e-c2718106978e")


@pytest.mark.asyncio
async def test_authorization_cache_miss_and_hit():
    redis = await get_redis()

    cache_key = f"auth_scope:{ORGANIZATION_ID}:{USER_ID}"

    # Ensure the test starts with an empty cache.
    await redis.delete(cache_key)

    try:
        with get_db_session() as db:
            repository = AuthorizationRepository(db)
            authorization_service = AuthorizationService(repository)

            cache_service = AuthorizationCacheService(
                authorization_service=authorization_service,
                ttl_seconds=60,
            )

            # First call: cache miss, PostgreSQL lookup and cache population.
            first_result = await cache_service.get_authorized_document_ids(
                organization_id=ORGANIZATION_ID,
                user_id=USER_ID,
            )

            cached_value = await redis.get(cache_key)
            ttl = await redis.ttl(cache_key)

            assert cached_value is not None
            assert ttl > 0

            # Verify cached JSON contains the expected document IDs.
            import json

            cached_ids = [UUID(item) for item in json.loads(cached_value)]
            assert cached_ids == first_result

            # Second call: cache hit.
            second_result = await cache_service.get_authorized_document_ids(
                organization_id=ORGANIZATION_ID,
                user_id=USER_ID,
            )

            assert second_result == first_result

            # Verify sliding TTL.
            await redis.expire(cache_key, 1)
            third_result = await cache_service.get_authorized_document_ids(
                organization_id=ORGANIZATION_ID,
                user_id=USER_ID,
            )
            refreshed_ttl = await redis.ttl(cache_key)

            assert third_result == first_result
            assert refreshed_ttl > 1

            # Verify explicit invalidation.
            await cache_service.invalidate_authorized_document_ids(
                organization_id=ORGANIZATION_ID,
                user_id=USER_ID,
            )
            assert await redis.exists(cache_key) == 0

    finally:
        await redis.delete(cache_key)


@pytest.mark.asyncio
async def test_authorization_cache_stores_empty_result():
    redis = await get_redis()

    cache_key = f"auth_scope:{ORGANIZATION_ID}:{USER_ID}"

    await redis.delete(cache_key)

    try:
        with get_db_session() as db:
            repository = AuthorizationRepository(db)
            authorization_service = AuthorizationService(repository)

            cache_service = AuthorizationCacheService(
                authorization_service=authorization_service,
                ttl_seconds=60,
            )

            result = await cache_service.get_authorized_document_ids(
                organization_id=ORGANIZATION_ID,
                user_id=USER_ID,
            )

            # The cache must exist even when the result is empty.
            cached_value = await redis.get(cache_key)

            assert cached_value is not None
            assert cached_value == "[]" if result == [] else True

    finally:
        await redis.delete(cache_key)
