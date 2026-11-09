import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.checkpointer import close_checkpointer, get_store, initialize_checkpointer
from app.core.database import close_database, create_conversation_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize conversation checkpoints and cross-thread memory storage."""
    try:
        await asyncio.to_thread(create_conversation_tables)
        app.state.checkpointer = await initialize_checkpointer()
        app.state.store = get_store()
        yield
    finally:
        await close_checkpointer()
        await asyncio.to_thread(close_database)


app = FastAPI(
    title="SaviraCortex API",
    description="Organization-centric AI platform API.",
    version="1.0.0",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    openapi_url="/api/v1/openapi.json",
    lifespan=lifespan,
)

# Allow the local Next.js development server to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(api_router)
