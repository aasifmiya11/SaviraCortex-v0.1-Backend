from uuid import uuid4

from app.models import (
    OrganizationDepartment, OrganizationDepartmentMembership,
    OrganizationMembership, OrganizationRole, User, UserRoleAssignment,
)


def _add_member(db_session, organization_id, *, uid="firebase-member-uid", role="member"):
    user = User(id=uuid4(), firebase_uid=uid, email=f"{uid}@example.com", display_name="Team Member")
    db_session.add(user)
    db_session.flush()
    membership = OrganizationMembership(
        id=uuid4(), organization_id=organization_id, user_id=user.id, role=role,
    )
    db_session.add(membership)
    db_session.commit()
    return user, membership


def test_list_members_includes_custom_roles(client, db_session, organization_context):
    org = organization_context["organization"]
    member, membership = _add_member(db_session, org.id)
    member_role = organization_context["member_role"]
    db_session.add(UserRoleAssignment(
        id=uuid4(), organization_id=org.id, user_id=member.id, role_id=member_role.id,
    ))
    db_session.commit()

    response = client.get(f"/api/v1/organizations/{org.id}/members")

    assert response.status_code == 200
    item = next(row for row in response.json() if row["user_id"] == str(member.id))
    assert item["role"] == "member"
    assert item["custom_roles"] == ["Member"]


def test_owner_can_add_existing_user_and_duplicate_is_rejected(client, db_session, organization_context):
    org = organization_context["organization"]
    member = User(id=uuid4(), firebase_uid="existing-user-uid", email="existing@example.com", display_name="Existing")
    db_session.add(member)
    db_session.commit()

    url = f"/api/v1/organizations/{org.id}/members"
    response = client.post(url, json={"user_id": str(member.id)})
    duplicate = client.post(url, json={"user_id": str(member.id)})

    assert response.status_code == 201
    assert response.json()["role"] == "member"
    assert duplicate.status_code == 409


def test_admin_cannot_grant_admin_role(client, db_session, organization_context, firebase_claims):
    org = organization_context["organization"]
    admin, _ = _add_member(db_session, org.id, uid="firebase-admin-uid", role="admin")
    target = User(id=uuid4(), firebase_uid="firebase-target-uid", email="target@example.com", display_name="Target")
    db_session.add(target)
    db_session.commit()
    firebase_claims["uid"] = admin.firebase_uid

    response = client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(target.id), "role": "admin"},
    )

    assert response.status_code == 403


def test_only_owner_can_change_membership_role(client, db_session, organization_context):
    org = organization_context["organization"]
    member, _ = _add_member(db_session, org.id)
    response = client.patch(
        f"/api/v1/organizations/{org.id}/members/{member.id}",
        json={"role": "admin"},
    )
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_owner_membership_cannot_be_removed(client, organization_context):
    org = organization_context["organization"]
    owner_id = organization_context["owner"].id

    response = client.delete(f"/api/v1/organizations/{org.id}/members/{owner_id}")

    assert response.status_code == 409


def test_create_and_list_custom_roles(client, organization_context):
    org = organization_context["organization"]
    response = client.post(
        f"/api/v1/organizations/{org.id}/roles",
        json={"name": "  Analyst  ", "description": "  Read reports  "},
    )
    listed = client.get(f"/api/v1/organizations/{org.id}/roles")

    assert response.status_code == 201
    assert response.json()["name"] == "Analyst"
    assert response.json()["description"] == "Read reports"
    assert {role["name"] for role in listed.json()} == {"Member", "Analyst"}


def test_member_cannot_create_custom_role(client, db_session, organization_context, firebase_claims):
    org = organization_context["organization"]
    member, _ = _add_member(db_session, org.id)
    firebase_claims["uid"] = member.firebase_uid

    response = client.post(f"/api/v1/organizations/{org.id}/roles", json={"name": "Restricted"})

    assert response.status_code == 403


def test_create_and_list_departments(client, organization_context):
    org = organization_context["organization"]
    created = client.post(
        f"/api/v1/organizations/{org.id}/departments",
        json={"name": "  Research  ", "description": "  Research team  "},
    )
    listed = client.get(f"/api/v1/organizations/{org.id}/departments")

    assert created.status_code == 201
    assert created.json()["name"] == "Research"
    assert created.json()["description"] == "Research team"
    assert len(listed.json()) == 1


