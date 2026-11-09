from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.dependencies import get_db, get_verified_firebase_claims
from app.models import Document, DocumentVersion, OrganizationDepartment, OrganizationMembership, User
from app.repositories.authorization_repository import AuthorizationRepository
from app.schemas.v1.documents import (
    DocumentLibraryItem,
    DocumentLibraryResponse,
    DocumentUpdateRequest,
    DocumentVersionLibraryItem,
    DocumentVersionSummaryUpdateRequest,
    DocumentVersionSummaryUpdateResponse,
)
from app.services.document_management import (
    DocumentDeletionError,
    DocumentDeletionService,
)

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/organizations/{organization_id}/documents",
    tags=["Documents"],
)


def get_document_deletion_service() -> DocumentDeletionService | None:
    # Construct external clients only after membership and role checks pass.
    return None


def _current_member(
    db: Session,
    organization_id: UUID,
    firebase_claims: dict,
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


def _document_access_conditions(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
):
    conditions = AuthorizationRepository(db)._build_access_conditions(
        organization_id=organization_id,
        user_id=user_id,
    )
    if conditions is None:
        raise HTTPException(status_code=404, detail="Organization not found.")
    return conditions


def _document_query(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
    include_archived: bool,
):
    has_allow, has_deny = _document_access_conditions(
        db,
        organization_id=organization_id,
        user_id=user_id,
    )
    statement = (
        select(Document)
        .options(
            selectinload(Document.versions),
            joinedload(Document.department),
        )
        .where(
            Document.organization_id == organization_id,
            has_allow,
            ~has_deny,
        )
    )
    if not include_archived:
        statement = statement.where(Document.archived.is_(False))
    return statement


def _serialize_document(document: Document) -> DocumentLibraryItem:
    versions = sorted(
        document.versions,
        key=lambda version: version.version_number,
        reverse=True,
    )
    active_version = next(
        (version for version in versions if version.status == "active"),
        None,
    )
    return DocumentLibraryItem(
        id=document.id,
        title=document.title,
        document_type=document.document_type,
        description=document.description,
        department_id=document.department_id,
        department_name=document.department.name if document.department else None,
        archived=document.archived,
        created_at=document.created_at,
        active_version_id=active_version.id if active_version else None,
        versions=[
            DocumentVersionLibraryItem(
                id=version.id,
                version_number=version.version_number,
                version_label=version.version_label,
                original_filename=version.original_filename,
                summary=version.summary,
                status=version.status,
                page_count=version.page_count,
                effective_from=version.effective_from,
                effective_until=version.effective_until,
                supersedes_version_id=version.supersedes_version_id,
                created_at=version.created_at,
            )
            for version in versions
        ],
    )


def _require_manager(membership: OrganizationMembership) -> None:
    if membership.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail="Only organization owners and admins can change document metadata or lifecycle.",
        )


