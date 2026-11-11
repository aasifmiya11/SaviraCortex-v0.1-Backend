from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.checkpointer import get_checkpointer
from app.core.dependencies import get_db, get_verified_firebase_claims
from app.models import ConversationMessage, GenerationFeedback, OrganizationMembership, User
from app.repositories.conversation_repository import (
    ConversationNotFoundError,
    ConversationRepository,
)
from app.schemas.v1.conversations import ConversationRenameRequest
from app.services.conversation_time_travel_service import (
    ConversationTimeTravelError, ConversationTimeTravelService,
)

from app.storage.file_storage import FileStorage

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/organizations/{organization_id}/conversations",
    tags=["Conversations"],
)


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


@router.get("", summary="List the authenticated user's conversations")
def list_conversations(
    organization_id: UUID,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    user = _current_member(db, organization_id, firebase_claims)
    items, total = ConversationRepository(db).list_for_user(
        organization_id=organization_id,
        user_id=user.id,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [
            {
                "conversation_id": str(item.id),
                "title": item.title,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
                "parent_conversation_id": str(item.parent_conversation_id) if item.parent_conversation_id else None,
                "parent_message_id": str(item.parent_message_id) if item.parent_message_id else None,
                "branch_action": item.branch_action,
            }
            for item in items
        ],
        "count": len(items),
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
    }


@router.get(
    "/{conversation_id}/messages",
    summary="Retrieve a page of conversation messages, newest page first",
)
def list_conversation_messages(
    organization_id: UUID,
    conversation_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    path_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    user = _current_member(db, organization_id, firebase_claims)
    repository = ConversationRepository(db)
    try:
        repository.get_owned(conversation_id, organization_id, user.id)
    except ConversationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        ) from exc

    items, total = repository.list_messages(
        conversation_id=conversation_id,
        limit=limit,
        offset=offset,
        path_id=path_id,
    )
    generation_ids = [
        UUID((item.message_metadata or {}).get("generation_id"))
        for item in items
        if (item.message_metadata or {}).get("generation_id")
    ]
    feedback_by_generation = {}
    if generation_ids:
        feedback_rows = db.execute(
            select(GenerationFeedback.id, GenerationFeedback.feedback_status).where(
                GenerationFeedback.id.in_(generation_ids),
                GenerationFeedback.organization_id == organization_id,
                GenerationFeedback.user_id == user.id,
            )
        ).all()
        feedback_by_generation = {str(row.id): row.feedback_status for row in feedback_rows}

    # Resolve each assistant response to the user turn that preceded it. Regenerated
    # responses carry this same group id in metadata, allowing the client to switch
    # versions without duplicating the user question.
    prior_user_by_sequence: dict[int, str] = {}
    history = db.scalars(select(ConversationMessage).where(
        ConversationMessage.conversation_id == conversation_id,
        ConversationMessage.path_id == path_id,
    ).order_by(ConversationMessage.sequence.asc())).all()
    latest_user_id: str | None = None
    for history_item in history:
        if history_item.role == "user":
            latest_user_id = str(history_item.id)
        elif latest_user_id:
            prior_user_by_sequence[history_item.sequence] = latest_user_id

    serialized_items = []
    for item in items:
        metadata = dict(item.message_metadata or {})
        if item.role == "user":
            metadata.setdefault("path_group_id", str(item.id))
        elif item.role == "assistant":
            metadata.setdefault("path_group_id", prior_user_by_sequence.get(item.sequence))
        attachments = metadata.get("attachments") or []
        if attachments:
            try:
                storage = FileStorage()
                owner_prefix = (
                    f"{storage.prefix}organizations/{organization_id}/users/{user.id}/conversation-images/"
                )
                for attachment in attachments:
                    key = attachment.get("storage_key")
                    if isinstance(key, str) and key.startswith(owner_prefix):
                        attachment["url"] = storage.generate_download_url(key, expiration_seconds=300)
            except Exception:
                logger.exception("Unable to create temporary image URLs for conversation %s.", conversation_id)
        generation_id = metadata.get("generation_id")
        if generation_id:
            metadata["feedback_status"] = feedback_by_generation.get(generation_id)
        serialized_items.append(
            {
                "message_id": str(item.id),
                "sequence": item.sequence,
                "role": item.role,
                "content": item.content,
                "metadata": {**metadata, "path_id": str(item.path_id) if item.path_id else None},
                "path_id": str(item.path_id) if item.path_id else None,
                "created_at": item.created_at,
            }
        )
    return {
        "items": serialized_items,
        "count": len(items),
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
    }


class ConversationBranchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["edit_input", "regenerate", "fork"]
    target_message_id: UUID
    edited_query: str | None = Field(default=None, min_length=1, max_length=8000)


@router.post("/{conversation_id}/branches", status_code=status.HTTP_201_CREATED,
             summary="Create a time-travel branch from a conversation checkpoint")
async def create_conversation_branch(
    organization_id: UUID,
    conversation_id: UUID,
    payload: ConversationBranchRequest,
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    user = _current_member(db, organization_id, firebase_claims)
    try:
        result = await ConversationTimeTravelService(db).create_branch(
            source_conversation_id=conversation_id,
            organization_id=organization_id,
            user_id=user.id,
            action=payload.action,
            target_message_id=payload.target_message_id,
            edited_query=payload.edited_query,
        )
        return result
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Conversation or message not found.") from exc
    except ConversationTimeTravelError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{conversation_id}/paths", summary="List alternate timelines for a question")
def list_conversation_paths(
    organization_id: UUID, conversation_id: UUID, branch_point_message_id: UUID,
    db: Session = Depends(get_db), firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    user = _current_member(db, organization_id, firebase_claims)
    try:
        return ConversationTimeTravelService(db).list_paths(
            conversation_id=conversation_id, organization_id=organization_id,
            user_id=user.id, branch_point_message_id=branch_point_message_id,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found.") from exc


@router.get("/{conversation_id}/branches", summary="List direct conversation branches")
def list_conversation_branches(
    organization_id: UUID,
    conversation_id: UUID,
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    user = _current_member(db, organization_id, firebase_claims)
    repository = ConversationRepository(db)
    try:
        repository.get_owned(conversation_id, organization_id, user.id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found.") from exc
    from sqlalchemy import select
    from app.models import Conversation
    items = db.scalars(select(Conversation).where(
        Conversation.parent_conversation_id == conversation_id,
        Conversation.organization_id == organization_id,
        Conversation.user_id == user.id,
    ).order_by(Conversation.created_at.desc())).all()
    return {"items": [{
        "conversation_id": str(item.id), "title": item.title,
        "branch_action": item.branch_action,
        "parent_message_id": str(item.parent_message_id) if item.parent_message_id else None,
        "parent_checkpoint_id": item.parent_checkpoint_id,
        "created_at": item.created_at,
    } for item in items]}


@router.patch("/{conversation_id}", summary="Rename a conversation")
def rename_conversation(
    organization_id: UUID,
    conversation_id: UUID,
    payload: ConversationRenameRequest,
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    user = _current_member(db, organization_id, firebase_claims)
    repository = ConversationRepository(db)
    try:
        conversation = repository.get_owned(
            conversation_id, organization_id, user.id
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        ) from exc
    conversation = repository.rename(conversation, payload.title)
    return {
        "conversation_id": str(conversation.id),
        "title": conversation.title,
        "updated_at": conversation.updated_at,
    }


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a conversation and its LangGraph checkpoints",
)
async def delete_conversation(
    organization_id: UUID,
    conversation_id: UUID,
    db: Session = Depends(get_db),
    firebase_claims: dict = Depends(get_verified_firebase_claims),
):
    user = _current_member(db, organization_id, firebase_claims)
    repository = ConversationRepository(db)
    try:
        conversation = repository.get_owned(
            conversation_id, organization_id, user.id
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        ) from exc

    checkpointer = get_checkpointer()
    if checkpointer is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conversation persistence is temporarily unavailable.",
        )

    try:
        # Safe to retry: deleting a thread with no remaining checkpoints is idempotent.
        await checkpointer.adelete_thread(str(conversation.id))
        repository.delete(conversation)
    except Exception as exc:
        db.rollback()
        logger.exception(
            "Conversation deletion failed (conversation_id=%s).",
            conversation_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The conversation could not be fully deleted. Please retry.",
        ) from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)
