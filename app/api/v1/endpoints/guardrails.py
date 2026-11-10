from __future__ import annotations

from copy import deepcopy
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_verified_firebase_claims
from app.guardrails.runtime_schemas import (
    GuardrailPolicyPatch,
    resolve_effective_policy,
)
from app.models import GuardrailAuditEvent, Organization, OrganizationMembership, User

router = APIRouter(
    prefix="/organizations/{organization_id}/guardrails",
    tags=["Guardrails"],
)


def _organization_and_role(
    db: Session,
    organization_id: UUID,
    claims: dict,
) -> tuple[Organization, str]:
    firebase_uid = claims.get("uid")
    if not isinstance(firebase_uid, str) or not firebase_uid.strip():
        raise HTTPException(status_code=401, detail="Verified Firebase identity is missing a UID.")
    user = db.scalar(select(User).where(User.firebase_uid == firebase_uid))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    membership = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization not found or access denied.")
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found.")
    return organization, membership.role


@router.get("", summary="Get effective guardrail policy for an organization")
def get_guardrail_policy(
    organization_id: UUID,
    db: Session = Depends(get_db),
    claims: dict = Depends(get_verified_firebase_claims),
):
    organization, _ = _organization_and_role(db, organization_id, claims)
    return {
        "organization_id": str(organization_id),
        "configured_policy": deepcopy(organization.guardrail_policy or {}),
        "effective_policy": resolve_effective_policy(organization.guardrail_policy or {}).model_dump(mode="json"),
    }


@router.patch("", summary="Update organization guardrail policy")
def update_guardrail_policy(
    organization_id: UUID,
    payload: GuardrailPolicyPatch,
    db: Session = Depends(get_db),
    claims: dict = Depends(get_verified_firebase_claims),
):
    organization, role = _organization_and_role(db, organization_id, claims)
    if role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organization owners and admins can manage guardrail settings.",
        )

    current = deepcopy(organization.guardrail_policy or {})
    updates = payload.model_dump(mode="json", exclude_unset=True)
    candidate = {**current, **updates}
    try:
        effective = resolve_effective_policy(candidate)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    organization.guardrail_policy = candidate
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return {
        "organization_id": str(organization_id),
        "configured_policy": deepcopy(organization.guardrail_policy or {}),
        "effective_policy": effective.model_dump(mode="json"),
    }


@router.get("/audit", summary="List privacy-conscious guardrail audit events")
def list_guardrail_audit_events(
    organization_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    claims: dict = Depends(get_verified_firebase_claims),
):
    _, role = _organization_and_role(db, organization_id, claims)
    if role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organization owners and admins can view guardrail audit events.",
        )
    events = db.scalars(
        select(GuardrailAuditEvent)
        .where(GuardrailAuditEvent.organization_id == organization_id)
        .order_by(desc(GuardrailAuditEvent.created_at))
        .limit(limit)
    ).all()
    return {
        "events": [
            {
                "id": str(event.id),
                "request_id": str(event.request_id),
                "stage": event.stage,
                "decision": event.decision,
                "categories": event.categories or [],
                "details": event.details or {},
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in events
        ]
    }
