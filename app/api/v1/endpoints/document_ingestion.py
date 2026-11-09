from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import tempfile
import threading
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from app.core.database import SessionLocal
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_verified_firebase_claims
from app.models import (
    Document,
    DocumentVersion,
    OrganizationDepartmentMembership,
    OrganizationMembership,
    OrganizationDepartment,
    OrganizationRole,
    User,
)
from app.schemas.v1.document_ingestion import (
    DocumentIngestionAnalysisResponse,
    DocumentIngestionFinalizeRequest,
    DocumentIngestionFinalizeResponse,
    DocumentVersionIndexingResponse,
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


def _require_manager(membership: OrganizationMembership) -> None:
    if membership.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail="Only organization owners and admins can ingest or index documents.",
        )


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
    user, membership = _current_member(db, organization_id, firebase_claims)
    _require_manager(membership)
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
    _require_manager(membership)
    if payload.action in {"supersede", "delete_and_ingest"} and payload.target_document_id is not None:
        from app.repositories.authorization_repository import AuthorizationRepository

        authorized_document_ids = set(
            AuthorizationRepository(db).get_authorized_document_ids(
                organization_id=organization_id,
                user_id=user.id,
            )
        )
        if payload.target_document_id not in authorized_document_ids:
            raise HTTPException(
                status_code=404,
                detail="The selected document was not found or you do not have permission to modify it.",
            )
    workflow = workflow or DocumentIngestionWorkflowService()
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
            archived=payload.archived,
            target_document_id=payload.target_document_id,
            allow_unmatched_supersede=membership.role in {"owner", "admin"},
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
    user, membership = _current_member(db, organization_id, firebase_claims)
    _require_manager(membership)
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

