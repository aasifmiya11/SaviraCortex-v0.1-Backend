from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import tempfile
import threading
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from app.core.database import SessionLocal
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_verified_firebase_claims
from app.models import OrganizationDepartmentMembership, OrganizationMembership, User
from app.schemas.v1.document_ingestion import (
    DocumentIngestionAnalysisResponse,
    DocumentIngestionFinalizeRequest,
    DocumentIngestionFinalizeResponse,
)
from app.services.document_ingestion.workflow_service import (
    DocumentIngestionWorkflowError,
    DocumentIngestionWorkflowService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/organizations/{organization_id}/documents", tags=["Document ingestion"])
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024


def get_ingestion_workflow() -> DocumentIngestionWorkflowService | None:
    # Construct external-service clients only after organization authorization succeeds.
    return None


def _current_member(
    db: Session, organization_id: UUID, firebase_claims: dict
) -> tuple[User, OrganizationMembership]:
    firebase_uid = firebase_claims.get("uid")
    if not isinstance(firebase_uid, str) or not firebase_uid.strip():
        raise HTTPException(status_code=401, detail="Verified Firebase identity is missing a UID.")
    user = db.scalar(select(User).where(User.firebase_uid == firebase_uid))
    if user is None:
        raise HTTPException(status_code=404, detail="This Firebase account is not registered in SaviraCortex.")
    membership = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization not found or you are not a member of it.")
    return user, membership


@router.post(
    "/ingestion-sessions",
    response_model=DocumentIngestionAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze and stage a PDF for document ingestion",
)
def analyze_document_upload(
    organization_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
    workflow: DocumentIngestionWorkflowService = Depends(get_ingestion_workflow),
):
    user, _membership = _current_member(db, organization_id, firebase_claims)
    workflow = workflow or DocumentIngestionWorkflowService()
    filename = (file.filename or "").replace("\\", "/").split("/")[-1].strip()
    if not filename or not filename.lower().endswith(".pdf"):
        file.file.close()
        raise HTTPException(status_code=422, detail="Only PDF files are accepted.")

    temp_path: str | None = None
    total_bytes = 0
    try:
        with tempfile.NamedTemporaryFile(prefix="savira-ingest-", suffix=".pdf", delete=False) as temporary:
            temp_path = temporary.name
            while True:
                chunk = file.file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="PDF exceeds the 25 MB upload limit.")
                temporary.write(chunk)

        if total_bytes == 0:
            raise HTTPException(status_code=422, detail="The uploaded PDF is empty.")

        result = workflow.analyze_and_stage(
            db,
            temp_path,
            organization_id=organization_id,
            uploaded_by_user_id=user.id,
            original_filename=filename[:500],
            file_size=total_bytes,
        )
        return result
    except HTTPException:
        raise
    except DocumentIngestionWorkflowError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "Document ingestion analysis failed (organization_id=%s, filename=%s)",
            organization_id,
            filename,
        )
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Document analysis or temporary storage failed. Please retry the upload.",
        ) from exc
    finally:
        file.file.close()
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


@router.post(
    "/ingestion-sessions/{ingestion_session_id}/complete",
    response_model=DocumentIngestionFinalizeResponse,
    summary="Confirm the metadata and persist an analyzed PDF",
)
def finalize_document_ingestion(
    organization_id: UUID,
    ingestion_session_id: UUID,
    payload: DocumentIngestionFinalizeRequest,
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
    workflow: DocumentIngestionWorkflowService = Depends(get_ingestion_workflow),
):
    user, membership = _current_member(db, organization_id, firebase_claims)
    workflow = workflow or DocumentIngestionWorkflowService()
    if payload.department_id is not None and membership.role == "member":
        department_assignment = db.get(
            OrganizationDepartmentMembership,
            (organization_id, user.id, payload.department_id),
        )
        if department_assignment is None:
            raise HTTPException(
                status_code=403,
                detail="You can only assign documents to departments you belong to.",
            )
    try:
        return workflow.finalize(
            db,
            organization_id=organization_id,
            ingestion_session_id=ingestion_session_id,
            uploaded_by_user_id=user.id,
            action=payload.action,
            title=payload.title,
            document_type=payload.document_type,
            description=payload.description,
            department_id=payload.department_id,
            archived=payload.archived,
            target_document_id=payload.target_document_id,
        )
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TimeoutError as exc:
        db.rollback()
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "Document ingestion finalization failed (organization_id=%s, ingestion_session_id=%s)",
            organization_id,
            ingestion_session_id,
        )
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="The document could not be finalized. The staged upload remains available for retry.",
        ) from exc


@router.post(
    "/ingestion-sessions/stream",
    summary="Upload and analyze a PDF while streaming real processing progress",
)
def analyze_document_upload_stream(
    organization_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
    workflow_override: DocumentIngestionWorkflowService | None = Depends(get_ingestion_workflow),
):
    user, _membership = _current_member(db, organization_id, firebase_claims)
    filename = (file.filename or "").replace("\\", "/").split("/")[-1].strip()
    if not filename or not filename.lower().endswith(".pdf"):
        file.file.close()
        raise HTTPException(status_code=422, detail="Only PDF files are accepted.")

    temp_path: str | None = None
    total_bytes = 0
    try:
        with tempfile.NamedTemporaryFile(prefix="savira-ingest-", suffix=".pdf", delete=False) as temporary:
            temp_path = temporary.name
            while True:
                chunk = file.file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="PDF exceeds the 25 MB upload limit.")
                temporary.write(chunk)
        if total_bytes == 0:
            raise HTTPException(status_code=422, detail="The uploaded PDF is empty.")
    except HTTPException:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
        raise
    finally:
        file.file.close()

    events: queue.Queue = queue.Queue()
    user_id = user.id

    def run_pipeline() -> None:
        try:
            with SessionLocal() as worker_db:
                workflow = workflow_override or DocumentIngestionWorkflowService()

                def publish_progress(payload: dict) -> None:
                    events.put({"type": "progress", **payload})

                result = workflow.analyze_and_stage(
                    worker_db,
                    temp_path,
                    organization_id=organization_id,
                    uploaded_by_user_id=user_id,
                    original_filename=filename[:500],
                    file_size=total_bytes,
                    progress_callback=publish_progress,
                )
                events.put({"type": "result", "data": result})
        except DocumentIngestionWorkflowError as exc:
            events.put({"type": "error", "detail": str(exc), "status_code": 422})
        except Exception:
            logger.exception(
                "Streaming document ingestion failed (organization_id=%s, filename=%s)",
                organization_id,
                filename,
            )
            events.put({
                "type": "error",
                "detail": "Document analysis or temporary storage failed. Please retry the upload.",
                "status_code": 503,
            })
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            events.put(None)

    worker = threading.Thread(target=run_pipeline, name="document-ingestion", daemon=True)
    worker.start()

    async def event_stream():
        yield "data: " + json.dumps({
            "type": "progress",
            "stage": "receive_pdf",
            "state": "completed",
            "message": "PDF received by SaviraCortex.",
        }) + "\n\n"
        while True:
            try:
                item = await asyncio.to_thread(events.get, True, 15)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            if item is None:
                break
            yield "data: " + json.dumps(item, default=str) + "\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