def test_member_cannot_create_department(client, db_session, organization_context, firebase_claims):
    org = organization_context["organization"]
    member, _ = _add_member(db_session, org.id)
    firebase_claims["uid"] = member.firebase_uid

    response = client.post(f"/api/v1/organizations/{org.id}/departments", json={"name": "Restricted"})

    assert response.status_code == 403


def test_assign_list_and_unassign_department_member(client, db_session, organization_context):
    org = organization_context["organization"]
    member, _ = _add_member(db_session, org.id)
    department = OrganizationDepartment(id=uuid4(), organization_id=org.id, name="Engineering")
    db_session.add(department)
    db_session.commit()
    base = f"/api/v1/organizations/{org.id}/departments/{department.id}/members"

    assigned = client.post(base, json={"user_id": str(member.id)})
    listed = client.get(base)
    removed = client.delete(f"{base}/{member.id}")

    assert assigned.status_code == 201
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert removed.status_code == 204
    assert db_session.get(OrganizationDepartmentMembership, (org.id, member.id, department.id)) is None


def test_owner_can_assign_multiple_custom_roles_to_one_member(client, db_session, organization_context):
    org = organization_context["organization"]
    member, _ = _add_member(db_session, org.id)
    ceo = OrganizationRole(id=uuid4(), organization_id=org.id, name="CEO")
    engineering_lead = OrganizationRole(id=uuid4(), organization_id=org.id, name="Engineering Lead")
    db_session.add_all([ceo, engineering_lead])
    db_session.commit()

    response = client.post(
        f"/api/v1/organizations/{org.id}/members/{member.id}/roles",
        json={"role_ids": [str(ceo.id), str(engineering_lead.id)]},
    )

    assert response.status_code == 200
    assert {role["name"] for role in response.json()} == {"CEO", "Engineering Lead"}
    listed = client.get(f"/api/v1/organizations/{org.id}/members")
    item = next(row for row in listed.json() if row["user_id"] == str(member.id))
    assert item["role"] == "member"
    assert item["custom_roles"] == ["CEO", "Engineering Lead"]


def test_admin_can_assign_multiple_custom_roles(client, db_session, organization_context, firebase_claims):
    org = organization_context["organization"]
    admin, _ = _add_member(db_session, org.id, uid="firebase-admin-roles-uid", role="admin")
    member, _ = _add_member(db_session, org.id, uid="firebase-target-roles-uid")
    role = OrganizationRole(id=uuid4(), organization_id=org.id, name="CTO")
    db_session.add(role)
    db_session.commit()
    firebase_claims["uid"] = admin.firebase_uid

    response = client.post(
        f"/api/v1/organizations/{org.id}/members/{member.id}/roles",
        json={"role_ids": [str(role.id)]},
    )

    assert response.status_code == 200
    assert response.json()[0]["name"] == "CTO"


def test_member_cannot_assign_custom_roles(client, db_session, organization_context, firebase_claims):
    org = organization_context["organization"]
    member, _ = _add_member(db_session, org.id, uid="firebase-role-member-uid")
    target, _ = _add_member(db_session, org.id, uid="firebase-role-target-uid")
    role = OrganizationRole(id=uuid4(), organization_id=org.id, name="Manager")
    db_session.add(role)
    db_session.commit()
    firebase_claims["uid"] = member.firebase_uid

    response = client.post(
        f"/api/v1/organizations/{org.id}/members/{target.id}/roles",
        json={"role_ids": [str(role.id)]},
    )

    assert response.status_code == 403


def test_custom_role_assignment_rejects_role_from_another_organization(client, db_session, organization_context):
    org = organization_context["organization"]
    member, _ = _add_member(db_session, org.id)
    other_org = __import__("app.models", fromlist=["Organization"]).Organization(
        id=uuid4(), name="Another organization"
    )
    db_session.add(other_org)
    db_session.flush()
    foreign_role = OrganizationRole(id=uuid4(), organization_id=other_org.id, name="Foreign CEO")
    db_session.add(foreign_role)
    db_session.commit()

    response = client.post(
        f"/api/v1/organizations/{org.id}/members/{member.id}/roles",
        json={"role_ids": [str(foreign_role.id)]},
    )

    assert response.status_code == 404
