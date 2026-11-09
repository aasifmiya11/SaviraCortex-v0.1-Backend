from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.document_acl import DocumentACL
from app.models.documents import Document
from app.models.organization_department_memberships import (
    OrganizationDepartmentMembership,
)
from app.models.organization_departments import OrganizationDepartment
from app.models.organization_memberships import OrganizationMembership
from app.models.organization_roles import OrganizationRole
from app.models.organizations import Organization
from app.models.user_role_assignments import UserRoleAssignment
from app.models.users import User
from app.repositories.authorization_repository import AuthorizationRepository


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _identity(db, *, membership_role="member"):
    organization = Organization(name="Authorization Test Org")
    user = User(email=f"{uuid4()}@example.test")
    db.add_all([organization, user])
    db.flush()

    dept_a = OrganizationDepartment(
        organization_id=organization.id,
        name="Department A",
        created_by=user.id,
    )
    dept_b = OrganizationDepartment(
        organization_id=organization.id,
        name="Department B",
        created_by=user.id,
    )
    dept_c = OrganizationDepartment(
        organization_id=organization.id,
        name="Department C",
        created_by=user.id,
    )
    db.add_all([dept_a, dept_b, dept_c])
    db.flush()

    membership = OrganizationMembership(
        organization_id=organization.id,
        user_id=user.id,
        role=membership_role,
    )
    db.add(membership)
    db.flush()

    return organization, user, membership, dept_a, dept_b, dept_c


def _document(db, organization, title):
    document = Document(
        organization_id=organization.id,
        title=title,
        document_type="policy",
    )
    db.add(document)
    db.flush()
    return document


def _acl(
    db,
    organization,
    document,
    *,
    principal_type,
    effect,
    user_id=None,
    role_id=None,
    department_id=None,
):
    db.add(
        DocumentACL(
            organization_id=organization.id,
            document_id=document.id,
            principal_type=principal_type,
            effect=effect,
            user_id=user_id,
            role_id=role_id,
            department_id=department_id,
        )
    )
    db.flush()


def _assign_role(db, organization, user):
    role = OrganizationRole(
        organization_id=organization.id,
        name="Auditor",
    )
    db.add(role)
    db.flush()
    db.add(
        UserRoleAssignment(
            organization_id=organization.id,
            user_id=user.id,
            role_id=role.id,
        )
    )
    db.flush()
    return role


def _assign_department(db, organization, user, department):
    db.add(
        OrganizationDepartmentMembership(
            organization_id=organization.id,
            user_id=user.id,
            department_id=department.id,
        )
    )
    db.flush()


def test_grants_are_union_of_user_role_and_multiple_departments(db):
    organization, user, _, dept_a, dept_b, dept_c = _identity(db)
    role = _assign_role(db, organization, user)
    _assign_department(db, organization, user, dept_a)
    _assign_department(db, organization, user, dept_b)

    direct_doc = _document(db, organization, "Direct grant")
    role_doc = _document(db, organization, "Role grant")
    dept_doc = _document(db, organization, "Department ACL grant")
    automatic_doc = _document(db, organization, "Department ACL grant from second department")
    unrelated_doc = _document(db, organization, "Unrelated department")

    _acl(
        db, organization, direct_doc,
        principal_type="user", effect="allow", user_id=user.id,
    )
    _acl(
        db, organization, role_doc,
        principal_type="role", effect="allow", role_id=role.id,
    )
    _acl(
        db, organization, dept_doc,
        principal_type="department", effect="allow",
        department_id=dept_a.id,
    )
    _acl(
        db, organization, automatic_doc,
        principal_type="department", effect="allow",
        department_id=dept_b.id,
    )
    _acl(
        db, organization, unrelated_doc,
        principal_type="department", effect="allow",
        department_id=dept_c.id,
    )

    authorized = set(
        AuthorizationRepository(db).get_authorized_document_ids(
            organization.id, user.id
        )
    )

    assert authorized == {
        direct_doc.id,
        role_doc.id,
        dept_doc.id,
        automatic_doc.id,
    }
    assert unrelated_doc.id not in authorized


