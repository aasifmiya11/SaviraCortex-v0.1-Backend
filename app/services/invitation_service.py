from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.firebase import _firebase_app
from app.models import (
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    OrganizationRole,
    User,
    UserRoleAssignment,
)
from app.schemas.v1.invitations import (
    InvitationAcceptRequest,
    InvitationAcceptResponse,
    InvitationCreateRequest,
    InvitationCreateResponse,
    InvitationListItem,
    InvitationPreviewResponse,
)
from app.services.invitation_mailer import send_invitation_email

logger = logging.getLogger(__name__)


def _as_utc(value: datetime) -> datetime:
    """SQLite may return naive values for timezone-aware DateTime columns."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class InvitationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _manager(self, organization_id, claims: dict):
        uid = claims.get("uid")
        if not isinstance(uid, str) or not uid.strip():
            raise HTTPException(status_code=401, detail="A valid Firebase identity is required.")
        membership = self.session.scalar(
            select(OrganizationMembership)
            .join(User, User.id == OrganizationMembership.user_id)
            .where(
                OrganizationMembership.organization_id == organization_id,
                User.firebase_uid == uid,
            )
        )
        if membership is None or membership.role not in {"owner", "admin"}:
            raise HTTPException(status_code=403, detail="Only organization owners and admins can manage invitations.")
        return membership

    def create(self, organization_id, payload: InvitationCreateRequest, claims: dict):
        manager = self._manager(organization_id, claims)
        if payload.role == "admin" and manager.role != "owner":
            raise HTTPException(status_code=403, detail="Only the organization owner can invite an administrator.")

        organization = self.session.get(Organization, organization_id)
        if organization is None:
            raise HTTPException(status_code=404, detail="Organization not found.")

        email = payload.email.strip().lower()
        if self.session.scalar(select(User.id).where(User.email == email)):
            raise HTTPException(status_code=409, detail="An account already exists for this email address.")

        now = datetime.now(timezone.utc)
        pending = self.session.scalar(
            select(OrganizationInvitation).where(
                OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.email == email,
                OrganizationInvitation.status == "pending",
                OrganizationInvitation.expires_at > now,
            )
        )
        if pending:
            raise HTTPException(status_code=409, detail="A valid invitation already exists for this email address.")

        raw_token = secrets.token_urlsafe(32)
        invitation = OrganizationInvitation(
            id=uuid4(),
            organization_id=organization_id,
            invited_by_user_id=manager.user_id,
            email=email,
            candidate_name=payload.candidate_name,
            invited_role=payload.role,
            token_hash=_hash_token(raw_token),
            status="pending",
            expires_at=now + timedelta(days=settings.INVITATION_EXPIRY_DAYS),
        )
        self.session.add(invitation)
        try:
            self.session.commit()
            inviter = self.session.get(User, manager.user_id)
            send_invitation_email(
                to_email=email,
                candidate_name=payload.candidate_name,
                organization_name=organization.name,
                inviter_name=(inviter.display_name if inviter else None) or "Your organization administrator",
                token=raw_token,
            )
            invitation.email_sent_at = datetime.now(timezone.utc)
            self.session.commit()
            self.session.refresh(invitation)
        except RuntimeError as exc:
            self.session.rollback()
            persisted = self.session.get(OrganizationInvitation, invitation.id)
            if persisted is not None:
                self.session.delete(persisted)
                self.session.commit()
            raise HTTPException(status_code=503, detail="Invitation email delivery is unavailable. Check SMTP configuration.") from exc
        except Exception as exc:
            self.session.rollback()
            raise HTTPException(status_code=502, detail="The invitation could not be completed. Please try again.") from exc

        return InvitationCreateResponse(
            id=invitation.id,
            email=invitation.email,
            candidate_name=invitation.candidate_name,
            role=invitation.invited_role,
            custom_role="Member",
            status=invitation.status,
            expires_at=invitation.expires_at,
            email_sent_at=invitation.email_sent_at,
        )

    def list_for_organization(self, organization_id, claims: dict):
        self._manager(organization_id, claims)
        rows = self.session.scalars(
            select(OrganizationInvitation)
            .where(OrganizationInvitation.organization_id == organization_id)
            .order_by(OrganizationInvitation.created_at.desc())
        ).all()
        now = datetime.now(timezone.utc)
        return [
            InvitationListItem(
                id=row.id,
                email=row.email,
                candidate_name=row.candidate_name,
                role=row.invited_role,
                custom_role="Member",
                status="expired" if row.status == "pending" and _as_utc(row.expires_at) <= now else row.status,
                created_at=row.created_at,
                expires_at=row.expires_at,
                email_sent_at=row.email_sent_at,
            )
            for row in rows
        ]

    def _valid_invitation(self, token: str, lock: bool = False):
        query = select(OrganizationInvitation).where(
            OrganizationInvitation.token_hash == _hash_token(token),
            OrganizationInvitation.status == "pending",
            OrganizationInvitation.expires_at > datetime.now(timezone.utc),
        )
        if lock:
            query = query.with_for_update()
        invitation = self.session.scalar(query)
        if invitation is None:
            raise HTTPException(status_code=410, detail="This invitation is invalid, expired, or already used.")
        return invitation

    def preview(self, token: str):
        invitation = self._valid_invitation(token)
        organization = self.session.get(Organization, invitation.organization_id)
        if organization is None:
            raise HTTPException(status_code=410, detail="The invited organization is no longer available.")
        return InvitationPreviewResponse(
            email=invitation.email,
            candidate_name=invitation.candidate_name,
            organization_name=organization.name,
            expires_at=invitation.expires_at,
        )

    def accept(self, payload: InvitationAcceptRequest):
        invitation = self._valid_invitation(payload.token, lock=True)
        email = invitation.email
        if self.session.scalar(select(User.id).where(User.email == email)):
            raise HTTPException(status_code=409, detail="An account already exists for this email. Contact the organization administrator.")

        from firebase_admin import auth as firebase_auth

        firebase_user = None
        app = _firebase_app()
        try:
            firebase_user = firebase_auth.create_user(
                email=email,
                display_name=payload.full_name,
                email_verified=True,
                app=app,
                password=payload.password,
            )
            user = User(
                id=uuid4(),
                firebase_uid=firebase_user.uid,
                email=email,
                phone_number=payload.phone_number,
                display_name=payload.full_name,
            )
            membership = OrganizationMembership(
                id=uuid4(),
                organization_id=invitation.organization_id,
                user_id=user.id,
                # System-level access remains "member". The organization-specific
                # default role is assigned separately as "Member" below.
                role="member",
            )
            member_role = self.session.scalar(
                select(OrganizationRole).where(
                    OrganizationRole.organization_id == invitation.organization_id,
                    OrganizationRole.name == "Member",
                )
            )
            if member_role is None:
                member_role = OrganizationRole(
                    id=uuid4(),
                    organization_id=invitation.organization_id,
                    name="Member",
                    description="Default role for organization members.",
                )
                self.session.add(member_role)
                self.session.flush()
            role_assignment = UserRoleAssignment(
                id=uuid4(),
                organization_id=invitation.organization_id,
                user_id=user.id,
                role_id=member_role.id,
            )
            invitation.status = "accepted"
            invitation.accepted_at = datetime.now(timezone.utc)
            # Flush in FK dependency order; SQLite does not reliably infer the
            # composite membership/role assignment dependencies from bare FKs.
            self.session.add(user)
            self.session.flush()
            self.session.add(membership)
            self.session.flush()
            self.session.add(role_assignment)
            self.session.flush()
            custom_token = firebase_auth.create_custom_token(firebase_user.uid, app=app)
            self.session.commit()
        except firebase_auth.EmailAlreadyExistsError as exc:
            self.session.rollback()
            raise HTTPException(status_code=409, detail="A Firebase account already uses this email. Contact your organization administrator.") from exc
        except IntegrityError as exc:
            self.session.rollback()
            if firebase_user is not None:
                try:
                    firebase_auth.delete_user(firebase_user.uid, app=app)
                except Exception:
                    pass
            raise HTTPException(status_code=409, detail="Account creation conflicted with existing data.") from exc
        except Exception as exc:
            logger.exception("Invitation acceptance failed during Firebase/database account creation.")
            self.session.rollback()
            if firebase_user is not None:
                try:
                    firebase_auth.delete_user(firebase_user.uid, app=app)
                except Exception:
                    pass
            raise HTTPException(status_code=500, detail="Account creation failed. Please try again.") from exc

        if isinstance(custom_token, bytes):
            custom_token = custom_token.decode("utf-8")
        return InvitationAcceptResponse(
            message="Your SaviraCortex account has been created.",
            user_id=user.id,
            organization_id=invitation.organization_id,
            role=membership.role,
            custom_token=custom_token,
        )
