from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    conversations,
    department_memberships,
    departments,
    document_ingestion,
    documents,
    generation,
    health,
    home,
    invitations,
    memberships,
    organization_roles,
    organizations,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(home.router)
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(departments.router)
api_router.include_router(organizations.router)
api_router.include_router(organization_roles.router)
api_router.include_router(memberships.router)
api_router.include_router(department_memberships.router)
api_router.include_router(invitations.router)
api_router.include_router(document_ingestion.router)
api_router.include_router(documents.router)
api_router.include_router(conversations.router)
api_router.include_router(generation.router)
