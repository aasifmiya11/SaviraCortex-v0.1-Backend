
import json
from json import JSONDecodeError
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.redis import get_redis
from .authorization_service import AuthorizationService


class AuthorizationCacheService:
    def __init__(
        self,
        authorization_service: AuthorizationService,
        ttl_seconds: int = 300,
    ):
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be greater than zero.")

        self.authorization_service = authorization_service
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _build_cache_key(
        organization_id: UUID,
        user_id: UUID,
    ) -> str:
        return f"auth_scope:{organization_id}:{user_id}"

    async def get_authorized_document_ids(
        self,
        organization_id: UUID,
        user_id: UUID,
    ) -> list[UUID]:
        cache_key = self._build_cache_key(
            organization_id=organization_id,
            user_id=user_id,
        )

        redis_client: Redis | None = None
        cached_value: str | None = None

        # 1. Try retrieving the authorization scope from Valkey.
        try:
            redis_client = await get_redis()
            cached_value = await redis_client.get(cache_key)

        except RedisError:
            # Cache failure should not prevent authorization.
            redis_client = None

        # 2. Return cached document IDs when the cache is valid.
        if cached_value is not None:
            try:
                cached_ids = json.loads(cached_value)

                if not isinstance(cached_ids, list):
                    raise ValueError("Invalid authorization cache format.")

                if not all(isinstance(item, str) for item in cached_ids):
                    raise ValueError("Invalid document ID in authorization cache.")

                return [UUID(item) for item in cached_ids]

            except (JSONDecodeError, ValueError, TypeError):
                # Invalid cache entry: remove it and recalculate.
                if redis_client is not None:
                    try:
                        await redis_client.delete(cache_key)
                    except RedisError:
                        pass

        # 3. Cache miss: calculate authorization using PostgreSQL.
        authorized_ids = (
            self.authorization_service.get_authorized_document_ids(
                organization_id=organization_id,
                user_id=user_id,
            )
        )

        # 4. Store the resulting logical document IDs in Valkey.
        if redis_client is not None:
            try:
                serialized_ids = json.dumps(
                    [str(document_id) for document_id in authorized_ids]
                )

                await redis_client.set(
                    cache_key,
                    serialized_ids,
                    ex=self.ttl_seconds,
                )

            except RedisError:
                # Return the database result even if caching fails.
                pass

        return authorized_ids