@router.get(
    "",
    response_model=DocumentLibraryResponse,
    summary="List the organization's accessible documents and versions",
)
def list_documents(
    organization_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=255),
    include_archived: bool = Query(default=False),
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    user, membership = _current_member(db, organization_id, firebase_claims)
    _require_manager(membership)
    show_archived = include_archived and membership.role in {"owner", "admin"}
    statement = _document_query(
        db,
        organization_id=organization_id,
        user_id=user.id,
        include_archived=show_archived,
    )
    count_statement = select(func.count(Document.id)).where(
        Document.organization_id == organization_id,
    )
    has_allow, has_deny = _document_access_conditions(
        db,
        organization_id=organization_id,
        user_id=user.id,
    )
    count_statement = count_statement.where(has_allow, ~has_deny)
    if not show_archived:
        count_statement = count_statement.where(Document.archived.is_(False))

    normalized_search = search.strip() if search else ""
    if normalized_search:
        search_filter = Document.title.ilike(f"%{normalized_search}%")
        statement = statement.where(search_filter)
        count_statement = count_statement.where(search_filter)

    total = int(db.scalar(count_statement) or 0)
    documents = db.scalars(
        statement.order_by(Document.created_at.desc(), Document.id)
        .limit(limit)
        .offset(offset)
    ).unique().all()

    return DocumentLibraryResponse(
        items=[_serialize_document(document) for document in documents],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentLibraryItem,
    summary="Get document metadata, summary and complete version history",
)
def get_document(
    organization_id: UUID,
    document_id: UUID,
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    user, membership = _current_member(db, organization_id, firebase_claims)
    _require_manager(membership)
    statement = _document_query(
        db,
        organization_id=organization_id,
        user_id=user.id,
        include_archived=membership.role in {"owner", "admin"},
    ).where(Document.id == document_id)
    document = db.scalars(statement).unique().first()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found or you do not have access to it.")
    return _serialize_document(document)


@router.patch(
    "/{document_id}",
    response_model=DocumentLibraryItem,
    summary="Update document metadata or archive state",
)
def update_document(
    organization_id: UUID,
    document_id: UUID,
    payload: DocumentUpdateRequest,
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    _user, membership = _current_member(db, organization_id, firebase_claims)
    _require_manager(membership)

    document = db.scalars(
        _document_query(
            db,
            organization_id=organization_id,
            user_id=_user.id,
            include_archived=True,
        )
        .where(Document.id == document_id)
        # The query eager-loads the optional department with a LEFT OUTER JOIN.
        # PostgreSQL cannot lock the nullable side of that join, so lock only
        # the document row while leaving the department relationship unlocked.
        .with_for_update(of=Document)
    ).unique().first()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    changes = payload.model_dump(exclude_unset=True)
    department_id = changes.get("department_id")
    if department_id is not None:
        department = db.scalar(
            select(OrganizationDepartment).where(
                OrganizationDepartment.id == department_id,
                OrganizationDepartment.organization_id == organization_id,
            )
        )
        if department is None:
            raise HTTPException(
                status_code=422,
                detail="The selected department does not belong to this organization.",
            )

    for field, value in changes.items():
        setattr(document, field, value)

    try:
        db.commit()
        db.refresh(document)
    except Exception:
        db.rollback()
        logger.exception("Document update failed (organization_id=%s, document_id=%s)", organization_id, document_id)
        raise HTTPException(status_code=503, detail="The document could not be updated. Please retry.")

    if "title" in changes and any(version.summary for version in document.versions):
        try:
            from app.rag.vector_stores.qdrant_summary import summary_store

            for version in document.versions:
                if not version.summary:
                    continue
                summary_store.upsert_summary(
                    document_id=document.id,
                    document_version_id=version.id,
                    version_number=version.version_number,
                    title=document.title,
                    summary=version.summary,
                    status=version.status,
                    organization_id=organization_id,
                )
        except Exception as exc:
            logger.exception(
                "Document title was saved but summary-vector metadata sync failed "
                "(organization_id=%s, document_id=%s)",
                organization_id,
                document_id,
            )
            raise HTTPException(
                status_code=503,
                detail="The title was saved, but the summary search index could not be synchronized. Save the title again to retry synchronization.",
            ) from exc

    return _serialize_document(document)


@router.patch(
    "/{document_id}/versions/{version_id}",
    response_model=DocumentVersionSummaryUpdateResponse,
    summary="Edit a document-version summary and synchronize its summary vector",
)
def update_document_version_summary(
    organization_id: UUID,
    document_id: UUID,
    version_id: UUID,
    payload: DocumentVersionSummaryUpdateRequest,
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    _user, membership = _current_member(db, organization_id, firebase_claims)
    _require_manager(membership)

    document = db.scalars(
        _document_query(
            db,
            organization_id=organization_id,
            user_id=_user.id,
            include_archived=True,
        ).where(Document.id == document_id)
    ).unique().first()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found or you do not have access to it.")

    version = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.id == version_id,
            DocumentVersion.document_id == document_id,
        )
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Document version not found.")

    version.summary = payload.summary
    try:
        db.commit()
        db.refresh(version)
    except Exception as exc:
        db.rollback()
        logger.exception(
            "Document summary update failed (organization_id=%s, document_id=%s, version_id=%s)",
            organization_id,
            document_id,
            version_id,
        )
        raise HTTPException(status_code=503, detail="The document summary could not be saved.") from exc

    summary_index_synced = True
    try:
        from app.rag.vector_stores.qdrant_summary import summary_store

        summary_store.upsert_summary(
            document_id=document.id,
            document_version_id=version.id,
            version_number=version.version_number,
            title=document.title,
            summary=version.summary,
            status=version.status,
            organization_id=organization_id,
        )
    except Exception:
        summary_index_synced = False
        logger.exception(
            "Document summary was saved but summary-vector sync failed "
            "(organization_id=%s, document_id=%s, version_id=%s)",
            organization_id,
            document_id,
            version_id,
        )

    return DocumentVersionSummaryUpdateResponse(
        version=DocumentVersionLibraryItem(
            id=version.id,
            version_number=version.version_number,
            version_label=version.version_label,
            original_filename=version.original_filename,
            summary=version.summary,
            status=version.status,
            page_count=version.page_count,
            effective_from=version.effective_from,
            effective_until=version.effective_until,
            supersedes_version_id=version.supersedes_version_id,
            created_at=version.created_at,
        ),
        summary_index_synced=summary_index_synced,
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_200_OK,
    summary="Permanently delete a document, its versions, source PDFs and search indexes",
)
def delete_document(
    organization_id: UUID,
    document_id: UUID,
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
    deletion_service: DocumentDeletionService | None = Depends(get_document_deletion_service),
):
    _user, membership = _current_member(db, organization_id, firebase_claims)
    _require_manager(membership)
    accessible_document = db.scalars(
        _document_query(
            db,
            organization_id=organization_id,
            user_id=_user.id,
            include_archived=True,
        ).where(Document.id == document_id)
    ).unique().first()
    if accessible_document is None:
        raise HTTPException(status_code=404, detail="Document not found or you do not have access to it.")

    service = deletion_service or DocumentDeletionService()
    try:
        result = service.delete_document(
            db,
            document_id=document_id,
            organization_id=organization_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DocumentDeletionError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Document deletion failed (organization_id=%s, document_id=%s)", organization_id, document_id)
        raise HTTPException(
            status_code=503,
            detail="The document could not be fully deleted. Its records were preserved where possible; retry the deletion.",
        ) from exc

    return {
        "status": "deleted",
        "document_id": str(result.document_id),
        "deleted_versions": result.deleted_versions,
        "deleted_files": result.deleted_files,
        "deleted_chunk_and_bm25_points": True,
        "deleted_summary_points": True,
    }
