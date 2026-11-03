
from uuid import UUID

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from app.models.document_acl import DocumentACL
from app.models.documents import Document
from app.models.organization_memberships import OrganizationMembership
from app.models.user_role_assignments import UserRoleAssignment


class AuthorizationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_authorized_document_ids(
        self,
        organization_id: UUID,
        user_id: UUID,
    ) -> list[UUID]:
        """
        Return logical document IDs accessible to a user
        within the specified organization.

        Does not commit or modify database state.
        """

        membership = self.db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.user_id == user_id,
            )
        )

        # No organization membership means no access.
        if membership is None:
            return []

        base_query = select(Document.id).where(
            Document.organization_id == organization_id,
            Document.archived.is_(False),
        )

        # Owners and admins bypass document ACL checks.
        # Archived documents remain excluded.
        if membership.role in {"owner", "admin"}:
            return list(
                self.db.scalars(
                    base_query.order_by(Document.id)
                ).all()
            )

        # Custom roles assigned to this user in this organization.
        assigned_role_ids = select(
            UserRoleAssignment.role_id
        ).where(
            UserRoleAssignment.organization_id == organization_id,
            UserRoleAssignment.user_id == user_id,
        )

        # Build the matching ACL principal conditions.
        matching_principals = [
            and_(
                DocumentACL.principal_type == "user",
                DocumentACL.user_id == user_id,
            ),
            and_(
                DocumentACL.principal_type == "role",
                DocumentACL.role_id.in_(assigned_role_ids),
            ),
        ]

        # Department grants apply only when the membership
        # has an assigned department.
        if membership.department_id is not None:
            matching_principals.append(
                and_(
                    DocumentACL.principal_type == "department",
                    DocumentACL.department_id == membership.department_id,
                )
            )

        # At least one matching allow entry is required.
        has_allow = exists(
            select(1).where(
                DocumentACL.organization_id == organization_id,
                DocumentACL.document_id == Document.id,
                DocumentACL.effect == "allow",
                or_(*matching_principals),
            )
        )

        # An explicit user-level deny overrides role and
        # department grants.
        has_user_deny = exists(
            select(1).where(
                DocumentACL.organization_id == organization_id,
                DocumentACL.document_id == Document.id,
                DocumentACL.principal_type == "user",
                DocumentACL.user_id == user_id,
                DocumentACL.effect == "deny",
            )
        )

        statement = (
            base_query
            .where(has_allow)
            .where(~has_user_deny)
            .order_by(Document.id)
        )

        return list(self.db.scalars(statement).all())