@pytest.mark.parametrize("deny_type", ["user", "role", "department"])
def test_any_matching_explicit_deny_overrides_other_allows(db, deny_type):
    organization, user, _, _, dept_b, _ = _identity(db)
    role = _assign_role(db, organization, user)
    _assign_department(db, organization, user, dept_b)

    document = _document(db, organization, "Deny precedence")
    # A direct allow and a department allow both grant access.
    _acl(
        db, organization, document,
        principal_type="user", effect="allow", user_id=user.id,
    )
    _acl(
        db, organization, document,
        principal_type="department", effect="allow", department_id=dept_b.id,
    )

    deny_kwargs = {
        "user": {"principal_type": "user", "user_id": user.id},
        "role": {"principal_type": "role", "role_id": role.id},
        "department": {
            "principal_type": "department",
            "department_id": dept_b.id,
        },
    }[deny_type]
    _acl(db, organization, document, effect="deny", **deny_kwargs)

    authorized = AuthorizationRepository(db).get_authorized_document_ids(
        organization.id, user.id
    )
    assert document.id not in authorized


def test_same_principal_can_have_allow_and_deny_and_deny_wins(db):
    organization, user, _, _, _, _ = _identity(db)
    document = _document(db, organization, "Same principal allow and deny")
    _acl(
        db, organization, document,
        principal_type="user", effect="allow", user_id=user.id,
    )
    _acl(
        db, organization, document,
        principal_type="user", effect="deny", user_id=user.id,
    )

    assert document.id not in AuthorizationRepository(
        db
    ).get_authorized_document_ids(organization.id, user.id)


def test_owner_implicit_allow_is_still_overridden_by_explicit_deny(db):
    organization, user, _, _, _, _ = _identity(
        db, membership_role="owner"
    )
    allowed_document = _document(db, organization, "Owner implicit access")
    denied_document = _document(db, organization, "Owner explicit deny")
    _acl(
        db, organization, denied_document,
        principal_type="user", effect="deny", user_id=user.id,
    )

    authorized = set(
        AuthorizationRepository(db).get_authorized_document_ids(
            organization.id, user.id
        )
    )
    assert allowed_document.id in authorized
    assert denied_document.id not in authorized


def test_document_without_any_allow_rules_is_visible_to_all_members(db):
    organization, user, _, _, _, _ = _identity(db)
    document = _document(db, organization, "Unassigned")
    assert document.id in AuthorizationRepository(
        db
    ).get_authorized_document_ids(organization.id, user.id)


def test_membership_is_required_even_for_organization_wide_documents(db):
    organization = Organization(name="No Membership Organization")
    user = User(email=f"{uuid4()}@example.test")
    db.add_all([organization, user])
    db.flush()
    document = Document(
        organization_id=organization.id,
        title="Organization-wide but caller is not a member",
        document_type="policy",
        organization_wide_access=True,
    )
    db.add(document)
    db.flush()

    assert AuthorizationRepository(db).get_authorized_document_ids(
        organization.id, user.id
    ) == []


def test_deny_only_document_remains_visible_to_other_members(db):
    organization, denied_user, _, _, _, _ = _identity(db)
    other_user = User(email=f"{uuid4()}@example.test")
    db.add(other_user)
    db.flush()
    db.add(OrganizationMembership(
        organization_id=organization.id,
        user_id=other_user.id,
        role="member",
    ))
    db.flush()
    document = _document(db, organization, "Deny one member only")
    _acl(
        db, organization, document,
        principal_type="user", effect="deny", user_id=denied_user.id,
    )

    repository = AuthorizationRepository(db)
    assert document.id not in repository.get_authorized_document_ids(
        organization.id, denied_user.id
    )
    assert document.id in repository.get_authorized_document_ids(
        organization.id, other_user.id
    )
