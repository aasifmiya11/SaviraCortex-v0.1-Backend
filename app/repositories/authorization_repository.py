
from uuid import UUID

from typing import Any

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from app.models.document_acl import DocumentACL
from app.models.documents import Document
from app.models.document_versions import DocumentVersion
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

    def get_authorized_document_catalog(
        self,
        organization_id: UUID,
        user_id: UUID,
    ) -> list[dict[str, Any]]:
        """
        Return authorized active and superseded version metadata.

        Lifecycle state and archival state come from PostgreSQL. The
        catalogue is intended for retrieval planning, not authorization
        decisions outside this query.
        """
        membership = self.db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.user_id == user_id,
            )
        )

        if membership is None:
            return []

        statement = (
            select(Document, DocumentVersion)
            .join(
                DocumentVersion,
                DocumentVersion.document_id == Document.id,
            )
            .where(
                Document.organization_id == organization_id,
                Document.archived.is_(False),
                DocumentVersion.status.in_(("active", "superseded")),
            )
        )

        if membership.role not in {"owner", "admin"}:
            assigned_role_ids = select(
                UserRoleAssignment.role_id
            ).where(
                UserRoleAssignment.organization_id == organization_id,
                UserRoleAssignment.user_id == user_id,
            )

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

            if membership.department_id is not None:
                matching_principals.append(
                    and_(
                        DocumentACL.principal_type == "department",
                        DocumentACL.department_id == membership.department_id,
                    )
                )

            has_allow = exists(
                select(1).where(
                    DocumentACL.organization_id == organization_id,
                    DocumentACL.document_id == Document.id,
                    DocumentACL.effect == "allow",
                    or_(*matching_principals),
                )
            )
            has_user_deny = exists(
                select(1).where(
                    DocumentACL.organization_id == organization_id,
                    DocumentACL.document_id == Document.id,
                    DocumentACL.principal_type == "user",
                    DocumentACL.user_id == user_id,
                    DocumentACL.effect == "deny",
                )
            )
            statement = statement.where(has_allow, ~has_user_deny)

        statement = statement.order_by(
            Document.id,
            DocumentVersion.version_number.desc(),
        )

        catalogue = []
        for document, version in self.db.execute(statement):
            effective_year = (
                version.effective_from.year
                if version.effective_from is not None
                else version.created_at.year
            )
            catalogue.append(
                {
                    "document_id": str(document.id),
                    "document_version_id": str(version.id),
                    "document_title": document.title,
                    "document_summary": version.summary or "",
                    "version_year": effective_year,
                    "version_status": version.status,
                    "last_updated": version.created_at.isoformat(),
                }
            )

        return catalogue
