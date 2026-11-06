from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_verified_firebase_claims
from app.models import OrganizationMembership, User
from app.schemas.v1.generation import GenerationRequest, GenerationResponse
from app.services.generation.generation_service import (
    GenerationExecutionError,
    GenerationRuntimeUnavailableError,
    GenerationService,
    GenerationValidationError,
    InvalidGenerationQueryError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/organizations/{organization_id}/generation",
    tags=["Generation"],
)


def get_generation_service(
    db: Session = Depends(get_db),
) -> GenerationService:
    return GenerationService(db)


def _current_member(
    db: Session,
    organization_id: UUID,
    firebase_claims: dict,
) -> User:
    firebase_uid = firebase_claims.get("uid")
    if not isinstance(firebase_uid, str) or not firebase_uid.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Verified Firebase identity is missing a UID.",
        )

    user = db.scalar(select(User).where(User.firebase_uid == firebase_uid))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This Firebase account is not registered in SaviraCortex.",
        )

    membership = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user.id,
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found or you are not a member of it.",
        )

    return user


@router.post(
    "",
    response_model=GenerationResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate an organization-grounded answer with validated citations",
)
async def generate_answer(
    organization_id: UUID,
    payload: GenerationRequest,
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
    generation_service: GenerationService = Depends(get_generation_service),
) -> GenerationResponse:
    user = _current_member(db, organization_id, firebase_claims)

    try:
        return await generation_service.generate(
            query=payload.query,
            organization_id=organization_id,
            user_id=user.id,
            conversation_history=payload.conversation_history,
        )
    except InvalidGenerationQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except GenerationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The generated answer failed citation validation. Please retry.",
        ) from exc
    except (GenerationRuntimeUnavailableError, GenerationExecutionError) as exc:
        logger.exception(
            "Generation request unavailable (organization_id=%s, user_id=%s).",
            organization_id,
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The generation service is temporarily unavailable. Please try again.",
        ) from exc
