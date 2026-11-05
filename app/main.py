from fastapi import FastAPI

from app.api.v1.router import api_router

app = FastAPI(
    title="SaviraCortex API",
    description="Organization-centric AI platform API.",
    version="1.0.0",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    openapi_url="/api/v1/openapi.json",
)

app.include_router(api_router)
