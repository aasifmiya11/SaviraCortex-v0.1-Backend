from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
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


@router.post(
    "/stream",
    summary="Stream an organization-grounded conversational RAG answer",
)
async def generate_answer_stream(
    organization_id: UUID,
    payload: GenerationRequest,
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
    generation_service: GenerationService = Depends(get_generation_service),
) -> StreamingResponse:
    user = _current_member(db, organization_id, firebase_claims)

    async def event_stream():
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        async def run_generation() -> None:
            try:
                await generation_service.generate_stream(
                    query=payload.query,
                    organization_id=organization_id,
                    user_id=user.id,
                    conversation_history=payload.conversation_history,
                    on_event=queue.put_nowait,
                )
            except InvalidGenerationQueryError as exc:
                await queue.put({"type": "error", "code": "invalid_query", "message": str(exc)})
            except GenerationValidationError:
                await queue.put({"type": "error", "code": "citation_validation_failed", "message": "The answer failed citation validation. Please retry."})
            except Exception:
                logger.exception(
                    "Streaming generation failed (organization_id=%s, user_id=%s).",
                    organization_id, user.id,
                )
                await queue.put({"type": "error", "code": "generation_unavailable", "message": "The generation service is temporarily unavailable. Please try again."})
            finally:
                await queue.put(None)

        task = asyncio.create_task(run_generation())
        yield "event: status\ndata: {\"stage\":\"retrieving\",\"message\":\"Searching authorized documents…\"}\n\n"
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    break
                event_type = item.get("type", "message")
                yield f"event: {event_type}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
