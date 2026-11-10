from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_verified_firebase_claims
from app.models import Document, DocumentVersion, GenerationFeedback, OrganizationMembership, User
from app.schemas.v1.generation import (
    GenerationFeedbackRequest,
    GenerationRequest,
    GenerationResponse,
)
from app.services.generation.generation_service import (
    GenerationExecutionError,
    GenerationRuntimeUnavailableError,
    GenerationValidationError,
    InvalidGenerationQueryError,
)
from app.services.generation.persistent_generation_service import (
    PersistentGenerationService,
    generate_conversation_title,
)
from app.repositories.conversation_repository import ConversationNotFoundError
from app.guardrails.runtime_service import GuardrailBlockedError, GuardrailConsentRequiredError

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/organizations/{organization_id}/generation",
    tags=["Generation"],
)


def get_generation_service(
    db: Session = Depends(get_db),
) -> PersistentGenerationService:
    return PersistentGenerationService(db)


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


def _membership_role(db: Session, organization_id: UUID, user_id: UUID) -> str:
    return db.scalar(
        select(OrganizationMembership.role).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
        )
    ) or "member"


@router.post(
    "",
    response_model=GenerationResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate an organization-grounded answer with validated citations",
)
async def generate_answer(
    organization_id: UUID,
    payload: GenerationRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
    generation_service: PersistentGenerationService = Depends(get_generation_service),
) -> GenerationResponse:
    user = _current_member(db, organization_id, firebase_claims)

    try:
        response = await generation_service.generate(
            query=payload.query,
            organization_id=organization_id,
            user_id=user.id,
            conversation_id=payload.conversation_id,
            request_id=payload.request_id,
            pii_action=payload.pii_action,
        )
        if payload.conversation_id is None and response.conversation_id is not None:
            background_tasks.add_task(
                generate_conversation_title,
                conversation_id=response.conversation_id,
                organization_id=organization_id,
                user_id=user.id,
                first_message=payload.query,
            )
        return response
    except GuardrailConsentRequiredError as exc:
        raise HTTPException(
            status_code=428,
            detail={
                "code": "pii_consent_required",
                "message": str(exc),
                "redacted_preview": exc.redacted_preview,
                "entities": exc.entities,
                "allowed_actions": exc.allowed_actions,
            },
        ) from exc
    except GuardrailBlockedError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "guardrail_blocked", "message": exc.message},
        ) from exc
    except ConversationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
    generation_service: PersistentGenerationService = Depends(get_generation_service),
) -> StreamingResponse:
    user = _current_member(db, organization_id, firebase_claims)

    async def event_stream():
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        async def run_generation() -> None:
            def error_event(code: str, message: str) -> dict:
                event = {"type": "error", "code": code, "message": message}
                conversation_id = getattr(generation_service, "last_conversation_id", None)
                if conversation_id is not None:
                    event["conversation_id"] = str(conversation_id)
                    if payload.conversation_id is None:
                        background_tasks.add_task(
                            generate_conversation_title,
                            conversation_id=conversation_id,
                            organization_id=organization_id,
                            user_id=user.id,
                            first_message=payload.query,
                        )
                return event

            try:
                response = await generation_service.generate_stream(
                    query=payload.query,
                    organization_id=organization_id,
                    user_id=user.id,
                    conversation_id=payload.conversation_id,
                    request_id=payload.request_id,
                    pii_action=payload.pii_action,
                    on_event=queue.put_nowait,
                )
                if payload.conversation_id is None and response.conversation_id is not None:
                    background_tasks.add_task(
                        generate_conversation_title,
                        conversation_id=response.conversation_id,
                        organization_id=organization_id,
                        user_id=user.id,
                        first_message=payload.query,
                    )
            except GuardrailConsentRequiredError as exc:
                await queue.put({
                    "type": "error",
                    "code": "pii_consent_required",
                    "message": str(exc),
                    "redacted_preview": exc.redacted_preview,
                    "entities": exc.entities,
                    "allowed_actions": exc.allowed_actions,
                })
            except GuardrailBlockedError as exc:
                await queue.put({
                    "type": "error",
                    "code": "guardrail_blocked",
                    "message": exc.message,
                })
            except ConversationNotFoundError:
                await queue.put(error_event("conversation_not_found", "Conversation not found."))
            except InvalidGenerationQueryError as exc:
                await queue.put(error_event("invalid_query", str(exc)))
            except ValueError as exc:
                await queue.put(error_event("invalid_request", str(exc)))
            except GenerationValidationError:
                await queue.put(error_event("citation_validation_failed", "The answer failed citation validation. Please retry."))
            except Exception:
                logger.exception(
                    "Streaming generation failed (organization_id=%s, user_id=%s).",
                    organization_id, user.id,
                )
                await queue.put(error_event("generation_unavailable", "The generation service is temporarily unavailable. Please try again."))
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
        background=background_tasks,
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )



