from uuid import UUID

from typing import Any

from sqlalchemy import and_, exists, or_, select, true
from sqlalchemy.orm import Session

from app.models.document_acl import DocumentACL
from app.models.documents import Document
from app.models.document_versions import DocumentVersion
from app.models.organization_department_memberships import (
    OrganizationDepartmentMembership,
)
from app.models.organization_memberships import OrganizationMembership
from app.models.user_role_assignments import UserRoleAssignment


class AuthorizationRepository:
    def __init__(self, db: Session):
        self.db = db

    def _build_access_conditions(
        self,
        organization_id: UUID,
        user_id: UUID,
    ):
        """Build allow/deny predicates for all principals assigned to a member.

        Department IDs come from organization_department_memberships.
        """
        membership = self.db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.user_id == user_id,
            )
        )

        if membership is None:
            return None

        assigned_role_ids = select(
            UserRoleAssignment.role_id
        ).where(
            UserRoleAssignment.organization_id == organization_id,
            UserRoleAssignment.user_id == user_id,
        )

        department_ids = select(
            OrganizationDepartmentMembership.department_id
        ).where(
            OrganizationDepartmentMembership.organization_id == organization_id,
            OrganizationDepartmentMembership.user_id == user_id,
        )

        matching_principals = or_(
            and_(
                DocumentACL.principal_type == "user",
                DocumentACL.user_id == user_id,
            ),
            and_(
                DocumentACL.principal_type == "role",
                DocumentACL.role_id.in_(assigned_role_ids),
            ),
            and_(
                DocumentACL.principal_type == "department",
                DocumentACL.department_id.in_(department_ids),
            ),
        )

        has_acl_allow = exists(
            select(1).where(
                DocumentACL.organization_id == organization_id,
                DocumentACL.document_id == Document.id,
                DocumentACL.effect == "allow",
                matching_principals,
            )
        )

        # Assigning a document to a department grants access to all members
        # of that department, independently of an explicit ACL row.
        department_assignment_grant = Document.department_id.in_(department_ids)

        # Owners/admins retain their organization-wide implicit allow.
        # Explicit user, role, or department denies still override that allow.
        has_allow = (
            true()
            if membership.role in {"owner", "admin"}
            else or_(Document.organization_wide_access.is_(True), has_acl_allow, department_assignment_grant)
        )

        has_deny = exists(
            select(1).where(
                DocumentACL.organization_id == organization_id,
                DocumentACL.document_id == Document.id,
                DocumentACL.effect == "deny",
                matching_principals,
            )
        )

        return has_allow, has_deny

    def get_authorized_document_ids(
        self,
        organization_id: UUID,
        user_id: UUID,
    ) -> list[UUID]:
        """
        Return logical document IDs accessible to a user in an organization.

        Access is union-based across direct user, assigned-role, and
        department grants. Explicit denies for any matching principal override
        all allows. A document's department assignment is an automatic grant
        to members of that department.

        Does not commit or modify database state.
        """
        conditions = self._build_access_conditions(
            organization_id=organization_id,
            user_id=user_id,
        )
        if conditions is None:
            return []

        has_allow, has_deny = conditions
        statement = (
            select(Document.id)
            .where(
                Document.organization_id == organization_id,
                Document.archived.is_(False),
                has_allow,
                ~has_deny,
            )
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

        PostgreSQL remains the source of truth for authorization and lifecycle.
        """
        conditions = self._build_access_conditions(
            organization_id=organization_id,
            user_id=user_id,
        )
        if conditions is None:
            return []

        has_allow, has_deny = conditions
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
                has_allow,
                ~has_deny,
            )
            .order_by(
                Document.id,
                DocumentVersion.version_number.desc(),
            )
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

    def get_organization_document_catalog(
        self,
        organization_id: UUID,
    ) -> list[dict[str, Any]]:
        """Return non-archived active and superseded version metadata."""
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
            .order_by(
                Document.id,
                DocumentVersion.version_number.desc(),
            )
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