@router.post(
    "/versions/{document_version_id}/index",
    response_model=DocumentVersionIndexingResponse,
    summary="Retry indexing for a pending document version",
)
def retry_document_version_indexing(
    organization_id: UUID,
    document_version_id: UUID,
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    user, membership = _current_member(db, organization_id, firebase_claims)
    _require_manager(membership)
    version = db.scalar(
        select(DocumentVersion)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            DocumentVersion.id == document_version_id,
            Document.organization_id == organization_id,
        )
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Document version not found.")
    if version.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Only pending versions can be indexed; current status is {version.status}.",
        )
    if (
        version.uploaded_by_user_id != user.id
        and membership.role not in {"owner", "admin"}
    ):
        raise HTTPException(
            status_code=403,
            detail="Only the uploader or an organization owner/admin can retry indexing.",
        )

    try:
        from app.services.document_indexing.indexing_orchestrator import (
            DocumentIndexingOrchestrator,
        )

        result = DocumentIndexingOrchestrator().index_pending_version(
            document_version_id,
            organization_id=organization_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    except Exception as exc:
        logger.exception(
            "Unexpected document indexing retry failure (organization_id=%s, version_id=%s).",
            organization_id,
            document_version_id,
        )
        raise HTTPException(
            status_code=503,
            detail="Indexing is temporarily unavailable. You can retry this version again.",
        ) from exc

    return DocumentVersionIndexingResponse(
        document_id=result.document_id,
        document_version_id=result.document_version_id,
        version_number=result.version_number,
        version_status=result.status,
        page_count=result.page_count,
        ocr_page_count=result.ocr_page_count,
        chunk_count=result.chunk_count,
        summary_sync_pending=result.summary_sync_pending,
        lifecycle_sync_pending=result.lifecycle_sync_pending,
    )


@router.post(
    "/ingestion-batches/stream",
    summary="Upload and analyze a bounded batch of PDF documents",
)
def analyze_document_batch_stream(
    organization_id: UUID,
    files: list[UploadFile] = File(...),
    department_ids: list[UUID] = Form(default=[]),
    access_user_ids: list[UUID] = Form(default=[]),
    access_role_ids: list[UUID] = Form(default=[]),
    deny_department_ids: list[UUID] = Form(default=[]),
    deny_user_ids: list[UUID] = Form(default=[]),
    deny_role_ids: list[UUID] = Form(default=[]),
    organization_wide_access: bool = Form(default=True),
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
    workflow_override: DocumentIngestionWorkflowService | None = Depends(get_ingestion_workflow),
):
    """Analyze and stage batch PDFs sequentially, reporting each completed item.

    Each item is isolated: one failure or duplicate never cancels later items.
    The SSE connection only transports progress; minimizing the UI does not
    cancel the request or its worker tasks.
    """
    from uuid import uuid4
    from app.services.document_ingestion.batch_config import (
        MAX_BATCH_UPLOAD_BYTES,
        MAX_QUEUED_DOCUMENTS,
        MAX_DOCUMENT_WORKERS,
        QUEUE_SLOTS,
    )

    user, membership = _current_member(db, organization_id, firebase_claims)
    _require_manager(membership)
    if not files:
        raise HTTPException(status_code=422, detail="Select at least one PDF.")
    if len(files) > MAX_QUEUED_DOCUMENTS:
        raise HTTPException(
            status_code=413,
            detail=f"A batch can contain at most {MAX_QUEUED_DOCUMENTS} documents.",
        )

    department_ids = list(dict.fromkeys(department_ids))
    access_user_ids = list(dict.fromkeys(access_user_ids))
    access_role_ids = list(dict.fromkeys(access_role_ids))
    deny_department_ids = list(dict.fromkeys(deny_department_ids))
    deny_user_ids = list(dict.fromkeys(deny_user_ids))
    deny_role_ids = list(dict.fromkeys(deny_role_ids))
    if department_ids or deny_department_ids:
        valid_departments = set(db.scalars(select(OrganizationDepartment.id).where(
            OrganizationDepartment.organization_id == organization_id,
            OrganizationDepartment.id.in_(list(set(department_ids + deny_department_ids))),
        )).all())
        if valid_departments != set(department_ids + deny_department_ids):
            raise HTTPException(status_code=422, detail="One or more selected departments do not belong to this organization.")
    if access_role_ids or deny_role_ids:
        valid_roles = set(db.scalars(select(OrganizationRole.id).where(
            OrganizationRole.organization_id == organization_id,
            OrganizationRole.id.in_(list(set(access_role_ids + deny_role_ids))),
        )).all())
        if valid_roles != set(access_role_ids + deny_role_ids):
            raise HTTPException(status_code=422, detail="One or more selected roles do not belong to this organization.")
    if access_user_ids or deny_user_ids:
        valid_users = set(db.scalars(select(OrganizationMembership.user_id).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id.in_(list(set(access_user_ids + deny_user_ids))),
        )).all())
        if valid_users != set(access_user_ids + deny_user_ids):
            raise HTTPException(status_code=422, detail="One or more selected members do not belong to this organization.")

    batch_id = uuid4()
    staged_files: list[dict] = []
    temporary_paths: list[str] = []
    total_bytes = 0
    try:
        for index, upload in enumerate(files):
            filename = (upload.filename or "").replace("\\", "/").split("/")[-1].strip()
            if not filename or not filename.lower().endswith(".pdf"):
                raise HTTPException(status_code=422, detail=f"{filename or 'A selected file'} is not a PDF.")
            path = None
            size = 0
            with tempfile.NamedTemporaryFile(prefix="savira-batch-", suffix=".pdf", delete=False) as temporary:
                path = temporary.name
                temporary_paths.append(path)
                while True:
                    chunk = upload.file.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    size += len(chunk)
                    total_bytes += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise HTTPException(status_code=413, detail=f"{filename} exceeds the 25 MB per-file limit.")
                    if total_bytes > MAX_BATCH_UPLOAD_BYTES:
                        raise HTTPException(status_code=413, detail="The batch exceeds the configured total upload limit.")
                    temporary.write(chunk)
            if size == 0:
                raise HTTPException(status_code=422, detail=f"{filename} is empty.")
            staged_files.append({"index": index, "filename": filename[:500], "path": path, "size": size})
    except Exception:
        for temporary_path in temporary_paths:
            try:
                os.remove(temporary_path)
            except OSError:
                pass
        raise
    finally:
        for upload in files:
            upload.file.close()

    reserved = 0
    try:
        for _item in staged_files:
            if not QUEUE_SLOTS.acquire(blocking=False):
                raise HTTPException(
                    status_code=429,
                    detail=f"The ingestion queue is full. It supports {MAX_QUEUED_DOCUMENTS} waiting documents plus {MAX_DOCUMENT_WORKERS} active workers; retry this batch shortly.",
                )
            reserved += 1
    except HTTPException:
        for _ in range(reserved):
            QUEUE_SLOTS.release()
        for item in staged_files:
            try:
                os.remove(item["path"])
            except OSError:
                pass
        raise

    events: queue.Queue = queue.Queue()
    user_id = user.id

    def report_progress(item: dict, payload: dict) -> None:
        events.put({
            "type": "progress",
            "batch_id": str(batch_id),
            "item_id": item["index"],
            "filename": item["filename"],
            **payload,
        })

    def prepare_item(item: dict) -> dict:
        """Run expensive PDF extraction, summarization and embedding concurrently."""
        workflow = workflow_override or DocumentIngestionWorkflowService()
        try:
            prepared = workflow.prepare_for_batch(
                item["path"],
                progress_callback=lambda payload: report_progress(item, payload),
            )
            return {"prepared": prepared, "workflow": workflow}
        except DocumentIngestionWorkflowError as exc:
            return {"error": str(exc)}
        except Exception:
            logger.exception(
                "Batch document preparation failed (batch_id=%s, filename=%s)",
                batch_id,
                item["filename"],
            )
            return {"error": "Document analysis or temporary storage failed. Please retry this document."}

    def cosine_similarity(left, right) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        left_norm = sum(value * value for value in left) ** 0.5
        right_norm = sum(value * value for value in right) ** 0.5
        if left_norm == 0.0 or right_norm == 0.0:
            return 0.0
        return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)

    released_item_ids: set[int] = set()

    def cleanup_item(item: dict) -> None:
        item_id = item["index"]
        if item_id in released_item_ids:
            return
        released_item_ids.add(item_id)
        try:
            os.remove(item["path"])
        except OSError:
            pass
        QUEUE_SLOTS.release()

    def run_batch() -> None:
        try:
            # Process PDFs in upload order. Each file is extracted, summarized and embedded,
            # then matched against the vector store and earlier batch items, then staged.
            # The result is emitted before starting the next PDF so clients can finalize it
            # and update progress incrementally instead of waiting for the whole batch.
            batch_index: list[dict] = []
            for item in sorted(staged_files, key=lambda value: value["index"]):
                prepared_result = prepare_item(item)
                if prepared_result.get("error"):
                    events.put({
                        "type": "item_result",
                        "batch_id": str(batch_id),
                        "data": {
                            "item_id": item["index"],
                            "filename": item["filename"],
                            "status": "failed",
                            "error": prepared_result["error"],
                        },
                    })
                    cleanup_item(item)
                    continue

                prepared = prepared_result["prepared"]
                workflow = prepared_result["workflow"]
                current_embedding = prepared.summary_embedding
                batch_candidates = []
                for previous in batch_index:
                    score = cosine_similarity(current_embedding, previous["embedding"])
                    identity_overlap = set(getattr(prepared, "identity_tokens", ())).intersection(previous.get("identity_tokens", ()))
                    if score >= 0.80 or identity_overlap:
                        batch_candidates.append({
                            "batch_item_id": previous["item_id"],
                            "original_filename": previous["filename"],
                            "title": previous["title"],
                            "similarity_score": max(score, 0.99) if identity_overlap else score,
                            "matched_by": "batch_identity" if identity_overlap else "batch_summary",
                            "identity_match_reasons": sorted({token.split(":", 1)[0] for token in identity_overlap}),
                            "batch_ingestion_session_id": previous["ingestion_session_id"],
                        })
                batch_candidates.sort(
                    key=lambda candidate: candidate["similarity_score"],
                    reverse=True,
                )

                try:
                    with SessionLocal() as worker_db:
                        result = workflow.analyze_and_stage(
                            worker_db,
                            item["path"],
                            organization_id=organization_id,
                            uploaded_by_user_id=user_id,
                            original_filename=item["filename"],
                            file_size=item["size"],
                            department_ids=department_ids,
                            access_user_ids=access_user_ids,
                            access_role_ids=access_role_ids,
                            deny_department_ids=deny_department_ids,
                            deny_user_ids=deny_user_ids,
                            deny_role_ids=deny_role_ids,
                            organization_wide_access=organization_wide_access,
                            progress_callback=lambda payload: report_progress(item, payload),
                            prepared_document=prepared,
                            batch_candidates=batch_candidates,
                        )
                    if result.get("status") == "ready_for_review":
                        batch_index.append({
                            "item_id": item["index"],
                            "filename": item["filename"],
                            "title": result.get("title") or item["filename"],
                            "ingestion_session_id": str(result["ingestion_session_id"]),
                            "embedding": current_embedding,
                            "identity_tokens": getattr(prepared, "identity_tokens", ()),
                        })
                    events.put({
                        "type": "item_result",
                        "batch_id": str(batch_id),
                        "data": {
                            "item_id": item["index"],
                            "filename": item["filename"],
                            "status": result.get("status", "ready_for_review"),
                            "data": result,
                        },
                    })
                except DocumentIngestionWorkflowError as exc:
                    events.put({
                        "type": "item_result",
                        "batch_id": str(batch_id),
                        "data": {
                            "item_id": item["index"],
                            "filename": item["filename"],
                            "status": "failed",
                            "error": str(exc),
                        },
                    })
                except Exception:
                    logger.exception(
                        "Sequential batch processing failed (batch_id=%s, filename=%s)",
                        batch_id,
                        item["filename"],
                    )
                    events.put({
                        "type": "item_result",
                        "batch_id": str(batch_id),
                        "data": {
                            "item_id": item["index"],
                            "filename": item["filename"],
                            "status": "failed",
                            "error": "Document matching or staging failed. Please retry this document.",
                        },
                    })
                finally:
                    cleanup_item(item)
        finally:
            for remaining_item in staged_files:
                cleanup_item(remaining_item)
            events.put({"type": "completed", "batch_id": str(batch_id), "total": len(staged_files)})
            events.put(None)

    coordinator = threading.Thread(target=run_batch, name=f"document-batch-{batch_id}", daemon=True)
    coordinator.start()

    async def event_stream():
        yield "data: " + json.dumps({
            "type": "batch_started",
            "batch_id": str(batch_id),
            "total": len(staged_files),
            "max_workers": MAX_DOCUMENT_WORKERS,
            "max_queued": MAX_QUEUED_DOCUMENTS,
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
        headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
