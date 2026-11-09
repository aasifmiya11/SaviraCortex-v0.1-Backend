from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.checkpointer import get_checkpointer
from app.core.dependencies import get_db, get_verified_firebase_claims
from app.models import GenerationFeedback, OrganizationMembership, User
from app.repositories.conversation_repository import (
    ConversationNotFoundError,
    ConversationRepository,
)
from app.schemas.v1.conversations import ConversationRenameRequest

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

    serialized_items = []
    for item in items:
        metadata = dict(item.message_metadata or {})
        generation_id = metadata.get("generation_id")
        if generation_id:
            metadata["feedback_status"] = feedback_by_generation.get(generation_id)
        serialized_items.append(
            {
                "message_id": str(item.id),
                "sequence": item.sequence,
                "role": item.role,
                "content": item.content,
                "metadata": metadata,
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