@router.get(
    "/citations/{document_version_id}/content",
    summary="Stream an authorized citation PDF without exposing its B2 URL",
)
def stream_citation_document(
    organization_id: UUID,
    document_version_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    """Stream a citation PDF after rechecking the user's document ACL."""
    user = _current_member(db, organization_id, firebase_claims)

    from app.repositories.authorization_repository import AuthorizationRepository
    authorized_versions = AuthorizationRepository(db).get_authorized_document_catalog(
        organization_id=organization_id,
        user_id=user.id,
    )
    authorized_version_ids = {
        item["document_version_id"] for item in authorized_versions
    }
    if str(document_version_id) not in authorized_version_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The cited document is unavailable or you are not authorized to access it.",
        )

    version = db.scalar(
        select(DocumentVersion)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            DocumentVersion.id == document_version_id,
            Document.organization_id == organization_id,
            Document.archived.is_(False),
            DocumentVersion.status.in_(("active", "superseded")),
        )
    )
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The cited document version no longer exists.",
        )

    range_header = request.headers.get("range")
    if range_header and (
        not range_header.startswith("bytes=") or "," in range_header
    ):
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail="Only a single byte range is supported.",
        )

    try:
        from app.storage.file_storage import FileStorage
        object_response = FileStorage().get_file_response(
            version.storage_key,
            range_header=range_header,
        )
        body = object_response["Body"]
        headers = {
            "Content-Type": "application/pdf",
            "Content-Disposition": "inline",
            "Accept-Ranges": object_response.get("AcceptRanges", "bytes"),
            "Cache-Control": "private, no-store, no-cache, must-revalidate",
            "X-Content-Type-Options": "nosniff",
        }
        if object_response.get("ContentLength") is not None:
            headers["Content-Length"] = str(object_response["ContentLength"])
        if object_response.get("ContentRange"):
            headers["Content-Range"] = object_response["ContentRange"]

        return StreamingResponse(
            body.iter_chunks(chunk_size=1024 * 1024),
            status_code=206 if object_response.get("ContentRange") else 200,
            media_type="application/pdf",
            headers=headers,
            background=BackgroundTask(body.close),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "Could not stream citation PDF for version %s.",
            document_version_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The source document is temporarily unavailable.",
        ) from exc


@router.patch(
    "/{generation_id}/feedback",
    summary="Label a generated answer as relevant or not relevant",
)
def update_generation_feedback(
    organization_id: UUID,
    generation_id: UUID,
    payload: GenerationFeedbackRequest,
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    user = _current_member(db, organization_id, firebase_claims)
    role = _membership_role(db, organization_id, user.id)
    filters = [
        GenerationFeedback.id == generation_id,
        GenerationFeedback.organization_id == organization_id,
    ]
    if role not in {"owner", "admin"}:
        filters.append(GenerationFeedback.user_id == user.id)
    record = db.scalar(select(GenerationFeedback).where(*filters))
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generation record not found in this organization.",
        )

    record.feedback_status = payload.feedback_status
    record.feedback_updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(record)
    return {
        "generation_id": str(record.id),
        "feedback_status": record.feedback_status,
        "feedback_updated_at": record.feedback_updated_at,
    }


@router.get(
    "/feedback-dataset",
    summary="Export stored RAG examples for evaluation",
)
def get_feedback_dataset(
    organization_id: UUID,
    feedback_status: str | None = Query(
        default=None,
        pattern="^(relevant|not_relevant)$",
    ),
    labeled_only: bool = True,
    limit: int = Query(default=1000, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    user = _current_member(db, organization_id, firebase_claims)
    role = _membership_role(db, organization_id, user.id)
    statement = select(GenerationFeedback).where(
        GenerationFeedback.organization_id == organization_id
    )
    if role not in {"owner", "admin"}:
        statement = statement.where(GenerationFeedback.user_id == user.id)
    if feedback_status is not None:
        statement = statement.where(
            GenerationFeedback.feedback_status == feedback_status
        )
    elif labeled_only:
        statement = statement.where(
            GenerationFeedback.feedback_status.is_not(None)
        )

    records = db.scalars(
        statement.order_by(
            GenerationFeedback.created_at.desc()
        ).limit(limit).offset(offset)
    ).all()
    return {
        "items": [
            {
                "generation_id": str(record.id),
                "query": record.query,
                "generated_queries": record.generated_queries,
                "generated_query_count": record.generated_query_count,
                "retrieval_trace": record.retrieval_trace,
                "retrieved_documents": record.retrieved_documents,
                "answer_markdown": record.answer_markdown,
                "answer_status": record.answer_status,
                "feedback_status": record.feedback_status,
                "created_at": record.created_at,
                "feedback_updated_at": record.feedback_updated_at,
            }
            for record in records
        ],
        "count": len(records),
        "limit": limit,
        "offset": offset,
        "labeled_only": labeled_only and feedback_status is None,
    }
