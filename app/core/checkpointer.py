from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from app.core.config import settings

logger = logging.getLogger(__name__)

# psycopg's async protocol does not support the Windows Proactor event loop.
# Set the selector policy before Uvicorn/asyncio creates the application loop.
if sys.platform == "win32" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

_pool: Any | None = None
_checkpointer: Any | None = None
_store: Any | None = None


def _psycopg_conninfo(sqlalchemy_url: str) -> str:
    """Convert the backend SQLAlchemy URL to a psycopg-compatible URL."""
    value = sqlalchemy_url.strip()
    for prefix in (
        "postgresql+psycopg2://",
        "postgresql+psycopg://",
        "postgres+psycopg2://",
        "postgres+psycopg://",
    ):
        if value.startswith(prefix):
            return "postgresql://" + value[len(prefix):]
    if value.startswith("postgres://"):
        return "postgresql://" + value[len("postgres://"):]
    if re.match(r"^postgresql://", value):
        return value
    raise ValueError(
        "AIVEN_POSTGRES_URI must use a PostgreSQL URL supported by psycopg."
    )


async def initialize_checkpointer() -> Any:
    """Initialize LangGraph checkpoints and the cross-thread Store on one pool."""
    global _pool, _checkpointer, _store

    if _checkpointer is not None and _store is not None:
        return _checkpointer
    if not settings.AIVEN_POSTGRES_URI:
        raise RuntimeError("AIVEN_POSTGRES_URI is required for conversation persistence.")

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.store.postgres.aio import AsyncPostgresStore
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(
        conninfo=_psycopg_conninfo(settings.AIVEN_POSTGRES_URI),
        min_size=1,
        max_size=10,
        kwargs={"autocommit": True, "prepare_threshold": 0},
        open=False,
    )
    try:
        await pool.open(wait=True)
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()

        # Use the same embedding provider configured for the RAG pipeline so
        # Store vector dimensions always match the active provider.
        from app.rag.embeddings.provider import embedding_model

        store = AsyncPostgresStore(
            pool,
            index={
                "embed": embedding_model,
                "dims": int(embedding_model.dimensions),
                "fields": ["text"],
            },
        )
        await store.setup()
    except Exception:
        await pool.close()
        logger.exception(
            "Unable to initialize LangGraph PostgreSQL checkpoint and Store schemas."
        )
        raise

    _pool = pool
    _checkpointer = checkpointer
    _store = store
    logger.info("LangGraph PostgreSQL checkpointer and cross-thread Store initialized.")
    return checkpointer


def get_checkpointer() -> Any | None:
    return _checkpointer


def get_store() -> Any | None:
    """Return the lifecycle-managed cross-thread LangGraph Store."""
    return _store


@asynccontextmanager
async def conversation_thread_lock(conversation_id: UUID) -> AsyncIterator[None]:
    """Serialize graph turns for one conversation across API worker processes."""
    pool = _pool
    if pool is None:
        yield
        return

    async with pool.connection() as connection:
        key = int.from_bytes(
            hashlib.blake2b(str(conversation_id).encode("utf-8"), digest_size=8).digest(),
            byteorder="big",
            signed=True,
        )
        await connection.execute("SELECT pg_advisory_lock(%s)", (key,))
        try:
            yield
        finally:
            await connection.execute("SELECT pg_advisory_unlock(%s)", (key,))


async def close_checkpointer() -> None:
    """Close the shared async psycopg pool after Store/checkpointer use ends."""
    global _pool, _checkpointer, _store
    pool = _pool
    _pool = None
    _checkpointer = None
    _store = None
    if pool is not None:
        await pool.close()
        logger.info("LangGraph PostgreSQL checkpoint and Store pool closed.")
